import { join } from "node:path";

import { JsonlTail } from "./jsonl.js";
import type { HeartbeatState } from "./store/heartbeats.js";
import type { RegistryState } from "./store/registry.js";
import type { RunStore } from "./store/runs.js";
import type { Heartbeat, RegistryEvent, StreamEvent } from "./types.js";

/**
 * Polls QUANTLAB_HOME and turns new registry rows, heartbeats and saved runs
 * into stream events. It polls rather than using fs.watch, which misses events
 * on network and container filesystems and fires twice on others; one stat a
 * second per file is cheap and behaves the same everywhere.
 */
export class Watcher {
  private readonly registryTail: JsonlTail<RegistryEvent>;
  private readonly heartbeatTail: JsonlTail<Heartbeat>;
  private readonly knownRuns = new Set<string>();
  private timer: NodeJS.Timeout | null = null;
  private busy = false;
  private readonly ring: StreamEvent[] = [];
  static readonly RECENT = 60;

  constructor(
    home: string,
    private readonly registry: RegistryState,
    private readonly heartbeats: HeartbeatState,
    private readonly runs: RunStore,
    private readonly sink: (e: StreamEvent) => void,
  ) {
    this.registryTail = new JsonlTail(join(home, "registry.jsonl"));
    this.heartbeatTail = new JsonlTail(join(home, "heartbeats.jsonl"));
  }

  /** Newest first: what a client that connects now should see on its tape. */
  recent(): StreamEvent[] {
    return [...this.ring].reverse();
  }

  /** Emit an event that did not come from the files (console job updates). */
  record(e: StreamEvent): void {
    this.emit(e);
  }

  private emit(e: StreamEvent): void {
    this.ring.push(e);
    if (this.ring.length > Watcher.RECENT) this.ring.shift();
    this.sink(e);
  }

  /**
   * Load everything already on disk without broadcasting it, and seed the
   * recent-events buffer from the newest history so a fresh tape is not empty.
   */
  async prime(): Promise<void> {
    const rows = await this.registryTail.readNew();
    this.registry.apply(rows);
    const beats = await this.heartbeatTail.readNew();
    this.heartbeats.apply(beats);
    const history: StreamEvent[] = [];
    for (const r of rows.slice(-30)) {
      const study = r?.event === "trial" ? this.registry.summary(r.study) : null;
      if (r?.event === "trial" && study) history.push({ type: "trial", at: r.ts, trial: r, study });
    }
    for (const b of beats.slice(-20)) {
      const health = this.heartbeats.health(b.job);
      if (health) history.push({ type: "heartbeat", at: b.ts, beat: b, health });
    }
    for (const id of await this.runs.ids()) {
      const run = await this.runs.item(id);
      if (!run) continue;
      this.knownRuns.add(id);
      if (this.knownRuns.size <= 10) history.push({ type: "run", at: run.created, run });
    }
    history.sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
    this.ring.push(...history.slice(-Watcher.RECENT));
  }

  start(everyMs: number): void {
    this.timer = setInterval(() => void this.tick(), everyMs);
    this.timer.unref();
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  /** One poll; public so tests can drive it without timers. */
  async tick(): Promise<void> {
    if (this.busy) return;
    this.busy = true;
    try {
      const at = new Date().toISOString();
      const rows = await this.registryTail.readNew();
      this.registry.apply(rows);
      for (const r of rows) {
        if (r?.event !== "trial") continue;
        const study = this.registry.summary(r.study);
        if (study) this.emit({ type: "trial", at, trial: r, study });
      }
      const beats = await this.heartbeatTail.readNew();
      this.heartbeats.apply(beats);
      for (const b of beats) {
        const health = this.heartbeats.health(b.job);
        if (health) this.emit({ type: "heartbeat", at, beat: b, health });
      }
      for (const id of await this.runs.ids()) {
        if (this.knownRuns.has(id)) continue;
        const run = await this.runs.item(id);
        if (!run) continue; // still being written; picked up on a later tick
        this.knownRuns.add(id);
        this.emit({ type: "run", at, run });
      }
    } finally {
      this.busy = false;
    }
  }
}
