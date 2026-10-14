const nf = (d: number) => new Intl.NumberFormat("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

export function num(v: number | null | undefined, digits = 2): string {
  return v == null || !Number.isFinite(v) ? "—" : nf(digits).format(v);
}

export function signed(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return (v > 0 ? "+" : v < 0 ? "−" : "") + nf(digits).format(Math.abs(v));
}

export function pct(v: number | null | undefined, digits = 1): string {
  return v == null || !Number.isFinite(v) ? "—" : signed(v * 100, digits) + "%";
}

/** A share of a whole (win rate, fill rate): no sign. */
export function share(v: number | null | undefined, digits = 0): string {
  return v == null || !Number.isFinite(v) ? "—" : nf(digits).format(v * 100) + "%";
}

export function usd(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return (v < 0 ? "−$" : "$") + nf(0).format(Math.abs(v));
}

export function int(v: number | null | undefined): string {
  return v == null ? "—" : nf(0).format(v);
}

export const tone = (v: number | null | undefined) => (v == null || v === 0 ? "" : v > 0 ? "pos" : "neg");

export function clock(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString("en-GB", { hour12: false });
}

export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export function day(ms: number | null | undefined): string {
  return ms == null ? "—" : new Date(ms).toISOString().slice(0, 10);
}

export function params(p: Record<string, unknown>): string {
  return Object.entries(p).map(([k, v]) => `${k}=${v}`).join(", ") || "defaults";
}
