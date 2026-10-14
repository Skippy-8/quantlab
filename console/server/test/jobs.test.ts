import { readFileSync } from "node:fs";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { buildArgv, JobRunner, loadTemplates, parseOutput, validateRequest } from "../src/jobs.js";
import type { Job, StrategyTemplate } from "../src/types.js";
import { FAKE_CLI } from "./helpers.js";

const here = dirname(fileURLToPath(import.meta.url));
const templates: StrategyTemplate[] = [
  { name: "sma_crossover", description: "", defaults: { fast: 20, slow: 100, allow_short: true }, grid: {} },
];
const ok = { strategy: "sma_crossover", data: "binance/klines_1h", study: "demo" };

describe("validateRequest", () => {
  it("accepts a well-formed request", () => {
    expect(validateRequest({ ...ok, params: { fast: 10, allow_short: false }, symbols: ["BTCUSDT"],
                             start: "2024-01", end: "2024-06-30", save: "SMA 10/100 (test)" }, templates)).toEqual([]);
  });

  it.each([
    [{ strategy: "rm -rf" }, /unknown strategy/],
    [{ data: "../../etc/passwd" }, /source\/dataset/],
    [{ study: "a b" }, /study/],
    [{ params: { "--rules": 1 } }, /bad parameter name/],
    [{ params: { volume: 1 } }, /has no parameter 'volume'/],
    [{ params: { fast: "--tearsheet=/tmp/x" } }, /bad value/],
    [{ params: { fast: "1;id" } }, /bad value/],
    [{ symbols: ["--rules"] }, /bad symbol/],
    [{ start: "yesterday" }, /bad date/],
    [{ save: "--rules x.yaml" }, /save name/],
    [{ save: "name\nwith newline" }, /save name/],
  ])("rejects %j", (patch, message) => {
    expect(validateRequest({ ...ok, ...patch } as never, templates).join("; ")).toMatch(message);
  });

  it("allows negative numbers", () => {
    expect(validateRequest({ ...ok, params: { fast: -5 } }, templates)).toEqual([]);
  });
});

describe("buildArgv", () => {
  it("maps a request onto quantlab backtest flags", () => {
    expect(buildArgv({ ...ok, params: { fast: 10, slow: 50 }, symbols: ["A", "B"], start: "2024-01", save: "x" }))
      .toEqual(["backtest", "sma_crossover", "--data", "binance/klines_1h", "--study", "demo",
                "--param", "fast=10", "slow=50", "--symbols", "A", "B", "--start", "2024-01", "--save", "x"]);
  });
});

describe("parseOutput", () => {
  it("reads the summary, verdict and saved run from real CLI output", () => {
    const lines = readFileSync(join(here, "fixtures", "backtest-output.txt"), "utf8").split("\n");
    const r = parseOutput(lines);
    expect(r.summary).toMatchObject({ trades: 79, day_t: -0.547, exits: { maker: 75, eod: 4 } });
    expect(r.verdict).toMatchObject({ k: 1, bar: 2, passed: false });
    expect(r.verdict?.text).toMatch(/^FAIL: day t -0.547 below the bar/);
    expect(r.runId).toBe("20261014-120000-abc123");
  });

  it("copes with output that has none of it", () => {
    expect(parseOutput(["Traceback", "ValueError"])).toEqual({ summary: null, verdict: null, runId: null });
  });
});

function runner(home: string, over: Partial<ConstructorParameters<typeof JobRunner>[0]> = {}) {
  const updates: Job[] = [];
  const lines: string[] = [];
  const r = new JobRunner({
    cli: FAKE_CLI, env: {}, home, maxConcurrent: 1, timeoutMs: 10_000,
    onUpdate: (j) => updates.push(structuredClone(j)), onLine: (_id, l) => lines.push(l), ...over,
  });
  return { r, updates, lines };
}

const settle = (r: JobRunner, id: string) => new Promise<Job>((resolve) => {
  const t = setInterval(() => {
    const j = r.get(id)!;
    if (j.state === "succeeded" || j.state === "failed") {
      clearInterval(t);
      resolve(j);
    }
  }, 20);
});

describe("JobRunner", () => {
  it("runs the CLI, streams its output, parses the result and writes heartbeats", async () => {
    const home = await mkdtemp(join(tmpdir(), "ql-jobs-"));
    const { r, updates, lines } = runner(home);
    const job = await settle(r, r.submit({ ...ok, params: { fast: 10 } }).id);
    expect(job.state).toBe("succeeded");
    expect(job.exitCode).toBe(0);
    expect(lines[0]).toBe(`args: ${JSON.stringify(buildArgv({ ...ok, params: { fast: 10 } }).slice(1))}`);
    expect(job.result?.runId).toBe("20261014-120000-abc123");
    expect(updates.map((u) => u.state)).toEqual(["queued", "running", "succeeded"]);
    const beats = (await readFile(join(home, "heartbeats.jsonl"), "utf8")).trim().split("\n").map((l) => JSON.parse(l));
    expect(beats.map((b) => b.status)).toEqual(["start", "ok"]);
    expect(beats[0]).toMatchObject({ job: "console_backtest", strategy: "sma_crossover" });
    expect(beats[0].ts).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$/); // Python's isoformat
  });

  it("marks a crashing run failed and records the error heartbeat", async () => {
    const home = await mkdtemp(join(tmpdir(), "ql-jobs-"));
    const { r } = runner(home);
    const job = await settle(r, r.submit({ ...ok, strategy: "boom" }).id);
    expect(job.state).toBe("failed");
    expect(job.exitCode).toBe(2);
    const last = JSON.parse((await readFile(join(home, "heartbeats.jsonl"), "utf8")).trim().split("\n").at(-1)!);
    expect(last).toMatchObject({ status: "error", error: "ValueError: no data for that window" });
  });

  it("kills a run that exceeds its timeout", async () => {
    const home = await mkdtemp(join(tmpdir(), "ql-jobs-"));
    const { r } = runner(home, { timeoutMs: 300 });
    const job = await settle(r, r.submit({ ...ok, strategy: "slow" }).id);
    expect(job.state).toBe("failed");
    expect(job.log.join("\n")).toMatch(/timed out/);
  });

  it("queues beyond the concurrency limit", async () => {
    const home = await mkdtemp(join(tmpdir(), "ql-jobs-"));
    const { r } = runner(home);
    const a = r.submit(ok);
    const b = r.submit(ok);
    expect(r.get(a.id)!.state).toBe("running");
    expect(r.get(b.id)!.state).toBe("queued");
    expect((await settle(r, b.id)).state).toBe("succeeded");
  });

  it("reports a CLI that cannot be started", async () => {
    const home = await mkdtemp(join(tmpdir(), "ql-jobs-"));
    const { r } = runner(home, { cli: ["/nonexistent/quantlab"] });
    const job = await settle(r, r.submit(ok).id);
    expect(job.state).toBe("failed");
    expect(job.log.join("\n")).toMatch(/could not start/);
  });
});

describe("loadTemplates", () => {
  it("reads `quantlab strategies --json`", async () => {
    const t = await loadTemplates(FAKE_CLI, {});
    expect(t.map((x) => x.name)).toContain("sma_crossover");
  });
});
