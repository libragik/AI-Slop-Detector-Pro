# Frozen temporal diagnostic: 25 existing files

**Prepared September 8, 2026; no API calls by this preparation.** This is a separate candidate after the failed maximum-score rule. The final [manifest](./fixtures/sightengine-temporal-screen-v2.json) binds the [policy](./fixtures/sightengine-temporal-policy-v2.json), reviewed aggregator and exact media/evidence hashes. [Freeze receipt](./runs/sightengine-temporal-screen-v2-freeze/receipt.json). The earlier v1 preparation remains unchanged; v2 adds the executable schema and aggregator binding before inference, with identical media selection and thresholds.

| Cohort | Files / parents | Interpretation |
| --- | --- | --- |
| Publisher-assigned modern-generator positives | 12 / 12 registered source parents | Four original, four mild and four severe; deterministic hash-balanced assignment. Labels are dataset-author assertions, not verified generation jobs. Report this recall separately. |
| Documented camera and conventional CGI negatives | 12 / 6 parents | NASA, NOAA, USGS, pendulum, rolling-track and Sintel; two variants/intervals each. Three camera events and three CGI sources, with known processing limitations. |
| Directly receipted raw Veo output | 1 / 1 already consumed parent | Different bytes from the silent five-control file, same generated visual parent. A consistency check, not new-source recognition. |

The five submitted file hashes and the user's Reel hash are absent. Source ancestry still overlaps for NOAA, pendulum, Sintel and Veo, as marked in each row. All files were used in earlier development work; no independent/population claim follows. There is no eligible new mixed-positive file with verified insertion truth after the exclusions. The temporal rule's subsecond limitation remains untested here.

The rule fixes score **>=0.5**, at least **two consecutive returned samples** with gaps **<=0.6 seconds**, and the existing complete 0.5-second sampling contract. Intervening negative/invalid samples cannot be skipped. Isolated positive samples remain unresolved; without a persistent run the result is Inconclusive. Zero hits means No clear AI indicators, never proof of non-generative origin. A persistent run can coexist with unresolved isolated alerts, which must remain visible. Technical incompleteness fails the study separately.

Advancement requires all 25 technical completions, zero sustained false alerts on the twelve documented negatives, at least 10/12 negative files and 5/6 negative parents clearly negative, at least 10/12 publisher-labeled AI detections with at least 3/4 in each quality, and the raw Veo check positive. Abstentions count as non-detections in unconditional recall. Report source-parent outcomes, usable coverage, all isolated alerts, false alerts, errors, latency and actual operations. A pass only informs a narrow experimental next step; it does not validate calibrated confidence, new mixed clips or subsecond detection.

The exact reservation is **1,485 operations**, hard planning cap **3,000**, 25 sequential requests, no retry of an uncertain submission. Reported vendor usage remains authoritative. Preparation verified all media bytes and fresh duration probes, preserved source snapshots, read no secrets and performed no network/model/media-edit action.

Final identities:

- Manifest: `1374a18b17699d6aef0ef0868b21f9f580bdbaa667f26caa45d92d0dcacc25b7`.
- Bound candidate policy: `e312121b5efbdfe21f75bde8b42a4f017d606f97e6668f4a0cdd404938a77a32`.
- Aggregator source: `527b15281583255c975c60b7f8f3b44981c2a6744a6ab4af514bc61b667a7453`.
- Aggregator policy fingerprint: `6544a9d76ce994fecfc2c736b4f3af79b744f1cafa11a1e66145e849e30aea89`.
