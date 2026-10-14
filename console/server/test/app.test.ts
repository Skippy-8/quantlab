import { appendFile, mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { AddressInfo } from "node:net";

import { afterEach, describe, expect, it } from "vitest";
import WebSocket from "ws";

import { buildConsole, type Console } from "../src/app.js";
import type { StreamEvent } from "../src/types.js";
import { fixtureHome, jsonl, testConfig, trial } from "./helpers.js";

let c: Console | null = null;
afterEach(async () => {
  await c?.app.close();
  c = null;
});

async function start(over = {}) {
  const f = await fixtureHome();
  c = await buildConsole(testConfig(f.home, f.lake, over));
  return { ...f, c };
}

describe("read API", () => {
  it("summarises the platform", async () => {
    const { c } = await start();
    const o = (await c.app.inject("/api/overview")).json();
    expect(o).toMatchObject({ runs: 1, studies: 1, trials: 4, datasets: 1, jobs: { OK: 1 } });
  });

  it("folds the registry the way Python does", async () => {
    const { c } = await start();
    const [s] = (await c.app.inject("/api/studies")).json();
    expect(s).toMatchObject({ study: "trend", runs: 4, k: 3, bar: 2, clearing: 2, preregistered: true });
    expect(s.best).toMatchObject({ day_t: 2.6 });
    expect((await c.app.inject("/api/studies/trend/trials")).json().trials).toHaveLength(4);
    expect((await c.app.inject("/api/studies/nope/trials")).statusCode).toBe(404);
  });

  it("reads a saved run's Parquet files through DuckDB", async () => {
    const { c, runId } = await start();
    const [item] = (await c.app.inject("/api/runs")).json();
    expect(item).toMatchObject({ id: runId, name: "Fixture run", final_equity: 101000, total_return: 0.01 });
    const d = (await c.app.inject(`/api/runs/${runId}`)).json();
    expect(d.equity).toHaveLength(3); // 72 hourly bars -> 3 days
    expect(d.equity[0]).toEqual([Date.parse("2024-01-01T23:00:00Z"), 100230]);
    expect(d.exits).toEqual([{ exit: "maker", trades: 2, mean_bp: 35 }, { exit: "stop", trades: 1, mean_bp: -25 }]);
    expect(d.symbols).toEqual([{ symbol: "ETHUSDT", trades: 1, net_bp: 30 }, { symbol: "BTCUSDT", trades: 2, net_bp: 15 }]);
  });

  it("refuses run ids that could walk out of the runs directory", async () => {
    const { c } = await start();
    for (const id of ["..%2F..%2Fetc", "20261014-120000-abc12", "x"]) {
      expect((await c.app.inject(`/api/runs/${id}`)).statusCode).toBe(404);
    }
  });

  it("catalogs the lake, skipping empty datasets", async () => {
    const { c } = await start();
    expect((await c.app.inject("/api/catalog")).json()).toEqual([
      expect.objectContaining({ source: "binance", dataset: "klines_1h", rows: 48, symbols: 2,
                                first: Date.parse("2024-01-01T00:00:00Z"), last: Date.parse("2024-01-01T23:00:00Z") }),
    ]);
  });
});

describe("jobs API", () => {
  it("validates, launches and reports a job", async () => {
    const { c } = await start();
    const bad = await c.app.inject({ method: "POST", url: "/api/jobs",
      payload: { strategy: "sma_crossover", data: "x", study: "s" } });
    expect(bad.statusCode).toBe(400);
    const extra = await c.app.inject({ method: "POST", url: "/api/jobs",
      payload: { strategy: "sma_crossover", data: "a/b", study: "s", shell: "rm -rf /" } });
    expect(extra.statusCode).toBe(400); // unknown fields are rejected by the schema
    const res = await c.app.inject({ method: "POST", url: "/api/jobs",
      payload: { strategy: "sma_crossover", data: "binance/klines_1h", study: "s", params: { fast: 10 } } });
    expect(res.statusCode).toBe(202);
    const id = res.json().id;
    for (let i = 0; i < 100 && c.runner.get(id)?.state !== "succeeded"; i++) await new Promise((r) => setTimeout(r, 30));
    const job = (await c.app.inject(`/api/jobs/${id}`)).json();
    expect(job.state).toBe("succeeded");
    expect(job.log.length).toBeGreaterThan(5);
  });

  it("can be switched off", async () => {
    const { c } = await start({ allowJobs: false });
    const res = await c.app.inject({ method: "POST", url: "/api/jobs",
      payload: { strategy: "sma_crossover", data: "a/b", study: "s" } });
    expect(res.statusCode).toBe(403);
  });
});

describe("stream", () => {
  it("greets with a snapshot and recent history, then pushes new trials, heartbeats and runs", async () => {
    const { c, home } = await start();
    await c.app.listen({ port: 0, host: "127.0.0.1" });
    const port = (c.app.server.address() as AddressInfo).port;
    const ws = new WebSocket(`ws://127.0.0.1:${port}/api/stream`);
    const got: StreamEvent[] = [];
    ws.on("message", (m) => got.push(JSON.parse(String(m))));
    await new Promise((r) => ws.once("open", r));
    for (let i = 0; i < 50 && got.length === 0; i++) await new Promise((r) => setTimeout(r, 20));

    const hello = got[0]!;
    expect(hello.type).toBe("hello");
    if (hello.type === "hello") {
      expect(hello.overview.trials).toBe(4);
      expect(hello.recent.map((e) => e.type)).toEqual(expect.arrayContaining(["trial", "heartbeat", "run"]));
    }

    await appendFile(join(home, "registry.jsonl"), jsonl([trial("trend", "d", 0.5)]));
    await appendFile(join(home, "heartbeats.jsonl"), jsonl([{ ts: "2026-10-14T13:00:00+00:00", job: "fetch", status: "error", error: "HTTP 500" }]));
    const run = join(home, "runs", "20261014-130000-def456");
    await mkdir(run);
    await writeFile(join(run, "manifest.json"), JSON.stringify({ name: "New", strategy: "s", study: "trend", created_utc: "x" }));
    await writeFile(join(run, "summary.json"), JSON.stringify({ trades: 1 }));
    await c.watcher.tick();
    for (let i = 0; i < 50 && got.length < 4; i++) await new Promise((r) => setTimeout(r, 20));
    ws.close();

    const trialEvt = got.find((e) => e.type === "trial");
    expect(trialEvt && trialEvt.type === "trial" && trialEvt.study.k).toBe(4);
    const beat = got.find((e) => e.type === "heartbeat");
    expect(beat && beat.type === "heartbeat" && beat.health.status).toBe("FAILING");
    const runEvt = got.find((e) => e.type === "run");
    expect(runEvt && runEvt.type === "run" && runEvt.run.name).toBe("New");
  });
});
