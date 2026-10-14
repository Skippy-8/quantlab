"""Deflated Sharpe, PSR and multiple-testing corrections.

Why raw Sharpe misleads: picking the best of many tried strategies manufactures
Sharpe, short samples overstate it, and negatively skewed, fat-tailed returns
(stopped-out strategies, short options) make the textbook standard error too
small. The functions here correct for all three.

Sources:
* Bailey & Lopez de Prado (2014), "The Deflated Sharpe Ratio", Journal of
  Portfolio Management 40(5): PSR, the expected-maximum benchmark SR*, DSR.
* Harvey & Liu (2015), "Backtesting", JPM 42(1): Holm and BHY haircuts.
* Bailey, Borwein, Lopez de Prado & Zhu (2014), "Pseudo-Mathematics and
  Financial Charlatanism": the minimum backtest length.

Pure functions, numpy only (no scipy dependency; the normal CDF and quantile
are implemented directly and tested against known values).
"""
from __future__ import annotations

import math
from typing import Iterable, Optional, Sequence

import numpy as np

EULER_GAMMA = 0.5772156649015329


# ── the normal distribution ────────────────────────────────────────────────

def norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """Inverse normal CDF (Acklam's rational approximation, |error| < 1.15e-9)."""
    if not 0.0 < p < 1.0:
        if p <= 0.0:
            return -math.inf
        if p >= 1.0:
            return math.inf
        return float("nan")
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00)
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
        (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def log_sf(z: float) -> float:
    """log(1 - Phi(z)), accurate in the far tail.

    ``1 - norm_cdf(z)`` underflows to 0 above z ~ 8.3, which makes p-values of 0
    and quantiles of +inf. Working in logs keeps the tail usable (the Harvey-Liu
    haircut is otherwise non-monotone in sample length)."""
    if z < 8.0:
        v = 1.0 - norm_cdf(z)
        return math.log(v) if v > 0 else -math.inf
    corr = 1.0 - 1.0 / (z * z) + 3.0 / (z ** 4)
    return -0.5 * z * z - math.log(z) - 0.5 * math.log(2.0 * math.pi) + math.log(max(corr, 1e-12))


def ppf_from_log_sf(target: float) -> float:
    """The z whose upper-tail log-probability is ``target`` (bisection; monotone)."""
    if target >= math.log(0.5):
        return norm_ppf(1.0 - math.exp(target))
    lo, hi = 0.0, 40.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if log_sf(mid) > target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ── moments and PSR ────────────────────────────────────────────────────────

def moments(returns: Sequence[float]) -> dict:
    """Per-observation Sharpe, skew and RAW kurtosis (3.0 for a normal, not excess)."""
    x = np.asarray([v for v in returns if v is not None and np.isfinite(v)], dtype=float)
    n = x.size
    if n < 3:
        return {"n": int(n), "sr": 0.0, "skew": 0.0, "kurt": 3.0, "sd": 0.0}
    mu, sd = float(x.mean()), float(x.std(ddof=1))
    # a constant series has sd ~1e-18, not 0: judge sd against the scale of the data
    if sd <= 1e-12 * max(abs(mu), float(np.abs(x).mean()), 1e-300):
        return {"n": int(n), "sr": 0.0, "skew": 0.0, "kurt": 3.0, "sd": 0.0}
    z = (x - mu) / sd
    return {"n": int(n), "sr": mu / sd, "sd": sd, "skew": float((z ** 3).mean()), "kurt": float((z ** 4).mean())}


def psr(sr: float, n: float, skew: float, kurt: float, sr_benchmark: float = 0.0) -> float:
    """Probabilistic Sharpe Ratio: P(true SR > benchmark).

    ``sr`` and ``sr_benchmark`` must share ``n``'s periodicity (per-observation SR
    with n observations, or annualised SR with n years). The standard error
    carries skew and kurtosis, so negative skew and fat tails widen it:
    ``se = sqrt((1 - skew*SR + (kurt-1)/4 * SR^2) / (n-1))``."""
    if n <= 1.0:
        return float("nan")
    var = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr
    if var <= 0:
        return float("nan")
    return norm_cdf((sr - sr_benchmark) / math.sqrt(var / (n - 1)))


def expected_max_sr(n_trials: int, var_trial_sr: float) -> float:
    """SR*: the Sharpe a skill-less best-of-N is expected to reach."""
    if n_trials < 2 or var_trial_sr <= 0:
        return 0.0
    s = math.sqrt(var_trial_sr)
    a = norm_ppf(1.0 - 1.0 / n_trials)
    b = norm_ppf(1.0 - 1.0 / (n_trials * math.e))
    return s * ((1.0 - EULER_GAMMA) * a + EULER_GAMMA * b)


def dsr(returns: Optional[Sequence[float]] = None, *, sr: Optional[float] = None, n: Optional[float] = None,
        skew: float = 0.0, kurt: float = 3.0, n_trials: int = 1, var_trial_sr: Optional[float] = None,
        trial_srs: Optional[Iterable[float]] = None) -> dict:
    """Deflated Sharpe Ratio = PSR evaluated at the expected-max benchmark SR*.

    Give ``returns`` (moments computed here) or ``sr``/``n``/``skew``/``kurt``, and
    either ``var_trial_sr`` or ``trial_srs``: the Sharpes of EVERY trial in the
    family, abandoned ones included (the trial registry exists to supply them)."""
    if returns is not None:
        m = moments(returns)
        sr, n, skew, kurt = m["sr"], m["n"], m["skew"], m["kurt"]
    if sr is None or n is None:
        raise ValueError("need returns, or sr and n")
    if var_trial_sr is None:
        if trial_srs is not None:
            arr = np.asarray([v for v in trial_srs if v is not None and np.isfinite(v)], dtype=float)
            var_trial_sr = float(arr.var(ddof=1)) if arr.size > 1 else 0.0
            n_trials = max(n_trials, int(arr.size))
        else:
            var_trial_sr = 0.0
    sr_star = expected_max_sr(n_trials, var_trial_sr)
    return {"sr": float(sr), "n": float(n), "skew": float(skew), "kurt": float(kurt),
            "n_trials": int(n_trials), "var_trial_sr": float(var_trial_sr), "sr_star": float(sr_star),
            "psr_vs_zero": psr(sr, float(n), skew, kurt, 0.0), "dsr": psr(sr, float(n), skew, kurt, sr_star)}


# ── multiple testing ───────────────────────────────────────────────────────

def holm(pvals: Sequence[float], alpha: float = 0.05) -> dict:
    """Holm step-down: controls the family-wise error rate."""
    p = np.asarray(pvals, dtype=float)
    k = p.size
    adj, running = np.empty(k), 0.0
    for i, idx in enumerate(np.argsort(p)):
        running = max(running, (k - i) * p[idx])
        adj[idx] = min(running, 1.0)
    return {"method": "holm", "alpha": alpha, "k": int(k), "p_adjusted": adj.tolist(),
            "reject": (adj < alpha).tolist(), "n_reject": int((adj < alpha).sum())}


def bhy(pvals: Sequence[float], alpha: float = 0.05) -> dict:
    """Benjamini-Hochberg-Yekutieli: false discovery rate under ARBITRARY dependence.

    The c(k) = sum(1/i) factor is what keeps it valid when trials are correlated,
    which strategy trials always are. Because of it, BHY can reject fewer
    hypotheses than Holm when k is small; that is correct, not a bug."""
    p = np.asarray(pvals, dtype=float)
    k = p.size
    if k == 0:
        return {"method": "bhy", "alpha": alpha, "k": 0, "p_adjusted": [], "reject": [], "n_reject": 0}
    c = float(np.sum(1.0 / np.arange(1, k + 1)))
    adj, running = np.empty(k), 1.0
    for i, idx in enumerate(np.argsort(p)[::-1]):
        running = min(running, p[idx] * k * c / (k - i))
        adj[idx] = min(running, 1.0)
    return {"method": "bhy", "alpha": alpha, "k": int(k), "c_k": c, "p_adjusted": adj.tolist(),
            "reject": (adj < alpha).tolist(), "n_reject": int((adj < alpha).sum())}


def haircut_sharpe(sr_annual: float, years: float, n_trials: int, method: str = "bhy") -> dict:
    """Harvey-Liu haircut: the annualised Sharpe that survives a multiple-testing adjustment.

    Units: ANNUALISED Sharpe and a sample length in YEARS (t = SR * sqrt(years)).
    Reproduces the paper's worked example: SR 0.92 over 20 years at 200 trials
    -> ~0.44 (a ~52% haircut). The haircut is nonlinear: marginal Sharpes are cut
    to nearly zero while high ones barely move."""
    if years < 0.1 or sr_annual <= 0:
        return {"sr": float(sr_annual), "haircut_sr": 0.0, "haircut_pct": 1.0, "method": method,
                "n_trials": int(n_trials)}
    t = sr_annual * math.sqrt(years)
    log_p = math.log(2.0) + log_sf(abs(t))
    if method in ("bonferroni", "holm"):
        log_mult = math.log(max(n_trials, 1))
    else:
        c = float(np.sum(1.0 / np.arange(1, n_trials + 1))) if n_trials >= 1 else 1.0
        log_mult = math.log(max(n_trials, 1)) + math.log(c)
    log_p_adj = min(log_p + log_mult, 0.0)
    t_adj = ppf_from_log_sf(log_p_adj - math.log(2.0))
    sr_adj = max(t_adj, 0.0) / math.sqrt(years)
    return {"sr": float(sr_annual), "years": float(years), "t": float(t),
            "p": float(math.exp(log_p)) if log_p > -700 else 0.0,
            "p_adjusted": float(math.exp(log_p_adj)) if log_p_adj > -700 else 0.0,
            "haircut_sr": float(sr_adj), "haircut_pct": float(1.0 - sr_adj / sr_annual),
            "method": method, "n_trials": int(n_trials)}


def noise_bar(n_trials: int, floor: float = 0.0) -> float:
    """The |t| a best-of-N search reaches from noise alone: sqrt(2 ln N) (MinBTL bound),
    never below ``floor``."""
    return max(floor, math.sqrt(2.0 * math.log(max(n_trials, 1))))


def minbtl_years(n_trials: int, target_sr: float = 1.0) -> float:
    """Minimum backtest length (years) before noise alone is expected to deliver an
    annualised Sharpe of ``target_sr`` from a best-of-N search: 2 ln N / SR^2.
    Necessary, not sufficient."""
    if n_trials < 2 or target_sr <= 0:
        return 0.0
    return 2.0 * math.log(n_trials) / (target_sr ** 2)
