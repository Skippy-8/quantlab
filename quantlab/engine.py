"""The standardized scoring engine.

A strategy decides WHAT to trade; this module decides HOW it fills, and it is
the same for every strategy. Keeping execution out of strategy code is what
makes two backtests comparable and stops a strategy from quietly assuming a
fill the market would not have given it.

Execution model
---------------
* ``signal[t]`` is the position wanted after bar ``t``'s close (-1, 0 or +1).
  Nothing executes on bar ``t`` itself.
* Every signal entry and exit is a limit order on its own side of the book: a
  buy rests at the bid, a sell at the ask, re-pegged to the new touch each close.
* A resting limit fills only when a LATER bar trades strictly THROUGH its price
  (``low < bid`` for a buy, ``high > ask`` for a sell). Touching the price is
  not a fill: queue position is unknowable. Limit fills pay the maker fee.
* An entry not filled within ``entry_ttl_bars`` is cancelled and counted as a
  missed trade, never booked. An exit not filled within ``exit_ttl_bars``
  crosses the spread and pays the taker fee. A position open at the end of the
  data is closed the same way (``eod``).

Exit rules (optional, :class:`ExitRules`)
-----------------------------------------
Stops, profit-target ladders, breakeven, trailing stops and time stops, priced
off the ACTUAL fill. Distances are a fraction of price (``unit="pct"``) or a
multiple of ATR(14) measured on the bar before entry (``unit="atr"``).

* Inside a bar the stop is checked BEFORE any target (pessimistic: OHLC bars do
  not say which came first). A stop fills at the stop, or at the open when the
  bar gaps through it, and pays the taker fee.
* A target is a resting limit: it fills only when price trades through it, at
  the target, paying the maker fee. Each target closes a fraction of the
  ORIGINAL size.
* ``breakeven_after=k`` moves the stop to the entry price once k targets fill.
* A trailing stop follows the best price since entry and only ever tightens.
* ``time_stop_bars`` closes whatever remains at that close, crossing the spread.

Each partial close is its own row in ``trades`` (with ``size``, a fraction of the
original unit, and ``position_id``); ``positions`` aggregates them.

Costs
-----
* Fees: maker / taker in bp per side.
* Funding: if the frame has ``funding_rate`` (the rate settled at that bar),
  every settlement a slice is open through is booked as ``-side * rate``.
* Borrow: shorts pay ``short_borrow_bp_per_year`` pro rata to time held.
* Futures rolls: if the frame has a boolean ``roll`` column, every roll bar a
  position is held through costs ``roll_cost_bp`` (crossing out of one contract
  and into the next).
* P&L is in basis points of notional per unit:
  ``side * (exit / entry - 1) * 1e4 - fees + funding - borrow - rolls``.
  ``quantlab.portfolio`` turns it into a dollar equity curve under a sizing rule.

Quotes: without ``bbo_bid`` / ``bbo_ask`` columns the engine builds them as
``close -/+ assumed_half_spread_bp`` and says so in the summary.

Integrity checks (run by :func:`evaluate` before any P&L is computed)
---------------------------------------------------------------------
* :func:`check_no_lookahead` - signals at or before time T must not change when
  rows after T are added (catches ``shift(-k)``, centred windows, ``bfill`` and
  every full-sample statistic).
* :func:`check_symbol_order_invariance` - signals must not depend on the order
  of the symbol blocks (catches rolling/shift/diff without a ``groupby``).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Callable, Iterable

import numpy as np
import pandas as pd

SignalFn = Callable[[pd.DataFrame], pd.DataFrame]
OHLC = ("timestamp", "open", "high", "low", "close", "volume")


class LookaheadError(AssertionError):
    """A strategy's signal for some past time depends on data that came later."""


@dataclass(frozen=True)
class ExitRules:
    """Mechanical exits attached to every position. All distances are positive."""
    unit: str = "pct"                                # "pct" (fraction of price) or "atr"
    stop_loss: float | None = None
    take_profits: tuple[tuple[float, float], ...] = ()   # ((distance, fraction of original size), ...)
    breakeven_after: int | None = None               # move the stop to entry after this many targets
    trailing_stop: float | None = None
    time_stop_bars: int | None = None

    @property
    def active(self) -> bool:
        return bool(self.stop_loss or self.take_profits or self.trailing_stop or self.time_stop_bars)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EngineConfig:
    maker_fee_bp: float = 2.0
    taker_fee_bp: float = 5.0
    entry_ttl_bars: int = 3
    exit_ttl_bars: int = 3
    assumed_half_spread_bp: float = 2.0              # used only when the data has no quotes
    short_borrow_bp_per_year: float = 0.0
    roll_cost_bp: float = 0.0
    min_history_bars: int = 0                        # point-in-time eligibility
    volume_window_bars: int = 24
    min_window_quote_volume: float = 0.0
    days_per_year: int = 365                         # 365 crypto, 252 equities
    exits: ExitRules = field(default_factory=ExitRules)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    summary: dict
    frame: pd.DataFrame | None = None
    daily: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    positions: pd.DataFrame = field(default_factory=pd.DataFrame)


# ── preparation ────────────────────────────────────────────────────────────

def prepare(df: pd.DataFrame, cfg: EngineConfig = EngineConfig()) -> pd.DataFrame:
    """Validate columns, sort by (symbol, timestamp), add quotes if missing."""
    out = df.copy()
    if "timestamp" not in out.columns and "ts_ms" in out.columns:
        out["timestamp"] = pd.to_datetime(out["ts_ms"], unit="ms", utc=True)
    if "volume" not in out.columns and "quote_volume" in out.columns:
        out["volume"] = out["quote_volume"]
    if "volume" not in out.columns:
        out["volume"] = 0.0
    missing = [c for c in OHLC if c not in out.columns]
    if missing:
        raise ValueError(f"data is missing required columns: {missing}")
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    if "symbol" not in out.columns:
        out["symbol"] = "ASSET"
    if "bbo_bid" not in out.columns or "bbo_ask" not in out.columns:
        h = cfg.assumed_half_spread_bp / 1e4
        out["bbo_bid"] = out["close"] * (1 - h)
        out["bbo_ask"] = out["close"] * (1 + h)
        out["quotes_assumed"] = True
    elif "quotes_assumed" not in out.columns:
        out["quotes_assumed"] = False
    return out.sort_values(["symbol", "timestamp"], kind="stable").reset_index(drop=True)


def eligibility(df: pd.DataFrame, cfg: EngineConfig) -> np.ndarray:
    """A row may hold a position only if its symbol has enough history and
    enough recent quote volume. Both are trailing, so this is point in time."""
    vol = pd.to_numeric(df["quote_volume" if "quote_volume" in df.columns else "volume"],
                        errors="coerce").fillna(0.0)
    w = max(int(cfg.volume_window_bars), 1)
    qv = vol.groupby(df["symbol"], sort=False).transform(lambda s: s.rolling(w, min_periods=w).sum())
    ok = df.groupby("symbol", sort=False).cumcount() >= cfg.min_history_bars
    if cfg.min_window_quote_volume > 0:
        ok &= qv >= cfg.min_window_quote_volume
    return ok.fillna(False).to_numpy()


def clean_signal(sig) -> pd.Series:
    """NaN (indicator warm-up) means flat; anything outside {-1, 0, 1} is an error."""
    s = pd.to_numeric(pd.Series(sig), errors="coerce").fillna(0.0)
    bad = ~s.isin([-1, 0, 1])
    if bad.any():
        raise ValueError(f"signal must be -1, 0 or 1; got e.g. {s[bad].iloc[:3].tolist()}")
    return s.astype(int)


def signals(fn: SignalFn, df: pd.DataFrame) -> np.ndarray:
    out = fn(df.copy())
    if not isinstance(out, pd.DataFrame) or "signal" not in out.columns:
        raise ValueError("a strategy must return the DataFrame with a 'signal' column")
    if len(out) != len(df):
        raise ValueError(f"a strategy must not add or drop rows ({len(df)} in, {len(out)} out)")
    return clean_signal(out["signal"].to_numpy()).to_numpy()


# ── integrity checks ───────────────────────────────────────────────────────

def check_no_lookahead(fn: SignalFn, df: pd.DataFrame, cuts: Iterable[float] = (0.5, 0.7, 0.9)) -> bool:
    """Truncation invariance BY TIME (works on a multi-symbol panel)."""
    full = signals(fn, df)
    times = np.sort(df["timestamp"].unique())
    for c in cuts:
        k = int(len(times) * c)
        if k < 2:
            continue
        mask = (df["timestamp"] <= times[k - 1]).to_numpy()
        part = signals(fn, df[mask].reset_index(drop=True))
        diff = np.flatnonzero(part != full[mask])
        if diff.size:
            row = df[mask].iloc[int(diff[0])]
            raise LookaheadError(
                f"signal for {row['symbol']} at {row['timestamp']} is {part[diff[0]]} on data truncated at "
                f"{pd.Timestamp(times[k - 1])} but {full[mask][diff[0]]} on the full data: "
                "the strategy reads future rows")
    return True


def check_symbol_order_invariance(fn: SignalFn, df: pd.DataFrame) -> bool:
    """Reverse the symbol blocks; every signal must stay the same."""
    if df["symbol"].nunique() < 2:
        return True
    full = signals(fn, df)
    order = {s: i for i, s in enumerate(sorted(df["symbol"].unique(), reverse=True))}
    idx = np.lexsort((np.arange(len(df)), df["symbol"].map(order).to_numpy()))
    rev = signals(fn, df.iloc[idx].reset_index(drop=True))
    back = np.empty_like(rev)
    back[idx] = rev
    diff = np.flatnonzero(back != full)
    if diff.size:
        row = df.iloc[int(diff[0])]
        raise LookaheadError(f"signal for {row['symbol']} at {row['timestamp']} changes when the symbols are "
                             "reordered: one symbol's rows leak into another's (group by symbol)")
    return True


# ── the fill simulator ─────────────────────────────────────────────────────

_COUNTERS = ("entries_placed", "entries_filled", "entries_expired", "entries_cancelled",
             "exits_cancelled", "bars", "bars_in_market")


def _bars_per_year(ts: np.ndarray, days_per_year: int) -> float:
    if len(ts) < 3:
        return float(days_per_year)
    step = np.median(np.diff(ts).astype("timedelta64[s]").astype(float))
    return days_per_year * 86400.0 / step if step > 0 else float(days_per_year)


class _Position:
    __slots__ = ("pid", "side", "entry_px", "entry_t", "remaining", "stop", "targets", "filled_targets",
                 "best", "dist_unit")

    def __init__(self, pid, side, px, t, ex: ExitRules, atr_at_entry):
        self.pid, self.side, self.entry_px, self.entry_t = pid, side, px, t
        self.remaining, self.filled_targets, self.best = 1.0, 0, px
        unit = (atr_at_entry if ex.unit == "atr" else px)
        self.dist_unit = unit if unit and np.isfinite(unit) and unit > 0 else None
        d = self.dist_unit
        self.stop = px - side * ex.stop_loss * d if (ex.stop_loss and d) else None
        self.targets = [[px + side * dist * d, frac, False] for dist, frac in ex.take_profits] if d else []


def _run_symbol(g: pd.DataFrame, cfg: EngineConfig, pid0: int) -> tuple[list[dict], dict]:
    n = len(g)
    ex = cfg.exits
    ts = g["timestamp"].to_numpy()
    bid_a, ask_a = g["bbo_bid"].to_numpy(float), g["bbo_ask"].to_numpy(float)
    qok = (np.isfinite(bid_a) & np.isfinite(ask_a) & (bid_a > 0) & (bid_a < ask_a)).tolist()
    op, hi, lo = g["open"].to_numpy(float).tolist(), g["high"].to_numpy(float).tolist(), g["low"].to_numpy(float).tolist()
    cl, bid, ask = g["close"].to_numpy(float).tolist(), bid_a.tolist(), ask_a.tolist()
    sig = clean_signal(g["signal"].to_numpy()).to_numpy().tolist()
    cf = np.concatenate([[0.0], np.cumsum(np.nan_to_num(g["funding_rate"].to_numpy(float)))]) \
        if "funding_rate" in g.columns else None
    rolls = np.concatenate([[0], np.cumsum(g["roll"].fillna(False).astype(int).to_numpy())]) \
        if ("roll" in g.columns and cfg.roll_cost_bp) else None
    atr_a = None
    if ex.active and ex.unit == "atr":
        from quantlab.indicators import atr
        atr_a = atr(g, 14).to_numpy(float)
    borrow_per_bar = cfg.short_borrow_bp_per_year / _bars_per_year(ts, cfg.days_per_year)
    c = dict.fromkeys(_COUNTERS, 0)
    c["bars"] = n
    rows: list[dict] = []
    pos: _Position | None = None
    order = None
    pid = pid0
    blocked = 0          # after a mechanical exit: no re-entry that way until the signal changes

    def book(px, t, fee, kind, size, last_settle):
        """Close `size` (fraction of the original unit) of the open position at px."""
        side, e = pos.side, pos.entry_px
        gross = side * (px / e - 1.0) * 1e4
        x = min(last_settle, n - 1)
        fund = 0.0
        if cf is not None and x >= pos.entry_t + 1:
            fund = -side * float(cf[x + 1] - cf[pos.entry_t + 1]) * 1e4
        borrow = borrow_per_bar * (t - pos.entry_t) if side < 0 else 0.0
        roll = cfg.roll_cost_bp * float(rolls[t + 1] - rolls[pos.entry_t + 1]) if rolls is not None else 0.0
        rows.append({"position_id": pos.pid, "side": "LONG" if side > 0 else "SHORT", "entry_time": ts[pos.entry_t],
                     "exit_time": ts[t], "entry_price": e, "exit_price": px, "size": size,
                     "bars_held": int(t - pos.entry_t), "gross_bp": gross, "fee_bp": cfg.maker_fee_bp + fee,
                     "funding_bp": fund, "borrow_bp": borrow, "roll_bp": roll,
                     "net_bp": gross - cfg.maker_fee_bp - fee + fund - borrow - roll, "exit": kind})
        pos.remaining = round(pos.remaining - size, 12)

    for t in range(n):
        # 1. resting signal orders placed at an earlier close can fill inside bar t
        if order is not None:
            px = order["px"]
            if (lo[t] < px) if order["side"] > 0 else (hi[t] > px):
                if order["kind"] == "entry":
                    a = atr_a[t - 1] if (atr_a is not None and t > 0) else None
                    pos = _Position(pid, order["side"], px, t, ex, a)
                    pid += 1
                    c["entries_filled"] += 1
                else:
                    book(px, t, cfg.maker_fee_bp, "maker", pos.remaining, t)
                    pos = None
                order = None
        # 2. mechanical exits inside bar t (not on the entry bar itself)
        if pos is not None and t > pos.entry_t and ex.active:
            s = pos.side
            if pos.stop is not None and ((lo[t] <= pos.stop) if s > 0 else (hi[t] >= pos.stop)):
                fill = min(op[t], pos.stop) if s > 0 else max(op[t], pos.stop)
                kind = "breakeven" if (ex.breakeven_after and pos.filled_targets >= ex.breakeven_after
                                       and abs(pos.stop - pos.entry_px) < 1e-12) else "stop"
                book(fill, t, cfg.taker_fee_bp, kind, pos.remaining, t)
                blocked, pos, order = pos.side, None, None
            else:
                for tg in pos.targets:
                    if tg[2] or pos.remaining <= 1e-12:
                        continue
                    if (hi[t] > tg[0]) if s > 0 else (lo[t] < tg[0]):
                        book(tg[0], t, cfg.maker_fee_bp, "target", min(tg[1], pos.remaining), t)
                        tg[2] = True
                        pos.filled_targets += 1
                        if ex.breakeven_after and pos.filled_targets >= ex.breakeven_after:
                            pos.stop = pos.entry_px if pos.stop is None else (
                                max(pos.stop, pos.entry_px) if s > 0 else min(pos.stop, pos.entry_px))
                if pos.remaining <= 1e-12:
                    blocked, pos, order = pos.side, None, None
        if pos is not None:
            c["bars_in_market"] += 1
            if ex.trailing_stop and pos.dist_unit:
                pos.best = max(pos.best, hi[t]) if pos.side > 0 else min(pos.best, lo[t])
                # a pct trail is a fraction of the BEST price; an ATR trail is a fixed ATR distance
                step = ex.trailing_stop * (pos.best if ex.unit == "pct" else pos.dist_unit)
                trail = pos.best - pos.side * step
                pos.stop = trail if pos.stop is None else (max(pos.stop, trail) if pos.side > 0 else min(pos.stop, trail))
            if ex.time_stop_bars and t - pos.entry_t >= ex.time_stop_bars:
                px = (bid[t] if pos.side > 0 else ask[t]) if qok[t] else cl[t]
                book(px, t, cfg.taker_fee_bp, "time", pos.remaining, t + 1)
                blocked, pos, order = pos.side, None, None
        # 3. signal decisions at the close of bar t
        target, quote_ok = sig[t], qok[t]
        if blocked and target != blocked:
            blocked = 0
        cur = pos.side if pos is not None else 0
        if order is not None:
            order["age"] += 1
            if order["kind"] == "entry":
                if cur != 0 or target != order["side"]:
                    order, c["entries_cancelled"] = None, c["entries_cancelled"] + 1
                elif order["age"] >= cfg.entry_ttl_bars:
                    order, c["entries_expired"] = None, c["entries_expired"] + 1
            else:
                if cur == 0 or target == cur:
                    order, c["exits_cancelled"] = None, c["exits_cancelled"] + 1
                elif order["age"] >= cfg.exit_ttl_bars:
                    px = (bid[t] if cur > 0 else ask[t]) if quote_ok else cl[t]
                    book(px, t, cfg.taker_fee_bp, "taker", pos.remaining, t + 1)
                    pos, order = None, None
            if order is not None and quote_ok:
                order["px"] = bid[t] if order["side"] > 0 else ask[t]
        cur = pos.side if pos is not None else 0
        if order is None and quote_ok:
            if cur != 0 and target != cur:
                order = {"kind": "exit", "side": -cur, "px": bid[t] if cur < 0 else ask[t], "age": 0}
            elif cur == 0 and target != 0 and target != blocked:
                order = {"kind": "entry", "side": target, "px": bid[t] if target > 0 else ask[t], "age": 0}
                c["entries_placed"] += 1
    if pos is not None:
        t = n - 1
        book((bid[t] if pos.side > 0 else ask[t]) if qok[t] else cl[t], t, cfg.taker_fee_bp, "eod", pos.remaining, t)
    return rows, c


def _quote_report(df: pd.DataFrame, assumed: bool) -> dict:
    bid, ask, cl = (df[c].to_numpy(float) for c in ("bbo_bid", "bbo_ask", "close"))
    ok = np.isfinite(bid) & np.isfinite(ask) & np.isfinite(cl) & (bid > 0) & (bid < ask) & (cl > 0)
    sp = (ask[ok] - bid[ok]) / cl[ok] * 1e4
    const = bool(sp.size and np.ptp(sp) < 1e-6)
    note = ("no quotes in the data: a constant assumed spread was used" if assumed else
            "constant spread: the quotes look synthetic (the close is always the mid)" if const else "")
    return {"assumed": bool(assumed), "bars_without_valid_quote": int((~ok).sum()),
            "median_spread_bp": round(float(np.median(sp)), 4) if sp.size else None,
            "constant_spread": const, "note": note}


def to_positions(trades: pd.DataFrame) -> pd.DataFrame:
    """One row per position: net = sum over its slices of size * net_bp."""
    if trades.empty:
        return pd.DataFrame(columns=["position_id", "symbol", "side", "entry_time", "exit_time", "entry_price",
                                     "bars_held", "net_bp", "gross_bp", "exit", "slices"])
    t = trades.assign(w_net=trades["net_bp"] * trades["size"], w_gross=trades["gross_bp"] * trades["size"])
    g = t.groupby("position_id", sort=True)
    return pd.DataFrame({
        "symbol": g["symbol"].first(), "side": g["side"].first(), "entry_time": g["entry_time"].first(),
        "exit_time": g["exit_time"].max(), "entry_price": g["entry_price"].first(),
        "bars_held": g["bars_held"].max(), "net_bp": g["w_net"].sum(), "gross_bp": g["w_gross"].sum(),
        "exit": g["exit"].last(), "slices": g.size()}).reset_index()


def daily_pnl(trades: pd.DataFrame, start, end) -> pd.Series:
    """Net bp per CALENDAR day (days without an exit are 0), keyed by exit date."""
    days = pd.date_range(pd.Timestamp(start).floor("D"), pd.Timestamp(end).floor("D"), freq="D")
    if trades.empty:
        return pd.Series(0.0, index=days)
    w = trades["net_bp"] * (trades["size"] if "size" in trades else 1.0)
    by = w.groupby(pd.to_datetime(trades["exit_time"], utc=True).dt.floor("D")).sum()
    return by.reindex(days, fill_value=0.0)


def summarise(positions: pd.DataFrame, counters: dict, daily: pd.Series, cfg: EngineConfig,
              quotes: dict | None = None, slices: pd.DataFrame | None = None) -> dict:
    s = {"trades": int(len(positions)), **{k: int(v) for k, v in counters.items()}, "quotes": quotes or {},
         "entry_fill_rate": round(counters["entries_filled"] / counters["entries_placed"], 4)
         if counters["entries_placed"] else None,
         "time_in_market": round(counters["bars_in_market"] / max(counters["bars"], 1), 4),
         "config": cfg.to_dict()}
    if positions.empty:
        return s
    net = positions["net_bp"]
    traded = daily[daily != 0]
    half = len(daily) // 2
    sd_traded = traded.std(ddof=1) if len(traded) > 1 else float("nan")
    sd_cal = daily.std(ddof=1) if len(daily) > 1 else float("nan")
    wins, losses = net[net > 0].sum(), -net[net < 0].sum()
    equity = daily.cumsum()
    exits = (slices if slices is not None and len(slices) else positions)["exit"].value_counts()
    s.update({
        "mean_net_bp_per_trade": round(float(net.mean()), 3),
        "median_net_bp_per_trade": round(float(net.median()), 3),
        "mean_gross_bp_per_trade": round(float(positions["gross_bp"].mean()), 3),
        "mean_funding_bp_per_trade": round(float((slices["funding_bp"] * slices["size"]).groupby(
            slices["position_id"]).sum().mean()), 3) if slices is not None and len(slices) else 0.0,
        "win_rate": round(float((net > 0).mean()), 4),
        "profit_factor": round(float(wins / losses), 4) if losses > 0 else None,
        "sum_net_bp": round(float(net.sum()), 2),
        "exits": {k: int(v) for k, v in exits.items()},
        "mean_bars_held": round(float(positions["bars_held"].mean()), 2),
        "days_traded": int(len(traded)),
        "calendar_days": int(len(daily)),
        "day_t": round(float(traded.mean() / (sd_traded / math.sqrt(len(traded)))), 3)
        if len(traded) > 2 and sd_traded > 0 else None,
        "calendar_sharpe": round(float(daily.mean() / sd_cal * math.sqrt(cfg.days_per_year)), 3)
        if len(daily) > 1 and sd_cal > 0 else None,
        "half1_mean_day_bp": round(float(daily.iloc[:half].mean()), 3) if half else None,
        "half2_mean_day_bp": round(float(daily.iloc[half:].mean()), 3),
        "max_drawdown_bp": round(float((equity - equity.cummax()).min()), 2),
    })
    return s


def run_backtest(df: pd.DataFrame, cfg: EngineConfig = EngineConfig()) -> BacktestResult:
    """Fill-simulate a frame that already has a ``signal`` column. Each symbol is
    run on its own and the trades are pooled. No eligibility is applied here."""
    df = prepare(df, cfg)
    if "signal" not in df.columns:
        raise ValueError("run_backtest needs a 'signal' column (use evaluate() to run a strategy)")
    rows, total, pid = [], dict.fromkeys(_COUNTERS, 0), 0
    for sym, g in df.groupby("symbol", sort=True):
        tr, c = _run_symbol(g.reset_index(drop=True), cfg, pid)
        for r in tr:
            r["symbol"] = sym
        pid += len({r["position_id"] for r in tr}) + 1
        rows += tr
        total = {k: total[k] + c[k] for k in total}
    cols = ["position_id", "symbol", "side", "entry_time", "exit_time", "entry_price", "exit_price", "size",
            "bars_held", "gross_bp", "fee_bp", "funding_bp", "borrow_bp", "roll_bp", "net_bp", "exit"]
    trades = pd.DataFrame(rows, columns=cols)
    positions = to_positions(trades)
    daily = daily_pnl(trades, df["timestamp"].min(), df["timestamp"].max())
    quotes = _quote_report(df, bool(df["quotes_assumed"].any()))
    return BacktestResult(trades=trades, summary=summarise(positions, total, daily, cfg, quotes, trades),
                          frame=df, daily=daily, positions=positions)


def _utc(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def evaluate(fn: SignalFn, df: pd.DataFrame, cfg: EngineConfig = EngineConfig(), *,
             score_from=None, score_to=None, check: bool = True) -> BacktestResult:
    """The whole standardized run: eligibility, integrity checks, signals, gating, fills.

    ``score_from`` / ``score_to`` restrict the SCORED window while still letting
    the strategy see earlier rows as warm-up (positions outside it are forced flat).
    """
    df = prepare(df, cfg)
    df["eligible"] = eligibility(df, cfg)
    if check:
        check_no_lookahead(fn, df)
        check_symbol_order_invariance(fn, df)
    raw = signals(fn, df)
    keep = df["eligible"].to_numpy(bool).copy()
    if score_from is not None:
        keep &= (df["timestamp"] >= _utc(score_from)).to_numpy()
    if score_to is not None:
        keep &= (df["timestamp"] < _utc(score_to)).to_numpy()
    df = df.assign(signal_raw=raw, signal=np.where(keep, raw, 0))
    res = run_backtest(df, cfg)
    res.summary["integrity_checks"] = "passed" if check else "skipped"
    return res
