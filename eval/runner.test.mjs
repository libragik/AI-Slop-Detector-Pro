import { afterAll, beforeAll, expect, test } from "vitest";
import { mkdir, mkdtemp, readFile, writeFile, rm, readdir } from "node:fs/promises";
import { createHash } from "node:crypto";
import { execFileSync, spawnSync } from "node:child_process";
import { resolve, relative } from "node:path";

let directory, manifest;
beforeAll(async () => {
  await mkdir(resolve("eval/runs"), { recursive: true });
  directory = await mkdtemp(resolve("eval/runs/runner-test-"));
  manifest = resolve(directory, "manifest.jsonl");
  // These adapters exercise the runner contract without inspecting media.
  // Use local synthetic bytes so a fresh clone needs no downloaded corpus.
  const rows = await Promise.all(Array.from({ length: 5 }, async (_, index) => {
    const bytes = Buffer.from(`offline runner fixture ${index}`);
    const path = resolve(directory, `fixture-${index}.bin`);
    await writeFile(path, bytes);
    return { id: `fixture-${index}`, groupId: `source-${index}`, split: "development",
      path: relative(process.cwd(), path), sha256: createHash("sha256").update(bytes).digest("hex"),
      sourceUrl: "https://example.com/offline-test", license: "synthetic test fixture",
      groundTruth: "Runner contract fixture; not an accuracy sample", label: "ai", mimeType: "video/mp4" };
  }));
  await writeFile(manifest, rows.map(row => JSON.stringify(row)).join("\n") + "\n");
});
afterAll(async () => { if (directory) await rm(directory, { recursive: true, force: true }); });
const args = (adapter, output, extra = []) => ["scripts/eval-run.mjs", "--manifest", relative(process.cwd(), manifest),
  "--adapter", relative(process.cwd(), adapter), "--run", "--limit", "5", "--output", output, ...extra];

test("repeated errors stop execution, fail the process, and retries preserve earlier evidence", async () => {
  const adapter = resolve(directory, "failure.mjs"), output = resolve(directory, "failure");
  await writeFile(adapter, 'export async function analyzeEvaluationVideo() { throw new Error("fixture configuration failure"); }');
  const first = spawnSync(process.execPath, args(adapter, output), { encoding: "utf8" });
  expect(first.status, first.stderr).toBe(1);
  let report = JSON.parse(await readFile(resolve(output, "report.json"), "utf8"));
  expect(report.selection).toMatchObject({ selected: 5, attempted: 3, notAttempted: 2 });
  expect(report.overall.errors).toBe(3);
  const retried = spawnSync(process.execPath, args(adapter, output, ["--resume", "--retry-errors"]), { encoding: "utf8" });
  expect(retried.status, retried.stderr).toBe(1);
  report = JSON.parse(await readFile(resolve(output, "report.json"), "utf8"));
  expect(report.overall.attempted).toBe(3);
  expect((await readdir(output)).some(name => name.startsWith("prior-errors-"))).toBe(true);
});

test("a changed adapter cannot resume into an earlier experiment", async () => {
  const adapter = resolve(directory, "changing.mjs"), output = resolve(directory, "changing");
  await writeFile(adapter, 'export async function analyzeEvaluationVideo() { return {decision:"abstain",verdict:"Inconclusive"}; }');
  execFileSync(process.execPath, args(adapter, output), { encoding: "utf8" });
  await writeFile(adapter, 'export async function analyzeEvaluationVideo() { return {decision:"ai",verdict:"Probably AI"}; }');
  const resumed = spawnSync(process.execPath, args(adapter, output, ["--resume"]), { encoding: "utf8" });
  expect(resumed.status).toBe(1);
  expect(resumed.stderr).toContain("Resume configuration or source differs");
});

test("the actual detector module can be frozen and imported without calling a model", async () => {
  const adapter = resolve(directory, "module-load.mjs"), output = resolve(directory, "module-load");
  await writeFile(adapter, `import * as detector from ${JSON.stringify(resolve("src/lib/analyzer/evaluation.ts"))};
export async function analyzeEvaluationVideo() {
  if (typeof detector.analyzeEvaluationVideo !== "function" || typeof detector.analyzeBaselineEvaluationVideo !== "function") throw new Error("Missing exports");
  return {decision:"abstain",verdict:"Inconclusive"};
}`);
  execFileSync(process.execPath, args(adapter, output), { encoding: "utf8" });
  const plan = JSON.parse(await readFile(resolve(output, "plan.json"), "utf8"));
  expect(plan.execution).toBe("immutable-local-source-bundle");
  expect(plan.adapterBundleSha256).toMatch(/^[a-f0-9]{64}$/);
});
