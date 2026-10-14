"""No-code strategies: rules written as sentences, stored as YAML.

    name: RSI dip in an uptrend
    long_entry:  rsi(14) < 30 and close > sma(200)
    long_exit:   rsi(14) > 55
    exits: {unit: atr, stop_loss: 2, take_profits: [[2, 0.5], [4, 0.5]], breakeven_after: 1}

The language
------------
* columns: ``open high low close volume quote_volume funding_rate`` (plus any
  numeric column the data carries);
* every indicator in ``quantlab.indicators`` by name: ``sma(50)``, ``rsi(14)``,
  ``bb_lower(20, 2)``, ``atr(14)``, ``donchian_high(55)``, ``lag(close, 3)`` ...;
* ``crosses_above(a, b)`` / ``crosses_below(a, b)``;
* arithmetic ``+ - * /``, comparisons, ``and`` / ``or`` / ``not``, numbers.

Expressions are parsed with Python's ``ast`` and only the node types above are
allowed: attribute access, subscripts, lambdas, imports and every other name are
rejected, so a rule file cannot run arbitrary code.

Position logic, per symbol: flat -> long when ``long_entry`` is true; long ->
flat when ``long_exit`` is true (or when ``short_entry`` fires, which reverses).
With no ``long_exit``, the position is held exactly while ``long_entry`` is true.
Shorts mirror this. The engine's :class:`~quantlab.engine.ExitRules` can add
stops and targets on top.
"""
from __future__ import annotations

import ast
import operator
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from quantlab import indicators as I
from quantlab.engine import ExitRules

COLUMNS = {"open", "high", "low", "close", "volume", "quote_volume", "funding_rate"}
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
_CMP = {ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Lt: operator.lt, ast.LtE: operator.le,
        ast.Eq: operator.eq, ast.NotEq: operator.ne}


class RuleError(ValueError):
    pass


def crosses_above(df, a, b):
    a, b = _as_series(df, a), _as_series(df, b)
    return (a > b) & (I.lag(df, a) <= I.lag(df, b))


def crosses_below(df, a, b):
    a, b = _as_series(df, a), _as_series(df, b)
    return (a < b) & (I.lag(df, a) >= I.lag(df, b))


FUNCTIONS = {**I.REGISTRY, "crosses_above": crosses_above, "crosses_below": crosses_below}


def _as_series(df, v):
    return v if isinstance(v, pd.Series) else pd.Series(v, index=df.index, dtype=float)


class _Eval:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.cache: dict[str, pd.Series] = {}

    def __call__(self, node):
        m = getattr(self, f"_{type(node).__name__}", None)
        if m is None:
            raise RuleError(f"'{type(node).__name__}' is not allowed in a rule")
        return m(node)

    def _Expression(self, n):
        return self(n.body)

    def _Constant(self, n):
        if isinstance(n.value, (int, float, str)) and not isinstance(n.value, bool):
            return n.value
        raise RuleError(f"constant {n.value!r} is not allowed")

    def _Name(self, n):
        if n.id in COLUMNS or (n.id in self.df.columns and pd.api.types.is_numeric_dtype(self.df[n.id])):
            if n.id not in self.df.columns:
                raise RuleError(f"the data has no '{n.id}' column")
            return self.df[n.id]
        raise RuleError(f"unknown name '{n.id}' (columns: {sorted(COLUMNS)}; or call an indicator)")

    def _Call(self, n):
        if not isinstance(n.func, ast.Name) or n.func.id not in FUNCTIONS:
            name = getattr(n.func, "id", "?")
            raise RuleError(f"unknown function '{name}'")
        key = ast.dump(n)
        if key not in self.cache:
            args = [self(a) for a in n.args]
            kwargs = {k.arg: self(k.value) for k in n.keywords}
            self.cache[key] = FUNCTIONS[n.func.id](self.df, *args, **kwargs)
        return self.cache[key]

    def _BinOp(self, n):
        if type(n.op) not in _BIN:
            raise RuleError("only + - * / are allowed")
        return _BIN[type(n.op)](self(n.left), self(n.right))

    def _UnaryOp(self, n):
        v = self(n.operand)
        if isinstance(n.op, ast.Not):
            return ~_as_series(self.df, v).fillna(False).astype(bool)
        if isinstance(n.op, ast.USub):
            return -v
        raise RuleError("unsupported unary operator")

    def _Compare(self, n):
        out, left = None, self(n.left)
        for op, comp in zip(n.ops, n.comparators, strict=True):
            if type(op) not in _CMP:
                raise RuleError("unsupported comparison")
            right = self(comp)
            r = _as_series(self.df, _CMP[type(op)](left, right))
            out = r if out is None else (out & r)
            left = right
        return out

    def _BoolOp(self, n):
        vals = [_as_series(self.df, self(v)).fillna(False).astype(bool) for v in n.values]
        out = vals[0]
        for v in vals[1:]:
            out = (out & v) if isinstance(n.op, ast.And) else (out | v)
        return out


def evaluate_expr(expr: str, df: pd.DataFrame, cache: dict | None = None) -> pd.Series:
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as exc:
        raise RuleError(f"cannot parse {expr!r}: {exc.msg}") from exc
    ev = _Eval(df)
    if cache is not None:
        ev.cache = cache
    out = _as_series(df, ev(tree))
    return out.fillna(False).astype(bool) if out.dtype == bool or out.dtype == object else out.fillna(0).astype(bool)


@dataclass
class RuleStrategy:
    name: str
    long_entry: str | None = None
    long_exit: str | None = None
    short_entry: str | None = None
    short_exit: str | None = None
    description: str = ""
    exits: dict = field(default_factory=dict)

    def exit_rules(self) -> ExitRules:
        e = dict(self.exits or {})
        if "take_profits" in e:
            e["take_profits"] = tuple(tuple(x) for x in e["take_profits"])
        return ExitRules(**e)

    def validate(self, df: pd.DataFrame) -> None:
        if not (self.long_entry or self.short_entry):
            raise RuleError("a strategy needs a long_entry or a short_entry")
        for expr in (self.long_entry, self.long_exit, self.short_entry, self.short_exit):
            if expr:
                evaluate_expr(expr, df.head(300))

    def signal_fn(self):
        spec = self

        def fn(df: pd.DataFrame) -> pd.DataFrame:
            cache: dict = {}
            z = pd.Series(False, index=df.index)
            le = evaluate_expr(spec.long_entry, df, cache) if spec.long_entry else z
            lx = evaluate_expr(spec.long_exit, df, cache) if spec.long_exit else None
            se = evaluate_expr(spec.short_entry, df, cache) if spec.short_entry else z
            sx = evaluate_expr(spec.short_exit, df, cache) if spec.short_exit else None
            le_a, se_a = le.to_numpy(), se.to_numpy()
            lx_a = lx.to_numpy() if lx is not None else None
            sx_a = sx.to_numpy() if sx is not None else None
            out = np.zeros(len(df), dtype=int)
            for _, idx in df.groupby("symbol", sort=False).indices.items():
                pos = 0
                for i in idx:
                    if pos == 0:
                        pos = 1 if le_a[i] else (-1 if se_a[i] else 0)
                    elif pos == 1:
                        if se_a[i]:
                            pos = -1
                        elif (lx_a[i] if lx_a is not None else not le_a[i]):
                            pos = 0
                    else:
                        if le_a[i]:
                            pos = 1
                        elif (sx_a[i] if sx_a is not None else not se_a[i]):
                            pos = 0
                    out[i] = pos
            return df.assign(signal=out)
        return fn

    def to_yaml(self) -> str:
        import yaml
        d = {k: v for k, v in asdict(self).items() if v not in (None, "", {})}
        return yaml.safe_dump(d, sort_keys=False)

    @classmethod
    def from_yaml(cls, text: str) -> "RuleStrategy":
        import yaml
        d = yaml.safe_load(text) or {}
        unknown = set(d) - {f for f in cls.__dataclass_fields__}
        if unknown:
            raise RuleError(f"unknown keys in strategy file: {sorted(unknown)}")
        return cls(**d)

    def save(self, folder: str | Path) -> Path:
        p = Path(folder) / f"{''.join(c if c.isalnum() else '_' for c in self.name.lower()).strip('_')}.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_yaml())
        return p


EXAMPLES = [
    RuleStrategy("RSI dip in an uptrend", long_entry="rsi(14) < 30 and close > sma(200)", long_exit="rsi(14) > 55",
                 description="Buy short-term weakness only when the long-term trend is up.",
                 exits={"unit": "atr", "stop_loss": 2.5, "time_stop_bars": 72}),
    RuleStrategy("MACD trend with ADX filter", long_entry="crosses_above(macd(), macd_signal()) and adx(14) > 20",
                 short_entry="crosses_below(macd(), macd_signal()) and adx(14) > 20",
                 long_exit="crosses_below(macd(), macd_signal())", short_exit="crosses_above(macd(), macd_signal())",
                 description="Trade MACD crossovers only when a trend is present."),
    RuleStrategy("Bollinger squeeze breakout",
                 long_entry="close > bb_upper(20, 2) and (bb_upper(20, 2) - bb_lower(20, 2)) / close < 0.04",
                 long_exit="close < sma(20)",
                 description="Enter when price breaks out of a tight band.",
                 exits={"unit": "pct", "stop_loss": 0.03, "take_profits": [[0.03, 0.5], [0.06, 0.5]],
                        "breakeven_after": 1}),
]
