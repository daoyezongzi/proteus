# Proteus Current Work

## V0.2.3 automatic MVP — implementation complete, live acceptance open

- [x] Add a threshold-driven automatic path that discovers candidates and runs
  eBay recent sold, Amazon US exact competition, eBay Product compatibility and
  an anonymous NY DMV/NHTSA vehicle-model proxy without Agent calls.
- [x] Implement bounded SerpApi asynchronous submit/poll and reuse it for eBay
  category search, exact sold search and eBay Product compatibility.
- [x] Replace the obsolete eBay `_sacat` request parameter with documented
  `category_id` and retain strict response-parameter binding.
- [x] Add server-side `POST /api/v1/mvp/runs`, status retrieval and policy APIs;
  all candidates remain `human_review_required=true`.
- [x] Keep MarketCheck credential storage/readiness as an optional enhancement
  and keep HioBuy optional.
- [x] Run a one-part live NY DMV/NHTSA vehicle canary; 2015 Toyota Camry returned
  62,334 NY year/make registrations, 9 sampled VINs, 8 usable decodes and an
  estimated 23,375 model registrations.
- [ ] Freeze a 20-candidate accuracy/cost benchmark and validate category-specific
  thresholds; the NY metric remains a state proxy, not nationwide VIO.
- [ ] Re-run the SerpApi eBay canary after its sold/complete engine recovers or
  SerpApi support confirms the failure. On 2026-08-27 both an exact part query
  and the popular `brake pads` control returned the provider error
  `eBay hasn't returned any results for this query`; `show_only=Complete` did
  not reach a terminal result within the bounded wait.
- [ ] Manually label benchmark results and approve category-specific
  `min_us_active_vins`; the current default request example is illustrative.
- [ ] Replace the recent-sold and NY registration proxies with authorized
  365-day/VIO sources before promoting any result to strict
  `MARKET_OPPORTUNITY_CANDIDATE`.

## V0.2.2 strict market screening — contract complete

- [x] Freeze the market-opportunity gates as eBay US trailing-365-day sales
  `> 20`, Amazon US exact competitors `<= 5`, and resolved compatible US
  vehicle parc `>=` an explicit per-run threshold.
- [x] Select the lowest-configuration service mix that still covers the three
  gates: SerpApi for discovery/Amazon, eBay Product Research normalized evidence
  for annual sales, and TecAlliance TecDoc VIO for fitment-aware US parc.
  Experian VIO remains the vehicle-parc fallback.
- [x] Add provider-neutral `EBAY_ANNUAL_SALES` and `US_VEHICLE_PARC`
  capabilities and typed request contracts so vendors can be replaced without
  changing screening policy or frontend payloads.
- [x] Add deterministic strict evaluation and frontend-safe
  `GET /api/v1/screening/policy` and `POST /api/v1/screening/evaluate`
  contracts. Missing, malformed or unbound evidence fails closed to
  `REVIEW_REQUIRED`.
- [x] Keep the strict evaluator independent of HioBuy. V0.2.3 automatic MVP setup
  uses anonymous NY DMV/NHTSA by default; MarketCheck and HioBuy/receiver stay optional.
- [ ] Obtain one authorized eBay Product Research export sample, freeze its
  columns/timezone/window semantics, and implement the deterministic 365-day
  importer. An HTML scraper or inferred sold count is not acceptable evidence.
- [ ] Complete TecAlliance commercial onboarding, record the customer-specific
  API/auth contract outside Git, implement the adapter, and pass a one-part
  fitment/VIO canary. Do not invent an endpoint or credential name from public
  marketing material.
- [ ] Define and approve `min_us_vehicle_parc` from the target category and
  economics. Until then every strict run must supply it explicitly.
- [ ] Add an acquisition job that gathers the three normalized evidence records
  before calling the evaluator. The current endpoint evaluates supplied
  evidence; it does not yet automate Product Research or VIO acquisition.
- [ ] Benchmark the repaired SerpApi eBay paths. Async submit/poll and current
  `category_id` are implemented; the provider has still shown slow/unstable live
  processing and needs the frozen 20-item acceptance run.
- [ ] Run a frozen 20-part benchmark and produce at least one real
  `MARKET_OPPORTUNITY_CANDIDATE` whose three evidence records are current,
  market-bound and independently auditable.

## V0.2.1 two-account managed profile — compatibility engineering complete

- [x] Make eBay Motors sold listings the automatic candidate source without
  treating title extraction as final demand evidence; every candidate is
  rechecked by the exact eBay demand gate.
- [x] Add SerpApi Amazon competition and eBay category-discovery adapters with
  fixed US context, `no_cache=true`, explicit pagination uncertainty and
  fail-closed auth/parser behavior.
- [x] Preserve the historical two-account path: SerpApi for
  discovery/Amazon/eBay and HioBuy for 1688 order preview. It is now an explicit
  compatibility/supply-validation profile, not the strict market-screening
  default.
- [x] Add `proteus setup` with Windows/OS keyring storage for both keys and the
  receiver; environment variables remain explicit CI overrides.
- [x] Add a loopback FastAPI surface for health, redacted configuration,
  provider readiness, async run submission and run retrieval. Keep secrets and
  receiver data out of request/response bodies.
- [x] Add a candidate-discovery JSON contract and a managed run envelope while
  preserving V0.1/V0.2 report compatibility.

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

- [ ] Optional official-tier enhancement: confirm Amazon SP-API account/role access and automate retrieval of
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
- [ ] Benchmark the implemented marketplace-specific managed adapters instead of building another
  site parser first:
  [SerpApi Amazon](https://serpapi.com/amazon-search-api) and
  [DataForSEO Merchant Amazon](https://docs.dataforseo.com/v3/merchant-api-overview/)
  for competition evidence; [SerpApi eBay](https://serpapi.com/ebay-search-api)
  for active/sold search evidence. Require raw URL/marker, US market control,
  freshness and incomplete-page diagnostics before accepting any provider.
  The SerpApi Amazon, eBay exact-sold and eBay category-discovery adapters and
  offline contract tests are complete; production credentials and the 20-item
  live benchmark remain open.
- [ ] Add the official
  [eBay Browse API](https://developer.ebay.com/api-docs/buy/api-browse.html) for
  active listing discovery, GTIN and vehicle-fitment checks. Canary whether the
  current item contract exposes a usable `quantitySold`; do not treat it as the
  sold-history gate unless that field is documented and bound. eBay currently
  marks Marketplace Insights as restricted and closed to new users.
- [ ] Retain HioBuy only as an optional downstream supply-validation adapter.
  Confirm account purpose compatibility and procurement expectations before
  production use; lack of a HioBuy account must not block strict market screening.
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

- [x] Implement the initial backend job/report API with async run creation,
  status/result retrieval and server-side provider secrets/receiver data.
- [ ] Add cancellation, progress events and report export after the initial
  in-memory run contract passes a real provider benchmark.
- [ ] Add persistent runs, candidates, evidence, provider attempts and report
  versions so interrupted jobs can resume and historical decisions remain auditable.
- [ ] Add bounded retries, rate limits, per-run cost ceilings, idempotency,
  provider health/readiness and structured operational metrics.
- [x] Add local OS-keyring secret storage and redacted configuration/readiness
  responses for the single-user loopback deployment.
- [ ] Add API user authentication, persistence retention rules and audit logs
  before exposing the service beyond loopback or accepting multi-user data.
- [ ] Package a reproducible local deployment and health check before building
  the front end; then implement the UI against the frozen job/report API rather
  than calling third-party providers from the browser.

### D. Provider and product acceptance

- [ ] Obtain approved access and written purpose compatibility for SerpApi,
  eBay Product Research evidence use, and TecAlliance VIO. HioBuy/1688 access is
  required only when optional supply verification is enabled.
- [ ] Run one-item canaries, then the frozen 20-item provider benchmark for
  coverage, exact-match precision, freshness, critical fields, failure
  classification and external cost. The 2026-08-25 direct eBay browser canary
  returned HTTP 403. The managed canary runner now exists, but its first run was
  blocked before live calls because every production credential was absent.
- [ ] Approve the strict profile only after annual-sales, exact-competition and
  fitment-resolved VIO source/freshness/coverage semantics pass the benchmark.
  The historical `execution.mode=AUTOMATED_MANAGED` and official-tier
  `automation_qualified` flags remain compatibility concepts.
- [ ] Produce at least one current, real strict
  `MARKET_OPPORTUNITY_CANDIDATE`. Then run optional supply and economics checks
  before calling it a product recommendation.

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
