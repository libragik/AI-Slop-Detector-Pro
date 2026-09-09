# Shot-based AEGIS: feasibility assessment, not an executed study

The [fixed whole-window AEGIS screen](./AEGIS_DEVELOPMENT.md) failed its mixed-content gate. Its runner, checkpoint, threshold and failed outputs remain frozen, and the larger stage remains unrun. This assessment does not reopen that stage or turn one whole-generated success into an accuracy claim.

## A specific, limited hypothesis

AEGIS trains on one label per sampled clip. Its loss supervises clip-level heads, while temporal pooling combines observations; it has no segment-supervised objective requiring detection of any inserted AI interval. Separating edited shots could present inputs closer to that training task. This is a mechanistic hypothesis, not a demonstrated cause of the failed mixed result. The published `frame_scores` cannot supply trained localization: their head is not supervised by the inspected `compute_loss` and does not feed the fused decision. [Pinned training objective](https://github.com/MusapYildiz/ai_video_detection_benchmark/blob/d86a774fd971954a023e1cd00ed7ff5b2575e0d1/src/branches/detector_model.py#L274), [pixel branch](https://github.com/MusapYildiz/ai_video_detection_benchmark/blob/d86a774fd971954a023e1cd00ed7ff5b2575e0d1/src/branches/pixel_branch.py#L258).

One prospective wrapper would detect scene cuts with FFmpeg `scdet` at its installed default threshold 10, then use four-second windows at two-second strides within each shot, adding the final end-aligned window. Shots between one and four seconds would use the official whole-shot sampling path. The existing sixteen-frame preprocessing, batch size one, checkpoint, learned computation and main score threshold of 0.5 would stay fixed. A positive window would flag the complete video; if no window were positive and any portion were unsupported or failed, the video would abstain. False positives must be measured per complete video, including all its windows.

This policy has not been implemented or run. It requires a complete frozen specification for boundary timestamps, short shots, duplication, duration/resource limits and failure handling before inference. Its threshold is a prospective default, not a value selected from current detector outputs.

## Unresolved continuous mixtures

A two-second synthetic interval without a detected cut can remain mixed with camera footage in every four-second window. Shot segmentation cannot guarantee isolating it. Shorter shots also change sampled motion cadence; the official quality rules permit them but do not establish temporal-scale invariance. An any-window decision increases opportunities to falsely flag real footage. These are reasons to test a wrapper, not reasons to integrate one.

## Evidence needed before a new screen

A small rejection screen would require eight fresh parent sources: four documented text-only generations from two providers, two independently documented camera captures, and two independent conventional CGI renders. Keep exact job/capture/render records, parent hashes and deterministic edit timelines. Before inference, specify hard-cut and continuous two-second insert challenges, negative-only edits and matched repost derivatives. Related versions must remain grouped, with origin labels and edit recipes concealed from inference.

The proposed stop rule requires correct whole-generated and negative controls and detection of both insertion types; any failure stops the wrapper before a larger study. Even a pass would justify only further independent evaluation. The consumed coffee-generation control and existing benchmark outcomes cannot become a new untouched test.

Subsequent preparation found a [concrete local Wan generation path](./WAN_LOCAL_FEASIBILITY.md): official public safetensors and a Diffusers CPU implementation, with 28.929 GB of required model files. Full-weight Mac execution remains untested, but a second provider credential is not intrinsically required. The connected tools expose no direct second-provider video generator.

The [three agency camera sources](./INDEPENDENT_CAMERA_SOURCE_FEASIBILITY.md) were subsequently downloaded, hashed, probed, and [visually inspected at fixed one-second samples](./CAMERA_CONTROL_INSPECTION.md), with all frame hashes/PTS retained and zero detector calls. NOAA provides a conservative title-free camera excerpt; the other two are timelapses, and USGS retains overlays. They are not a broad ordinary-camera sample or verified raw masters. No new generation, wrapper inference, threshold fitting or production change occurred for this proposal. A complete frozen study still needs new generated/CGI parents and explicit construction/selection rules before inference.
