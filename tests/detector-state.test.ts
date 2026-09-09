import { describe, expect, it } from "vitest";
import { detectorInputReducer, initialDetectorInput, inputForScan } from "@/components/detector-state";

describe("report-bound fresh scans", () => {
  it("rescans report A after editing the URL to B while a new intake scan uses B", () => {
    let state = initialDetectorInput<string>();
    state = detectorInputReducer(state, { type: "url", url: " https://www.instagram.com/reel/ReportA/ " });
    const submitted = inputForScan(state)!;
    state = detectorInputReducer(state, { type: "completed", report: "report A", input: submitted });
    state = detectorInputReducer(state, { type: "url", url: "https://www.instagram.com/reel/VideoB/" });

    expect(state.completed?.report).toBe("report A");
    expect(inputForScan(state, true)).toEqual({ mode: "url", url: "https://www.instagram.com/reel/ReportA/" });
    expect(inputForScan(state)).toEqual({ mode: "url", url: "https://www.instagram.com/reel/VideoB/" });
    state = detectorInputReducer(state, { type: "url", url: "" });
    expect(inputForScan(state)).toBeNull();
    expect(inputForScan(state, true)).toEqual(submitted);
  });

  it("keeps the exact uploaded File when another file with the same name is selected or the mode changes", async () => {
    const first = new File(["first video bytes"], "clip.mp4", { type: "video/mp4" });
    const replacement = new File(["different video bytes"], "clip.mp4", { type: "video/mp4" });
    let state = detectorInputReducer(initialDetectorInput<string>(), { type: "mode", mode: "upload" });
    state = detectorInputReducer(state, { type: "file", file: first });
    const submitted = inputForScan(state)!;
    state = detectorInputReducer(state, { type: "completed", report: "uploaded report", input: submitted });
    state = detectorInputReducer(state, { type: "file", file: replacement });
    expect(inputForScan(state)).toEqual({ mode: "upload", file: replacement });

    state = detectorInputReducer(state, { type: "mode", mode: "url" });
    state = detectorInputReducer(state, { type: "url", url: "https://youtu.be/OtherVideo1" });
    const rescan = inputForScan(state, true);
    expect(rescan?.mode).toBe("upload");
    if (rescan?.mode !== "upload") throw new Error("The uploaded report lost its source");
    expect(rescan.file).toBe(first);
    expect(await rescan.file.text()).toBe("first video bytes");
    expect(inputForScan(state)).toEqual({ mode: "url", url: "https://youtu.be/OtherVideo1" });
  });

  it("keeps a URL report bound to its URL after switching the intake form to an upload", () => {
    let state = detectorInputReducer(initialDetectorInput<string>(), { type: "url", url: "https://youtu.be/SourceVideo" });
    const submitted = inputForScan(state)!;
    state = detectorInputReducer(state, { type: "completed", report: "URL report", input: submitted });
    state = detectorInputReducer(state, { type: "mode", mode: "upload" });
    state = detectorInputReducer(state, { type: "file", file: new File(["new"], "new.mp4") });
    expect(inputForScan(state, true)).toEqual(submitted);
    expect(inputForScan(state)?.mode).toBe("upload");
  });

  it("does not attach a previous source to the fictional sample or an unfinished report", () => {
    let state = detectorInputReducer(initialDetectorInput<string>(), { type: "url", url: "https://youtu.be/SourceVideo" });
    state = detectorInputReducer(state, { type: "completed", report: "real report", input: inputForScan(state)! });
    state = detectorInputReducer(state, { type: "demo", report: "fictional sample" });
    expect(inputForScan(state, true)).toBeNull();
    expect(state.completed?.isDemo).toBe(true);
    state = detectorInputReducer(state, { type: "clear-report" });
    expect(inputForScan(state, true)).toBeNull();
    expect(inputForScan(state)?.mode).toBe("url");
  });
});
