# Official signed Content Credential fixture

`CA.jpg` is the official C2PA JavaScript SDK's signed Reader test fixture,
copied unchanged from the `contentauth/c2pa-js` repository. Its test signer is
cryptographically valid but is not trusted by the application's trust policy.
The fixture declares conventional edits and contains no generative AI source
assertion. Tests must not change system trust settings or treat this test signer
as a trusted production issuer.

- Source: https://github.com/contentauth/c2pa-js/blob/7c5532da0419f64505e7271829fbe09d8c52d2d0/packages/c2pa-node/tests/fixtures/CA.jpg
- Upstream commit: `7c5532da0419f64505e7271829fbe09d8c52d2d0`
- Size: 166,864 bytes
- SHA-256: `e71bff58fc57640803e6e65f7534e2fb0c2f99018c85276cc14b30f04427cc76`
- License: upstream Adobe MIT license, included in `LICENSE`.

This image tests the provenance parser and native SDK signature validation. It
is not part of the video-detection accuracy corpus or evidence of AI detection
performance.
