import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import type { Overview, StreamEvent } from "../../server/src/types";

export type ConnState = "connecting" | "live" | "reconnecting";

interface StreamValue {
  state: ConnState;
  events: StreamEvent[];
  overview: Overview | null;
  /** Per-event-type counters; a page re-fetches when the types it shows change. */
  versions: Record<StreamEvent["type"], number>;
  subscribe: (fn: (e: StreamEvent) => void) => () => void;
}

const empty = { hello: 0, trial: 0, heartbeat: 0, run: 0, job: 0, "job-log": 0 };
const StreamContext = createContext<StreamValue | null>(null);
const KEEP = 200;

/**
 * One WebSocket for the app. Reconnects with capped exponential backoff, and
 * the server's hello snapshot on each (re)connect brings the counts back in line.
 */
export function StreamProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ConnState>("connecting");
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [versions, setVersions] = useState(empty);
  const listeners = useRef(new Set<(e: StreamEvent) => void>());

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry = 0;
    let timer: number | undefined;
    let closed = false;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/api/stream`);
      ws.onopen = () => {
        retry = 0;
        setState("live");
      };
      ws.onmessage = (msg) => {
        const e = JSON.parse(msg.data as string) as StreamEvent;
        if (e.type === "hello") {
          setOverview(e.overview);
          setEvents(e.recent.slice(0, KEEP));
        }
        if (e.type !== "job-log" && e.type !== "hello") setEvents((prev) => [e, ...prev].slice(0, KEEP));
        setVersions((v) => ({ ...v, [e.type]: v[e.type] + 1 }));
        for (const fn of listeners.current) fn(e);
      };
      ws.onclose = () => {
        if (closed) return;
        setState("reconnecting");
        timer = window.setTimeout(connect, Math.min(15_000, 500 * 2 ** retry++));
      };
    };
    connect();
    return () => {
      closed = true;
      window.clearTimeout(timer);
      ws?.close();
    };
  }, []);

  const value = useMemo<StreamValue>(
    () => ({
      state,
      events,
      overview,
      versions,
      subscribe: (fn) => {
        listeners.current.add(fn);
        return () => listeners.current.delete(fn);
      },
    }),
    [state, events, overview, versions],
  );
  return <StreamContext.Provider value={value}>{children}</StreamContext.Provider>;
}

export function useStream(): StreamValue {
  const v = useContext(StreamContext);
  if (!v) throw new Error("useStream outside StreamProvider");
  return v;
}
