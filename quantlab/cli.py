"""quantlab command line.

    quantlab fetch synthetic                      # demo data into the lake
    quantlab fetch binance BTCUSDT ETHUSDT --start 2024-01 --end 2024-06 [--funding]
    quantlab fetch yahoo SPY QQQ --start 2015-01-01
    quantlab fetch fred DGS10 CPIAUCSL UNRATE --start 2010-01  # macro series from FRED
    quantlab fetch ccxt BTC/USD ETH/USD --exchange kraken     # any exchange ccxt supports
    quantlab catalog                              # what is in the lake
    quantlab backtest sma_crossover --data synthetic/bars --param fast=10 --study demo
    quantlab backtest --rules my_strategy.yaml --tearsheet report.html --save "RSI dip v1"
    quantlab walkforward sma_crossover --train 90 --test 30
    quantlab import prices.csv --source custom --dataset daily      # any CSV/Parquet, columns detected
    quantlab quality binance/klines_1h                             # gaps, bad bars, outliers, splits
    quantlab options iron_condor --days 250 --every 5 --hold 14     # synthetic chain demo
    quantlab search bollinger_reversion --data synthetic/bars --study demo --perm 100
    quantlab registry [--study demo] [--json]     # trials, K and the current pass bar
    quantlab strategies [--json]                  # the built-in templates and their grids
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
        elif a.source == "fred":
            from quantlab.data.sources.extra import fred_series, fred_to_bars
            frames = [fred_to_bars(fred_series(s, _day(a.start))) for s in a.symbols]
            print(lake.write("fred", "series", pd.concat(frames, ignore_index=True)))
        elif a.source == "ccxt":
            from quantlab.data.sources.extra import ccxt_ohlcv
            print(lake.write(a.exchange, f"ohlcv_{a.interval}", ccxt_ohlcv(a.exchange, a.symbols, a.interval, _day(a.start))))


def _day(s: str) -> str:
    """'2024-01' -> '2024-01-01': the month form the other sources take, as a date."""
    return f"{s}-01" if len(s) == 7 else s


def cmd_catalog(a):
    cat = Lake().catalog()
    print(cat.to_string(index=False) if len(cat) else "the lake is empty: try `quantlab fetch synthetic`")


def cmd_backtest(a):
    from dataclasses import replace
    df = _load(a.data, a.symbols, a.start, a.end)
    cfg = _cfg(a)
    if a.rules:
        from pathlib import Path

        from quantlab.rules import RuleStrategy
        rule = RuleStrategy.from_yaml(Path(a.rules).read_text())
        fn, name, params, label = rule.signal_fn(), f"rules:{rule.name}", {"rules": a.rules}, rule.name
        if rule.exits:
            cfg = replace(cfg, exits=rule.exit_rules())
    else:
        if not a.strategy:
            raise SystemExit("give a template name or --rules FILE")
        spec = REGISTRY[a.strategy]
        params = _params(a.param, spec.defaults)
        fn, name, label = spec.make(**params), a.strategy, spec.description
    res = evaluate(fn, df, cfg, score_from=a.score_from)
    reg = Registry()
    reg.record(a.study, name, params, res.summary, fingerprint(df), window=str(a.score_from or ""))
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
        for split, t in splits.report(res.positions).items():
            print(f"\n-- by {split}\n{t.round(2).to_string()}")
    if a.tearsheet or a.save:
        from quantlab.portfolio import simulate
        pf = simulate(res)
        if a.tearsheet:
            from quantlab.report.tearsheet import Tearsheet
            Tearsheet.from_results(res, pf, label, verdict={"passed": v.passed, "text": f"K = {v.k}, bar {v.bar:.2f}"}) \
                .save(a.tearsheet)
            print(f"tearsheet -> {a.tearsheet}")
        if a.save:
            from quantlab.research import runs
            print(f"saved run {runs.save(a.save, name, params, res, pf, fingerprint(df), a.study)}")


def cmd_walkforward(a):
    from quantlab.validation import walk_forward
    spec = REGISTRY[a.strategy]
    grid = [dict(spec.defaults, **dict(zip(spec.grid, v, strict=True))) for v in itertools.product(*spec.grid.values())]
    wf = walk_forward(spec.make, grid, _load(a.data, a.symbols, a.start, a.end), a.train, a.test, cfg=_cfg(a))
    print(wf.folds.to_string(index=False))
    print(json.dumps(wf.stats, indent=1))


def cmd_import(a):
    from quantlab.data import importer, quality
    df = importer.standardize(importer.load_file(a.file), symbol=a.symbol)
    print(quality.report(df)["symbols"].to_string(index=False))
    print(Lake().write(a.source, a.dataset, df))


def cmd_quality(a):
    from quantlab.data import quality
    rep = quality.report(_load(a.data))
    print(rep["symbols"].to_string(index=False))
    if len(rep["findings"]):
        print(rep["findings"].head(a.limit).to_string(index=False))
    return 0 if set(rep["symbols"]["grade"]) <= {"A", "B"} else 1


def cmd_options(a):
    from quantlab.options import STRUCTURES, compare_fills, synthetic
    chain = synthetic(days=a.days, seed=a.seed)
    entries = sorted(chain["date"].unique())[::a.every]
    print(compare_fills(chain, STRUCTURES[a.structure], entries, hold_days=a.hold).round(2).to_string())


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


def cmd_strategies(a):
    rows = [{"name": k, "description": s.description, "defaults": s.defaults, "grid": s.grid}
            for k, s in sorted(REGISTRY.items())]
    if a.json:
        print(json.dumps(rows, default=str))
    else:
        for r in rows:
            print(f"{r['name']:22s} {r['description']}  defaults {r['defaults']}")


def cmd_registry(a):
    reg = Registry()
    if a.json:
        print(json.dumps([{"study": st, "runs": len(reg.trials(st)), "k": reg.k(st), "bar": reg.bar(st),
                           "preregistered": reg.prereg_for(st) is not None}
                          for st in ([a.study] if a.study else reg.studies())]))
        return
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
    p.add_argument("source", choices=["synthetic", "binance", "yahoo", "fred", "ccxt"])
    p.add_argument("symbols", nargs="*")
    p.add_argument("--start", default="2024-01")
    p.add_argument("--end", default="2024-06")
    p.add_argument("--interval", default="1h")
    p.add_argument("--funding", action="store_true")
    p.add_argument("--exchange", default="kraken", help="ccxt exchange id")
    p.add_argument("--bars", type=int, default=4000)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--edge", type=float, default=0.0, help="planted mean-reversion edge (synthetic)")
    p.set_defaults(fn=cmd_fetch)

    sub.add_parser("catalog").set_defaults(fn=cmd_catalog)

    p = sub.add_parser("backtest")
    p.add_argument("strategy", nargs="?", choices=sorted(REGISTRY))
    p.add_argument("--rules", help="a YAML rule-strategy file instead of a template")
    p.add_argument("--tearsheet", help="write an HTML tearsheet here")
    p.add_argument("--save", help="save the run under this name")
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

    p = sub.add_parser("walkforward")
    p.add_argument("strategy", choices=sorted(REGISTRY))
    p.add_argument("--train", type=int, default=90, help="training window, days")
    p.add_argument("--test", type=int, default=30, help="trading window, days")
    data_args(p)
    p.set_defaults(fn=cmd_walkforward)

    p = sub.add_parser("import")
    p.add_argument("file")
    p.add_argument("--source", default="custom")
    p.add_argument("--dataset", default="bars")
    p.add_argument("--symbol", default=None, help="for files without a symbol column")
    p.set_defaults(fn=cmd_import)

    p = sub.add_parser("quality")
    p.add_argument("data", help="source/dataset")
    p.add_argument("--limit", type=int, default=40)
    p.set_defaults(fn=cmd_quality)

    p = sub.add_parser("options")
    p.add_argument("structure")
    p.add_argument("--days", type=int, default=250)
    p.add_argument("--every", type=int, default=5)
    p.add_argument("--hold", type=int, default=14)
    p.add_argument("--seed", type=int, default=7)
    p.set_defaults(fn=cmd_options)

    p = sub.add_parser("registry")
    p.add_argument("--study")
    p.add_argument("--json", action="store_true", help="machine-readable K and bar per study")
    p.set_defaults(fn=cmd_registry)

    p = sub.add_parser("strategies")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_strategies)

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
