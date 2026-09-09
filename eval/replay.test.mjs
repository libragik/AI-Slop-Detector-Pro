import { expect, test } from "vitest";
import { scoringInputs, replayRow, policyDecision } from "./replay.mjs";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { mkdtemp, mkdir, writeFile, readFile, rm } from "node:fs/promises";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";

test("replay reconstructs the pipeline context and preserves model observations and elapsed time", () => {
  const original = {
    id: "fake-dev-control", decision: "ai", elapsedMs: 999,
    result: { analyzerVersion: "original", detectorFingerprint: "original-model-pass-fingerprint",
      videoAnalysis: { raw: "unchanged", inspection: { passes: [{ status: "failed" }] } }, provenance: { status: "missing" },
      youtube: { metadata: { containsSyntheticMedia: false }, comments: { creatorAdmissionFound: false } },
      socialContext: { disclosureReasons: ["Creator explicitly labeled the work generated"] },
      finalScore: 70, verdict: "AI indicators detected", confidence: "Not calibrated",
    },
  };
  const before = structuredClone(original);
  const output = replayRow(original, input => {
    expect(input).toEqual(scoringInputs(original.result));
    expect(input.disclosure.disclosed).toBe(true);
    input.video.raw = "cannot mutate original";
    return { finalScore: 70, verdict: "Inconclusive", confidence: "Not calibrated" };
  }, { policyVersion: "test-new-policy" });
  expect(original).toEqual(before);
  expect(output.row.result.videoAnalysis).toEqual(before.result.videoAnalysis);
  expect(output.row.result.detectorFingerprint).toBe("original-model-pass-fingerprint");
  expect(output.row.elapsedMs).toBe(999);
  expect(output.row.decision).toBe("abstain");
  expect(output.changes.changedScoreFields).toEqual(["verdict"]);
  expect(output.changes.decisionChanged).toBe(true);
  expect(policyDecision({ verdict: "Verified AI provenance" })).toBe("ai");
  expect(() => policyDecision({ verdict: "unknown" })).toThrow("Unexpected");
});

test("replay does not open saved outputs before unseal and never overwrites input", async () => {
  const run = promisify(execFile);
  const script = resolve("scripts/eval-replay-scorer.mjs");
  await expect(run(process.execPath, [script, "--input", "/missing", "--output", "/missing-too"])).rejects.toThrow("Requires --input");
  const directory = await mkdtemp(join(tmpdir(), "detector-replay-test-"));
  try {
    const input = join(directory, "input"), output = join(directory, "output");
    await mkdir(input);
    const original = { id: "fake-dev-error", label: "real", groupId: "fake-dev-error", split: "development", error: "test operational failure", elapsedMs: 15 };
    const bytes = JSON.stringify(original) + "\n";
    await writeFile(join(input, "predictions.jsonl"), bytes);
    await writeFile(join(input, "plan.json"), JSON.stringify({ selected: 1, split: "development" }));
    await run(process.execPath, [script, "--input", input, "--output", output, "--unseal"]);
    expect(await readFile(join(input, "predictions.jsonl"), "utf8")).toBe(bytes);
    expect(await readFile(join(output, "predictions.jsonl"), "utf8")).toBe(bytes);
    const receipt = JSON.parse(await readFile(join(output, "replay-equivalence.json"), "utf8"));
    expect(receipt.retainedErrors).toBe(1);
    expect(receipt.modelRequests).toBe(0);
    expect(receipt.replayed).toBe(0);
    expect(receipt.bundleSha256).toMatch(/^[a-f0-9]{64}$/);
    await expect(run(process.execPath, [script, "--input", input, "--output", output, "--unseal"])).rejects.toThrow("EEXIST");
  } finally { await rm(directory, { recursive: true, force: true }); }
});
