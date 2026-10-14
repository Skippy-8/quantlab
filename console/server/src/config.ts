import { resolve } from "node:path";

export interface Config {
  /** QUANTLAB_HOME: registry.jsonl, heartbeats.jsonl, runs/. */
  home: string;
  /** QUANTLAB_LAKE: <source>/<dataset>/symbol=<SYM>/data.parquet. */
  lake: string;
  /** The quantlab CLI as an argv prefix, e.g. ["quantlab"] or [".venv/bin/quantlab"]. */
  cli: string[];
  host: string;
  port: number;
  /** POST /api/jobs spawns the Python CLI; switch it off for a read-only console. */
  allowJobs: boolean;
  maxConcurrentJobs: number;
  jobTimeoutMs: number;
  /** How often the watcher looks for new registry rows, heartbeats and runs. */
  pollMs: number;
  /** Expected interval per job in hours, for STALE detection (CONSOLE_EXPECT="fetch=24,sec_sync=84"). */
  expected: Record<string, number>;
  /** Built front end to serve at /, if present. */
  webDist: string | null;
}

export function parseExpected(spec: string | undefined): Record<string, number> {
  const out: Record<string, number> = {};
  for (const part of (spec ?? "").split(",")) {
    const [job, hours] = part.split("=").map((s) => s.trim());
    const h = Number(hours);
    if (job && Number.isFinite(h) && h > 0) out[job] = h;
  }
  return out;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  return {
    home: resolve(env.QUANTLAB_HOME ?? ".quantlab"),
    lake: resolve(env.QUANTLAB_LAKE ?? "data/lake"),
    cli: (env.QUANTLAB_CLI ?? "quantlab").split(" ").filter(Boolean),
    host: env.CONSOLE_HOST ?? "127.0.0.1",
    port: Number(env.CONSOLE_PORT ?? 8787),
    allowJobs: (env.CONSOLE_ALLOW_JOBS ?? "true") !== "false",
    maxConcurrentJobs: Number(env.CONSOLE_MAX_JOBS ?? 2),
    jobTimeoutMs: Number(env.CONSOLE_JOB_TIMEOUT_S ?? 900) * 1000,
    pollMs: Number(env.CONSOLE_POLL_MS ?? 1000),
    expected: parseExpected(env.CONSOLE_EXPECT),
    webDist: env.CONSOLE_WEB_DIST ?? null,
  };
}
