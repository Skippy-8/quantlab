import { useEffect, useMemo, useRef, useState } from "react";

import type { Dataset, Job, JobRequest, StrategyTemplate } from "../../../server/src/types";
import { api, useResource } from "../api";
import { Card, Empty, PageHead, Pill, type Tone } from "../components/ui";
import { ago, num, signed } from "../format";
import { useStream } from "../stream";

type JobRow = Omit<Job, "log">;
const STATE_TONE: Record<Job["state"], Tone> = { queued: "", running: "accent", succeeded: "pos", failed: "neg" };

function Form({ onLaunched }: { onLaunched: (id: string) => void }) {
  const strategies = useResource<StrategyTemplate[]>("/strategies");
  const catalog = useResource<Dataset[]>("/catalog");
  const [strategy, setStrategy] = useState("");
  const [data, setData] = useState("");
  const [study, setStudy] = useState("console");
  const [save, setSave] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const tpl = strategies.data?.find((s) => s.name === strategy) ?? strategies.data?.[0];
  useEffect(() => {
    if (tpl && !strategy) setStrategy(tpl.name);
  }, [tpl, strategy]);
  useEffect(() => {
    const first = catalog.data?.[0];
    if (first && !data) setData(`${first.source}/${first.dataset}`);
  }, [catalog.data, data]);
  useEffect(() => {
    if (tpl) setValues(Object.fromEntries(Object.entries(tpl.defaults).map(([k, v]) => [k, String(v)])));
  }, [tpl]);

  if (strategies.error) return <Empty>{strategies.error}</Empty>;

  const submit = async (ev: React.FormEvent) => {
    ev.preventDefault();
    if (!tpl) return;
    setBusy(true);
    setError(null);
    const p: JobRequest["params"] = {};
    for (const [k, raw] of Object.entries(values)) {
      const d = tpl.defaults[k];
      p[k] = typeof d === "number" ? Number(raw) : typeof d === "boolean" ? raw === "true" : raw;
    }
    try {
      const job = await api<JobRow>("/jobs", {
        method: "POST",
        body: JSON.stringify({ strategy: tpl.name, data, study, params: p, ...(save.trim() ? { save: save.trim() } : {}) }),
      });
      onLaunched(job.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="stack">
      <div className="form">
        <div className="field">
          <label htmlFor="strategy">Strategy</label>
          <select id="strategy" value={tpl?.name ?? ""} onChange={(e) => setStrategy(e.target.value)}>
            {strategies.data?.map((s) => <option key={s.name} value={s.name}>{s.description}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="data">Data</label>
          <select id="data" value={data} onChange={(e) => setData(e.target.value)}>
            {catalog.data?.map((d) => (
              <option key={`${d.source}/${d.dataset}`} value={`${d.source}/${d.dataset}`}>{d.source}/{d.dataset}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="study">Study</label>
          <input id="study" value={study} onChange={(e) => setStudy(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="save">Save as (optional)</label>
          <input id="save" value={save} placeholder="e.g. Donchian 100/20" onChange={(e) => setSave(e.target.value)} />
        </div>
        {Object.keys(values).map((k) => (
          <div className="field" key={k}>
            <label htmlFor={`p-${k}`}>{k}{tpl?.grid[k] ? <span className="small"> · grid {tpl.grid[k].join(", ")}</span> : null}</label>
            <input id={`p-${k}`} className="mono" value={values[k]} onChange={(e) => setValues({ ...values, [k]: e.target.value })} />
          </div>
        ))}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <button className="btn" disabled={busy || !tpl || !data}>{busy ? "Launching…" : "Run backtest"}</button>
        <span className="small muted">Counted in the study's registry, like any other run.</span>
      </div>
      {error ? <div className="error" role="alert">{error}</div> : null}
    </form>
  );
}

function JobLog({ id }: { id: string }) {
  const { subscribe } = useStream();
  const [job, setJob] = useState<Job | null>(null);
  const logRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    let live = true;
    void api<Job>(`/jobs/${id}`).then((j) => live && setJob(j)).catch(() => undefined);
    const off = subscribe((e) => {
      if (e.type === "job-log" && e.jobId === id) setJob((j) => (j ? { ...j, log: [...j.log, e.line] } : j));
      if (e.type === "job" && e.job.id === id) setJob((j) => (j ? { ...j, ...e.job } : j));
    });
    return () => {
      live = false;
      off();
    };
  }, [id, subscribe]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [job?.log.length]);

  if (!job) return <Empty>Loading job {id}…</Empty>;
  const v = job.result?.verdict;
  const s = job.result?.summary as Record<string, number> | null | undefined;
  return (
    <Card
      flush
      title={<>Job <span className="mono">{job.id}</span> <Pill tone={STATE_TONE[job.state]}>{job.state.toUpperCase()}</Pill></>}
      sub={<span className="mono small">quantlab {job.argv.join(" ")}</span>}
      action={job.result?.runId ? <a href={`#/runs/${job.result.runId}`}>Open the saved run →</a> : null}
    >
      {v ? (
        <div className="card-body" style={{ display: "flex", gap: 22, flexWrap: "wrap", alignItems: "center", borderBottom: "1px solid var(--line)" }}>
          <Pill tone={v.passed ? "pos" : "neg"}>{v.passed ? "PASS" : "FAIL"}</Pill>
          <span>day t <b className="num">{signed(s?.day_t)}</b></span>
          <span>bar <b className="num">{num(v.bar)}</b> (K = {v.k})</span>
          <span>trades <b className="num">{s?.trades ?? "—"}</b></span>
          {v.passed ? null : <span className="small muted">{v.text.replace(/^FAIL:\s*/, "")}</span>}
        </div>
      ) : null}
      <pre className="log" ref={logRef}>{job.log.join("\n") || "starting…"}</pre>
    </Card>
  );
}

export function Launch({ jobId }: { jobId?: string }) {
  const { versions } = useStream();
  const jobs = useResource<JobRow[]>("/jobs", versions.job);
  const health = useResource<{ jobsEnabled: boolean }>("/health");
  const selected = jobId ?? jobs.data?.[0]?.id;
  const recent = useMemo(() => jobs.data?.slice(0, 12) ?? [], [jobs.data]);

  return (
    <>
      <PageHead
        eyebrow="Launch"
        title="Run a backtest"
        lede="The Node service validates the request against the templates the Python platform reports, spawns the quantlab CLI without a shell, and streams its output here line by line."
      />
      <div className="stack">
        <Card title="New run">
          {health.data && !health.data.jobsEnabled ? <Empty>Launching is switched off on this console (CONSOLE_ALLOW_JOBS=false).</Empty>
            : <Form onLaunched={(id) => (location.hash = `#/launch/${id}`)} />}
        </Card>
        {selected ? <JobLog key={selected} id={selected} /> : null}
        {recent.length ? (
          <Card title="Recent jobs" flush>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Job</th><th>State</th><th>Strategy</th><th>Data</th><th>Study</th><th>Started</th></tr></thead>
                <tbody>
                  {recent.map((j) => (
                    <tr key={j.id} className="link" onClick={() => (location.hash = `#/launch/${j.id}`)}>
                      <td className="mono"><a href={`#/launch/${j.id}`}>{j.id}</a></td>
                      <td><Pill tone={STATE_TONE[j.state]}>{j.state.toUpperCase()}</Pill></td>
                      <td className="mono small">{j.request.strategy}</td>
                      <td className="mono small">{j.request.data}</td>
                      <td className="small">{j.request.study}</td>
                      <td className="small muted">{ago(j.startedAt ?? j.createdAt)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        ) : null}
      </div>
    </>
  );
}
