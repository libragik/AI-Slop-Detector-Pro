import type { SightengineEvidence } from "@/lib/analyzer/sightengine-types";

function seconds(value: number) { return `${Number(value.toFixed(3))}s`; }

export function SpecialistEvidence({ evidence }: { evidence: SightengineEvidence }) {
  const flagged = evidence.samples.filter(sample => sample.valid && sample.positive).length;
  const complete = evidence.status === "complete" && evidence.coverage.complete;
  const heading = !complete ? "Specialist scan incomplete"
    : evidence.verdict === "persistent_ai_indicators" ? "Repeated AI indicators found"
      : evidence.isolatedAlerts.length ? "Isolated alerts need review" : "No flags in sampled frames";
  const failure = evidence.failureCode === "unsupported_input"
    ? "This video could not be submitted. Check that it is a supported video file within the app's three-minute, 500 MB upload allowance."
    : evidence.failureCode === "quota_or_rate_limit" ? "The specialist service could not accept this scan because of its usage or rate limit."
      : evidence.failureCode === "not_configured" || evidence.failureCode === "access_refused" ? "The specialist service is not available with the current configuration."
        : "A complete specialist result was not available. The remaining evidence is retained below.";
  return <details className="specialist-evidence report-details" aria-label="Sightengine visual evidence">
    <summary><span>Sightengine</span><span className="detail-summary">{complete ? `${flagged} of ${evidence.samples.length} sampled frames flagged` : "Scan incomplete"}</span></summary>
    <div className="detail-body">
    <h3>{heading}</h3>
    {!complete && <p>{failure}</p>}
    {evidence.samples.length > 0 && <>
      <ol className="specialist-evidence__timeline" aria-label="Returned frame samples" style={evidence.samples.length > 120 ? { gap: 0 } : undefined}>
        {evidence.samples.map(sample => <li key={sample.index}
          className={sample.valid ? sample.positive ? "sample-flagged" : "sample-clear" : "sample-unresolved"}
          title={`${sample.positionSeconds === null ? "Unknown time" : seconds(sample.positionSeconds)}: ${sample.valid ? sample.positive ? "AI indicator flagged" : "No flag" : "Invalid sample"}`}>
          <span className="sr-only">{sample.positionSeconds === null ? "Unknown time" : seconds(sample.positionSeconds)}: {sample.valid ? sample.positive ? "flagged" : "no flag" : "invalid"}</span>
        </li>)}
      </ol>
      <div className="specialist-evidence__legend"><span>Brown: flagged</span><span>Gray: no flag</span><span>Sampled every 0.5 seconds</span></div>
    </>}
    {evidence.persistentRuns.length > 0 && <p>Repeated flags at sampled positions from {evidence.persistentRuns.map(run => `${seconds(run.firstSampleSeconds)} to ${seconds(run.lastSampleSeconds)}`).join("; ")}. These endpoints do not establish that every intervening frame was generated.</p>}
    {evidence.isolatedAlerts.length > 0 && <p>Unresolved isolated alerts: {evidence.isolatedAlerts.map(alert => seconds(alert.positionSeconds)).join(", ")}. Brief AI inserts can produce isolated alerts.</p>}
    <p className="specialist-evidence__note">This is evidence to review, not proof of origin or a confidence percentage. AI between samples can be missed. This scan evaluates visual generation; it does not verify voices or face identity.</p>
    {evidence.samples.length > 0 && <details className="nested-details">
      <summary>Inspect sampled timestamps and raw scores</summary>
      <p>Vendor scores range from 0 to 1. They have not been calibrated into probabilities for videos submitted here.</p>
      <div className="specialist-evidence__table"><table><thead><tr><th>Time</th><th>Raw score</th><th>Observation</th></tr></thead>
        <tbody>{evidence.samples.map(sample => <tr key={sample.index}><td>{sample.positionSeconds === null ? "Unknown" : seconds(sample.positionSeconds)}</td><td>{sample.aiGenerated ?? "Unavailable"}</td><td>{sample.valid ? sample.positive ? "Flagged" : "No flag" : "Invalid"}</td></tr>)}</tbody>
      </table></div>
    </details>}
    </div>
  </details>;
}
