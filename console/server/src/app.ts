import { existsSync } from "node:fs";
import { resolve } from "node:path";

import fastifyStatic from "@fastify/static";
import fastifyWebsocket from "@fastify/websocket";
import Fastify, { type FastifyInstance } from "fastify";
import type { WebSocket } from "ws";

import type { Config } from "./config.js";
import { Db } from "./db.js";
import { JobRunner, loadTemplates, validateRequest } from "./jobs.js";
import { HeartbeatState } from "./store/heartbeats.js";
import { LakeStore } from "./store/lake.js";
import { RegistryState } from "./store/registry.js";
import { RunStore } from "./store/runs.js";
import type { JobHealthStatus, JobRequest, Overview, StrategyTemplate, StreamEvent } from "./types.js";
import { Watcher } from "./watcher.js";

export interface Console {
  app: FastifyInstance;
  watcher: Watcher;
  runner: JobRunner;
  broadcast: (e: StreamEvent) => void;
}

export interface Deps {
  /** Override template discovery (tests); otherwise asked of the CLI on first use. */
  templates?: StrategyTemplate[];
  logger?: boolean;
}

const jobBody = {
  type: "object",
  required: ["strategy", "data", "study"],
  additionalProperties: false,
  properties: {
    strategy: { type: "string", maxLength: 64 },
    data: { type: "string", maxLength: 128 },
    study: { type: "string", maxLength: 64 },
    params: { type: "object", maxProperties: 16, additionalProperties: { type: ["number", "boolean", "string"] } },
    symbols: { type: "array", maxItems: 64, items: { type: "string" } },
    start: { type: "string" },
    end: { type: "string" },
    save: { type: "string" },
  },
} as const;

export async function buildConsole(config: Config, deps: Deps = {}): Promise<Console> {
  // reject unknown body fields outright instead of Ajv's default of silently stripping them
  const app = Fastify({ logger: deps.logger ?? false, ajv: { customOptions: { removeAdditional: false } } });
  const db = await Db.open();
  const registry = new RegistryState();
  const heartbeats = new HeartbeatState(config.expected);
  const runs = new RunStore(config.home, db);
  const lake = new LakeStore(config.lake, db);
  const sockets = new Set<WebSocket>();
  const cliEnv = { QUANTLAB_HOME: config.home, QUANTLAB_LAKE: config.lake };

  const broadcast = (e: StreamEvent) => {
    const msg = JSON.stringify(e);
    for (const ws of sockets) if (ws.readyState === ws.OPEN) ws.send(msg);
  };

  const watcher = new Watcher(config.home, registry, heartbeats, runs, broadcast);
  await watcher.prime();

  const runner = new JobRunner({
    cli: config.cli,
    env: cliEnv,
    home: config.home,
    maxConcurrent: config.maxConcurrentJobs,
    timeoutMs: config.jobTimeoutMs,
    onUpdate: ({ log: _log, ...job }) => {
      const e = { type: "job", at: new Date().toISOString(), job } as const;
      // every state change reaches live clients; only the outcome is kept for the tape
      if (job.state === "succeeded" || job.state === "failed") watcher.record(e);
      else broadcast(e);
    },
    onLine: (jobId, line) => broadcast({ type: "job-log", at: new Date().toISOString(), jobId, line }),
  });

  let templates: Promise<StrategyTemplate[]> | null = deps.templates ? Promise.resolve(deps.templates) : null;
  const getTemplates = () => {
    templates ??= loadTemplates(config.cli, cliEnv).catch((err) => {
      templates = null; // let the next request retry
      throw err;
    });
    return templates;
  };

  const overview = async (): Promise<Overview> => {
    const jobs: Record<JobHealthStatus, number> = { OK: 0, RUNNING: 0, FAILING: 0, STALE: 0, NEVER_RAN: 0 };
    for (const h of heartbeats.list()) jobs[h.status] += 1;
    return {
      runs: (await runs.ids()).length,
      studies: registry.list().length,
      trials: registry.totalTrials(),
      datasets: (await lake.datasets()).length,
      jobs,
      activeJobs: runner.active(),
    };
  };

  await app.register(fastifyWebsocket);

  app.get("/api/health", async () => ({
    ok: true,
    home: config.home,
    lake: config.lake,
    jobsEnabled: config.allowJobs,
    uptimeS: Math.round(process.uptime()),
  }));
  app.get("/api/overview", overview);
  app.get("/api/studies", async () => registry.list());
  app.get<{ Params: { study: string } }>("/api/studies/:study/trials", async (req, reply) => {
    const summary = registry.summary(req.params.study);
    if (!summary) return reply.code(404).send({ error: "no such study" });
    return { summary, trials: registry.trials(req.params.study) };
  });
  app.get("/api/runs", async () => runs.list());
  app.get<{ Params: { id: string } }>("/api/runs/:id", async (req, reply) => {
    const run = await runs.detail(req.params.id);
    return run ?? reply.code(404).send({ error: "no such run" });
  });
  app.get("/api/monitor", async () => heartbeats.list());
  app.get("/api/catalog", async () => lake.catalog());
  app.get("/api/strategies", async (_req, reply) => {
    try {
      return await getTemplates();
    } catch (err) {
      return reply.code(503).send({ error: `could not list strategies: ${(err as Error).message}` });
    }
  });
  app.get("/api/jobs", async () => runner.list().map(({ log: _log, ...j }) => j));
  app.get<{ Params: { id: string } }>("/api/jobs/:id", async (req, reply) => {
    return runner.get(req.params.id) ?? reply.code(404).send({ error: "no such job" });
  });
  app.post<{ Body: JobRequest }>("/api/jobs", { schema: { body: jobBody } }, async (req, reply) => {
    if (!config.allowJobs) return reply.code(403).send({ error: "job launching is disabled on this console" });
    let tpls: StrategyTemplate[];
    try {
      tpls = await getTemplates();
    } catch (err) {
      return reply.code(503).send({ error: `could not list strategies: ${(err as Error).message}` });
    }
    const errors = validateRequest(req.body, tpls);
    if (errors.length) return reply.code(400).send({ error: errors.join("; "), errors });
    const { log: _log, ...job } = runner.submit(req.body);
    return reply.code(202).send(job);
  });

  app.get("/api/stream", { websocket: true }, async (socket) => {
    sockets.add(socket);
    socket.on("close", () => sockets.delete(socket));
    socket.send(JSON.stringify({ type: "hello", at: new Date().toISOString(), overview: await overview(),
                                 recent: watcher.recent() }));
  });

  const dist = config.webDist ? resolve(config.webDist) : null;
  if (dist && existsSync(dist)) {
    await app.register(fastifyStatic, { root: dist, wildcard: false });
    app.setNotFoundHandler((req, reply) =>
      req.url.startsWith("/api/") ? reply.code(404).send({ error: "not found" }) : reply.sendFile("index.html"),
    );
  }

  app.addHook("onClose", async () => {
    watcher.stop();
    runner.stopAll();
    for (const ws of sockets) ws.close();
  });

  return { app, watcher, runner, broadcast };
}
