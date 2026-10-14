import { useEffect, useRef, useState } from "react";

import { day, num, usd } from "../format";

/** Width of a container, tracked with ResizeObserver so charts redraw crisply at any size. */
export function useWidth<T extends HTMLElement>(fallback = 640) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([entry]) => entry && setWidth(Math.max(240, entry.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return { ref, width };
}

function ticks(lo: number, hi: number, n = 4): number[] {
  if (hi === lo) return [lo];
  const raw = (hi - lo) / n;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(v);
  return out;
}

/** Equity with an area fill, the drawdown underneath, and the latest value marked. */
export function EquityChart({ points, height = 300 }: { points: [number, number][]; height?: number }) {
  const { ref, width } = useWidth<HTMLDivElement>();
  if (points.length < 2) return <div ref={ref} className="empty">Not enough history to chart.</div>;

  const pad = { l: 64, r: 16, t: 12, b: 26 };
  const ddH = 56;
  const eqH = height - pad.t - pad.b - ddH - 14;
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const x0 = xs[0]!;
  const x1 = xs.at(-1)!;
  const lo = Math.min(...ys);
  const hi = Math.max(...ys);
  const span = hi - lo || Math.abs(hi) * 0.01 || 1;
  const yLo = lo - span * 0.06;
  const yHi = hi + span * 0.06;
  const X = (t: number) => pad.l + ((t - x0) / (x1 - x0 || 1)) * (width - pad.l - pad.r);
  const Y = (v: number) => pad.t + (1 - (v - yLo) / (yHi - yLo)) * eqH;

  let peak = -Infinity;
  const dd = points.map(([t, v]) => {
    peak = Math.max(peak, v);
    return [t, peak > 0 ? v / peak - 1 : 0] as const;
  });
  const worst = Math.min(...dd.map((d) => d[1]), -1e-9);
  const ddTop = pad.t + eqH + 14;
  const DY = (v: number) => ddTop + (v / worst) * ddH;

  const line = points.map(([t, v], i) => `${i ? "L" : "M"}${X(t).toFixed(1)},${Y(v).toFixed(1)}`).join("");
  const area = `${line}L${X(x1).toFixed(1)},${(pad.t + eqH).toFixed(1)}L${X(x0).toFixed(1)},${(pad.t + eqH).toFixed(1)}Z`;
  const ddPath = `M${X(x0)},${ddTop}` + dd.map(([t, v]) => `L${X(t).toFixed(1)},${DY(v).toFixed(1)}`).join("") +
    `L${X(x1)},${ddTop}Z`;
  const months = Math.max(1, Math.round((x1 - x0) / (30 * 864e5)));
  const xTicks = Array.from({ length: Math.min(6, months) + 1 }, (_, i) => x0 + ((x1 - x0) * i) / Math.min(6, months));
  const last = points.at(-1)!;

  return (
    <div ref={ref}>
      <svg className="chart" width={width} height={height} role="img"
           aria-label={`Equity from ${usd(ys[0])} to ${usd(last[1])}, worst drawdown ${num(worst * 100, 1)}%`}>
        {ticks(yLo, yHi).map((v) => (
          <g key={v}>
            <line className="grid-line" x1={pad.l} x2={width - pad.r} y1={Y(v)} y2={Y(v)} />
            <text x={pad.l - 8} y={Y(v) + 4} textAnchor="end">{usd(v)}</text>
          </g>
        ))}
        <path className="area" d={area} />
        <path className="series" d={line} />
        <circle className="end" cx={X(last[0])} cy={Y(last[1])} r={4} />
        <path className="dd" d={ddPath} />
        <text x={pad.l - 8} y={ddTop + 10} textAnchor="end">0%</text>
        <text x={pad.l - 8} y={ddTop + ddH} textAnchor="end">{num(worst * 100, 1)}%</text>
        {xTicks.map((t, i) => (
          <text key={t} x={X(t)} y={height - 6}
                textAnchor={i === 0 ? "start" : i === xTicks.length - 1 ? "end" : "middle"}>{day(t).slice(0, 7)}</text>
        ))}
      </svg>
    </div>
  );
}

/** Every trial in a study as a dot on the t axis, against the bar the study faces. */
export function TrialStrip({ ts, bar, height = 70 }: { ts: { t: number; pass: boolean }[]; bar: number; height?: number }) {
  const { ref, width } = useWidth<HTMLDivElement>(320);
  const pad = 14;
  const lo = Math.min(-3, ...ts.map((d) => d.t));
  const hi = Math.max(3, bar + 0.5, ...ts.map((d) => d.t));
  const X = (v: number) => pad + ((v - lo) / (hi - lo)) * (width - 2 * pad);
  const mid = height / 2 - 6;
  return (
    <div ref={ref}>
      <svg className="chart" width={width} height={height} role="img"
           aria-label={`${ts.length} trials; ${ts.filter((d) => d.pass).length} clear the bar of ${num(bar)}`}>
        <line className="grid-line" x1={pad} x2={width - pad} y1={mid} y2={mid} />
        <line className="grid-line" x1={X(0)} x2={X(0)} y1={mid - 14} y2={mid + 14} />
        <line className="bar-line" x1={X(bar)} x2={X(bar)} y1={4} y2={mid + 18} />
        {ts.map((d, i) => (
          <circle key={i} className={d.pass ? "dot-pass" : "dot-fail"} cx={X(d.t)}
                  cy={mid + ((i * 7) % 15) - 7} r={4} />
        ))}
        <text x={X(0)} y={height - 4} textAnchor="middle">t = 0</text>
        <text x={X(bar)} y={height - 4} textAnchor="middle">bar {num(bar)}</text>
      </svg>
    </div>
  );
}

export function Bars({ rows }: { rows: { label: string; value: number; text: string }[] }) {
  const max = Math.max(...rows.map((r) => Math.abs(r.value)), 1e-9);
  return (
    <div className="bars">
      {rows.map((r) => (
        <div className="row" key={r.label}>
          <span className="mono small">{r.label}</span>
          <span className="track">
            <span className={`fill ${r.value < 0 ? "neg" : ""}`} style={{ width: `${(Math.abs(r.value) / max) * 100}%`, display: "block" }} />
          </span>
          <span className={`num small r ${r.value < 0 ? "neg" : ""}`} style={{ textAlign: "right" }}>{r.text}</span>
        </div>
      ))}
    </div>
  );
}
