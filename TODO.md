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

## Deliverable MVP — critical path

### A. Live source and discovery layer

- [x] Add provider-neutral `preflight/acquire/estimate_cost` contracts, an
  explicit allowlist registry and a `FunnelProviders` boundary so business gates
  do not import vendor payloads or choose implicit fallbacks.
- [x] Add a redacted `providers check` one-item canary and a SerpApi eBay Sold
  adapter with fixed US/new/sold/no-cache parameters, raw listing evidence,
  incomplete-page diagnostics and fail-closed parser/auth outcomes.

- [ ] Confirm Amazon SP-API account/role access and automate retrieval of
  `GET_B2B_PRODUCT_OPPORTUNITIES_NOT_YET_ON_AMAZON`; downloaded CSV replay does
  not qualify as a fully automatic source. Reuse the community
  [`python-amazon-sp-api`](https://github.com/saleweaver/python-amazon-sp-api)
  Reports client unless its credential/report behavior fails the canary. Version
  2.1.20 imports cleanly on the project Python 3.12 environment; credentials,
  Seller report access and create/poll/download integration remain open.
- [ ] Preserve all usable MPN/model/UPC identifiers from each report row and
  implement the frozen independent `UPC -> exact MPN -> exact model` query plan;
  the engineering preview currently evaluates only its selected primary identifier.
- [ ] Add a separate `SearchDiscoveryProvider` contract for exact, domain-scoped
  URL discovery. It must retain query, URL, title/snippet, provider, retrieval
  time and provider crawl/index time. Search absence is never zero-results
  evidence and search snippets alone cannot set a gate to `PASSED`.
- [ ] Pilot [`tavily-python`](https://github.com/tavily-ai/tavily-python) first
  because its current keyless mode supports bounded `search` and `extract`;
  compare exact-part coverage and cost with
  [Brave Search](https://api-dashboard.search.brave.com/app/documentation/web-search)
  and [Exa Search + Contents](https://exa.ai/docs/reference/search). Keep Agent
  query expansion optional and downstream of deterministic exact-ID queries.
- [ ] Benchmark marketplace-specific managed data instead of building another
  site parser first:
  [SerpApi Amazon](https://serpapi.com/amazon-search-api) and
  [DataForSEO Merchant Amazon](https://docs.dataforseo.com/v3/merchant-api-overview/)
  for competition evidence; [SerpApi eBay](https://serpapi.com/ebay-search-api)
  for active/sold search evidence. Require raw URL/marker, US market control,
  freshness and incomplete-page diagnostics before accepting any provider.
  The SerpApi eBay adapter and offline contract tests are complete; production
  credentials and the 20-item live benchmark remain open.
- [ ] Add the official
  [eBay Browse API](https://developer.ebay.com/api-docs/buy/api-browse.html) for
  active listing discovery, GTIN and vehicle-fitment checks. Canary whether the
  current item contract exposes a usable `quantitySold`; do not treat it as the
  sold-history gate unless that field is documented and bound. eBay currently
  marks Marketplace Insights as restricted and closed to new users.
- [ ] Retain HioBuy as the first 1688 structured candidate because its standard
  API covers search/detail/order preview, but confirm account purpose compatibility
  and procurement expectations before production use.
- [ ] Evaluate [Crawlee for Python](https://crawlee.dev/python/) as the reusable
  request queue, retry, throttling, resume and Playwright orchestration layer.
  Use it only for ordinarily accessible pages; adopting the library must not
  enable proxy rotation, fingerprint spoofing or challenge bypass.

### B. Product identity and commercial decision

- [ ] Build cross-platform identity resolution across normalized part number,
  UPC/EAN, brand, model, title and vehicle fitment. Conflicting identifiers or
  unresolved cross-references must remain `REVIEW_REQUIRED`.
- [ ] Add an explicit unit-economics model: target sale price, purchase price,
  domestic and international shipping, marketplace/payment fees, exchange-rate
  timestamp, tax/duty allowance, return/risk reserve, net profit and margin.
- [ ] Freeze minimum net-profit/margin thresholds and rank opportunity candidates
  by profit, evidence confidence, demand strength and supplier risk. A three-gate
  pass without acceptable economics must not become a product recommendation.
- [ ] Capture an authorized HioBuy unavailable-preview fixture and confirm how
  `unavailable_lines` binds offer/SKU/quantity; until then an unbound negative
  response remains `REVIEW_REQUIRED` to avoid a false rejection.
- [ ] Freeze a bounded multi-offer fallback policy for 1688 so one unavailable
  exact offer cannot reject a candidate while another exact offer is still untested.

### C. Backend product surface

- [ ] Implement a backend job/report API with run creation, progress/status,
  cancellation, result retrieval and report export; keep provider secrets and
  receiver data server-side.
- [ ] Add persistent runs, candidates, evidence, provider attempts and report
  versions so interrupted jobs can resume and historical decisions remain auditable.
- [ ] Add bounded retries, rate limits, per-run cost ceilings, idempotency,
  provider health/readiness and structured operational metrics.
- [ ] Add authenticated secret management, retention/redaction rules and audit
  logs before accepting production credentials or receiver data.
- [ ] Package a reproducible local deployment and health check before building
  the front end; then implement the UI against the frozen job/report API rather
  than calling third-party providers from the browser.

### D. Provider and product acceptance

- [ ] Obtain approved production credentials and written purpose compatibility
  for every selected Amazon, eBay, search, managed and HioBuy/1688 path.
- [ ] Run one-item canaries, then the frozen 20-item provider benchmark for
  coverage, exact-match precision, freshness, critical fields, failure
  classification and external cost. The 2026-08-25 direct eBay browser canary
  returned HTTP 403. The managed canary runner now exists, but its first run was
  blocked before live calls because every production credential was absent.
- [ ] Replace or approve managed providers only after their source/freshness/
  coverage semantics pass the benchmark; current managed results cannot set
  `automation_qualified=true`.
- [ ] Produce at least one current, real, economically acceptable three-gate
  `OPPORTUNITY_CANDIDATE` with successful 1688 order preview and
  `automation_qualified=true`.

## Search/crawl evidence boundary — frozen

- [x] Search indexes and Agent search may discover a URL that the current runtime
  cannot fetch. “Searchable” therefore does not imply “directly crawlable from
  this IP/session” or “complete enough for a negative decision.”
- [x] Search snippets and extracted public pages may create candidate/positive
  evidence records, but absence remains `REVIEW_REQUIRED`; current sold history
  and 1688 purchasability still require their dedicated evidence paths.
- [x] Do not adopt community scrapers that require residential proxy pools,
  browser/TLS impersonation, login-wall evasion or CAPTCHA bypass under the
  current product boundary. They may be listed for an authorization review but
  are not implementation dependencies.

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
