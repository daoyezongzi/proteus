# Proteus Development Log

## 2026-08-25 — V0.1 implementation boundary frozen

- Completed the remaining pre-work for the eBay-first slice: fixed the input,
  first-page output, `EBAY_US` market context, status vocabulary, evidence
  invariants and implementation acceptance gate.
- Added a provider-neutral JSON Schema for `AcquisitionOutcome`,
  `ListingEvidence` and field-level `Evidence`.
- Added 11 fixture coverage categories: 2 live reconnaissance queries, 7
  acquisition-status cases, 4 normalization cases, 8 matching cases and 6
  sold-label cases.
- Decision: only exact/normalized-exact, new listings with an explicitly parsed
  positive sold count can contribute to observed demand; related, ambiguous or
  missing-sold cases require review, and side/condition mismatches are rejected.
- Boundary: V0.1 is CLI + JSON eBay evidence acquisition, not the original
  Amazon → eBay → 1688 opportunity funnel. The exact delta is recorded in
  [V0_1_SCOPE_CONTRACT.md](V0_1_SCOPE_CONTRACT.md).

## 2026-08-25 — Phase 0 initial data-source reconnaissance

- Completed official-document, anonymous HTTP and normal-browser checks for
  `53630-53010` and `A18-67004-004`.
- Confirmed an eBay browser vertical slice is technically viable: both fixtures
  were discoverable and listing-level sold evidence was visible.
- Confirmed direct anonymous HTTP search failed for Amazon and eBay, while 1688
  returned a challenge payload; 1688 browser search required login.
- Confirmed Amazon Creators API and 1688 Open Platform are conditional paths,
  but local credentials/approval are absent, so neither API was executed.
- Decision: proceed eBay-first; hold the complete three-platform funnel until
  Amazon and 1688 provider gates pass.
- Detailed evidence and boundaries: [DATA_SOURCE_RECONNAISSANCE.md](DATA_SOURCE_RECONNAISSANCE.md).
