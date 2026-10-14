import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { Db } from "../src/db.js";
import type { Config } from "../src/config.js";

export const FAKE_CLI = [process.execPath, join(dirname(fileURLToPath(import.meta.url)), "fixtures", "fake-quantlab.mjs")];

export const trial = (study: string, key: string, day_t: number, halves: [number, number] = [1, 1], ts = "2026-10-14T10:00:00+00:00") => ({
  event: "trial", ts, study, strategy: "sma_crossover", params: { fast: 20 }, data: "fp", window: "", key,
  prereg_sha256: null, trades: 100, day_t, calendar_sharpe: day_t, mean_net_bp_per_trade: 3,
  half1_mean_day_bp: halves[0], half2_mean_day_bp: halves[1], calendar_days: 365,
});

export const jsonl = (rows: unknown[]) => rows.map((r) => JSON.stringify(r)).join("\n") + "\n";

/**
 * A QUANTLAB_HOME and lake laid out exactly as the Python platform writes them,
 * including Parquet files with pandas' __index_level_0__ index column, built
 * with DuckDB so the test needs no Python.
 */
export async function fixtureHome(): Promise<{ home: string; lake: string; runId: string }> {
  const root = await mkdtemp(join(tmpdir(), "ql-console-"));
  const home = join(root, "home");
  const lake = join(root, "lake");
  const runId = "20261014-120000-abc123";
  const run = join(home, "runs", runId);
  await mkdir(run, { recursive: true });
  await writeFile(join(home, "registry.jsonl"), jsonl([
    trial("trend", "a", 1.2), trial("trend", "b", 2.6), trial("trend", "b", 2.6), trial("trend", "c", -0.4),
    { event: "prereg", ts: "2026-10-14T09:00:00+00:00", study: "trend", spec: "spec.md", spec_sha256: "x" },
  ]));
  await writeFile(join(home, "heartbeats.jsonl"), jsonl([
    { ts: "2026-10-14T08:00:00+00:00", job: "fetch", status: "start" },
    { ts: "2026-10-14T08:01:00+00:00", job: "fetch", status: "ok", seconds: 60 },
  ]));
  await writeFile(join(run, "manifest.json"), JSON.stringify({ id: runId, name: "Fixture run", strategy: "sma_crossover",
    params: { fast: 20 }, study: "trend", created_utc: "2026-10-14T12:00:00+00:00", code: "abc1234" }));
  await writeFile(join(run, "summary.json"), JSON.stringify({ trades: 3, day_t: 1.5, calendar_sharpe: 1.1, win_rate: 0.66 }));
  await writeFile(join(run, "portfolio.json"), JSON.stringify({ final_equity: 101000, total_return: 0.01 }));

  const db = await Db.open();
  const q = (p: string) => `'${p.replaceAll("'", "''")}'`;
  // hourly equity over three days; the API keeps the last bar of each day
  await db.query(`COPY (SELECT 100000 + i * 10.0 AS equity,
                         TIMESTAMPTZ '2024-01-01 00:00:00+00' + INTERVAL (i) HOUR AS __index_level_0__
                    FROM range(72) t(i)) TO ${q(join(run, "equity.parquet"))} (FORMAT parquet)`);
  await db.query(`COPY (SELECT * FROM (VALUES (1, 'BTCUSDT', 'maker', 40.0), (2, 'BTCUSDT', 'stop', -25.0),
                         (3, 'ETHUSDT', 'maker', 30.0)) v(position_id, symbol, exit, net_bp))
                    TO ${q(join(run, "positions.parquet"))} (FORMAT parquet)`);
  for (const sym of ["BTCUSDT", "ETHUSDT"]) {
    const dir = join(lake, "binance", "klines_1h", `symbol=${sym}`);
    await mkdir(dir, { recursive: true });
    await db.query(`COPY (SELECT TIMESTAMPTZ '2024-01-01 00:00:00+00' + INTERVAL (i) HOUR AS timestamp, 1.0 AS close
                      FROM range(24) t(i)) TO ${q(join(dir, "data.parquet"))} (FORMAT parquet)`);
  }
  await mkdir(dirname(join(lake, "empty", "nothing", "x")), { recursive: true });
  return { home, lake, runId };
}

export function testConfig(home: string, lake: string, over: Partial<Config> = {}): Config {
  return {
    home, lake, cli: FAKE_CLI, host: "127.0.0.1", port: 0, allowJobs: true, maxConcurrentJobs: 2,
    jobTimeoutMs: 10_000, pollMs: 50, expected: {}, webDist: null, ...over,
  };
}
