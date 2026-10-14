// Wire types shared by the API and the web client. The registry, heartbeat and
// run shapes mirror what the Python platform writes to QUANTLAB_HOME.

export interface TrialEvent {
  event: "trial";
  ts: string;
  study: string;
  strategy: string;
  params: Record<string, unknown>;
  data: string;
  window: string;
  key: string;
  prereg_sha256: string | null;
  note?: string;
  trades: number | null;
  day_t: number | null;
  calendar_sharpe: number | null;
  mean_net_bp_per_trade: number | null;
  half1_mean_day_bp: number | null;
  half2_mean_day_bp: number | null;
  calendar_days: number | null;
}

export interface PreregEvent {
  event: "prereg";
  ts: string;
  study: string;
  spec: string;
  spec_sha256: string;
  note?: string;
}

export type RegistryEvent = TrialEvent | PreregEvent;

export interface StudySummary {
  study: string;
  runs: number;
  /** Distinct trials: repeated runs of the same strategy, parameters and data count once. */
  k: number;
  /** The |t| a best-of-K search reaches from noise alone, never below the floor. */
  bar: number;
  best: { strategy: string; params: Record<string, unknown>; day_t: number } | null;
  /** Trials whose day t clears the current bar AND are positive in both calendar halves. */
  clearing: number;
  preregistered: boolean;
  lastTs: string | null;
}

export interface Heartbeat {
  ts: string;
  job: string;
  status: "start" | "ok" | "error";
  seconds?: number;
  error?: string;
  [extra: string]: unknown;
}

export type JobHealthStatus = "OK" | "RUNNING" | "FAILING" | "STALE" | "NEVER_RAN";

export interface JobHealth {
  job: string;
  status: JobHealthStatus;
  lastTs: string;
  lastOk: string | null;
  lastError: string | null;
  runs: number;
  failures: number;
  medianSeconds: number | null;
  expectedEveryH: number | null;
}

export interface RunListItem {
  id: string;
  name: string;
  strategy: string;
  study: string;
  created: string;
  code: string | null;
  trades: number | null;
  day_t: number | null;
  calendar_sharpe: number | null;
  total_return: number | null;
  final_equity: number | null;
}

export interface RunDetail extends RunListItem {
  manifest: Record<string, unknown>;
  summary: Record<string, unknown>;
  portfolio: Record<string, unknown> | null;
  /** Equity at the last bar of each UTC day: [epoch ms, dollars]. */
  equity: [number, number][];
  exits: { exit: string; trades: number; mean_bp: number }[];
  symbols: { symbol: string; trades: number; net_bp: number }[];
}

export interface Dataset {
  source: string;
  dataset: string;
  rows: number;
  symbols: number;
  first: number | null;
  last: number | null;
  sizeMb: number;
}

export interface StrategyTemplate {
  name: string;
  description: string;
  defaults: Record<string, number | boolean | string>;
  grid: Record<string, (number | boolean | string)[]>;
}

export interface JobRequest {
  strategy: string;
  data: string;
  study: string;
  params?: Record<string, number | boolean | string>;
  symbols?: string[];
  start?: string;
  end?: string;
  save?: string;
}

export type JobState = "queued" | "running" | "succeeded" | "failed";

export interface JobResult {
  summary: Record<string, unknown> | null;
  verdict: { k: number; bar: number; passed: boolean; text: string } | null;
  runId: string | null;
}

export interface Job {
  id: string;
  request: JobRequest;
  state: JobState;
  argv: string[];
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  exitCode: number | null;
  log: string[];
  result: JobResult | null;
}

export interface Overview {
  runs: number;
  studies: number;
  trials: number;
  datasets: number;
  jobs: Record<JobHealthStatus, number>;
  activeJobs: number;
}

/** Everything the server pushes over /api/stream. */
export type StreamEvent =
  | { type: "hello"; at: string; overview: Overview; recent: StreamEvent[] }
  | { type: "trial"; at: string; trial: TrialEvent; study: StudySummary }
  | { type: "heartbeat"; at: string; beat: Heartbeat; health: JobHealth }
  | { type: "run"; at: string; run: RunListItem }
  | { type: "job"; at: string; job: Omit<Job, "log"> }
  | { type: "job-log"; at: string; jobId: string; line: string };
