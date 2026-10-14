import type { JobHealth, StreamEvent } from "../../../server/src/types";
import { useResource } from "../api";
import { Card, Connection, Empty, Kpi, PageHead, Pill, type Tone } from "../components/ui";
import { ago, clock, int, num, params } from "../format";
import { useStream } from "../stream";

const HEALTH_TONE: Record<JobHealth["status"], Tone> = {
  OK: "pos", RUNNING: "accent", FAILING: "neg", STALE: "warn", NEVER_RAN: "warn",
};

function Describe({ e }: { e: StreamEvent }) {
  switch (e.type) {
    case "trial":
      return (
        <span>
          <b>{e.trial.strategy}</b> <span className="muted">({params(e.trial.params)})</span> in{" "}
          <a href={`#/studies/${encodeURIComponent(e.trial.study)}`}>{e.trial.study}</a>: t{" "}
          <span className="num">{num(e.trial.day_t)}</span> against a bar of{" "}
          <span className="num">{num(e.study.bar)}</span> (K = {e.study.k})
        </span>
      );
    case "run":
      return (
        <span>
          Saved run <a href={`#/runs/${e.run.id}`}>{e.run.name}</a>{" "}
          <span className="muted">· {e.run.trades ?? 0} trades · t {num(e.run.day_t)}</span>
        </span>
      );
    case "heartbeat":
      return (
        <span>
          <span className="mono">{e.beat.job}</span>{" "}
          {e.beat.status === "start" ? "started" : e.beat.status === "ok" ? `finished in ${num(e.beat.seconds ?? null, 1)}s` : "failed"}
          {e.beat.error ? <span className="neg small"> · {e.beat.error}</span> : null}
        </span>
      );
    case "job":
      return (
        <span>
          Console job <a href={`#/launch/${e.job.id}`}>{e.job.id}</a> {e.job.state}{" "}
          <span className="muted">· {e.job.request.strategy} on {e.job.request.data}</span>
        </span>
      );
    default:
      return null;
  }
}

const KIND: Record<string, { label: string; tone: Tone }> = {
  trial: { label: "TRIAL", tone: "accent" },
  run: { label: "RUN", tone: "pos" },
  heartbeat: { label: "BEAT", tone: "" },
  job: { label: "JOB", tone: "warn" },
};

export function Live() {
  const { state, events, overview, versions } = useStream();
  const health = useResource<JobHealth[]>("/monitor", versions.heartbeat);
  const ov = useResource<NonNullable<typeof overview>>("/overview", versions.trial + versions.run + versions.heartbeat + versions.job);
  const o = ov.data ?? overview;
  const failing = (o?.jobs.FAILING ?? 0) + (o?.jobs.STALE ?? 0);

  return (
    <>
      <PageHead
        eyebrow="Live"
        title="Research floor"
        lede="Every trial, saved run and scheduled job across the platform, as it happens. Run a backtest anywhere (the CLI, the dashboard, a notebook, this console) and it lands here within a second."
        right={<Connection state={state} />}
      />
      <div className="grid kpis">
        <Kpi label="Saved runs" value={int(o?.runs)} />
        <Kpi label="Studies" value={int(o?.studies)} hint={`${int(o?.trials)} trials recorded`} />
        <Kpi label="Datasets in the lake" value={int(o?.datasets)} />
        <Kpi label="Jobs needing attention" value={int(failing)} tone={failing ? "neg" : "pos"}
             hint={failing ? "failing or stale" : "all healthy"} />
      </div>
      <div className="grid two">
        <Card title="Event tape" sub="Newest first, streamed over a WebSocket" flush>
          {events.length === 0 ? (
            <Empty>Waiting for activity. Launch a backtest, or run <span className="mono">quantlab backtest</span> anywhere.</Empty>
          ) : (
            <ul className="tape" aria-live="polite">
              {events.map((e, i) => (
                <li key={`${e.at}-${i}`}>
                  <time dateTime={e.at}>{clock(e.at)}</time>
                  <Pill tone={KIND[e.type]?.tone ?? ""}>{KIND[e.type]?.label ?? e.type}</Pill>
                  <span className="what"><Describe e={e} /></span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Job health" sub="From heartbeats.jsonl; a job that stops reporting turns stale" flush>
          {!health.data?.length ? (
            <Empty>No heartbeats yet.</Empty>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Job</th><th>Status</th><th>Last success</th><th className="r">Runs</th><th className="r">Typical</th></tr>
                </thead>
                <tbody>
                  {health.data.map((h) => (
                    <tr key={h.job}>
                      <td className="mono small">{h.job}</td>
                      <td><Pill tone={HEALTH_TONE[h.status]}>{h.status.replace("_", " ")}</Pill></td>
                      <td className="small muted">{ago(h.lastOk)}</td>
                      <td className="r num">{h.runs}{h.failures ? <span className="neg"> · {h.failures}✕</span> : null}</td>
                      <td className="r num muted">{h.medianSeconds == null ? "—" : `${num(h.medianSeconds, 1)}s`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
