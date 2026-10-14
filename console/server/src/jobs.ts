import { spawn, type ChildProcess } from "node:child_process";
import { randomUUID } from "node:crypto";
import { appendFile } from "node:fs/promises";
import { join } from "node:path";

import type { Job, JobRequest, JobResult, StrategyTemplate } from "./types.js";

const DATASET = /^[\w.-]+\/[\w.-]+$/;
const STUDY = /^[\w.-]{1,64}$/;
const SYMBOL = /^[\w.\-/]{1,32}$/;
const DATE = /^\d{4}-\d{2}(-\d{2})?$/;
const PARAM_KEY = /^[a-z_][a-z0-9_]{0,31}$/;
const PARAM_VALUE = /^[\w.-]{1,32}$/;
const SAVE_NAME = /^[\w .,:()+/&-]{1,80}$/;

/**
 * Validate a launch request against the templates the platform reports.
 * Arguments go to spawn() as an array, never through a shell, but they are
 * still allow-listed so a request cannot smuggle in extra CLI flags.
 */
export function validateRequest(req: JobRequest, templates: StrategyTemplate[]): string[] {
  const errors: string[] = [];
  const tpl = templates.find((t) => t.name === req.strategy);
  if (!tpl) errors.push(`unknown strategy '${req.strategy}'`);
  if (!DATASET.test(req.data ?? "")) errors.push("data must look like source/dataset");
  if (!STUDY.test(req.study ?? "")) errors.push("study must be 1-64 letters, digits, '.', '_' or '-'");
  for (const [k, v] of Object.entries(req.params ?? {})) {
    if (!PARAM_KEY.test(k)) errors.push(`bad parameter name '${k}'`);
    else if (tpl && !(k in tpl.defaults)) errors.push(`'${req.strategy}' has no parameter '${k}'`);
    // negative numbers are fine; anything else starting with '-' could read as a flag
    if (!PARAM_VALUE.test(String(v)) || (String(v).startsWith("-") && Number.isNaN(Number(v)))) {
      errors.push(`bad value for '${k}'`);
    }
  }
  for (const s of req.symbols ?? []) if (!SYMBOL.test(s) || s.startsWith("-")) errors.push(`bad symbol '${s}'`);
  for (const d of [req.start, req.end]) if (d !== undefined && !DATE.test(d)) errors.push(`bad date '${d}'`);
  if (req.save !== undefined && (!SAVE_NAME.test(req.save) || req.save.startsWith("-"))) {
    errors.push("save name: up to 80 plain characters");
  }
  return errors;
}

export function buildArgv(req: JobRequest): string[] {
  const argv = ["backtest", req.strategy, "--data", req.data, "--study", req.study];
  const params = Object.entries(req.params ?? {});
  if (params.length) argv.push("--param", ...params.map(([k, v]) => `${k}=${v}`));
  if (req.symbols?.length) argv.push("--symbols", ...req.symbols);
  if (req.start) argv.push("--start", req.start);
  if (req.end) argv.push("--end", req.end);
  if (req.save) argv.push("--save", req.save);
  return argv;
}

/**
 * Pull the structured result out of `quantlab backtest` output: the indented
 * JSON summary block, the verdict line, and the saved run id.
 */
export function parseOutput(lines: string[]): JobResult {
  let summary: Record<string, unknown> | null = null;
  const start = lines.findIndex((l) => l === "{");
  if (start >= 0) {
    const end = lines.findIndex((l, i) => i > start && l === "}");
    if (end > start) {
      try {
        summary = JSON.parse(lines.slice(start, end + 1).join("\n"));
      } catch {
        summary = null;
      }
    }
  }
  let verdict: JobResult["verdict"] = null;
  for (const l of lines) {
    const m = /^study '.*': K = (\d+), bar \|t\| >= ([\d.]+).*->\s+(PASS|FAIL)(.*)$/.exec(l);
    if (m) verdict = { k: Number(m[1]), bar: Number(m[2]), passed: m[3] === "PASS", text: l.split("->")[1]!.trim() };
  }
  const saved = lines.map((l) => /^saved run (\S+)$/.exec(l)?.[1]).find(Boolean) ?? null;
  return { summary, verdict, runId: saved };
}

export interface JobRunnerOptions {
  cli: string[];
  env: Record<string, string>;
  home: string;
  maxConcurrent: number;
  timeoutMs: number;
  onUpdate: (job: Job) => void;
  onLine: (jobId: string, line: string) => void;
}

const MAX_LOG_LINES = 2000;
const MAX_KEPT_JOBS = 50;
const isoSeconds = () => new Date().toISOString().replace(/\.\d{3}Z$/, "+00:00");

/** Queues backtests, runs a bounded number at once, streams their output, and writes heartbeats. */
export class JobRunner {
  private readonly jobs = new Map<string, Job>();
  private readonly queue: string[] = [];
  private readonly running = new Map<string, ChildProcess>();

  constructor(private readonly opts: JobRunnerOptions) {}

  list(): Job[] {
    return [...this.jobs.values()].reverse();
  }

  get(id: string): Job | undefined {
    return this.jobs.get(id);
  }

  active(): number {
    return this.running.size + this.queue.length;
  }

  submit(request: JobRequest): Job {
    const job: Job = {
      id: randomUUID().slice(0, 8),
      request,
      state: "queued",
      argv: buildArgv(request),
      createdAt: new Date().toISOString(),
      startedAt: null,
      finishedAt: null,
      exitCode: null,
      log: [],
      result: null,
    };
    this.jobs.set(job.id, job);
    this.trim();
    this.queue.push(job.id);
    this.opts.onUpdate(job);
    this.pump();
    return job;
  }

  /** Stop everything; used on shutdown. */
  stopAll(): void {
    this.queue.length = 0;
    for (const child of this.running.values()) child.kill("SIGTERM");
  }

  private trim(): void {
    const done = [...this.jobs.values()].filter((j) => j.state === "succeeded" || j.state === "failed");
    for (const j of done.slice(0, Math.max(0, this.jobs.size - MAX_KEPT_JOBS))) this.jobs.delete(j.id);
  }

  private pump(): void {
    while (this.running.size < this.opts.maxConcurrent && this.queue.length) {
      const job = this.jobs.get(this.queue.shift()!);
      if (job) this.start(job);
    }
  }

  private async beat(status: "start" | "ok" | "error", extra: Record<string, unknown>): Promise<void> {
    const row = { ts: isoSeconds(), job: "console_backtest", status, ...extra };
    try {
      await appendFile(join(this.opts.home, "heartbeats.jsonl"), JSON.stringify(row) + "\n");
    } catch {
      // monitoring must never take the job down with it
    }
  }

  private start(job: Job): void {
    const [cmd, ...prefix] = this.opts.cli;
    job.state = "running";
    job.startedAt = new Date().toISOString();
    this.opts.onUpdate(job);
    void this.beat("start", { job_id: job.id, strategy: job.request.strategy });
    const t0 = Date.now();

    const child = spawn(cmd!, [...prefix, ...job.argv], {
      env: { ...process.env, ...this.opts.env, PYTHONUNBUFFERED: "1" },
      stdio: ["ignore", "pipe", "pipe"],
    });
    this.running.set(job.id, child);

    const timer = setTimeout(() => {
      this.push(job, `[console] timed out after ${Math.round(this.opts.timeoutMs / 1000)}s`);
      child.kill("SIGTERM");
    }, this.opts.timeoutMs);

    const pipe = (stream: NodeJS.ReadableStream | null) => {
      let carry = "";
      stream?.setEncoding("utf8");
      stream?.on("data", (chunk: string) => {
        const parts = (carry + chunk).split(/\r?\n|\r/);
        carry = parts.pop() ?? "";
        for (const line of parts) this.push(job, line);
      });
      stream?.on("end", () => carry && this.push(job, carry));
    };
    pipe(child.stdout);
    pipe(child.stderr);

    let settled = false;
    const finish = (code: number | null, err?: Error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      this.running.delete(job.id);
      if (err) this.push(job, `[console] could not start ${cmd}: ${err.message}`);
      job.exitCode = code;
      job.finishedAt = new Date().toISOString();
      job.result = parseOutput(job.log);
      job.state = code === 0 ? "succeeded" : "failed";
      const seconds = Math.round((Date.now() - t0) / 100) / 10;
      void this.beat(code === 0 ? "ok" : "error", code === 0
        ? { seconds, job_id: job.id }
        : { job_id: job.id, error: (job.log.at(-1) ?? `exit ${code}`).slice(0, 300) });
      this.opts.onUpdate(job);
      this.pump();
    };
    child.on("error", (err) => finish(null, err));
    child.on("close", (code) => finish(code));
  }

  private push(job: Job, line: string): void {
    if (job.log.length >= MAX_LOG_LINES) job.log.shift();
    job.log.push(line);
    this.opts.onLine(job.id, line);
  }
}

/** Ask the platform which templates exist (`quantlab strategies --json`). */
export function loadTemplates(cli: string[], env: Record<string, string>): Promise<StrategyTemplate[]> {
  const [cmd, ...prefix] = cli;
  return new Promise((resolve, reject) => {
    const child = spawn(cmd!, [...prefix, "strategies", "--json"], { env: { ...process.env, ...env } });
    let out = "";
    let err = "";
    child.stdout.on("data", (c) => (out += c));
    child.stderr.on("data", (c) => (err += c));
    child.on("error", reject);
    child.on("close", (code) => {
      if (code !== 0) return reject(new Error(`quantlab strategies exited ${code}: ${err.trim().slice(-300)}`));
      try {
        resolve(JSON.parse(out) as StrategyTemplate[]);
      } catch (e) {
        reject(e as Error);
      }
    });
  });
}
