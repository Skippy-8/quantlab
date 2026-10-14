import { describe, expect, it } from "vitest";

import { HeartbeatState } from "../src/store/heartbeats.js";
import { noiseBar, RegistryState } from "../src/store/registry.js";
import type { Heartbeat, RegistryEvent } from "../src/types.js";
import { trial } from "./helpers.js";

describe("noiseBar", () => {
  it("matches quantlab.stats.deflated.noise_bar", () => {
    // values from Python: max(2, sqrt(2 ln K))
    expect(noiseBar(0)).toBe(2);
    expect(noiseBar(1)).toBe(2);
    expect(noiseBar(6)).toBe(2);
    expect(noiseBar(9)).toBeCloseTo(2.09629414793641, 12);
    expect(noiseBar(100)).toBeCloseTo(3.0348542587702925, 12);
    expect(noiseBar(9, 0)).toBeCloseTo(2.09629414793641, 12);
  });
});

describe("RegistryState", () => {
  it("counts distinct trials, not runs, and judges each against the current bar", () => {
    const r = new RegistryState();
    const keys = Array.from({ length: 9 }, (_, i) => `k${i}`);
    r.apply(keys.map((k, i) => trial("s", k, i === 0 ? 2.5 : 0.1)) as RegistryEvent[]);
    r.apply([trial("s", "k0", 2.5)] as RegistryEvent[]); // a re-run is not a new trial
    const s = r.summary("s")!;
    expect(s.runs).toBe(10);
    expect(s.k).toBe(9);
    expect(s.bar).toBeCloseTo(noiseBar(9));
    expect(s.best?.day_t).toBe(2.5);
    expect(s.clearing).toBe(2); // both runs of k0 clear 2.10
  });

  it("does not count a result that is negative in one half", () => {
    const r = new RegistryState();
    r.apply([trial("s", "a", 3.1, [5, -1])] as RegistryEvent[]);
    expect(r.summary("s")!.clearing).toBe(0);
  });

  it("raises the bar for old results as the study grows", () => {
    const r = new RegistryState();
    r.apply([trial("s", "first", 2.5)] as RegistryEvent[]);
    expect(r.summary("s")!.clearing).toBe(1);
    r.apply(Array.from({ length: 99 }, (_, i) => trial("s", `n${i}`, 0)) as RegistryEvent[]);
    expect(r.summary("s")!.bar).toBeGreaterThan(3);
    expect(r.summary("s")!.clearing).toBe(0);
  });

  it("notes pre-registration and ignores rows it does not understand", () => {
    const r = new RegistryState();
    r.apply([{ event: "prereg", ts: "t", study: "s", spec: "x", spec_sha256: "y" }, trial("s", "a", 1),
             { event: "unknown" } as never, null as never] as RegistryEvent[]);
    expect(r.summary("s")!.preregistered).toBe(true);
    expect(r.list()).toHaveLength(1);
  });
});

const beat = (job: string, status: Heartbeat["status"], ts: string, extra: Partial<Heartbeat> = {}): Heartbeat =>
  ({ job, status, ts, ...extra });

describe("HeartbeatState", () => {
  const now = new Date("2026-10-14T12:00:00Z");

  it("reports OK, RUNNING and FAILING from the latest beat", () => {
    const h = new HeartbeatState();
    h.apply([beat("a", "start", "2026-10-14T11:00:00Z"), beat("a", "ok", "2026-10-14T11:01:00Z", { seconds: 60 }),
             beat("b", "start", "2026-10-14T11:59:00Z"),
             beat("c", "ok", "2026-10-14T10:00:00Z"), beat("c", "error", "2026-10-14T11:00:00Z", { error: "boom" })]);
    expect(h.health("a", now)).toMatchObject({ status: "OK", runs: 1, medianSeconds: 60 });
    expect(h.health("b", now)?.status).toBe("RUNNING");
    expect(h.health("c", now)).toMatchObject({ status: "FAILING", failures: 1, lastError: "boom" });
  });

  it("turns a job STALE after its interval times 1.5, like quantlab monitor", () => {
    const h = new HeartbeatState({ daily: 24 });
    h.apply([beat("daily", "ok", "2026-10-13T00:00:00Z")]);
    expect(h.health("daily", new Date("2026-10-14T11:00:00Z"))?.status).toBe("OK"); // 35h < 36h
    expect(h.health("daily", new Date("2026-10-14T13:00:00Z"))?.status).toBe("STALE"); // 37h
  });

  it("does not leave a job killed mid-run reading RUNNING forever", () => {
    const h = new HeartbeatState({ daily: 24 });
    h.apply([beat("daily", "start", "2026-10-12T00:00:00Z")]);
    expect(h.health("daily", now)?.status).toBe("STALE");
  });

  it("lists expected jobs that never reported", () => {
    const h = new HeartbeatState({ sec_sync: 84 });
    expect(h.list(now)).toEqual([expect.objectContaining({ job: "sec_sync", status: "NEVER_RAN" })]);
  });
});
