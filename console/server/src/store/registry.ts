import type { RegistryEvent, StudySummary, TrialEvent } from "../types.js";

export const DEFAULT_FLOOR = 2.0;

/**
 * The |t| a best-of-K search reaches from noise alone, sqrt(2 ln K), never below
 * the floor. The same formula as quantlab.stats.deflated.noise_bar; the contract
 * test holds the two implementations to the same numbers.
 */
export function noiseBar(k: number, floor = DEFAULT_FLOOR): number {
  return Math.max(floor, Math.sqrt(2 * Math.log(Math.max(k, 1))));
}

interface StudyState {
  trials: TrialEvent[];
  keys: Set<string>;
  preregistered: boolean;
}

/** An in-memory fold over registry.jsonl, updated as rows are appended. */
export class RegistryState {
  private readonly studies = new Map<string, StudyState>();

  constructor(private readonly floor = DEFAULT_FLOOR) {}

  /** Apply new rows; returns the studies they touched. */
  apply(events: RegistryEvent[]): Set<string> {
    const touched = new Set<string>();
    for (const e of events) {
      if (!e || typeof e !== "object" || !("study" in e)) continue;
      const s = this.state(e.study);
      if (e.event === "trial") {
        s.trials.push(e);
        s.keys.add(e.key);
        touched.add(e.study);
      } else if (e.event === "prereg") {
        s.preregistered = true;
        touched.add(e.study);
      }
    }
    return touched;
  }

  private state(study: string): StudyState {
    let s = this.studies.get(study);
    if (!s) {
      s = { trials: [], keys: new Set(), preregistered: false };
      this.studies.set(study, s);
    }
    return s;
  }

  summary(study: string): StudySummary | null {
    const s = this.studies.get(study);
    if (!s || s.trials.length === 0) return null;
    const k = s.keys.size;
    const bar = noiseBar(k, this.floor);
    let best: StudySummary["best"] = null;
    let clearing = 0;
    for (const t of s.trials) {
      if (t.day_t == null) continue;
      if (!best || t.day_t > best.day_t) best = { strategy: t.strategy, params: t.params, day_t: t.day_t };
      const halves = (t.half1_mean_day_bp ?? 0) > 0 && (t.half2_mean_day_bp ?? 0) > 0;
      if (t.day_t >= bar && halves) clearing += 1;
    }
    return {
      study,
      runs: s.trials.length,
      k,
      bar,
      best,
      clearing,
      preregistered: s.preregistered,
      lastTs: s.trials.at(-1)?.ts ?? null,
    };
  }

  list(): StudySummary[] {
    return [...this.studies.keys()]
      .map((st) => this.summary(st))
      .filter((s): s is StudySummary => s !== null)
      .sort((a, b) => (b.lastTs ?? "").localeCompare(a.lastTs ?? ""));
  }

  trials(study: string): TrialEvent[] {
    return this.studies.get(study)?.trials ?? [];
  }

  totalTrials(): number {
    let n = 0;
    for (const s of this.studies.values()) n += s.trials.length;
    return n;
  }
}
