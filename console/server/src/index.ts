import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { buildConsole } from "./app.js";
import { loadConfig } from "./config.js";

const here = dirname(fileURLToPath(import.meta.url));
const config = loadConfig();
config.webDist ??= join(here, "..", "web");

const { app, watcher } = await buildConsole(config, { logger: true });
watcher.start(config.pollMs);

for (const sig of ["SIGINT", "SIGTERM"] as const) {
  process.once(sig, () => {
    void app.close().then(() => process.exit(0));
  });
}

await app.listen({ host: config.host, port: config.port });
app.log.info(`quantlab console on http://${config.host}:${config.port}  home=${config.home}  lake=${config.lake}`);
