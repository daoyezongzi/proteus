# Proteus Current Work

## Now

- [ ] Build the eBay fixture-to-evidence vertical slice with explicit US market
  context and localized sold-text parsing.
- [ ] Add fixtures covering negative, ambiguous, left/right, replacement and
  normalized-number cases.
- [ ] Define the shared acquisition outcome and evidence models before adding a
  second provider.

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
