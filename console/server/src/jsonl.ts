import { open, stat } from "node:fs/promises";

/**
 * Incremental reader for an append-only JSONL file.
 *
 * Each call returns only the rows appended since the last call. It consumes
 * whole lines only, so a writer caught mid-line (or mid multi-byte character)
 * is picked up on the next poll instead of being parsed half-written. A file
 * that shrinks is treated as rotated and re-read from the start. Malformed
 * lines are skipped, as the Python readers skip them.
 */
export class JsonlTail<T> {
  private offset = 0;

  constructor(readonly path: string) {}

  async readNew(): Promise<T[]> {
    let size: number;
    try {
      size = (await stat(this.path)).size;
    } catch {
      return [];
    }
    if (size < this.offset) this.offset = 0;
    if (size === this.offset) return [];

    const fh = await open(this.path, "r");
    try {
      const buf = Buffer.alloc(size - this.offset);
      const { bytesRead } = await fh.read(buf, 0, buf.length, this.offset);
      const end = buf.subarray(0, bytesRead).lastIndexOf(0x0a);
      if (end < 0) return [];
      this.offset += end + 1;
      const rows: T[] = [];
      for (const line of buf.subarray(0, end).toString("utf8").split("\n")) {
        if (!line.trim()) continue;
        try {
          rows.push(JSON.parse(line) as T);
        } catch {
          // a corrupt row must not hide the rows after it
        }
      }
      return rows;
    } finally {
      await fh.close();
    }
  }
}
