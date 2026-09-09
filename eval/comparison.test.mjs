import { expect, test } from "vitest";
import { executionSummary, exactMcNemar, pairedComparison } from "./comparison.mjs";
import { mkdtemp, mkdir, writeFile, readFile, rm } from "node:fs/promises";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const row = (id, decision, label = "ai") => ({ id, groupId: id, sha256: id, label, decision, elapsedMs: 10 });

test("scan completion does not hide failed model passes or missing traces", () => {
  const a = row("a", "abstain");
  a.result = { videoAnalysis: { inspection: { passes: [
    { kind: "sweep", mode: "static", model: "test", status: "complete", elapsedMs: 5, inputTokens: 10, outputTokens: 2 },
    { kind: "adjudication", mode: "agentic", model: "test", status: "failed", elapsedMs: 20 }
  ] } } };
  const summary = executionSummary([a, { ...row("b", "ai"), error: "timeout" }]);
  expect(summary.scansWithFailedPass).toBe(1);
  expect(summary.scansWithoutPassTrace).toBe(1);
  expect(summary.endToEndAiRecall.estimate).toBe(0);
  expect(summary.byPass["adjudication/agentic/test"].failed).toBe(1);
  expect(summary.byPass["adjudication/agentic/test"].missingInputTokenCount).toBe(1);
});

test("paired changes include abstention and retain exact source identity", () => {
  const old = [row("a", "not_ai"), row("b", "ai"), row("c", "abstain")];
  const next = [row("a", "ai"), row("b", "abstain"), row("c", "ai")];
  const result = pairedComparison(old, next);
  expect(result.ai.improved).toBe(2);
  expect(result.ai.regressed).toBe(1);
  expect(result.ai.exactPairedTwoSidedP).toBe(1);
  expect(exactMcNemar(6, 0)).toBe(.03125);
  expect(() => pairedComparison(old, [{ ...next[0], sha256: "changed" }, ...next.slice(1)])).toThrow("Paired source");
});

test("comparison requires an explicit unseal and accounts for missing attempts", async () => {
  const run = promisify(execFile);
  const script = resolve("scripts/eval-compare.mjs");
  await expect(run(process.execPath, [script])).rejects.toThrow("Requires --before");
  const directory = await mkdtemp(join(tmpdir(), "detector-comparison-test-"));
  try {
    const truth = [row("a", undefined), row("b", undefined, "real")].map(item => ({ ...item, split: "holdout" }));
    const manifestText = truth.map(item => JSON.stringify(item)).join("\n") + "\n";
    const manifest = join(directory, "manifest.jsonl");
    await writeFile(manifest, manifestText);
    const plan = { manifestSha256: createHash("sha256").update(manifestText).digest("hex"), selected: 2, split: "holdout" };
    const before = join(directory, "before");
    const after = join(directory, "after");
    for (const [path, predictions] of [[before, [row("a", "not_ai"), row("b", "not_ai", "real")]], [after, [row("a", "ai")]]]) {
      await mkdir(path);
      await writeFile(join(path, "plan.json"), JSON.stringify(plan));
      await writeFile(join(path, "report.json"), "{}");
      await writeFile(join(path, "predictions.jsonl"), predictions.map(item => JSON.stringify(item)).join("\n") + "\n");
    }
    const output = join(directory, "comparison.json");
    await run(process.execPath, [script, "--manifest", manifest, "--before", before, "--after", after, "--output", output, "--unseal"]);
    const summary = JSON.parse(await readFile(output, "utf8"));
    expect(summary.after.collection.notAttempted).toBe(1);
    expect(summary.after.execution.endToEndCorrectDecisionRate.estimate).toBe(.5);
    expect(summary.paired.transitions.nonAi["not_ai -> error"]).toBe(1);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
