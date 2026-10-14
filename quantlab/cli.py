"""quantlab command line.

    quantlab fetch synthetic                      # demo data into the lake
    quantlab fetch binance BTCUSDT ETHUSDT --start 2024-01 --end 2024-06 [--funding]
    quantlab fetch yahoo SPY QQQ --start 2015-01-01
    quantlab catalog                              # what is in the lake
    quantlab backtest sma_crossover --data synthetic/bars --param fast=10 --study demo
    quantlab search bollinger_reversion --data synthetic/bars --study demo --perm 100
    quantlab registry [--study demo]              # trials, K and the current pass bar
    quantlab prereg demo prereg/demo.md           # register a written spec before running
    quantlab vault seal data/vault                # freeze an out-of-sample set
    quantlab sec sync AAPL MSFT --since 2020-01-01
    quantlab monitor --job fetch=24 --data binance/klines_1h=36
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys

import pandas as pd

from quantlab import monitor
from quantlab.data.lake import Lake
from quantlab.engine import EngineConfig, evaluate
from quantlab.research import splits
from quantlab.research.registry import Registry, fingerprint
from quantlab.strategies import REGISTRY


def _coerce(v: str):
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    return {"true": True, "false": False}.get(v.lower(), v)


def _params(pairs: list[str], defaults: dict) -> dict:
    p = dict(defaults)
    for kv in pairs or []:
        k, v = kv.split("=", 1)
        p[k] = _coerce(v)
    return p


def _load(spec: str, symbols=None, start=None, end=None) -> pd.DataFrame:
    src, ds = spec.split("/", 1)
    df = Lake().read(src, ds, symbols, start, end)
    if df.empty:
        raise SystemExit(f"no data for {spec} (see `quantlab catalog`)")
    return df


def _cfg(a) -> EngineConfig:
    return EngineConfig(maker_fee_bp=a.maker_fee, taker_fee_bp=a.taker_fee,
                        days_per_year=252 if a.equities else 365)


def cmd_fetch(a):
    lake = Lake()
    with monitor.job(f"fetch_{a.source}"):
        if a.source == "synthetic":
            from quantlab.data.synthetic import panel
            print(lake.write("synthetic", "bars", panel(n_bars=a.bars, seed=a.seed, drift_after_drop=a.edge)))
        elif a.source == "binance":
            from quantlab.data.sources import binance as B
            k = B.fetch_klines(a.symbols, a.start, a.end, a.interval)
            if a.funding and len(k):
                k = B.attach_funding(k, B.fetch_funding(a.symbols, a.start, a.end))
            print(lake.write("binance", f"klines_{a.interval}", k))
        elif a.source == "yahoo":
            from quantlab.data.sources import yahoo
            print(lake.write("yahoo", "daily", yahoo.fetch_daily(a.symbols, a.start)))


def cmd_catalog(a):
    cat = Lake().catalog()
    print(cat.to_string(index=False) if len(cat) else "the lake is empty: try `quantlab fetch synthetic`")


def cmd_backtest(a):
    spec = REGISTRY[a.strategy]
    params = _params(a.param, spec.defaults)
    df = _load(a.data, a.symbols, a.start, a.end)
    res = evaluate(spec.make(**params), df, _cfg(a), score_from=a.score_from)
    reg = Registry()
    reg.record(a.study, a.strategy, params, res.summary, fingerprint(df), window=str(a.score_from or ""))
    v = reg.verdict(a.study, res.summary)
    s = res.summary
    print(json.dumps({k: s.get(k) for k in ("trades", "mean_net_bp_per_trade", "win_rate", "profit_factor",
                                             "day_t", "calendar_sharpe", "half1_mean_day_bp", "half2_mean_day_bp",
                                             "max_drawdown_bp", "entry_fill_rate", "exits")}, indent=1, default=str))
    if s.get("quotes", {}).get("note"):
        print(f"NOTE: {s['quotes']['note']}")
    print(f"\nstudy '{a.study}': K = {v.k}, bar |t| >= {v.bar:.2f}, DSR {v.dsr if v.dsr is None else round(v.dsr, 3)}"
          f"  ->  {'PASS' if v.passed else 'FAIL: ' + '; '.join(v.reasons)}")
    if a.splits:
        for name, t in splits.report(res.trades).items():
            print(f"\n-- by {name}\n{t.round(2).to_string()}")


def cmd_search(a):
    from quantlab.stats.permutation import search_null
    spec = REGISTRY[a.strategy]
    keys = list(spec.grid)
    combos = [dict(spec.defaults, **dict(zip(keys, vals, strict=True))) for vals in itertools.product(*spec.grid.values())]
    df = _load(a.data, a.symbols, a.start, a.end)
    cells = {",".join(f"{k}={c[k]}" for k in keys): spec.make(**c) for c in combos}
    reg, fp, cfg = Registry(), fingerprint(df), _cfg(a)
    for c in combos:                                   # every cell is a trial, recorded
        reg.record(a.study, a.strategy, c, evaluate(spec.make(**c), df, cfg, check=False).summary, fp)
    res = search_null(cells, df, cfg, n_perm=a.perm,
                      progress=lambda i, n: print(f"\r  shuffle {i}/{n}", end="", flush=True))
    print(f"\nbest cell {res.best_label}: {res.stat} {res.best_real:.2f}")
    print(f"whole-search permutation p = {res.p_value:.3f} over {a.perm} shuffles "
          f"(null best median {pd.Series(res.null_best).median():.2f})")
    print(f"study '{a.study}': K = {reg.k(a.study)}, bar {reg.bar(a.study):.2f}")


def cmd_registry(a):
    reg = Registry()
    for st in ([a.study] if a.study else reg.studies()):
        t = reg.trials(st)
        print(f"\n== {st}: {len(t)} runs, K = {reg.k(st)} distinct trials, bar |t| >= {reg.bar(st):.2f}"
              + (f", pre-registered {reg.prereg_for(st)['spec']}" if reg.prereg_for(st) else ""))
        cols = ["ts", "strategy", "params", "trades", "day_t", "calendar_sharpe", "mean_net_bp_per_trade"]
        print(t[cols].tail(20).to_string(index=False))


def cmd_prereg(a):
    print(Registry().preregister(a.study, a.spec, a.note))


def cmd_vault(a):
    from quantlab.research import vault
    if a.action == "seal":
        print(vault.seal(a.path, description=a.note))
    elif a.action == "verify":
        print(vault.verify(a.path))
    else:
        for r in vault.runs(a.path):
            print(r)


def cmd_sec(a):
    from quantlab.sec.store import InsiderStore
    from quantlab.sec.sync import sync
    store = InsiderStore()
    with monitor.job("sec_sync", tickers=len(a.tickers)):
        print(sync(a.tickers, a.since, store, heartbeat=lambda d: monitor.beat("sec_sync", "progress", **d)))
    print(store.summary())


def cmd_monitor(a):
    jobs = {k: float(v) for k, v in (x.split("=") for x in a.job or [])}
    data = {k: float(v) for k, v in (x.split("=") for x in a.data or [])}
    t = monitor.check(jobs, data, Lake() if data else None)
    print(t.to_string(index=False) if len(t) else "nothing configured to check")
    return 0 if (t["status"] == "OK").all() else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="quantlab", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def data_args(p):
        p.add_argument("--data", default="synthetic/bars", help="source/dataset in the lake")
        p.add_argument("--symbols", nargs="*")
        p.add_argument("--start")
        p.add_argument("--end")
        p.add_argument("--study", default="default")
        p.add_argument("--maker-fee", type=float, default=2.0)
        p.add_argument("--taker-fee", type=float, default=5.0)
        p.add_argument("--equities", action="store_true", help="annualise on 252 days")

    p = sub.add_parser("fetch")
    p.add_argument("source", choices=["synthetic", "binance", "yahoo"])
    p.add_argument("symbols", nargs="*")
    p.add_argument("--start", default="2024-01")
    p.add_argument("--end", default="2024-06")
    p.add_argument("--interval", default="1h")
    p.add_argument("--funding", action="store_true")
    p.add_argument("--bars", type=int, default=4000)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--edge", type=float, default=0.0, help="planted mean-reversion edge (synthetic)")
    p.set_defaults(fn=cmd_fetch)

    sub.add_parser("catalog").set_defaults(fn=cmd_catalog)

    p = sub.add_parser("backtest")
    p.add_argument("strategy", choices=sorted(REGISTRY))
    p.add_argument("--param", nargs="*", help="key=value overrides")
    p.add_argument("--score-from")
    p.add_argument("--splits", action="store_true")
    data_args(p)
    p.set_defaults(fn=cmd_backtest)

    p = sub.add_parser("search")
    p.add_argument("strategy", choices=sorted(REGISTRY))
    p.add_argument("--perm", type=int, default=100)
    data_args(p)
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("registry")
    p.add_argument("--study")
    p.set_defaults(fn=cmd_registry)

    p = sub.add_parser("prereg")
    p.add_argument("study")
    p.add_argument("spec")
    p.add_argument("--note", default="")
    p.set_defaults(fn=cmd_prereg)

    p = sub.add_parser("vault")
    p.add_argument("action", choices=["seal", "verify", "runs"])
    p.add_argument("path")
    p.add_argument("--note", default="")
    p.set_defaults(fn=cmd_vault)

    p = sub.add_parser("sec")
    p.add_argument("action", choices=["sync"])
    p.add_argument("tickers", nargs="+")
    p.add_argument("--since", default="2023-01-01")
    p.set_defaults(fn=cmd_sec)

    p = sub.add_parser("monitor")
    p.add_argument("--job", nargs="*", help="job=interval_hours")
    p.add_argument("--data", nargs="*", help="source/dataset=max_age_hours")
    p.set_defaults(fn=cmd_monitor)

    a = ap.parse_args(argv)
    return int(a.fn(a) or 0)


if __name__ == "__main__":
    sys.exit(main())
