import type { StudySummary, TrialEvent } from "../../../server/src/types";
import { useResource } from "../api";
import { TrialStrip } from "../components/charts";
import { Card, Empty, Kpi, PageHead, Pill } from "../components/ui";
import { int, num, params, signed, tone } from "../format";
import { useStream } from "../stream";

const clears = (t: TrialEvent, bar: number) =>
  t.day_t != null && t.day_t >= bar && (t.half1_mean_day_bp ?? 0) > 0 && (t.half2_mean_day_bp ?? 0) > 0;

export function Studies() {
  const { versions } = useStream();
  const studies = useResource<StudySummary[]>("/studies", versions.trial);
  return (
    <>
      <PageHead
        eyebrow="Studies"
        title="Research registry"
        lede="A study counts every distinct variant tried. The bar a result must clear rises with that count, √(2 ln K) and never below 2, because the best of many random strategies looks good by chance."
      />
      {!studies.data?.length ? (
        <Card><Empty>No trials recorded yet.</Empty></Card>
      ) : (
        <Card flush>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Study</th><th className="r">Runs</th><th className="r">K</th><th className="r">Bar</th>
                  <th>Best so far</th><th className="r">Best t</th><th>Verdict</th>
                </tr>
              </thead>
              <tbody>
                {studies.data.map((s) => (
                  <tr key={s.study} className="link" onClick={() => (location.hash = `#/studies/${encodeURIComponent(s.study)}`)}>
                    <td>
                      <a href={`#/studies/${encodeURIComponent(s.study)}`}>{s.study}</a>
                      {s.preregistered ? <> <Pill tone="accent">PRE-REG</Pill></> : null}
                    </td>
                    <td className="r num">{int(s.runs)}</td>
                    <td className="r num">{int(s.k)}</td>
                    <td className="r num">{num(s.bar)}</td>
                    <td className="small">{s.best ? <><span className="mono">{s.best.strategy}</span> <span className="muted">{params(s.best.params)}</span></> : "—"}</td>
                    <td className={`r num ${tone(s.best?.day_t)}`}>{signed(s.best?.day_t)}</td>
                    <td>{s.clearing ? <Pill tone="pos">{s.clearing} CLEAR</Pill> : <Pill>NOTHING CLEARS</Pill>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}

export function StudyView({ study }: { study: string }) {
  const { versions } = useStream();
  const res = useResource<{ summary: StudySummary; trials: TrialEvent[] }>(
    `/studies/${encodeURIComponent(study)}/trials`, versions.trial);
  if (res.error) return <Empty>{res.error}</Empty>;
  if (!res.data) return <Empty>Loading…</Empty>;
  const { summary: s, trials } = res.data;
  const withT = trials.filter((t) => t.day_t != null);
  return (
    <>
      <a className="back" href="#/studies">← All studies</a>
      <PageHead eyebrow="Study" title={study}
                lede="Each dot is one run. Green dots clear the current bar and are positive in both calendar halves; the dashed line is the bar, and it moves right as K grows." />
      <div className="grid kpis">
        <Kpi label="Distinct trials (K)" value={int(s.k)} hint={`${int(s.runs)} runs in total`} />
        <Kpi label="Current bar" value={num(s.bar)} hint="|t| needed to beat chance" />
        <Kpi label="Best day t" value={signed(s.best?.day_t)} tone={(s.best?.day_t ?? 0) >= s.bar ? "pos" : ""} />
        <Kpi label="Clearing the bar" value={int(s.clearing)} tone={s.clearing ? "pos" : ""} />
      </div>
      <div className="stack">
        <Card title="Every trial against the bar">
          <TrialStrip ts={withT.map((t) => ({ t: t.day_t!, pass: clears(t, s.bar) }))} bar={s.bar} />
        </Card>
        <Card title="Trials" sub="Newest first" flush>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>When</th><th>Strategy</th><th>Parameters</th><th className="r">Trades</th>
                  <th className="r">Day t</th><th className="r">Sharpe</th><th className="r">1st half bp/day</th><th className="r">2nd half bp/day</th></tr>
              </thead>
              <tbody>
                {[...trials].reverse().slice(0, 300).map((t, i) => (
                  <tr key={`${t.key}-${i}`}>
                    <td className="mono small muted">{t.ts.slice(0, 16).replace("T", " ")}</td>
                    <td className="mono small">{t.strategy}</td>
                    <td className="small muted">{params(t.params)}</td>
                    <td className="r num">{int(t.trades)}</td>
                    <td className={`r num ${clears(t, s.bar) ? "pos" : ""}`}>{signed(t.day_t)}</td>
                    <td className="r num">{num(t.calendar_sharpe)}</td>
                    <td className={`r num ${tone(t.half1_mean_day_bp)}`}>{signed(t.half1_mean_day_bp, 1)}</td>
                    <td className={`r num ${tone(t.half2_mean_day_bp)}`}>{signed(t.half2_mean_day_bp, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </>
  );
}
