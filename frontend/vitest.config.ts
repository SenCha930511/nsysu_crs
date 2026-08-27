import { defineConfig } from "vitest/config";

// Unit tests for the pure lib/config layers (timeslots, conflicts, totals).
// They are DOM-free, so the node environment is enough and stays fast.
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
