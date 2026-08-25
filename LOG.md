# Proteus Development Log

## 2026-08-25 — V0.2 automated-opportunity engineering preview complete

- Replaced the hand-curated-only entry point with deterministic candidate
  discovery from an Amazon B2B Product Opportunities CSV replay, including an
  automotive allowlist, primary-identifier selection, normalization, dedupe and
  row/field provenance.
- Implemented the fixed Amazon → eBay → 1688 short-circuit funnel. The runtime
  path is deterministic Python and does not call an Agent or LLM.
- Added managed Nexscope adapters for all three search surfaces and a HioBuy
  `search → detail → order preview` adapter. HioBuy is allowlisted to those
  three endpoints and has no create, pay or supplier-contact path.
- Bound non-manual 1688 decisions to the same provider request, offer, SKU and
  quantity; enforced source-specific provenance, freshness windows and
  credential-bearing redirect refusal.
- Added V0.2 acquisition/report schemas, fail-closed semantic revalidation and
  `automation_qualified`. CSV replay, managed-provider evidence, manual evidence
  and stale evidence cannot be presented as a current fully automatic result.
- Retained the V0.1 JSON route and corrected its checked-in synthetic eBay
  fixture to the V0.2 manual-provenance contract. The README command produces
  one synthetic `OPPORTUNITY_CANDIDATE` with
  `automation_qualified=false`.
- Documented the actual delivery surface: the runnable product is currently a
  Python CLI with V0.2 JSON contracts and provider callables. No front end,
  HTTP API, job runner, authentication layer or result store has been built.
- Passed 225 offline tests, Python bytecode compilation, JSON-contract checks,
  diff whitespace checks and a fresh Python 3.12 isolated-wheel CLI smoke run.
  Built `proteus_opportunity_finder-0.2.0-py3-none-any.whl` with SHA-256
  `7C32E8F985CC7FF8A2E2A66D98D800EFCD100AF57ABB28BE01D66F404D3E4874`.
- Product acceptance remains open. The current parser keeps one primary
  identifier per report row; automatic SP-API report retrieval, the complete
  UPC/MPN/model query chain, approved production credentials, HioBuy negative
  and multi-offer semantics, a real 20-item benchmark and at least one current
  `automation_qualified=true` opportunity are still required.

## 2026-08-25 — V0.1 engineering implementation complete

- Implemented the installable Python package, sequential candidate-pool CLI,
  schema-validated JSON I/O and atomic report writes.
- Implemented deterministic eBay → Amazon → 1688 short-circuit evaluation. All
  three stages must pass to produce `OPPORTUNITY_CANDIDATE`; failures and
  missing or ambiguous evidence remain explicit.
- Implemented the low-frequency eBay Playwright provider with system Edge
  support, first-page-only collection, finite retry, conservative matching and
  fail-closed `EBAY_US` market verification. It has no login, stealth or
  challenge-bypass path.
- Added traceable manual Amazon/1688 evidence import and runnable synthetic
  examples. The synthetic CLI run produced one three-gate opportunity candidate
  and is labelled engineering evidence only.
- Passed 109 offline tests plus Python bytecode compilation. Coverage includes
  all frozen opportunity fixtures, eBay parsing/status cases, JSON Schemas,
  provenance, short-circuit behavior and CLI partial-write prevention.
- Closed independent-review evidence gaps: Amazon now preserves and binds its
  query/count/source URL; 1688 binds purchasability, price and MOQ to the exact
  offer URL; eBay rejects mixed-region conflicts and wrong-page/query redirects.
- Mapped the remaining Playwright lifecycle exceptions to explicit acquisition
  statuses so one provider failure cannot escape and interrupt a candidate pool.
- Included both JSON Schemas in the built wheel and passed an isolated-venv CLI
  smoke run from outside the repository checkout.
- Live verification exposed two separate environment outcomes: an initial
  browser route resolved to Japan and produced a challenge/market mismatch;
  after using a US exit, the provider returned an explicit HTTP 403. Neither
  result was converted to zero demand or a passed gate.
- Product acceptance remains open: no current, traceable real candidate has yet
  passed all three platform gates. Synthetic fixtures are not a substitute for
  that acceptance condition.

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
