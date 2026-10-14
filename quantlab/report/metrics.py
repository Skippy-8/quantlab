"""Performance metrics from a daily return series (pure functions).

Conventions: returns are simple daily returns over CALENDAR days (days with no
position are 0, not missing), annualised with ``periods`` (365 for crypto, 252
for equities). A Sharpe computed only on days with trades overstates a strategy
that is mostly flat, so flat days count.
"""
from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd


def _clean(r: pd.Series) -> pd.Series:
    return pd.to_numeric(r, errors="coerce").fillna(0.0)


def equity_curve(r: pd.Series, start: float = 1.0) -> pd.Series:
    return start * (1 + _clean(r)).cumprod()


def drawdown(r: pd.Series) -> pd.Series:
    eq = equity_curve(r)
    return eq / eq.cummax() - 1


def drawdown_periods(r: pd.Series, top: int = 5) -> pd.DataFrame:
    """The ``top`` deepest drawdowns: start, trough, recovery (NaT if not recovered), depth, length."""
    dd = drawdown(r)
    out, in_dd, start = [], False, None
    for t, v in dd.items():
        if v < 0 and not in_dd:
            in_dd, start = True, t
        elif v >= 0 and in_dd:
            seg = dd[start:t]
            out.append({"start": start, "trough": seg.idxmin(), "recovered": t, "depth": float(seg.min()),
                        "days": int((t - start).days)})
            in_dd = False
    if in_dd:
        seg = dd[start:]
        out.append({"start": start, "trough": seg.idxmin(), "recovered": pd.NaT, "depth": float(seg.min()),
                    "days": int((dd.index[-1] - start).days)})
    return pd.DataFrame(out).sort_values("depth").head(top).reset_index(drop=True) if out else pd.DataFrame()


def summary(r: pd.Series, periods: int = 365, rf: float = 0.0) -> dict:
    r = _clean(r)
    n = len(r)
    if n < 2:
        return {}
    eq = equity_curve(r)
    years = n / periods
    total = float(eq.iloc[-1] - 1)
    cagr = float(eq.iloc[-1] ** (1 / years) - 1) if years > 0 and eq.iloc[-1] > 0 else float("nan")
    ex = r - rf / periods
    sd = r.std(ddof=1)
    down = r[r < 0]
    dsd = math.sqrt((down ** 2).sum() / n) if n else float("nan")
    dd = drawdown(r)
    mdd = float(dd.min())
    periods_dd = drawdown_periods(r, top=1)
    var95 = float(np.percentile(r, 5))
    tail = r[r <= var95]
    q95, q05 = np.percentile(r, 95), np.percentile(r, 5)
    monthly = (1 + r).groupby(r.index.to_period("M")).prod() - 1 if isinstance(r.index, pd.DatetimeIndex) else None
    return {
        "total_return": total, "cagr": cagr,
        "volatility": float(sd * math.sqrt(periods)),
        "sharpe": float(ex.mean() / sd * math.sqrt(periods)) if sd > 0 else float("nan"),
        "sortino": float(ex.mean() / dsd * math.sqrt(periods)) if dsd > 0 else float("nan"),
        "max_drawdown": mdd,
        "calmar": float(cagr / abs(mdd)) if mdd < 0 and math.isfinite(cagr) else float("nan"),
        "longest_drawdown_days": int(periods_dd["days"].iloc[0]) if len(periods_dd) else 0,
        "skew": float(r.skew()), "kurtosis": float(r.kurt() + 3),
        "var_95": var95, "cvar_95": float(tail.mean()) if len(tail) else float("nan"),
        "tail_ratio": float(abs(q95 / q05)) if q05 != 0 else float("nan"),
        "best_day": float(r.max()), "worst_day": float(r.min()),
        "positive_days": float((r[r != 0] > 0).mean()) if (r != 0).any() else float("nan"),
        "active_days": float((r != 0).mean()),
        "monthly_win_rate": float((monthly > 0).mean()) if monthly is not None and len(monthly) else float("nan"),
        "years": years,
    }


def monthly_table(r: pd.Series) -> pd.DataFrame:
    """Compounded return per month, years as rows, months as columns, plus the year."""
    r = _clean(r)
    m = (1 + r).groupby([r.index.year, r.index.month]).prod() - 1
    t = m.unstack(1).reindex(columns=range(1, 13))
    t.columns = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    t["Year"] = (1 + r).groupby(r.index.year).prod() - 1
    t.index.name = None
    return t


def rolling_sharpe(r: pd.Series, window: int = 90, periods: int = 365) -> pd.Series:
    r = _clean(r)
    return r.rolling(window).mean() / r.rolling(window).std() * math.sqrt(periods)


def benchmark_stats(r: pd.Series, b: pd.Series, periods: int = 365) -> dict:
    """Alpha, beta, correlation, tracking error, information ratio, up/down capture vs a benchmark."""
    d = pd.concat([_clean(r), _clean(b)], axis=1, join="inner").dropna()
    d.columns = ["s", "b"]
    if len(d) < 10 or d["b"].var() == 0:
        return {}
    beta = float(d["s"].cov(d["b"]) / d["b"].var())
    alpha = float((d["s"].mean() - beta * d["b"].mean()) * periods)
    active = d["s"] - d["b"]
    te = float(active.std() * math.sqrt(periods))
    up, dn = d[d["b"] > 0], d[d["b"] < 0]
    return {"alpha": alpha, "beta": beta, "correlation": float(d["s"].corr(d["b"])), "tracking_error": te,
            "information_ratio": float(active.mean() * periods / te) if te > 0 else float("nan"),
            "up_capture": float(up["s"].mean() / up["b"].mean()) if len(up) else float("nan"),
            "down_capture": float(dn["s"].mean() / dn["b"].mean()) if len(dn) else float("nan")}


def trade_stats(positions: pd.DataFrame) -> dict:
    """From the engine's per-position net (bp)."""
    if positions is None or positions.empty:
        return {}
    x = positions["net_bp"]
    w, lo = x[x > 0], x[x <= 0]
    return {"trades": int(len(x)), "win_rate": float((x > 0).mean()),
            "avg_win_bp": float(w.mean()) if len(w) else 0.0, "avg_loss_bp": float(lo.mean()) if len(lo) else 0.0,
            "payoff_ratio": float(w.mean() / -lo.mean()) if len(w) and len(lo) and lo.mean() < 0 else float("nan"),
            "expectancy_bp": float(x.mean()),
            "profit_factor": float(w.sum() / -lo.sum()) if lo.sum() < 0 else float("nan"),
            "avg_bars_held": float(positions["bars_held"].mean()),
            "longest_losing_streak": int(max((len(list(g)) for k, g in itertools.groupby(x <= 0) if k), default=0))}
