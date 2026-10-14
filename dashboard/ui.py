"""Shared building blocks for every dashboard page: the header, theme-aware charts,
and the pickers (data, strategy, exits, costs, sizing) so every page asks the same
questions the same way."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantlab.data.lake import Lake  # noqa: E402
from quantlab.engine import EngineConfig, ExitRules  # noqa: E402
from quantlab.portfolio import Sizing  # noqa: E402
from quantlab.report.theme import palette  # noqa: E402
from quantlab.research.registry import home  # noqa: E402
from quantlab.rules import EXAMPLES, RuleError, RuleStrategy  # noqa: E402
from quantlab.strategies import REGISTRY  # noqa: E402

RULES_DIR = home() / "strategies"


def is_dark() -> bool:
    try:
        return st.context.theme.type == "dark"
    except Exception:
        return False


def pal() -> dict:
    return palette(is_dark())


def header(eyebrow: str, title: str, lede: str = "") -> None:
    p = pal()
    st.html(f"""<div style="margin:-0.5rem 0 1.1rem 0">
      <div style="font:500 0.72rem 'IBM Plex Mono',monospace;letter-spacing:.14em;text-transform:uppercase;
                  color:{p['accent']}">{eyebrow}</div>
      <div style="font:650 2rem/1.15 'IBM Plex Sans',sans-serif;margin:.25rem 0 .35rem 0;text-wrap:balance">{title}</div>
      <div style="color:{p['muted']};max-width:72ch;font-size:0.98rem;line-height:1.55">{lede}</div></div>""")


def chart(fig, key: str | None = None) -> None:
    st.plotly_chart(fig, theme=None, width="stretch", key=key, config={"displaylogo": False})


def kpis(items: list[tuple[str, str, str | None]]) -> None:
    """items: (label, value, help)."""
    cols = st.columns(len(items))
    for c, (label, value, hlp) in zip(cols, items, strict=True):
        c.metric(label, value, help=hlp, border=True)


def fmt(v, kind: str = "num", digits: int = 2) -> str:
    try:
        if v is None or pd.isna(v):
            return "—"
    except (TypeError, ValueError):
        pass
    if kind == "pct":
        return f"{v * 100:+.{digits - 1}f}%"
    if kind == "pct0":
        return f"{v * 100:.1f}%"
    if kind == "bp":
        return f"{v:+.1f} bp"
    if kind == "usd":
        return f"−${-v:,.0f}" if v < 0 else f"${v:,.0f}"
    if kind == "int":
        return f"{int(v):,}"
    return f"{v:.{digits}f}"


def empty(msg: str) -> None:
    st.info(msg, icon=":material/info:")


# ── data ───────────────────────────────────────────────────────────────────

def ensure_demo_data() -> None:
    lake = Lake()
    if not lake.datasets():
        from quantlab.data.synthetic import panel
        lake.write("synthetic", "bars", panel(n_bars=4000))


def data_picker(key: str, container=None, default_symbols: int = 6):
    """Dataset, symbols and date range. Returns (df, label) or (None, None)."""
    c = container or st.sidebar
    lake = Lake()
    names = [f"{s}/{d}" for s, d in lake.datasets()]
    if not names:
        c.warning("The lake is empty.")
        if c.button("Load demo data", key=f"{key}_demo", type="primary"):
            ensure_demo_data()
            st.rerun()
        return None, None
    ds = c.selectbox("Dataset", names, key=f"{key}_ds", help="source/dataset in the Parquet lake")
    src, dset = ds.split("/", 1)
    syms = lake.symbols(src, dset)
    pick = c.multiselect("Symbols", syms, default=syms[:default_symbols], key=f"{key}_syms")
    cat = lake.catalog()
    row = cat[(cat["source"] == src) & (cat["dataset"] == dset)].iloc[0]
    lo, hi = row["first"].date(), row["last"].date()
    rng = c.date_input("Period", (lo, hi), min_value=lo, max_value=hi, key=f"{key}_rng")
    start, end = (rng if isinstance(rng, tuple) and len(rng) == 2 else (lo, hi))
    if not pick:
        return None, None
    df = lake.read(src, dset, pick, start=str(start), end=str(pd.Timestamp(end) + pd.Timedelta(days=1)))
    return df, f"{ds} · {len(pick)} symbols · {start} → {end}"


# ── strategies ─────────────────────────────────────────────────────────────

def saved_rules() -> list[RuleStrategy]:
    out = list(EXAMPLES)
    if RULES_DIR.exists():
        for f in sorted(RULES_DIR.glob("*.yaml")):
            try:
                out.append(RuleStrategy.from_yaml(f.read_text()))
            except RuleError:
                continue
    return out


def _param_inputs(defaults: dict, key: str, c) -> dict:
    out = {}
    cols = c.columns(2)
    for i, (k, v) in enumerate(defaults.items()):
        box = cols[i % 2]
        if isinstance(v, bool):
            out[k] = box.toggle(k.replace("_", " "), value=v, key=f"{key}_{k}")
        elif isinstance(v, int):
            out[k] = int(box.number_input(k.replace("_", " "), value=v, step=1, key=f"{key}_{k}"))
        else:
            out[k] = float(box.number_input(k.replace("_", " "), value=float(v), step=0.1, key=f"{key}_{k}"))
    return out


def strategy_picker(key: str, container=None):
    """Returns (label, signal_fn, params, rule_exits or None, spec_id)."""
    c = container or st.sidebar
    kind = c.segmented_control("Strategy type", ["Templates", "No-code rules"], default="Templates",
                               key=f"{key}_kind")
    if kind == "No-code rules":
        rules = saved_rules()
        names = [r.name for r in rules]
        name = c.selectbox("Rule set", names, key=f"{key}_rule")
        r = rules[names.index(name)]
        with c.expander("Rules", expanded=False):
            for lbl, expr in (("Long entry", r.long_entry), ("Long exit", r.long_exit),
                              ("Short entry", r.short_entry), ("Short exit", r.short_exit)):
                if expr:
                    st.markdown(f"**{lbl}**  \n`{expr}`")
        return r.name, r.signal_fn(), {"rules": {k: v for k, v in r.__dict__.items() if k != 'exits'}}, \
            (r.exit_rules() if r.exits else None), f"rules:{r.name}"
    sname = c.selectbox("Template", sorted(REGISTRY), format_func=lambda k: REGISTRY[k].description,
                        key=f"{key}_tpl")
    spec = REGISTRY[sname]
    params = _param_inputs(spec.defaults, f"{key}_{sname}", c)
    return spec.description, spec.make(**params), params, None, sname


def exits_form(key: str, preset: ExitRules | None = None, container=None) -> ExitRules:
    c = container or st.sidebar
    p = preset or ExitRules()
    with c.expander("Exits: stops and targets", expanded=bool(preset and preset.active)):
        unit = st.segmented_control("Distances in", ["pct", "atr"], default=p.unit, key=f"{key}_unit",
                                    format_func=lambda u: "% of price" if u == "pct" else "× ATR(14)")
        scale = 100.0 if unit == "pct" else 1.0
        sl = st.number_input("Stop loss", value=float((p.stop_loss or 0) * scale), step=0.5, key=f"{key}_sl",
                             help="0 = none")
        tr = st.number_input("Trailing stop", value=float((p.trailing_stop or 0) * scale), step=0.5, key=f"{key}_tr")
        n_tp = st.number_input("Profit targets", value=len(p.take_profits), min_value=0, max_value=4,
                               key=f"{key}_ntp")
        tps = []
        for i in range(int(n_tp)):
            a, b = st.columns(2)
            d0, f0 = (p.take_profits[i] if i < len(p.take_profits) else ((i + 1) * (0.02 if unit == "pct" else 1.0),
                                                                           round(1 / n_tp, 2)))
            d = a.number_input(f"Target {i + 1} distance", value=float(d0 * scale), step=0.5, key=f"{key}_tp{i}")
            f = b.number_input(f"Target {i + 1} size", value=float(f0), step=0.05, min_value=0.05, max_value=1.0,
                               key=f"{key}_tf{i}")
            tps.append((d / scale, f))
        be = st.number_input("Breakeven after target #", value=int(p.breakeven_after or 0), min_value=0,
                             max_value=4, key=f"{key}_be", help="0 = never")
        ts = st.number_input("Time stop (bars)", value=int(p.time_stop_bars or 0), min_value=0, key=f"{key}_ts")
    return ExitRules(unit=unit or "pct", stop_loss=(sl / scale) or None, take_profits=tuple(tps),
                     breakeven_after=int(be) or None, trailing_stop=(tr / scale) or None,
                     time_stop_bars=int(ts) or None)


def costs_form(key: str, exits: ExitRules, container=None) -> EngineConfig:
    c = container or st.sidebar
    with c.expander("Costs and calendar", expanded=False):
        a, b = st.columns(2)
        maker = a.number_input("Maker fee (bp)", value=2.0, step=0.5, key=f"{key}_mk")
        taker = b.number_input("Taker fee (bp)", value=5.0, step=0.5, key=f"{key}_tk")
        spread = a.number_input("Assumed half-spread (bp)", value=2.0, step=0.5, key=f"{key}_sp",
                                help="Used only when the data has no bid/ask")
        borrow = b.number_input("Short borrow (bp/yr)", value=0.0, step=25.0, key=f"{key}_br")
        dpy = st.segmented_control("Calendar", [365, 252], default=365, key=f"{key}_dpy",
                                   format_func=lambda d: "24/7 (365 d)" if d == 365 else "Exchange (252 d)")
    return EngineConfig(maker_fee_bp=maker, taker_fee_bp=taker, assumed_half_spread_bp=spread,
                        short_borrow_bp_per_year=borrow, days_per_year=int(dpy or 365), exits=exits)


def sizing_form(key: str, container=None) -> Sizing:
    c = container or st.sidebar
    with c.expander("Capital and sizing", expanded=False):
        method = st.selectbox("Sizing", ["fixed_fraction", "fixed_notional", "vol_target", "risk_per_trade"],
                              key=f"{key}_m", format_func=lambda m: {
                                  "fixed_fraction": "Fixed fraction of equity", "fixed_notional": "Fixed dollar amount",
                                  "vol_target": "Volatility target", "risk_per_trade": "Risk per trade (needs a stop)"}[m])
        cap = st.number_input("Starting capital ($)", value=100_000, step=10_000, key=f"{key}_cap")
        a, b = st.columns(2)
        frac = a.number_input("Fraction per position", value=0.10, step=0.05, key=f"{key}_f")
        notional = b.number_input("Dollars per position", value=10_000, step=1_000, key=f"{key}_n")
        tvol = a.number_input("Target vol (ann.)", value=0.15, step=0.05, key=f"{key}_tv")
        risk = b.number_input("Risk per trade", value=0.01, step=0.005, format="%.3f", key=f"{key}_r")
        lev = a.number_input("Max leverage", value=1.0, step=0.5, key=f"{key}_l")
        maxpos = b.number_input("Max open positions", value=0, min_value=0, key=f"{key}_mp", help="0 = no limit")
    return Sizing(method=method, initial_capital=float(cap), fraction=frac, notional=float(notional),
                  target_vol=tvol, risk_fraction=risk, max_leverage=lev, max_positions=int(maxpos) or None)
