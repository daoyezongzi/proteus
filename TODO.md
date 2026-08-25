# Proteus Current Work

## Now — V0.1 implementation

- [ ] Implement deterministic normalization, listing matching, sold-label
  parsing and the shared output models.
- [ ] Implement the low-volume eBay browser provider with the frozen `EBAY_US`
  market check and explicit acquisition statuses.
- [ ] Pass the offline fixture suite, then run the two live queries sequentially
  and record the evidence/result boundary.

## Pre-work complete

- [x] Freeze the single-query, first-page, eBay-only V0.1 scope and acceptance
  boundary in [V0_1_SCOPE_CONTRACT.md](V0_1_SCOPE_CONTRACT.md).
- [x] Define the shared `AcquisitionOutcome`, `ListingEvidence` and `Evidence`
  model in [contracts/v0_1_acquisition.schema.json](contracts/v0_1_acquisition.schema.json).
- [x] Fix `EBAY_US`, `en-US`, US ship-to and USD market context plus sold-label
  failure rules.
- [x] Add deterministic fixtures for positive, negative, ambiguous,
  normalized-number, cross-reference, replacement, left/right, condition and
  locale/failure cases in [fixtures/ebay_v0_1_cases.json](fixtures/ebay_v0_1_cases.json).

## Provider gates

- [ ] Confirm eBay production API eligibility and obtain an approved key through
  a local secret store.
- [ ] Confirm Amazon Associates/Creators API eligibility and written purpose
  compatibility before adding credentials.
- [ ] Identify an authorized 1688 buyer-side keyword-search API/solution, or make
  the V0 supply stage explicitly manual-assisted.

## Hold

- [ ] Do not build the complete three-platform funnel yet.
- [ ] Do not run 10,000-item load tests before provider access, rate and benchmark
  accuracy are established.
- [ ] Do not add CAPTCHA solving, stealth, proxy-pool or anti-bot bypass logic.

See [DATA_SOURCE_RECONNAISSANCE.md](DATA_SOURCE_RECONNAISSANCE.md) for the current
evidence boundary.
