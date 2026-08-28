# Proteus Development Log

## 2026-08-28 — Claude/TradeEye-style Northway operator workbench

- Rebuilt the Northway frontend into a focused operator workbench: fixed
  navigation rail, translucent utility bar, warm-white Anthropic-style palette,
  serif hierarchy and restrained status colors. The page remains dependency-free
  HTML/CSS/JS and keeps the existing loopback API contract.
- Kept the merged all-archetype behavior explicit in the UI. The scan scope now
  renders both Northway profiles and all nine enabled part types, while the
  result surface adds per-archetype coverage so zero results remain distinct from
  provider failures.
- Reworked candidate reports around the sellable product family: core metrics,
  six-stage status path, fitment/package identity, Amazon query pack, relevant
  products, source listings, evidence gaps and the three-item manual review
  checklist are readable without losing the full JSON export path.
- Preserved the existing request fields, async polling, status filters and
  rejected-result separation. Browser replay on the local stub completed one
  scan, switched to the rejected category, expanded the evidence chain and
  downloaded the complete JSON export. JavaScript syntax, HTTP homepage,
  `git diff --check` and all 325 offline tests passed.

## 2026-08-28 — Live run diagnosis: Amazon evidence budget and pagination

- Inspected the exported run `e2cf5192-fda9-4ee6-a42e-aa0906247fe6.json`.
  The API run completed locally from 13:06:52 to 13:17:39; the apparent
  endless scan was not a backend process crash. The JSON export is present
  in the user's Downloads directory.
- The run emitted 80 candidate reports, resolved 54 product families and used
  the full `80/80` request budget. Among the 54 resolved families, Amazon
  competition was `PASSED=0`, `REVIEW_REQUIRED=44` and `REJECTED=10`.
  The 10 rejections had an observed lower bound of 4, 5, 7, 11, 12, 13, 14,
  26, 36 or 39 interchangeable product clusters against a configured limit
  of 3; they are decisive lower-bound rejections rather than empty results.
- The 129 recorded Amazon query slots contained 20 `SUCCESS`, 48
  `PARTIAL_SUCCESS`, 2 `PARSER_FAILED`, 1 `HTTP_ERROR` and 58
  `REQUEST_BUDGET_EXHAUSTED`. Every partial query had `has_next_page=true`,
  so all 54 resolved families had incomplete competition evidence and none
  could prove low competition. The default budget covers the nine discovery
  requests but not the 129 family queries; sequential allocation starved
  later cable archetypes, which received no executed Amazon query.
- The Amazon family classifier recorded 209 `INTERCHANGEABLE`, 468
  `REVIEW_REQUIRED`, 144 `PACKAGE_MISMATCH`, 21 left/right counterpart and
  811 irrelevant observations. The large review/irrelevant share reflects
  conservative title evidence: part-type matches without an exact identifier
  or complete make/model fitment are not counted as interchangeable. This is
  separate from the primary run-level blocker, which is incomplete evidence.
- Follow-up priority: make family-query budget allocation candidate-aware,
  continue or explicitly bound paginated fitment queries, and surface budget
  exhaustion separately from Amazon competition failure in the result UI.

## 2026-08-28 — All-archetype scan and status-filtered review surface

- Removed the public single-part-type input. Every Northway V0.2.4 run now
  scans all nine narrow archetypes, preserves each discovery keyword/status in
  `discovery.per_archetype`, and exposes the full query manifest for later UI
  work. The request budget must cover every requested discovery page first.
- Kept the interface change functional and minimal: actionable/review results
  are shown by default, rejected results live in a separate selectable status
  category, and the complete JSON export still contains every report.
- Updated the result schema, API contract, replay harness, focused tests,
  README usage instructions, execution plan and current TODO. No visual redesign
  was included; stable data and DOM hooks are reserved for that later pass.
- Passed all 325 offline tests, Python compilation, dependency checks,
  JavaScript syntax checks, JSON parsing, schema validation and whitespace
  validation. Functional browser replay confirmed the default/rejected category
  switch, and the live API exposed nine archetypes with no single-type field.

## 2026-08-28 — V0.2.4 Northway initial-screening MVP runnable

- Implemented a separate `northway-product-family-mvp` runtime while preserving
  the V0.2.3 exact-OEM compatibility API. The new UI needs only SerpApi; domestic
  supply and margin are explicit manual-review items rather than extra required
  credentials for the initial screen.
- Added nine narrow trim/cable archetypes, deterministic out-of-scope controls,
  sellable-family resolution, left/right and pair identity, four/two-digit year
  normalization, fitment-aware Amazon query packs and conservative result
  classification.
- Separated substitute-product clusters, relevant ASIN count, seller offers by
  ASIN, total offer lower bound, family price floor and aftermarket price floor.
  Incomplete searches can reject on a decisive observed lower bound but cannot
  prove low competition.
- Added `/api/v1/northway/policy`, asynchronous run/status endpoints and a JSON
  download endpoint. The V0.2.4 request has no `max_candidates`; pages and a
  total provider request budget bound the run, and budget-exhausted candidates
  remain in the export with evidence gaps.
- Replaced the default operator surface with a Chinese-first Northway selection
  bench. It shows ranked family cards, pass/review/reject stages, Amazon queries,
  related products, source links and the three-item manual review checklist.
- Deterministic browser replay produced one market shortlist and one rejection
  from left/right fog-bezel families; JSON download fired successfully and the
  final desktop layout was visually verified.
- A real SerpApi fog-light-bezel probe inspected 60 eBay results, found 41 sold
  listings, emitted 14 candidate listing groups and resolved seven families.
  With a five-request budget and one Amazon query per family it returned three
  market shortlists, three review cases and eight rejections. The probe exposed
  `11-14` short-year parsing, which was fixed and covered by a regression test.
- Full unit tests, Python compilation, JavaScript syntax validation, dependency
  checks, strict JSON parsing and `git diff --check` passed. The only test warning
  is the existing Starlette/httpx TestClient deprecation notice.

## 2026-08-28 — Northway product-family target frozen

- Reviewed the current product brief, execution plan, TODO, development log and
  the latest local Proteus task history. The drift occurred because runnable
  acquisition proxies and non-empty discovery were optimized before product
  identity: broad eBay `6028` discovery plus `OEM` title-token extraction can
  emit years, generic terms and highly substitutable products even when an
  exact OEM query looks sparse.
- Replaced the product objective with Northway-style vehicle-specific small
  replacement parts whose complete substitute-product family is genuinely
  under-supplied on Amazon US. northwayautoparts is a product-shape and gold-
  labeling reference, not a fixed candidate feed or an automatic pass list.
- Froze two first-batch category profiles: small vehicle-specific trim/covers
  and simple vehicle-specific mechanical cables. Universal-fit goods,
  chemicals, generic accessories, complex electronics, safety-critical parts,
  lamp assemblies, large panels and heavy assemblies are explicitly out of
  scope.
- Reclassified the benchmark roles: Northway listing/part examples form the
  primary gold set; `467903X100` is an external Northway-like extension case;
  `00289-ACRKT` and Universal-fit goods are negative controls.
- Defined `sellable_product_family` from part type, fitment, required engine or
  transmission qualifiers, mounting position/side, critical specifications and
  package quantity. OEM/MPN/UPC and Replacement/Replaces relations now serve
  discovery and traceability rather than defining the competition boundary.
- Separated substitute product/ASIN count, seller offers per ASIN and the
  substitute-family price floor. The lowest aftermarket family price cannot be
  hidden by an expensive OEM result, and offer saturation cannot be reported as
  product variety.
- Froze the bounded-unlimited run rule: no `max_candidates` truncation inside a
  configured scan manifest, while pages/cursors, rate limits and budgets remain
  explicit. Incomplete evidence continues to other independent collectors;
  only an explicit scope, identity or business-gate failure may short-circuit
  expensive downstream work.
- Required a complete JSON review artifact containing every candidate, actual
  category profile and scan manifest, family identity, query pack, rule
  readings, source evidence, provider attempts, failure reasons and rank.
- Updated `proteus.md`, `V0_2_EXECUTION_PLAN.md` and `TODO.md`, then added the
  provider-independent V0.2.4 product-family resolution JSON Schema and a
  versioned Northway fixture covering seven store-derived gold cases, the
  `467903X100` extension case and two out-of-scope controls.
- Added contract tests for schema validity, all fixture outcomes, profile
  coverage, left/right separation, pair semantics, extension-sample role and
  negative-family suppression. All 18 focused tests passed and both new JSON
  files passed strict parsing.
- This entry records the design/fixture checkpoint. The later V0.2.4 entry above
  supersedes its implementation-status sentence with a runnable initial-screening
  path; the V0.2.3 compatibility runtime itself remains unchanged.

## 2026-08-28 — Discovery extraction debug and five-gate automatic MVP

- Reproduced `6028` / `auto parts` against the live provider. The request was
  successful and returned 60 cards; 49 had explicit sold evidence, but none of
  those 49 titles contained a token accepted by the conservative part-number
  extractor. This was a keyword/rule mismatch, not a false provider failure.
- Ran the same category with `OEM` and immediately extracted the requested 20
  candidates (including `00289-ACRKT`, `12204-37010` and `42602-0R040`), so the
  editable discovery keyword now defaults to `OEM`.
- Added discovery funnel statistics for results seen, eligible sold listings,
  listings with an extractable part number and emitted candidates. The
  bilingual empty-result notice now exposes these counts; the schema keeps the
  field optional so historical V0.2 discovery records remain replayable.
- Changed the frontend-editable eBay recent-sold threshold default from `20` to
  `0`. The rule remains strict `eligible_listing_count > threshold`, so the
  default requires at least one exact sold listing rather than treating a
  missing/invalid count as a pass.
- Removed the NY vehicle-population proxy from the automatic MVP, including its
  request field, policy criterion, report stage and sixth frontend mesh. eBay
  compatibility remains the fifth gate; the separate strict-market-screening
  VIO contract and adapters remain available.
- Passed all 293 offline tests, Python bytecode compilation, dependency checks,
  JavaScript syntax checks and `git diff --check`. Restarted the loopback API
  and verified the live policy and OpenAPI defaults.
- Browser-tested the real operator bench on desktop and at a 390px mobile
  viewport. Both show five non-overlapping gates, editable `OEM` / `0` / `20` /
  `10` defaults, no horizontal overflow and no browser console errors.

## 2026-08-27 — Configurable Amazon price and offer-saturation gates

- Added two independent automatic-MVP gates after exact Amazon product count:
  the minimum price across exact search results must be strictly above a
  frontend-editable USD threshold (default `$20`), and the active-offer
  saturation proxy must be at or below a frontend-editable ceiling (default
  `10`). The existing exact-product ceiling remains a separate rule.
- Preserved strict uncertainty semantics. Missing prices cannot pass; a value
  such as `343+ used & new offers` is retained as a lower bound and decisively
  rejects against `10`, while an incomplete lower bound below the ceiling
  requires human review.
- Extended the SerpApi Amazon evidence with exact-result minimum price,
  per-product offer-count observations and completeness flags. The metric is
  explicitly an active-offer proxy, not a claim of deduplicated seller count.
- Added both controls to the bilingual operator bench and the asynchronous API
  request contract, including decimal price input and the requested seller
  ceiling default of `10`.
- Passed all 295 offline tests, Python bytecode compilation, dependency checks,
  JavaScript syntax checks and `git diff --check`. Restarted the loopback API;
  live health, policy, OpenAPI and served frontend probes all expose defaults
  `$20` and `10`.
- Browser-tested the real loopback operator bench on desktop and a 390px mobile
  viewport. Both new controls are visible and editable (`25.50` / `7` probe),
  defaults restore to `20` / `10`, all six gates fit without overlap, and the
  page emitted no console errors.

## 2026-08-27 — Discovery zero-result and provider-failure states separated

- Reproduced the empty discovery card with one live `6028` / `auto parts`
  request. DNS, TCP 443 and the SerpApi home page were reachable, while the
  search endpoint consistently ended its TLS connection with
  `UNEXPECTED_EOF_WHILE_READING`; this is a provider/search-path transport
  failure, not evidence of zero demand.
- Corrected automatic-run accounting so `pages_attempted` and
  `pages_completed` are distinct and a failed page is never reported as
  successfully read. The discovery summary now carries its aggregate status.
- Corrected the SerpApi parser contract: a top-level `error` paired with
  `search_metadata.status=Success` is the provider's documented empty-result
  shape and now maps to `ZERO_RESULTS`, while actual transport/API failures
  remain explicit.
- Split the frontend's former ambiguous empty notice into provider failure,
  explicit zero results and successful-page/no-extracted-candidate states. The
  failure view surfaces the first redacted backend diagnostic without exposing
  provider credentials or raw responses.
- Passed all 290 offline tests, Python bytecode compilation, JavaScript syntax
  checks and direct frontend notice probes. Live acceptance remains blocked by
  the current TLS failure on the SerpApi search endpoint.

## 2026-08-27 — Anonymous NY DMV/NHTSA vehicle proxy replaces MarketCheck default

- Replaced the automatic MVP's required MarketCheck vehicle stage with an
  anonymous NY DMV Socrata + NHTSA vPIC adapter. NY DMV supplies active
  year/make VIN totals; a bounded fixed-offset VIN sample is decoded by NHTSA
  and matched to eBay year/make/model fitments.
- Added fail-closed partial semantics, deterministic sampling evidence, model
  normalization, fitment deduplication and injectable transports. No API
  credential is needed; incomplete count/sample/decode never becomes zero or a
  passing vehicle gate. MarketCheck remains an optional compatibility adapter.
- A real anonymous 2015 Toyota Camry canary succeeded: 62,334 NY active
  year/make registrations, 9 sampled VINs, 8 usable decodes, 3 Camry matches,
  and an estimated 23,375 NY model registrations. This is not nationwide
  official VIO and no formal confidence interval is claimed.
- Automatic MVP configuration now requires only `SERPAPI_API_KEY`;
  `/api/v1/mvp/*` paths, request fields and async job shape are unchanged, so
  frontend work can continue without migration.
- Live end-to-end selection acceptance remains open because the SerpApi eBay
  engine previously returned errors/timeouts and the 20-candidate benchmark has
  not yet passed.

## 2026-08-27 — Automatic two-key MVP implemented; live eBay acceptance blocked upstream

- Added an independent `automatic-mvp` path that performs deterministic eBay
  sold-category discovery, exact eBay demand recheck, Amazon US exact
  competition, eBay Product compatibility and MarketCheck US used-active-
  inventory VIN proxy screening. Every pass remains
  `human_review_required=true` and is distinct from the strict 365-day/VIO
  profile.
- Added bounded SerpApi asynchronous submit/poll with trusted-host validation,
  transient poll-disconnect retry and no credential-bearing redirects. Updated
  eBay discovery to the documented `category_id` parameter and removed the
  now-rejected `_sop=13` value.
- Added normalized eBay compatibility and MarketCheck YMMT adapters. MarketCheck
  fixes `country=us`, `car_type=used`, `dedup=true` and `rows=0`; output is
  explicitly an observable proxy, never official vehicles-in-operation data.
- Added the frontend-ready policy and asynchronous job endpoints under
  `/api/v1/mvp`, plus MarketCheck OS-keyring configuration. The automatic MVP
  requires `SERPAPI_API_KEY` and `MARKETCHECK_API_KEY`; HioBuy remains optional.
- Live SerpApi diagnostics were kept redacted. The configured account accepted
  asynchronous searches, but both the exact `53630-53010` sold query and the
  popular `brake pads` control ended with the provider error `eBay hasn't
  returned any results for this query`; a `show_only=Complete` control exceeded
  the bounded wait. MarketCheck is not configured locally, so no live vehicle
  proxy call was attempted.
- Passed 280 offline tests, bytecode compilation, `pip check` and whitespace
  validation. Product acceptance remains open until the SerpApi eBay engine
  recovers or is replaced, MarketCheck is configured, and a human-labelled
  20-candidate benchmark meets coverage, cost and precision targets.

## 2026-08-27 — Strict market screening contract and simplified service profile

- Replaced the product-level definition of opportunity with three explicit
  market gates: eBay US trailing-365-day units sold `> 20`, Amazon US exact
  competitors `<= 5`, and fitment-resolved compatible US vehicle parc at or
  above an explicit per-run threshold. A pass is now
  `MARKET_OPPORTUNITY_CANDIDATE`; supply and economics remain downstream.
- Selected SerpApi for discovery/Amazon, eBay Product Research normalized
  evidence for annual sales, and TecAlliance TecDoc VIO for fitment-aware US
  parc, with Experian VIO as fallback. HioBuy is now an optional compatibility
  adapter rather than a default market-screening dependency.
- Added provider-neutral annual-sales and vehicle-parc capabilities/requests,
  deterministic strict evaluation and fail-closed source/market/window
  validation. No customer-specific TecAlliance endpoint or auth scheme was
  guessed from public material.
- Added frontend-safe policy/evaluation endpoints and exposed the strategy in
  redacted provider/config status. First-time setup now requires only SerpApi;
  `--with-hiobuy` explicitly enables the historical supply profile.
- The current configured SerpApi live probe passed Amazon. The eBay discovery
  call returned `HTTP_ERROR`, while the exact eBay call timed out; neither was
  converted to zero demand or a rejection. Product Research import,
  TecAlliance live acquisition, the VIO threshold and the 20-part benchmark
  remain open product-acceptance items.
- Passed 263 tests, forced bytecode compilation, `pip check` and
  `git diff --check`. The real redacted setup status returned
  `serpapi=configured, optional_hiobuy=not_ready`, confirming that the base
  profile works with one configured account and does not require HioBuy.

## 2026-08-25 — Two-account automatic discovery profile and frontend API

- Replaced the default managed MVP dependency set with two upstream accounts:
  SerpApi supplies eBay Motors sold-category candidates, Amazon competition and
  exact eBay sold verification; HioBuy supplies exact 1688 detail and bound
  order preview. Amazon B2B and Nexscope remain explicit compatibility options.
- Added deterministic eBay-title candidate extraction. Only new listings with
  an explicit positive sold count can seed tokens, and every token is re-run
  through the existing exact eBay demand gate before supply is queried.
- Added a SerpApi Amazon adapter with fixed US context and fresh searches. A
  next page, malformed product or market mismatch preserves uncertainty and
  cannot prove the low-competition threshold.
- Added `proteus setup`, backed by the OS keyring, so both API keys and the
  HioBuy receiver are entered once. Environment variables remain higher-priority
  CI overrides; status and API responses expose presence/source only.
- Added a loopback-only FastAPI interface for health, redacted config/provider
  status, asynchronous run creation and run retrieval. The initial queue is
  deliberately in-memory and replaceable behind `FrontendService`.
- Added `v0_2_candidate_discovery.schema.json`, the
  `EBAY_SOLD_DISCOVERY_API` provenance method and a managed run envelope. The
  existing official-tier meaning of `automation_qualified` was not weakened;
  automatic managed runs identify themselves as `AUTOMATED_MANAGED`.
- Passed 253 tests, `compileall`, `pip check` and wheel packaging (SHA-256
  `2C9BC1C0A58C59B0E49A5F3B324A08C46E71D22EEAAED4F935C76A5EF2837302`).
  The live loopback `/health`, config-status
  and OpenAPI endpoints returned HTTP 200. With no credentials configured, the
  new default canary returned `blocked=4`, `live_attempted=false`; no upstream
  request was sent.

## 2026-08-25 — Replaceable provider core and managed canary runner

- Added a provider-neutral `preflight/acquire/estimate_cost` lifecycle,
  capability registry and `FunnelProviders` boundary. The Amazon/eBay/1688
  business funnel now consumes provider objects; vendor selection is confined
  to CLI configuration and registry construction.
- Added a SerpApi eBay sold-search adapter with fixed `ebay.com`, US location,
  new-condition, `show_only=Sold` and `no_cache=true` parameters. It accepts only
  explicit positive sold counts bound to exact/new listings and preserves
  pagination/parser uncertainty as partial or review-required evidence.
- Added `proteus providers check`, which writes a redacted one-item report and
  distinguishes local configuration blockers, live acquisition status and
  contract validity. It never sends a request when the required key or HioBuy
  receiver is absent.
- The first managed canary produced `passed=0 / blocked=4`: Amazon SP-API,
  Nexscope, SerpApi and HioBuy production credentials were all absent; HioBuy
  also lacked a runtime receiver, and the official Amazon create/poll/download
  adapter remains open. This is an access block, not a negative market result.
- Installed and imported `python-amazon-sp-api 2.1.20` under Python 3.12 and
  passed `pip check`; exposed it as the optional `amazon` dependency group.
  This validates wheel compatibility only, not Seller authorization.
- Independent unauthenticated reachability probes returned SerpApi HTTP 401,
  HioBuy OpenAPI HTTP 200, Nexscope HTTP 200 with error envelope `code=11209`,
  and Amazon SP-API NA HTTP 403. Managed API hosts are reachable, so the earlier
  Japan/VPN concern is not the primary blocker for this path.
- Passed 241 offline tests, Python bytecode compilation, editable dependency
  resolution and wheel packaging. The wheel SHA-256 is
  `58DF16526901FC28626C04003C11C28CEF71ED5F56DB5F660F0A86DFDFEA3214`.
  The configurable
  profile test proves eBay can switch from Nexscope to SerpApi without changing
  funnel decisions; secrets remain absent from output.

## 2026-08-25 — Search/crawl wheel research added to the MVP path

- Confirmed the architectural distinction between discovery and decision:
  Agent/search APIs can return indexed URLs, snippets and sometimes extracted
  page content, but indexing does not prove that the current runtime can fetch
  the origin or that an absent result is a valid negative.
- The live `53630-53010` experiment supports that boundary: general search found
  exact third-party product pages while direct Amazon/eBay/1688 evidence paths
  remained unavailable. Search is useful as a candidate and URL discovery layer,
  not as a replacement for current platform and order-preview evidence.
- Selected an implementation shortlist instead of building more bespoke parsers:
  `python-amazon-sp-api` for Amazon Reports; Tavily first and Brave/Exa as search
  comparisons; SerpApi/DataForSEO for marketplace-managed benchmarks; eBay
  Browse API for active inventory/fitment; HioBuy for 1688 order preview; and
  Crawlee Python for queue/retry/resume orchestration.
- Rejected proxy/impersonation-dependent community eBay actors from the normal
  path because they conflict with the frozen no-proxy/no-stealth boundary. A
  third-party managed provider still needs written purpose compatibility and a
  provider benchmark before integration.
- Expanded `TODO.md` from provider access alone to the complete deliverable-MVP
  path: multi-identifier identity resolution, search discovery, unit economics,
  ranking, backend job service, persistence, secret handling, deployment,
  front end and real product acceptance.

## 2026-08-25 — V0.2 one-item live canary remains blocked

- Probed real Lexus/Toyota part `53630-53010`. Public catalog evidence confirms
  the identifier and product identity, but it does not satisfy any of the
  frozen Amazon/eBay/1688 opportunity gates.
- The current environment has no Amazon SP-API/B2B report input, Nexscope key,
  HioBuy key or runtime receiver configuration.
- The checked-in eBay browser provider reached the fixed US search context but
  returned explicit `HTTP_ERROR` with raw marker `HTTP 403`; it preserved zero
  eligible listings and did not convert the provider failure into zero demand.
- Independent public probes could not complete the remaining gates: the Amazon
  search request returned HTTP 503 and the 1688 search surface was unavailable.
  No challenge bypass, login automation, proxy or VPN manipulation was used.
- Result: no real opportunity report was produced. This canary remains
  `REVIEW_REQUIRED` until an approved provider supplies current, bound evidence.

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
