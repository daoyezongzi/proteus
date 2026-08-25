# Proteus Current Work

## V0.2 engineering preview — complete

- [x] Generate one deterministic primary-identifier candidate per Amazon B2B
  Product Opportunities CSV row instead of requiring a hand-curated OEM/MPN pool.
- [x] Run the deterministic Amazon → eBay → 1688 short-circuit funnel without
  Agent/LLM calls in the runtime path.
- [x] Add Nexscope managed REST adapters with explicit auth/HTTP/timeout/parser,
  market and incomplete-page outcomes.
- [x] Add HioBuy 1688 search/detail/order-preview verification with exact
  offer/SKU/quantity binding and no create/pay path.
- [x] Add V0.2 schemas, candidate provenance and `automation_qualified`; retain
  V0.1 JSON input compatibility.
- [x] Bind every non-manual supply decision to a structured
  offer/SKU/quantity preview and make automatic qualification fail closed on
  stale reports or evidence.
- [x] Bind provider/request/offer/SKU/quantity into field-level preview evidence,
  enforce source-specific provenance, and refuse credential-bearing redirects.
- [x] Preserve the rule that listing-level 1688 evidence cannot prove
  purchasability.

## Product acceptance — open

- [ ] Confirm Amazon SP-API account/role access and automate retrieval of
  `GET_B2B_PRODUCT_OPPORTUNITIES_NOT_YET_ON_AMAZON`; downloaded CSV replay does
  not qualify as a fully automatic source.
- [ ] Preserve all usable MPN/model/UPC identifiers from each report row and
  implement the frozen independent `UPC -> exact MPN -> exact model` query plan;
  the engineering preview currently evaluates only its selected primary identifier.
- [ ] Obtain approved production credentials and written purpose compatibility
  for every selected Amazon, eBay, Nexscope and HioBuy/1688 path.
- [ ] Run one-item canaries, then the frozen 20-item provider benchmark for
  coverage, exact-match precision, freshness, critical fields, failure
  classification and external cost.
- [ ] Capture an authorized HioBuy unavailable-preview fixture and confirm how
  `unavailable_lines` binds offer/SKU/quantity; until then an unbound negative
  response remains `REVIEW_REQUIRED` to avoid a false rejection.
- [ ] Freeze a bounded multi-offer fallback policy for 1688 so one unavailable
  exact offer cannot reject a candidate while another exact offer is still untested.
- [ ] Replace or approve managed providers only after their source/freshness/
  coverage semantics pass the benchmark; current managed results cannot set
  `automation_qualified=true`.
- [ ] Produce at least one current, real, three-gate
  `OPPORTUNITY_CANDIDATE` with successful 1688 order preview and
  `automation_qualified=true`.

## Compatibility and safety

- [x] Keep the V0.1 direct candidate, offline eBay and manual Amazon/1688 input
  route runnable; these outputs are never automation-qualified.
- [x] Keep Playwright eBay only as an explicitly selected compatibility path,
  not the V0.2 default.
- [x] Do not add CAPTCHA solving, stealth, login automation, proxy pools,
  automatic VPN switching, order creation, payment or supplier contact.
- [x] Do not scale beyond the 20-item benchmark before provider access,
  accuracy, freshness and cost gates pass.

See [V0_2_EXECUTION_PLAN.md](V0_2_EXECUTION_PLAN.md) for the frozen execution
boundary and [DATA_SOURCE_RECONNAISSANCE.md](DATA_SOURCE_RECONNAISSANCE.md) for
the original public-access reconnaissance.
