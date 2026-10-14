const base = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round" } as const;

export const icons = {
  live: (
    <svg viewBox="0 0 24 24" {...base} aria-hidden="true"><path d="M3 12h4l3-8 4 16 3-8h4" /></svg>
  ),
  runs: (
    <svg viewBox="0 0 24 24" {...base} aria-hidden="true"><path d="M4 19V5M4 19h16M8 15l4-5 3 3 5-6" /></svg>
  ),
  studies: (
    <svg viewBox="0 0 24 24" {...base} aria-hidden="true"><path d="M5 20V10M12 20V4M19 20v-7M3 20h18" /></svg>
  ),
  launch: (
    <svg viewBox="0 0 24 24" {...base} aria-hidden="true"><path d="M7 4l12 8-12 8z" /></svg>
  ),
  data: (
    <svg viewBox="0 0 24 24" {...base} aria-hidden="true">
      <ellipse cx="12" cy="6" rx="7" ry="3" /><path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3" />
    </svg>
  ),
};
