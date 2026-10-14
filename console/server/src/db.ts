import { DuckDBInstance, type DuckDBConnection, type DuckDBValue } from "@duckdb/node-api";

/**
 * One in-memory DuckDB for the process. Parquet files are queried in place;
 * nothing is copied or cached, so a query always sees the files as they are.
 */
export class Db {
  private constructor(private readonly con: DuckDBConnection) {}

  static async open(): Promise<Db> {
    const inst = await DuckDBInstance.create(":memory:");
    const con = await inst.connect();
    await con.run("SET TimeZone = 'UTC'");
    return new Db(con);
  }

  /** Rows as plain JS objects; BIGINT counts come back as numbers. */
  async query<T>(sql: string, params?: Record<string, DuckDBValue>): Promise<T[]> {
    const reader = await this.con.runAndReadAll(sql, params);
    return reader.getRowObjectsJS().map((row) => {
      const out: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(row)) out[k] = typeof v === "bigint" ? Number(v) : v;
      return out as T;
    });
  }
}
