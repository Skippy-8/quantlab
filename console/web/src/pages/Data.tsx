import type { Dataset } from "../../../server/src/types";
import { useResource } from "../api";
import { Card, Empty, PageHead } from "../components/ui";
import { day, int, num } from "../format";

export function Data() {
  const cat = useResource<Dataset[]>("/catalog");
  return (
    <>
      <PageHead
        eyebrow="Data"
        title="The lake"
        lede="Hive-partitioned Parquet, one file per symbol, queried in place by DuckDB running inside the Node process. Nothing is copied or cached, so these numbers are always the files as they are now."
      />
      <Card flush>
        {cat.error ? <Empty>{cat.error}</Empty> : !cat.data?.length ? (
          <Empty>The lake is empty. Try <span className="mono">quantlab fetch synthetic</span>.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Dataset</th><th className="r">Rows</th><th className="r">Symbols</th><th>First bar</th><th>Last bar</th><th className="r">Size</th></tr>
              </thead>
              <tbody>
                {cat.data.map((d) => (
                  <tr key={`${d.source}/${d.dataset}`}>
                    <td className="mono">{d.source}/{d.dataset}</td>
                    <td className="r num">{int(d.rows)}</td>
                    <td className="r num">{int(d.symbols)}</td>
                    <td className="num small">{day(d.first)}</td>
                    <td className="num small">{day(d.last)}</td>
                    <td className="r num">{num(d.sizeMb, 1)} MB</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
