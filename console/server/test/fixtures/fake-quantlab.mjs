#!/usr/bin/env node
// Stands in for the Python CLI in tests: same arguments, same output shape.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const [cmd, ...rest] = process.argv.slice(2);

if (cmd === "strategies") {
  process.stdout.write(JSON.stringify([
    { name: "sma_crossover", description: "Moving-average crossover (trend)",
      defaults: { fast: 20, slow: 100, allow_short: true }, grid: { fast: [10, 20, 50], slow: [100, 200] } },
    { name: "boom", description: "Always crashes", defaults: {}, grid: {} },
    { name: "slow", description: "Never finishes", defaults: {}, grid: {} },
  ]));
} else if (cmd === "backtest" && rest[0] === "boom") {
  process.stderr.write("Traceback (most recent call last):\nValueError: no data for that window\n");
  process.exit(2);
} else if (cmd === "backtest" && rest[0] === "slow") {
  setTimeout(() => undefined, 60_000);
} else if (cmd === "backtest") {
  process.stdout.write(`args: ${JSON.stringify(rest)}\n`);
  process.stdout.write(readFileSync(join(here, "backtest-output.txt"), "utf8"));
} else {
  process.stderr.write(`unknown command ${cmd}\n`);
  process.exit(64);
}
