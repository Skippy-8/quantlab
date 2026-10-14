// Cross-language contract: run against a QUANTLAB_HOME the Python platform just
// wrote (CI does this after its CLI smoke test) and require the Node service to
// reach the same numbers as `quantlab registry --json`.
import { execFileSync } from "node:child_process";

import { describe, expect, it } from "vitest";

import { buildConsole } from "../src/app.js";
import { loadConfig } from "../src/config.js";

const enabled = Boolean(process.env.QUANTLAB_HOME && process.env.QUANTLAB_CLI);

describe.skipIf(!enabled)("contract with the Python platform", () => {
  it("agrees on every study's K and bar, and reads every saved run", async () => {
    const cfg = loadConfig();
    const [cmd, ...prefix] = cfg.cli;
    const py = JSON.parse(execFileSync(cmd!, [...prefix, "registry", "--json"], { encoding: "utf8" })) as
      { study: string; runs: number; k: number; bar: number }[];
    expect(py.length).toBeGreaterThan(0);

    const { app } = await buildConsole(cfg);
    const node = (await app.inject("/api/studies")).json() as { study: string; runs: number; k: number; bar: number }[];
    for (const p of py) {
      const n = node.find((s) => s.study === p.study);
      expect(n, p.study).toBeDefined();
      expect(n!.runs).toBe(p.runs);
      expect(n!.k).toBe(p.k);
      expect(n!.bar).toBeCloseTo(p.bar, 12);
    }
    for (const run of (await app.inject("/api/runs")).json() as { id: string }[]) {
      const d = (await app.inject(`/api/runs/${run.id}`)).json();
      expect(d.equity.length, run.id).toBeGreaterThan(0);
    }
    const cat = (await app.inject("/api/catalog")).json() as { rows: number }[];
    expect(cat.length).toBeGreaterThan(0);
    await app.close();
  });
});
