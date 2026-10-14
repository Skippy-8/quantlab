import type { RunDetail, RunListItem } from "../../../server/src/types";
import { useResource } from "../api";
import { Bars, EquityChart } from "../components/charts";
import { Card, Empty, Kpi, PageHead, Pill } from "../components/ui";
import { int, num, pct, share, signed, tone, usd } from "../format";
import { useStream } from "../stream";

export function Runs() {
  const { versions } = useStream();
  const runs = useResource<RunListItem[]>("/runs", versions.run);
  return (
    <>
      <PageHead
        eyebrow="Runs"
        title="Saved runs"
        lede="Each saved backtest is a manifest (strategy, parameters, engine and sizing, data fingerprint, code version) plus its positions and equity, so any run can be reproduced and compared."
      />
      <Card flush>
        {runs.error ? <Empty>{runs.error}</Empty> : !runs.data?.length ? (
          <Empty>No saved runs yet. Save one with <span className="mono">--save "name"</span>, or from the Launch page.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Run</th><th>Strategy</th><th>Study</th><th className="r">Trades</th><th className="r">Day t</th>
                  <th className="r">Sharpe</th><th className="r">Return</th><th>Code</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.map((r) => (
                  <tr key={r.id} className="link" onClick={() => (location.hash = `#/runs/${r.id}`)}>
                    <td><a href={`#/runs/${r.id}`}>{r.name}</a><div className="small muted mono">{r.created.slice(0, 16).replace("T", " ")}</div></td>
                    <td className="mono small">{r.strategy}</td>
                    <td className="small">{r.study}</td>
                    <td className="r num">{int(r.trades)}</td>
                    <td className={`r num ${tone(r.day_t)}`}>{signed(r.day_t)}</td>
                    <td className="r num">{num(r.calendar_sharpe)}</td>
                    <td className={`r num ${tone(r.total_return)}`}>{pct(r.total_return)}</td>
                    <td className="mono small muted">{r.code ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

export function RunView({ id }: { id: string }) {
  const run = useResource<RunDetail>(`/runs/${id}`);
  if (run.error) return <Empty>{run.error}</Empty>;
  const r = run.data;
  if (!r) return <Empty>Loading…</Empty>;
  const s = r.summary;
  const maxDd = (() => {
    let peak = -Infinity, worst = 0;
    for (const [, v] of r.equity) { peak = Math.max(peak, v); worst = Math.min(worst, v / peak - 1); }
    return worst;
  })();
  return (
    <>
      <a className="back" href="#/runs">← All runs</a>
      <PageHead eyebrow={`Run · ${r.study}`} title={r.name}
                lede={`${r.strategy} · created ${r.created.replace("T", " ").slice(0, 16)} UTC · code ${r.code ?? "unknown"}`}
                right={<Pill tone="accent">{r.id}</Pill>} />
      <div className="grid kpis">
        <Kpi label="Final equity" value={usd(r.final_equity)} tone={tone(r.total_return)} hint={pct(r.total_return)} />
        <Kpi label="Day t-stat" value={signed(r.day_t)} hint="mean daily P&L / its standard error" />
        <Kpi label="Calendar Sharpe" value={num(r.calendar_sharpe)} />
        <Kpi label="Max drawdown" value={pct(maxDd)} tone={maxDd < 0 ? "neg" : ""} />
        <Kpi label="Trades" value={int(r.trades)} hint={`win rate ${share(s.win_rate as number)}`} />
      </div>
      <div className="stack">
        <Card title="Equity and drawdown" sub="Dollar equity at each day's last bar; the red band below is the drawdown">
          <EquityChart points={r.equity} />
        </Card>
        <div className="grid two">
          <Card title="By symbol" sub="Net basis points summed over each symbol's trades">
            <Bars rows={r.symbols.map((x) => ({ label: x.symbol, value: x.net_bp, text: `${signed(x.net_bp, 0)} bp` }))} />
          </Card>
          <Card title="How positions closed" sub="Count and mean net bp per exit type">
            <div className="table-wrap">
              <table>
                <thead><tr><th>Exit</th><th className="r">Trades</th><th className="r">Mean net bp</th></tr></thead>
                <tbody>
                  {r.exits.map((x) => (
                    <tr key={x.exit}>
                      <td className="mono small">{x.exit}</td>
                      <td className="r num">{int(x.trades)}</td>
                      <td className={`r num ${tone(x.mean_bp)}`}>{signed(x.mean_bp, 1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
        <Card title="Manifest" sub="Everything needed to reproduce this run">
          <details>
            <summary>Show the manifest</summary>
            <pre className="json">{JSON.stringify(r.manifest, null, 2)}</pre>
          </details>
        </Card>
      </div>
    </>
  );
}
