# Proteus Development Log

## 2026-08-25 — V0.1 product boundary corrected to retain opportunity finding

- Corrected the prior scope error: an eBay-only evidence collector is an
  internal implementation milestone, not the first product version.
- Restored all three business gates in V0.1. An opportunity candidate now
  requires Amazon low-competition, eBay observed-demand and 1688 purchasable-
  supply evidence.
- Kept the feasibility boundary intact: eBay is the only automated provider in
  V0.1; Amazon and 1688 use explicit, traceable manual evidence until their
  authorized provider gates pass.
- Added the three-stage `OpportunityCandidateReport` contract and 19 synthetic
  gate/decision fixtures. Missing or blocked evidence produces
  `REVIEW_REQUIRED`, never an opportunity candidate.
- Product acceptance now requires at least one real, evidence-backed
  `OPPORTUNITY_CANDIDATE` from a small current candidate pool.

## 2026-08-25 — V0.1 eBay acquisition sub-slice frozen

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
- This eBay-only boundary is retained as an internal acquisition component. It
  was superseded as the product boundary by the three-gate correction above.

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
