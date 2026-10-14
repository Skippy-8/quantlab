from __future__ import annotations

import pandas as pd
import streamlit as st
from ui import RULES_DIR, data_picker, empty, header, saved_rules

from quantlab.engine import check_no_lookahead, check_symbol_order_invariance, prepare
from quantlab.indicators import REGISTRY as IND
from quantlab.rules import RuleError, RuleStrategy

header("Build", "Strategy Builder",
       "Write a strategy as rules, without code. Every indicator is computed per symbol and is causal, and rule "
       "text is parsed, never executed, so a rule file cannot run anything but arithmetic on your data.")

rules = saved_rules()
names = ["New strategy"] + [r.name for r in rules]
pick = st.selectbox("Start from", names, index=1)
base = RuleStrategy("My strategy", long_entry="rsi(14) < 30 and close > sma(200)", long_exit="rsi(14) > 55") \
    if pick == "New strategy" else rules[names.index(pick) - 1]

left, right = st.columns([3, 2], gap="large")
with left:
    name = st.text_input("Name", value=base.name)
    desc = st.text_input("Description", value=base.description)
    a, b = st.columns(2)
    le = a.text_area("Long entry", value=base.long_entry or "", height=90)
    lx = b.text_area("Long exit", value=base.long_exit or "", height=90,
                     help="Empty: hold exactly while the entry condition is true")
    se = a.text_area("Short entry", value=base.short_entry or "", height=90)
    sx = b.text_area("Short exit", value=base.short_exit or "", height=90)
    with st.expander("Mechanical exits (optional)", expanded=bool(base.exits)):
        e = dict(base.exits or {})
        c1, c2, c3 = st.columns(3)
        unit = c1.selectbox("Unit", ["pct", "atr"], index=["pct", "atr"].index(e.get("unit", "pct")))
        sl = c2.number_input("Stop loss", value=float(e.get("stop_loss") or 0.0), step=0.005 if unit == "pct" else 0.5,
                             format="%.3f")
        ts = c3.number_input("Time stop (bars)", value=int(e.get("time_stop_bars") or 0), min_value=0)
        tp_text = st.text_input("Profit targets as distance:fraction, comma separated",
                                value=", ".join(f"{d}:{f}" for d, f in e.get("take_profits", [])))
        be = st.number_input("Breakeven after target #", value=int(e.get("breakeven_after") or 0), min_value=0)
    exits = {k: v for k, v in {"unit": unit, "stop_loss": sl or None, "time_stop_bars": ts or None,
                               "breakeven_after": be or None}.items() if v}
    if tp_text.strip():
        try:
            exits["take_profits"] = [[float(x.split(":")[0]), float(x.split(":")[1])] for x in tp_text.split(",")]
        except (ValueError, IndexError):
            st.error("Targets must look like `0.02:0.5, 0.04:0.5`.")
    spec = RuleStrategy(name, le or None, lx or None, se or None, sx or None, desc, exits if len(exits) > 1 else {})

with right:
    st.markdown("**Check it against data**")
    df, lbl = data_picker("rb", container=st.container(), default_symbols=3)
    if df is not None:
        try:
            spec.validate(df)
            d = prepare(df)
            fn = spec.signal_fn()
            check_no_lookahead(fn, d)
            check_symbol_order_invariance(fn, d)
            sig = fn(d)["signal"]
            st.success("Valid, causal and per-symbol.", icon=":material/check_circle:")
            c1, c2, c3 = st.columns(3)
            c1.metric("Long bars", f"{(sig > 0).mean():.1%}", border=True)
            c2.metric("Short bars", f"{(sig < 0).mean():.1%}", border=True)
            c3.metric("Entries", int((sig.groupby(d['symbol']).diff().fillna(0) != 0).sum()), border=True)
        except RuleError as exc:
            st.error(f"Rule error: {exc}", icon=":material/error:")
        except Exception as exc:
            st.error(f"{type(exc).__name__}: {exc}")
    else:
        empty("Pick data to validate the rules.")
    st.markdown("**Save**")
    st.code(spec.to_yaml(), language="yaml")
    if st.button("Save strategy", type="primary", icon=":material/save:"):
        p = spec.save(RULES_DIR)
        st.success(f"Saved to `{p}`. It now appears under **No-code rules** in every lab.")

with st.expander("Language reference", icon=":material/menu_book:"):
    st.markdown("Columns: `open high low close volume quote_volume funding_rate`.  Operators: `+ - * /`, comparisons, "
                "`and or not`.  Crossovers: `crosses_above(a, b)`, `crosses_below(a, b)`.")
    rows = []
    for k, f in sorted(IND.items()):
        doc = (f.__doc__ or "").strip().split("\n")[0]
        rows.append({"Function": k, "Description": doc})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=360)
