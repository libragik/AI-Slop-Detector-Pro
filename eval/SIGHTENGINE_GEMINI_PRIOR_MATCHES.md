# Existing Gemini coverage before the paired comparison

Read-only search before the new 25-file Gemini run found **0/25** exact-byte predictions matching the preintegration detector fingerprint `e5924b9a24e01b6da7c2a09667f9122a7e8bc4bf42d097212e3bac40f74c352f` (policy 2.8, Gemini 3.7 Flash, 2 fps sweep and agentic review). The reference is the preserved source/bundle and receipt in `eval/runs/user-reel-Da7nZ5hs6H7-gemini-v1/`; the changing application checkout is not the reference.

Six files have older exact-byte successful predictions: four original benchmark clips (`056c0a6ab03ea042ef9969b7`, `14b4ba66fa34440f9c90b5c5`, `2129c615634c154928e05d23`, `b3ca93a3fd4d871394078d3e`) and two Sintel excerpts (`9d01860ad2c4dfa73fe779b0`, `fc45bccf51b8b03a5aad0542`). These were produced by the legacy baseline, evidence 2.1, 2.4 with Gemini 3.8, or 2.5 with 2/8 fps configurations. None can be presented as an exact current-policy paired result. Synthetic contract/error records were excluded from successful inference coverage.

The other **19/25** files have no located successful exact-byte Gemini prediction: eight AI derivatives, ten documented negatives and the original audio-bearing receipted Veo file. All four sustained Sightengine false positives fall in this missing set. The bounded search covered 18 prediction journals and 77 JSON artifacts in the relevant detector evaluation run families, without reading credentials or making new model calls.

This gap motivated the explicitly authorized single 25-file run in `eval/runs/sightengine-temporal-screen-v2-gemini-comparison/`. Its results are a paired development comparison on already selected/consumed sources, not fresh independent validation.
