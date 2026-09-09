# Sightengine API: bounded access decision

**Executed September 8, 2026 after the user purchased API access and supplied credentials. The frozen maximum-frame decision rule failed and was not adopted. A later temporal evidence integration is documented separately.** All five submissions completed without retries, using 370 reported operations. The whole Veo clip and its four sampled insert positions scored positive; two conventional CGI controls also received isolated positive frames. The NOAA camera control was negative. Mixed localization failed because a CGI-only position was positive. [Actual results](./runs/sightengine-api-diagnostic-v1/receipt.json), [independent audit](./runs/sightengine-api-diagnostic-v1-independent-audit/REPORT.md).

The original protocol, execution claim and result are preserved. Requiring persistent positives while retaining isolated alerts as uncertain is a **new, unvalidated hypothesis**, motivated by these development results. It does not retroactively pass this test. [Follow-up design](./SIGHTENGINE_FOLLOWUP_DESIGN.md).

The completed [local training experiment](./DINOV2_TRAINING_DEVELOPMENT.md) failed its detection gates. The [post-result route review](./POST_DINOV2_ROUTE_DECISION.md) found no additional local candidate with both a verified runtime and established commercial checkpoint permission. Sightengine now has the limited diagnostic evidence summarized above; broad accuracy remains unestablished.

## Original frozen test

The [API fixture](./fixtures/sightengine-api-diagnostic-v1.json) fixes the same five consumed development files used in the refused browser-demo plan. The API protocol is separate: it uses returned frame scores and timestamps rather than a browser's video-level label.

| Order | Fixed file | Required clip outcome |
| --- | --- | --- |
| 1 | Receipt-backed whole Veo generation, 8 s | AI |
| 2 | Conventional CGI with the Veo insert at 3–5 s, 8 s total | AI, with the positive samples confined to the inserted interval |
| 3 | Matched conventional CGI, 8 s | Negative |
| 4 | Procedural pendulum render, 8 s | Negative |
| 5 | Documented NOAA camera trim, 5 s | Negative |

The request uses the documented synchronous video endpoint, `models=genai`, and a 0.5-second interval. Returned frame scores at least 0.5 are positive; the maximum supplies the clip decision. These are uncalibrated vendor scores. Complete reported sampling is required: first timestamp within 0.1 seconds of the start, successive gaps at most 0.6 seconds, and final timestamp within 0.6 seconds of the end. Timestamps must be ordered, distinct and inside the clip. Reported timestamps do not prove every-frame inspection. [Official API contract](https://sightengine.com/docs/ai-generated-video-detection).

Raw `info.position` values are retained and divided by 1,000 for seconds. This fixed millisecond interpretation is inferred from the official synchronous guide's second-frame example at position 2000, within its endpoint limited to clips shorter than 60 seconds. It is not a separately explicit unit declaration in the reviewed docs. Actual coverage that conflicts with this interpretation stops the run; the runner does not choose units based on which result looks correct. [Official synchronous guide](https://sightengine.com/docs/moderate-stored-video), [saved unit evidence](./sources/sightengine-api-v1/timestamp-unit-evidence.json).

Advancement requires all five clip outcomes to be correct, complete processing, valid operation accounting, and mixed-clip localization: at least one positive timestamp inside [3,5), with zero positive timestamps outside it. This localization gate responds to the trained candidate's demonstrated CGI false flags; it is fixed before seeing any API results. It is not a claim that this small test can establish a service's reliability.

## Limits and actual access needed

- Five sequential submissions, at most one per file, with a one-second pause after the previous response before the next submission. This conservative pacing respects the plan's one-request-per-second limit despite variable worker startup time. Use neutral upload filenames and no origin metadata in the request. Verify original file and provenance-reference hashes before submission.
- The five files total 37 seconds. At two samples per second and five operations per frame, reserving an extra endpoint sample for every clip gives 395 nominal operations. The runner stops before additional submissions if reservations or reported usage would exceed its 500-operation planning bound. The vendor controls billing; a local estimate cannot impose a server-side charge ceiling on a submitted request. [Operation definition](https://sightengine.com/faq/what-is-an-operation).
- Pricing checked during preparation: Starter $29/month with 10,000 included operations, video files up to 50 MB, and one concurrent video job; additional operations $0.002 each. The user has since purchased access. The exact current plan and remaining balance were not inspected by this evaluation. [Official pricing](https://sightengine.com/pricing).
- Hard 180-second limit per request, at most 1 MiB returned response, no redirects and no retry after an uncertain submission. Authentication, quota, accounting, malformed-result or transport failures stop remaining submissions. Classification errors are retained and do not prevent completing the other fixed controls when access and accounting remain valid.
- A separate immutable run directory records intent before each submission and retains outcomes, returned positions, scores, request identity, operations, errors and unattempted cases. Rerunning the same directory cannot send a duplicate job. Credentials stay in local process environment variables `SIGHTENGINE_API_USER` and `SIGHTENGINE_API_SECRET`; do not paste them into chat or save them in evaluation artifacts.

The request model name is fixed, but the public API documentation does not provide an immutable model release pin. Record the test date and returned identifiers; a later run cannot be assumed to use identical vendor weights.

## Preparation and next decision

The [standalone runner](../scripts/eval-sightengine-api.py) is complete and independently reviewed. All 19 [offline tests](./runs/sightengine-api-diagnostic-v1-offline-contract-v2/receipt.json) passed, including malformed/partial results, timestamp units, wrong mixed localization, uncertain submission without retry, actual outgoing-byte identity, secret handling and request pacing. The [actual preparation](./runs/sightengine-api-diagnostic-v1-preparation-v2/preparation.json) rehashed the five videos and all referenced provenance files without a network request.

The protocol was frozen at `2026-09-05T07:54:04.814473+00:00`, SHA-256 `4067a7bb937f9b7d351a19dde5766c161a62c32c04dc42537d0775380b6251f2`. Its runner SHA-256 is `b953a1dd11f3f2b5bf81f3c9d7819466fed1d98c7defeb234e0439c82ca852be`. The [freeze receipt](./runs/sightengine-api-diagnostic-v1-freeze/receipt.json), SHA-256 `5eb2c7bbcd085da9c250c2547640af4a527f3e3d8f623013748eee581ac2edf0`, retains proposed/frozen protocol copies, executable/test/doc snapshots and a successful post-freeze input validation. There are now five completed predictions and a permanent execution claim. The original browser study and all failed local experiments remain unchanged.

The following invocation has already completed; it is retained for documentation and must not be repeated:

```sh
eval/.venv/bin/python scripts/eval-sightengine-api.py --run \
  --fixture eval/fixtures/sightengine-api-diagnostic-v1.json \
  --output eval/runs/sightengine-api-diagnostic-v1 \
  --execute-api-requests
```

The global execution claim is preserved. Changing the output folder cannot authorize a duplicate study.

API access is no longer a blocker. The failed result motivates a separate temporal-evidence candidate and prospective tests, including the exact user-reported Instagram Reel. This five-control result does not establish product reliability or a confidence percentage.

September 8 follow-up: the separately frozen 25-file temporal screen also failed its gates. The app now displays that component as attributed evidence with conservative disagreement handling, not as a validated standalone verdict. See [integration and limits](../docs/SIGHTENGINE_INTEGRATION.md).
