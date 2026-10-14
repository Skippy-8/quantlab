import type { Heartbeat, JobHealth } from "../types.js";

const GRACE = 1.5; // the same grace factor as quantlab.monitor.check

interface JobState {
  last: Heartbeat;
  lastOk: Heartbeat | null;
  lastError: Heartbeat | null;
  runs: number;
  failures: number;
  durations: number[];
}

function median(xs: number[]): number | null {
  if (xs.length === 0) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m]! : (s[m - 1]! + s[m]!) / 2;
}

/** A fold over heartbeats.jsonl: each job's current health. */
export class HeartbeatState {
  private readonly jobs = new Map<string, JobState>();

  constructor(private readonly expected: Record<string, number> = {}) {}

  apply(beats: Heartbeat[]): Set<string> {
    const touched = new Set<string>();
    for (const b of beats) {
      if (!b?.job || !b.status) continue;
      let s = this.jobs.get(b.job);
      if (!s) {
        s = { last: b, lastOk: null, lastError: null, runs: 0, failures: 0, durations: [] };
        this.jobs.set(b.job, s);
      }
      s.last = b;
      if (b.status === "ok") {
        s.lastOk = b;
        s.runs += 1;
        if (typeof b.seconds === "number") s.durations = [...s.durations.slice(-49), b.seconds];
      } else if (b.status === "error") {
        s.lastError = b;
        s.runs += 1;
        s.failures += 1;
      }
      touched.add(b.job);
    }
    return touched;
  }

  health(job: string, now = new Date()): JobHealth | null {
    const s = this.jobs.get(job);
    if (!s) return null;
    const every = this.expected[job] ?? null;
    const overdue = (ts: string) => every !== null && now.getTime() - Date.parse(ts) > every * GRACE * 3_600_000;
    let status: JobHealth["status"];
    // a job killed without writing 'error' would otherwise read RUNNING forever
    if (s.last.status === "start") status = overdue(s.last.ts) ? "STALE" : "RUNNING";
    else if (s.last.status === "error") status = "FAILING";
    else if (!s.lastOk) status = "NEVER_RAN";
    else if (overdue(s.lastOk.ts)) status = "STALE";
    else status = "OK";
    return {
      job,
      status,
      lastTs: s.last.ts,
      lastOk: s.lastOk?.ts ?? null,
      lastError: s.lastError?.error ?? null,
      runs: s.runs,
      failures: s.failures,
      medianSeconds: median(s.durations),
      expectedEveryH: every,
    };
  }

  /** Every job seen, plus expected jobs that never wrote a heartbeat. */
  list(now = new Date()): JobHealth[] {
    const out = [...this.jobs.keys()].map((j) => this.health(j, now)!);
    for (const [job, every] of Object.entries(this.expected)) {
      if (!this.jobs.has(job)) {
        out.push({ job, status: "NEVER_RAN", lastTs: "", lastOk: null, lastError: null, runs: 0, failures: 0,
                   medianSeconds: null, expectedEveryH: every });
      }
    }
    return out.sort((a, b) => a.job.localeCompare(b.job));
  }
}
