"""A standalone HTML tearsheet for one backtest: the report you would hand to a reviewer.

    from quantlab.report.tearsheet import Tearsheet
    Tearsheet.from_results(res, pf, title="SMA crossover", benchmark=btc_daily_returns).save("report.html")

The file is self-contained apart from Plotly and the fonts (loaded from public CDNs), prints
cleanly, and follows the reader's light/dark preference for everything except the charts.
"""
from __future__ import annotations

import html
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd
import plotly.io as pio

from quantlab.report import charts as C
from quantlab.report import metrics as M
from quantlab.report.theme import DARK, FONT_URL, LIGHT


def _fmt(v, kind: str = "num") -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    if kind == "pct":
        return f"{v * 100:+.2f}%"
    if kind == "pct0":
        return f"{v * 100:.1f}%"
    if kind == "bp":
        return f"{v:+.1f} bp"
    if kind == "usd":
        return f"−${-v:,.0f}" if v < 0 else f"${v:,.0f}"
    if kind == "int":
        return f"{int(v):,}"
    return f"{v:.2f}"


HEADLINE = [("total_return", "Total return", "pct"), ("cagr", "CAGR", "pct"), ("sharpe", "Sharpe", "num"),
            ("sortino", "Sortino", "num"), ("max_drawdown", "Max drawdown", "pct"), ("calmar", "Calmar", "num")]
RISK = [("volatility", "Volatility (ann.)", "pct0"), ("longest_drawdown_days", "Longest drawdown (days)", "int"),
        ("var_95", "Daily VaR 95%", "pct"), ("cvar_95", "Daily CVaR 95%", "pct"), ("skew", "Skew", "num"),
        ("kurtosis", "Kurtosis", "num"), ("tail_ratio", "Tail ratio", "num"), ("best_day", "Best day", "pct"),
        ("worst_day", "Worst day", "pct"), ("monthly_win_rate", "Positive months", "pct0"),
        ("active_days", "Days in market", "pct0")]
TRADES = [("trades", "Trades", "int"), ("win_rate", "Win rate", "pct0"), ("expectancy_bp", "Expectancy", "bp"),
          ("avg_win_bp", "Average win", "bp"), ("avg_loss_bp", "Average loss", "bp"),
          ("payoff_ratio", "Payoff ratio", "num"), ("profit_factor", "Profit factor", "num"),
          ("avg_bars_held", "Bars held (avg)", "num"), ("longest_losing_streak", "Longest losing streak", "int")]
BENCH = [("alpha", "Alpha (ann.)", "pct"), ("beta", "Beta", "num"), ("correlation", "Correlation", "num"),
         ("information_ratio", "Information ratio", "num"), ("up_capture", "Up capture", "num"),
         ("down_capture", "Down capture", "num")]


@dataclass
class Tearsheet:
    title: str
    daily_returns: pd.Series
    positions: pd.DataFrame
    equity: pd.Series
    periods: int = 365
    benchmark: pd.Series | None = None
    subtitle: str = ""
    notes: list[str] = field(default_factory=list)
    verdict: dict | None = None

    @classmethod
    def from_results(cls, res, pf, title: str, benchmark: pd.Series | None = None, verdict=None,
                     notes: list[str] | None = None) -> "Tearsheet":
        cfg = res.summary.get("config", {})
        sizing = pf.stats.get("sizing", {})
        sub = (f"{res.frame['symbol'].nunique()} symbols · {pd.Timestamp(res.frame['timestamp'].min()):%Y-%m-%d} → "
               f"{pd.Timestamp(res.frame['timestamp'].max()):%Y-%m-%d} · sizing {sizing.get('method')} · "
               f"fees {cfg.get('maker_fee_bp')}/{cfg.get('taker_fee_bp')} bp maker/taker")
        return cls(title, pf.daily_returns, res.positions, pf.equity, cfg.get("days_per_year", 365), benchmark,
                   sub, notes or [], verdict)

    def stats(self) -> dict:
        s = M.summary(self.daily_returns, self.periods)
        s.update(M.trade_stats(self.positions))
        if self.benchmark is not None:
            s.update(M.benchmark_stats(self.daily_returns, self.benchmark, self.periods))
        return s

    def _table(self, rows, s) -> str:
        cells = "".join(f"<tr><th>{html.escape(label)}</th><td>{_fmt(s.get(k), kind)}</td></tr>"
                        for k, label, kind in rows if k in s)
        return f"<table class='kv'>{cells}</table>"

    def to_html(self) -> str:
        s = self.stats()
        figs = [C.equity(self.equity, None if self.benchmark is None else M.equity_curve(self.benchmark)),
                C.underwater(self.daily_returns), C.monthly_heatmap(self.daily_returns),
                C.rolling_sharpe(self.daily_returns, periods=self.periods), C.distribution(self.daily_returns),
                C.trade_map(self.positions)]
        divs = [pio.to_html(f, include_plotlyjs=(i == 0) and "cdn", full_html=False, config={"displaylogo": False})
                for i, f in enumerate(figs)]
        kpis = "".join(
            f"<div class='kpi'><span>{label}</span><b class='{('pos' if (s.get(k) or 0) > 0 else 'neg') if kind == 'pct' else ''}'>"
            f"{_fmt(s.get(k), kind)}</b></div>" for k, label, kind in HEADLINE)
        dd = M.drawdown_periods(self.daily_returns)
        dd_rows = "".join(f"<tr><td>{r.start:%Y-%m-%d}</td><td>{r.trough:%Y-%m-%d}</td>"
                          f"<td>{'' if pd.isna(r.recovered) else f'{r.recovered:%Y-%m-%d}'}</td>"
                          f"<td class='neg'>{r.depth * 100:.1f}%</td><td>{r.days}</td></tr>" for r in dd.itertuples())
        verdict = ""
        if self.verdict:
            ok = self.verdict.get("passed")
            verdict = (f"<div class='verdict {'ok' if ok else 'no'}'><b>{'Passes' if ok else 'Does not pass'}</b> "
                       f"the study's multiple-testing bar: {html.escape(self.verdict.get('text', ''))}</div>")
        notes = "".join(f"<li>{html.escape(n)}</li>" for n in self.notes)
        css_vars = lambda p: ";".join(f"--{k}:{v}" for k, v in p.items() if isinstance(v, str))  # noqa: E731
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(self.title)} · tearsheet</title>
<link rel="stylesheet" href="{FONT_URL}">
<style>
:root{{{css_vars(LIGHT)}}}
@media (prefers-color-scheme: dark){{:root{{{css_vars(DARK)}}} .chart{{background:#fff;border-radius:10px}}}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 'IBM Plex Sans',system-ui,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:40px 24px 64px}}
header .eyebrow{{font:500 12px 'IBM Plex Mono',monospace;letter-spacing:.12em;text-transform:uppercase;color:var(--accent)}}
h1{{font-size:32px;line-height:1.15;margin:6px 0 6px;text-wrap:balance}} .sub{{color:var(--muted);margin:0}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:28px 0}}
.kpi{{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px}}
.kpi span{{display:block;color:var(--muted);font-size:12px;letter-spacing:.04em;text-transform:uppercase}}
.kpi b{{display:block;font:500 24px 'IBM Plex Mono',monospace;margin-top:4px}}
.pos{{color:var(--pos)}} .neg{{color:var(--neg)}}
.grid{{display:grid;grid-template-columns:2fr 1fr;gap:16px}} .grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.card{{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin-bottom:16px}}
h2{{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0 0 10px}}
table{{border-collapse:collapse;width:100%;font-size:14px}} th,td{{padding:6px 4px;border-bottom:1px solid var(--line)}}
.kv th{{text-align:left;font-weight:400;color:var(--muted)}} .kv td{{text-align:right;font-family:'IBM Plex Mono',monospace}}
.dd th{{text-align:left;color:var(--muted);font-weight:500}} .dd td{{font-family:'IBM Plex Mono',monospace}}
.verdict{{border-radius:12px;padding:12px 16px;margin:0 0 16px;border:1px solid var(--line)}}
.verdict.ok{{background:color-mix(in srgb,var(--pos) 10%,var(--surface))}}
.verdict.no{{background:color-mix(in srgb,var(--neg) 9%,var(--surface))}}
ul{{color:var(--muted);padding-left:18px}} footer{{color:var(--muted);font-size:12px;margin-top:24px}}
@media (max-width:860px){{.grid,.grid2{{grid-template-columns:1fr}}}}
@media print{{body{{background:#fff}} .card,.kpi{{break-inside:avoid}}}}
</style></head><body><main>
<header><div class="eyebrow">quantlab · backtest tearsheet</div><h1>{html.escape(self.title)}</h1>
<p class="sub">{html.escape(self.subtitle)}</p></header>
<section class="kpis">{kpis}</section>{verdict}
<div class="card chart">{divs[0]}</div>
<div class="grid"><div class="card chart">{divs[1]}{divs[3]}</div>
<div class="card"><h2>Risk</h2>{self._table(RISK, s)}</div></div>
<div class="grid2"><div class="card"><h2>Trades</h2>{self._table(TRADES, s)}</div>
<div class="card">{'<h2>Against the benchmark</h2>' + self._table(BENCH, s) if self.benchmark is not None else '<h2>Worst drawdowns</h2>'}
{'' if self.benchmark is not None else f"<table class='dd'><tr><th>Start</th><th>Trough</th><th>Recovered</th><th>Depth</th><th>Days</th></tr>{dd_rows}</table>"}</div></div>
<div class="card chart">{divs[2]}</div>
<div class="grid2"><div class="card chart">{divs[4]}</div><div class="card chart">{divs[5]}</div></div>
{f'<div class="card"><h2>Notes</h2><ul>{notes}</ul></div>' if notes else ''}
<footer>Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by quantlab. Returns are net of fees, funding and borrow
as modelled by the engine; past simulated performance is not a forecast.</footer>
</main></body></html>"""

    def save(self, path: str) -> str:
        with open(path, "w") as fh:
            fh.write(self.to_html())
        return path
