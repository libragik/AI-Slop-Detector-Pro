import { fileURLToPath } from "node:url";
import { configDefaults, defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    // Frozen run snapshots and the standalone Node contract are not Vitest suites.
    exclude: [
      ...configDefaults.exclude,
      ".next/**",
      "eval/runs/**",
      "scripts/eval-generate-veo-study.test.mjs",
    ],
  },
});
