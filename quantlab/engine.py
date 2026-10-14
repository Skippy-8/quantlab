"""The standardized scoring engine.

A strategy decides WHAT to trade; this module decides HOW it fills, and it is
the same for every strategy. Keeping execution out of strategy code is what
makes two backtests comparable and stops a strategy from quietly assuming a
fill the market would not have given it.

Execution model
---------------
* ``signal[t]`` is the position wanted after bar ``t``'s close (-1, 0 or +1).
  Nothing executes on bar ``t`` itself.
* Every entry and exit is a limit order on its own side of the book: a buy
  rests at the bid, a sell at the ask, re-pegged to the new touch at each close.
* A resting order fills only when a LATER bar trades strictly THROUGH its price
  (``low < bid`` for a buy, ``high > ask`` for a sell). Touching the price is
  not a fill, because queue position is unknowable. Fills pay the maker fee.
* An entry not filled within ``entry_ttl_bars`` is cancelled and counted as a
  missed trade, never booked.
* An exit not filled within ``exit_ttl_bars`` crosses the spread at that close
  and pays the taker fee. A position open at the end of the data is closed the
  same way (``eod``).
* Funding: if the frame has a ``funding_rate`` column (the rate settled at that
  bar), every settlement the position is open through is booked as
  ``-side * rate``.
* P&L is in basis points of notional, one unit per trade:
  ``side * (exit / entry - 1) * 1e4 - fees + funding``.

Quotes: if the data has no ``bbo_bid`` / ``bbo_ask`` columns the engine builds
them as ``close -/+ assumed_half_spread_bp`` and says so in the summary. A
constant synthetic spread means the close is always the mid, so signals that
read where the close sits inside the book carry no information. The summary
flags that too.

Integrity checks (run by :func:`evaluate` before any P&L is computed)
---------------------------------------------------------------------
* :func:`check_no_lookahead` - signals at or before time T must not change when
  rows after T are added. Catches ``shift(-k)``, centred windows, ``bfill`` and
  every full-sample statistic.
* :func:`check_symbol_order_invariance` - signals must not depend on the order
  of the symbol blocks. Catches rolling/shift/diff without a ``groupby``, which
  lets one symbol's rows bleed into the next.
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
class EngineConfig:
    maker_fee_bp: float = 2.0
    taker_fee_bp: float = 5.0
    entry_ttl_bars: int = 3
    exit_ttl_bars: int = 3
    # Used only when the data carries no bid/ask columns.
    assumed_half_spread_bp: float = 2.0
    # Point-in-time eligibility, computed from each symbol's own past only.
    min_history_bars: int = 0
    volume_window_bars: int = 24
    min_window_quote_volume: float = 0.0
    # Calendar days per year for the annualised Sharpe (365 crypto, 252 equities).
    days_per_year: int = 365

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    summary: dict
    frame: pd.DataFrame | None = None
    daily: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))


# ── preparation ────────────────────────────────────────────────────────────

def prepare(df: pd.DataFrame, cfg: EngineConfig = EngineConfig()) -> pd.DataFrame:
    """Validate columns, sort by (symbol, timestamp), add quotes if missing."""
    out = df.copy()
    if "timestamp" not in out.columns and "ts_ms" in out.columns:
        out["timestamp"] = pd.to_datetime(out["ts_ms"], unit="ms", utc=True)
    if "volume" not in out.columns and "quote_volume" in out.columns:
        out["volume"] = out["quote_volume"]
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
    vol = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
    if "quote_volume" in df.columns:
        vol = pd.to_numeric(df["quote_volume"], errors="coerce").fillna(0.0)
    w = max(int(cfg.volume_window_bars), 1)
    qv = vol.groupby(df["symbol"], sort=False).transform(lambda s: s.rolling(w, min_periods=w).sum())
    age = df.groupby("symbol", sort=False).cumcount()
    ok = (age >= cfg.min_history_bars)
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


def _run_symbol(g: pd.DataFrame, cfg: EngineConfig) -> tuple[list[dict], dict]:
    n = len(g)
    ts = g["timestamp"].to_numpy()
    bid_a, ask_a = g["bbo_bid"].to_numpy(float), g["bbo_ask"].to_numpy(float)
    qok = (np.isfinite(bid_a) & np.isfinite(ask_a) & (bid_a > 0) & (bid_a < ask_a)).tolist()
    hi, lo = g["high"].to_numpy(float).tolist(), g["low"].to_numpy(float).tolist()
    cl, bid, ask = g["close"].to_numpy(float).tolist(), bid_a.tolist(), ask_a.tolist()
    sig = clean_signal(g["signal"].to_numpy()).to_numpy().tolist()
    cf = None
    if "funding_rate" in g.columns:
        cf = np.concatenate([[0.0], np.cumsum(np.nan_to_num(g["funding_rate"].to_numpy(float)))])
    c = dict.fromkeys(_COUNTERS, 0)
    c["bars"] = n
    trades: list[dict] = []
    pos, entry_px, entry_t, order = 0, None, None, None

    def close(px, t, fee, kind, last_settle):
        gross = pos * (px / entry_px - 1.0) * 1e4
        x = min(last_settle, n - 1)
        fund = 0.0
        if cf is not None and x >= entry_t + 1:
            fund = -pos * float(cf[x + 1] - cf[entry_t + 1]) * 1e4
        trades.append({"side": "LONG" if pos > 0 else "SHORT", "entry_time": ts[entry_t], "exit_time": ts[t],
                       "entry_price": entry_px, "exit_price": px, "bars_held": int(t - entry_t),
                       "gross_bp": gross, "fee_bp": cfg.maker_fee_bp + fee, "funding_bp": fund,
                       "net_bp": gross - cfg.maker_fee_bp - fee + fund, "exit": kind})

    for t in range(n):
        # 1. an order placed at an earlier close can fill inside bar t
        if order is not None:
            px = order["px"]
            if (lo[t] < px) if order["side"] > 0 else (hi[t] > px):
                if order["kind"] == "entry":
                    pos, entry_px, entry_t = order["side"], px, t
                    c["entries_filled"] += 1
                else:
                    close(px, t, cfg.maker_fee_bp, "maker", t)
                    pos = 0
                order = None
        if pos != 0:
            c["bars_in_market"] += 1
        # 2. decisions at the close of bar t
        target, quote_ok = sig[t], qok[t]
        if order is not None:
            order["age"] += 1
            if order["kind"] == "entry":
                if pos != 0 or target != order["side"]:
                    order, c["entries_cancelled"] = None, c["entries_cancelled"] + 1
                elif order["age"] >= cfg.entry_ttl_bars:
                    order, c["entries_expired"] = None, c["entries_expired"] + 1
            else:
                if target == pos:
                    order, c["exits_cancelled"] = None, c["exits_cancelled"] + 1
                elif order["age"] >= cfg.exit_ttl_bars:
                    px = (bid[t] if pos > 0 else ask[t]) if quote_ok else cl[t]
                    close(px, t, cfg.taker_fee_bp, "taker", t + 1)
                    pos, order = 0, None
            if order is not None and quote_ok:
                order["px"] = bid[t] if order["side"] > 0 else ask[t]
        if order is None and quote_ok:
            if pos != 0 and target != pos:
                order = {"kind": "exit", "side": -pos, "px": bid[t] if pos < 0 else ask[t], "age": 0}
            elif pos == 0 and target != 0:
                order = {"kind": "entry", "side": target, "px": bid[t] if target > 0 else ask[t], "age": 0}
                c["entries_placed"] += 1
    if pos != 0:
        t = n - 1
        close((bid[t] if pos > 0 else ask[t]) if qok[t] else cl[t], t, cfg.taker_fee_bp, "eod", t)
    return trades, c


def _quote_report(df: pd.DataFrame, assumed: bool) -> dict:
    bid, ask, cl = (df[c].to_numpy(float) for c in ("bbo_bid", "bbo_ask", "close"))
    ok = np.isfinite(bid) & np.isfinite(ask) & np.isfinite(cl) & (bid > 0) & (bid < ask) & (cl > 0)
    sp = (ask[ok] - bid[ok]) / cl[ok] * 1e4
    const = bool(sp.size and np.ptp(sp) < 1e-6)
    note = ""
    if assumed:
        note = "no quotes in the data: a constant assumed spread was used"
    elif const:
        note = "constant spread: the quotes look synthetic (the close is always the mid)"
    return {"assumed": bool(assumed), "bars_without_valid_quote": int((~ok).sum()),
            "median_spread_bp": round(float(np.median(sp)), 4) if sp.size else None,
            "constant_spread": const, "note": note}


def daily_pnl(trades: pd.DataFrame, start, end) -> pd.Series:
    """Net bp per CALENDAR day (days without an exit are 0), keyed by exit date."""
    days = pd.date_range(pd.Timestamp(start).floor("D"), pd.Timestamp(end).floor("D"), freq="D")
    if trades.empty:
        return pd.Series(0.0, index=days)
    by = trades["net_bp"].groupby(pd.to_datetime(trades["exit_time"], utc=True).dt.floor("D")).sum()
    return by.reindex(days, fill_value=0.0)


def summarise(trades: pd.DataFrame, counters: dict, daily: pd.Series, cfg: EngineConfig,
              quotes: dict | None = None) -> dict:
    s = {"trades": int(len(trades)), **{k: int(v) for k, v in counters.items()}, "quotes": quotes or {},
         "entry_fill_rate": round(counters["entries_filled"] / counters["entries_placed"], 4)
         if counters["entries_placed"] else None,
         "time_in_market": round(counters["bars_in_market"] / max(counters["bars"], 1), 4),
         "config": cfg.to_dict()}
    if trades.empty:
        return s
    net = trades["net_bp"]
    traded = daily[daily != 0]
    half = len(daily) // 2
    sd_traded = traded.std(ddof=1) if len(traded) > 1 else float("nan")
    sd_cal = daily.std(ddof=1) if len(daily) > 1 else float("nan")
    wins, losses = net[net > 0].sum(), -net[net < 0].sum()
    equity = daily.cumsum()
    s.update({
        "mean_net_bp_per_trade": round(float(net.mean()), 3),
        "median_net_bp_per_trade": round(float(net.median()), 3),
        "mean_gross_bp_per_trade": round(float(trades["gross_bp"].mean()), 3),
        "mean_funding_bp_per_trade": round(float(trades["funding_bp"].mean()), 3),
        "win_rate": round(float((net > 0).mean()), 4),
        "profit_factor": round(float(wins / losses), 4) if losses > 0 else None,
        "sum_net_bp": round(float(net.sum()), 2),
        "exits": {k: int(v) for k, v in trades["exit"].value_counts().items()},
        "mean_bars_held": round(float(trades["bars_held"].mean()), 2),
        "days_traded": int(len(traded)),
        "calendar_days": int(len(daily)),
        # t on the daily series of days that traded; Sharpe over EVERY calendar day
        # (a Sharpe over trading days only overstates a strategy that is mostly flat)
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
    rows, total = [], dict.fromkeys(_COUNTERS, 0)
    for sym, g in df.groupby("symbol", sort=True):
        tr, c = _run_symbol(g.reset_index(drop=True), cfg)
        for r in tr:
            r["symbol"] = sym
        rows += tr
        total = {k: total[k] + c[k] for k in total}
    cols = ["symbol", "side", "entry_time", "exit_time", "entry_price", "exit_price", "bars_held",
            "gross_bp", "fee_bp", "funding_bp", "net_bp", "exit"]
    trades = pd.DataFrame(rows, columns=cols)
    daily = daily_pnl(trades, df["timestamp"].min(), df["timestamp"].max())
    quotes = _quote_report(df, bool(df["quotes_assumed"].any()))
    return BacktestResult(trades=trades, summary=summarise(trades, total, daily, cfg, quotes),
                          frame=df, daily=daily)


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
        keep &= (df["timestamp"] >= pd.Timestamp(score_from, tz="UTC")).to_numpy()
    if score_to is not None:
        keep &= (df["timestamp"] < pd.Timestamp(score_to, tz="UTC")).to_numpy()
    df = df.assign(signal_raw=raw, signal=np.where(keep, raw, 0))
    res = run_backtest(df, cfg)
    res.summary["integrity_checks"] = "passed" if check else "skipped"
    return res
