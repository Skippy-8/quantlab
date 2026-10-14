import type { ReactNode } from "react";

import type { ConnState } from "../stream";

export type Tone = "pos" | "neg" | "warn" | "accent" | "";

export function Pill({ tone = "", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className="pill" data-tone={tone}>
      {children}
    </span>
  );
}

export function Kpi({ label, value, hint, tone = "" }: { label: string; value: ReactNode; hint?: ReactNode; tone?: Tone }) {
  return (
    <div className="card kpi">
      <div className="label">{label}</div>
      <div className={`value ${tone}`}>{value}</div>
      {hint ? <div className="hint">{hint}</div> : null}
    </div>
  );
}

export function Card({ title, sub, action, children, flush = false }: {
  title?: ReactNode;
  sub?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  flush?: boolean;
}) {
  return (
    <section className="card">
      {title ? (
        <div className="card-head">
          <div>
            <h2>{title}</h2>
            {sub ? <div className="sub">{sub}</div> : null}
          </div>
          {action}
        </div>
      ) : null}
      {flush ? children : <div className="card-body">{children}</div>}
    </section>
  );
}

export function PageHead({ eyebrow, title, lede, right }: { eyebrow: string; title: string; lede?: string; right?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        {lede ? <p className="lede">{lede}</p> : null}
      </div>
      {right}
    </header>
  );
}

const CONN_TEXT: Record<ConnState, string> = { connecting: "connecting", live: "live", reconnecting: "reconnecting" };

export function Connection({ state }: { state: ConnState }) {
  return (
    <span className="conn" data-state={state} role="status" aria-live="polite">
      <span className="dot" aria-hidden="true" />
      {CONN_TEXT[state]}
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}
