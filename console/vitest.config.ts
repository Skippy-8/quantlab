import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["server/test/**/*.test.ts"],
    testTimeout: 30_000,
    pool: "forks",
  },
});
