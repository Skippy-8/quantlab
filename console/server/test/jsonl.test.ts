import { appendFile, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { JsonlTail } from "../src/jsonl.js";

const tmp = async () => join(await mkdtemp(join(tmpdir(), "ql-jsonl-")), "f.jsonl");

describe("JsonlTail", () => {
  it("returns only rows appended since the last read", async () => {
    const f = await tmp();
    await writeFile(f, '{"a":1}\n{"a":2}\n');
    const t = new JsonlTail<{ a: number }>(f);
    expect(await t.readNew()).toEqual([{ a: 1 }, { a: 2 }]);
    expect(await t.readNew()).toEqual([]);
    await appendFile(f, '{"a":3}\n');
    expect(await t.readNew()).toEqual([{ a: 3 }]);
  });

  it("waits for a half-written line instead of parsing it", async () => {
    const f = await tmp();
    await writeFile(f, '{"a":1}\n{"a":');
    const t = new JsonlTail<{ a: number }>(f);
    expect(await t.readNew()).toEqual([{ a: 1 }]);
    await appendFile(f, "2}\n");
    expect(await t.readNew()).toEqual([{ a: 2 }]);
  });

  it("never splits a multi-byte character across reads", async () => {
    const f = await tmp();
    const row = Buffer.from('{"note":"Δ drawdown €"}\n', "utf8");
    await writeFile(f, row.subarray(0, 12)); // ends inside 'Δ'
    const t = new JsonlTail<{ note: string }>(f);
    expect(await t.readNew()).toEqual([]);
    await appendFile(f, row.subarray(12));
    expect(await t.readNew()).toEqual([{ note: "Δ drawdown €" }]);
  });

  it("starts over when the file is rotated", async () => {
    const f = await tmp();
    await writeFile(f, '{"a":1}\n{"a":2}\n');
    const t = new JsonlTail<{ a: number }>(f);
    await t.readNew();
    await writeFile(f, '{"a":9}\n');
    expect(await t.readNew()).toEqual([{ a: 9 }]);
  });

  it("skips a corrupt row and keeps the rows after it", async () => {
    const f = await tmp();
    await writeFile(f, '{"a":1}\nnot json\n{"a":3}\n');
    expect(await new JsonlTail(f).readNew()).toEqual([{ a: 1 }, { a: 3 }]);
  });

  it("treats a missing file as empty", async () => {
    expect(await new JsonlTail(join(tmpdir(), "does-not-exist.jsonl")).readNew()).toEqual([]);
  });
});
