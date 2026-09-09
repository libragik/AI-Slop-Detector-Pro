import { cp, access } from "node:fs/promises";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const standalone = resolve(root, ".next/standalone");
try {
  await access(resolve(standalone, "server.js"));
} catch {
  console.error("Build the app with pnpm build before starting the production server.");
  process.exit(1);
}
// Match Docker's standalone layout for a local production run.
await cp(resolve(root, "public"), resolve(standalone, "public"), { recursive: true });
await cp(resolve(root, ".next/static"), resolve(standalone, ".next/static"), { recursive: true });
process.env.NODE_ENV = "production";
const nextRequire = createRequire(import.meta.resolve("next/package.json"));
nextRequire("@next/env").loadEnvConfig(root);
await import(pathToFileURL(resolve(standalone, "server.js")).href);
