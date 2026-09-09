export type InputMode = "url" | "upload";
export type ScanInput = { mode: "url"; url: string } | { mode: "upload"; file: File };

export type DetectorInputState<Report> = {
  mode: InputMode;
  url: string;
  file: File | null;
  completed: { report: Report; input: ScanInput | null; isDemo: boolean } | null;
};

export type DetectorInputAction<Report> =
  | { type: "mode"; mode: InputMode }
  | { type: "url"; url: string }
  | { type: "file"; file: File | null }
  | { type: "completed"; report: Report; input: ScanInput }
  | { type: "demo"; report: Report }
  | { type: "clear-report" };

export function initialDetectorInput<Report>(): DetectorInputState<Report> {
  return { mode: "url", url: "", file: null, completed: null };
}

export function detectorInputReducer<Report>(
  state: DetectorInputState<Report>,
  action: DetectorInputAction<Report>,
): DetectorInputState<Report> {
  switch (action.type) {
    case "mode": return { ...state, mode: action.mode };
    case "url": return { ...state, url: action.url };
    case "file": return { ...state, file: action.file };
    case "completed": return { ...state, completed: { report: action.report, input: action.input, isDemo: false } };
    case "demo": return { ...state, completed: { report: action.report, input: null, isDemo: true } };
    case "clear-report": return { ...state, completed: null };
  }
}

/** A report's rescan uses its captured source, even if the intake form has since changed. */
export function inputForScan<Report>(state: DetectorInputState<Report>, fresh = false): ScanInput | null {
  if (fresh) return state.completed?.input ?? null;
  if (state.mode === "upload") return state.file ? { mode: "upload", file: state.file } : null;
  const url = state.url.trim();
  return url.length > 8 ? { mode: "url", url } : null;
}
