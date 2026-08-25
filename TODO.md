# Proteus Current Work

## Now — V0.1 minimum opportunity finder

- [ ] Implement the three-gate domain models and deterministic opportunity
  evaluator against both fixture suites.
- [ ] Implement the low-volume eBay browser provider with the frozen `EBAY_US`
  market check, matching, sold parsing and explicit acquisition statuses.
- [ ] Implement candidate-pool CLI plus traceable manual-evidence import for the
  Amazon competition and 1688 supply stages.
- [ ] Run a real small candidate pool with current three-platform evidence and
  produce at least one `OPPORTUNITY_CANDIDATE` for product acceptance.

## Pre-work complete

- [x] Freeze the three-gate opportunity outcome while limiting V0.1 automation
  to the currently feasible eBay path in [V0_1_SCOPE_CONTRACT.md](V0_1_SCOPE_CONTRACT.md).
- [x] Define eBay acquisition plus the shared three-platform opportunity report
  contracts in [contracts](contracts).
- [x] Fix `EBAY_US`, manual Amazon/1688 evidence requirements, opportunity
  thresholds and failure/review semantics.
- [x] Add deterministic eBay fixtures and end-to-end opportunity gate fixtures
  under [fixtures](fixtures).

## Provider gates

- [ ] Confirm eBay production API eligibility and obtain an approved key through
  a local secret store.
- [ ] Confirm Amazon Associates/Creators API eligibility and written purpose
  compatibility before adding credentials.
- [ ] Identify an authorized 1688 buyer-side keyword-search API/solution, or make
  the V0 supply stage explicitly manual-assisted.

## Hold

- [ ] Do not build a complete three-platform automated acquisition funnel yet.
- [ ] Do not run 10,000-item load tests before provider access, rate and benchmark
  accuracy are established.
- [ ] Do not add CAPTCHA solving, stealth, proxy-pool or anti-bot bypass logic.

See [DATA_SOURCE_RECONNAISSANCE.md](DATA_SOURCE_RECONNAISSANCE.md) for the current
evidence boundary.
