import { readdir, stat } from "node:fs/promises";
import { join } from "node:path";

import type { Db } from "../db.js";
import type { Dataset } from "../types.js";

const NAME = /^[\w.-]+$/;

/** The Parquet lake quantlab.data.lake writes: <source>/<dataset>/symbol=<SYM>/data.parquet. */
export class LakeStore {
  constructor(
    private readonly root: string,
    private readonly db: Db,
  ) {}

  async datasets(): Promise<{ source: string; dataset: string; files: string[] }[]> {
    const out = [];
    for (const source of await safeDir(this.root)) {
      if (!NAME.test(source)) continue;
      for (const dataset of await safeDir(join(this.root, source))) {
        if (!NAME.test(dataset)) continue;
        const files = (await safeDir(join(this.root, source, dataset)))
          .filter((d) => d.startsWith("symbol="))
          .map((d) => join(this.root, source, dataset, d, "data.parquet"));
        const present = [];
        for (const f of files) if (await isFile(f)) present.push(f);
        if (present.length) out.push({ source, dataset, files: present });
      }
    }
    return out;
  }

  async catalog(): Promise<Dataset[]> {
    const out: Dataset[] = [];
    for (const d of await this.datasets()) {
      const glob = join(this.root, d.source, d.dataset, "symbol=*", "data.parquet");
      const [row] = await this.db.query<{ rows: number; symbols: number; first: number | null; last: number | null }>(
        `SELECT count(*) AS rows, count(DISTINCT symbol) AS symbols,
                epoch_ms(min(timestamp)) AS first, epoch_ms(max(timestamp)) AS last
           FROM read_parquet($g, hive_partitioning = true)`,
        { g: glob },
      );
      let bytes = 0;
      for (const f of d.files) bytes += (await stat(f)).size;
      out.push({ source: d.source, dataset: d.dataset, rows: row?.rows ?? 0, symbols: row?.symbols ?? 0,
                 first: row?.first ?? null, last: row?.last ?? null, sizeMb: Math.round(bytes / 1e4) / 100 });
    }
    return out;
  }
}

async function safeDir(path: string): Promise<string[]> {
  try {
    return (await readdir(path, { withFileTypes: true })).filter((e) => e.isDirectory()).map((e) => e.name).sort();
  } catch {
    return [];
  }
}

async function isFile(path: string): Promise<boolean> {
  try {
    return (await stat(path)).isFile();
  } catch {
    return false;
  }
}
