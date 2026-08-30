# Proteus Development Log

## 2026-08-30 — V0.2.8 页面状态/资源计数探针（等待真实 Edge 复验）

- 最新真实 capture `cap_ae57bd060df54879af70f35a2522bc84` 仍是
  `PARSER_FAILED/PAGE_OFFERS_NOT_CONFIRMED`：第一页 35 个链接、0 个商品候选，
  `offerlist` 仅 1 个链接/1 张图片，`newofferlist` 仅 1 个链接，Shadow Root
  全部为菜单结构，两个 iframe 均无可读商品文档。现有证据已排除“只差再加一个普通
  offer 选择器”这一解释；`has_next_page=true` 不是停顿根因。
- 增加有界页面状态探针：`readyState`、正文/可见图片数量、Performance Resource
  总数及商品/接口关键词计数、顶层 `data-*` 属性名和 `onclick` 数量。只保存计数与
  属性名，不保存资源 URL、请求内容、页面原文、Cookie 或令牌。
- 本地全量回归通过；下一步需在普通 Edge Reload 扩展后重新点击同一店铺。若
  `readyState=complete` 且资源/图片也无商品迹象，应转向页面实际接口/壳渲染路径；
  若资源迹象明显但商品仍为 0，再单独延长等待窗口或跟踪渲染时序，暂不盲改选择器。

## 2026-08-30 — V0.2.8 Shadow Root 结构探针（等待真实 Edge 复验）

- 当前真实 capture `cap_a8257cd1a865431cb8c80eb5d9d0bd06` 已确认 API 页面提交链路正常：
  `collector_version=0.2.8`、`parser_version=1.1.0`，第一页有 35 个链接但 0 个商品候选，
  `has_next_page=true`，因此暂停为 `PAGE_OFFERS_NOT_CONFIRMED/PARSER_FAILED`，没有把页面误判成空店。
- 现有证据还显示页面含 1 个开放 Shadow Root 和 2 个 iframe；原探针只能计数，无法区分商品层与验证组件。
- 增加有界 `shadow_root_hints`：仅保存宿主标签/类名、子节点数、链接数、商品选择器命中数、
  候选数、嵌套 Shadow Root 数和文本长度，不保存根内文本、Cookie、令牌或跨域 frame 内容，也不改变商品采集语义。
- 同一探针补充顶层安全 1688 链接候选和身份属性名（不保存外站 URL 或属性值），用于判断商品是否是
  无标准 offer 链接的动态卡片。
- 进一步补充顶层疑似商品结构和 iframe 可读性摘要；跨域 iframe 只记录 `1688/foreign/blank`、
  尺寸及是否同源可读，不扩大权限或保存 frame 地址/内容。
- 相关 Edge/API 回归通过；下一步需要用户在普通 Edge Reload 扩展并再次点击采集，让真实页面产生该结构证据，
  再决定是递归 Shadow DOM 采集还是启用受限 `all_frames` 路径。

## 2026-08-30 — V0.2.8 Edge 首页解析诊断与保守续采

- 上一份真实证据显示任务停在 `PARSER_FAILED`、`pages_completed=0`，但没有保存第一页
  的结构线索；因此无法区分 DOM 选择器过时、iframe/Shadow DOM、嵌入数据或页面仍在验证。
  根因不是“没有下一页”：第一页未证明商品清单时，保守策略本来就不应翻页。
- 扩展解析器现在支持店铺相对 offer 链接、offerId 查询参数和常见 `data-*` 商品身份字段，
  统一去跟踪参数后生成 detail URL；下一页额外探测中文/英文标签和常见箭头控件，但仍只
  在已渲染控件明确可用时推进。
- 无商品或分页未知时提交有界 `parser_probe`，包含链接/匹配数、候选摘要、iframe/开放
  Shadow Root 和少量嵌入数据标记。服务端校验并保存 `page_evidence` 与诊断，重复失败不
  无限追加；前端在任务状态和最近快照中显示诊断，明确“尚未进入自动翻页”。探针只接受
  HTTPS 1688 域名及数字页码/offer ID 查询参数。
- 本地验证：全量 Python 回归通过；Python 编译、Node 合约与 JavaScript 语法、`pip check`、
  `git diff --check` 均通过；PEP 517 构建出 `proteus_opportunity_finder-0.2.8-py3-none-any.whl`
  （SHA-256 `e709abacadf0dcbdc13a0c3d0cd7ba0222758d2efd28cc71392890becbf44bd6`）。真实
  ordinary-Edge 复验仍需用户在 `edge://extensions` Reload 后点击工具栏扩展；本次服务重启
  后尚未收到新的 capture POST，因此不宣称自动翻页已在真实店铺验收。

## 2026-08-30 — V0.2.7 Edge collector reconnection

- User acceptance exposed `Could not establish connection. Receiving end does not exist.` after a
  capture had already been claimed. The first divergent step was the popup's direct
  `tabs.sendMessage`: a 1688 tab opened before an unpacked extension install/reload did not yet have
  the declarative content script that receives `collector:start`. The raw browser error was not a
  1688 verification failure and did not mean the store was empty.
- The popup now recognizes only the missing-content-script connection error, reloads that one active
  store tab, and relies on the collector's existing page-load auto-resume path. Chrome documents that
  tab reload itself needs no extra permission, so the manifest remains limited to `activeTab`,
  `storage`, the 1688 host and the loopback API; extension version is 0.2.7.
- Pending discovery and claim are idempotently recoverable from `CAPTURING` as well as `PENDING` or
  `PAUSED`. This lets an extension reload recover the same unexpired, host-bound, token-authorized
  session instead of leaving it stranded; completed and expired sessions remain non-claimable.
- Regression tests reproduced both the absent receiver and lost extension-session state before the
  fix, then verified automatic tab reload, no reload for unrelated errors and same-session
  reattachment. All 399 pytest tests passed; Python compilation, dependency checks, eight JavaScript
  syntax checks, six Node contract tests, 21 JSON parses and `git diff --check` also passed. The only
  warning remains Starlette's existing `TestClient` httpx deprecation notice.
- A restarted real loopback API reported 0.2.7 and completed
  `PENDING → CAPTURING → pending discovery of that same CAPTURING id → idempotent CAPTURING claim`
  against the saved example shop. The smoke task was then cleared by restarting the in-memory API;
  the service remains healthy on port 8765. A PEP 517 wheel built as
  `proteus_opportunity_finder-0.2.7-py3-none-any.whl` with SHA-256
  `63935605853E3947941ECEA53D74F212A69AF4BD84872540C5028D5149C8CA14`. Live ordinary-Edge
  confirmation still requires the user to reload the unpacked extension and click it on the real
  store tab; the Agent does not silently install an extension or bypass 1688 verification.

## 2026-08-30 — V0.2.6 bounded supplier-first store scout

- Added “供应商反向选品” as a separate navigation workspace. One run fixes one saved 1688
  supplier, captures an immutable bounded store snapshot, preserves every normalized observed
  offer, matches the current ACTIVE leaf catalog, then spends the separate market budget only
  on offers with a conservatively resolved product family.
- Added strict source semantics and contracts. Duplicate/tracked pasted URLs normalize to one
  HTTPS 1688 source; a distinct second source, credentials, HTTP, or foreign host is rejected.
  Page/offer bounds produce `PARTIAL`; login, risk control, timeout and parse failure remain
  distinct; `EMPTY` requires an explicit zero count, no next page and complete pagination.
- Replaced the supplier-first UI's hidden-browser path with a project-owned Manifest V3 Edge
  extension under `browser-extension/supplier-collector`. A user-created bounded task is bound
  to one saved shop host and a short-lived opaque token; the extension runs only after a toolbar
  click in ordinary Edge, scrolls and paginates deterministic rendered DOM, and posts normalized
  offers plus hashed page evidence only to the loopback API. It has no cookie, debugger, proxy,
  webRequest, remote-code, messaging, cart, checkout or CAPTCHA-solving capability.
- Added thread-safe capture lifecycle endpoints for pending discovery, claim, idempotent sequential
  page ingest, pause/resume and status, plus a packaged non-executable selector profile. Unknown
  pagination, unproven empty pages, authentication and risk control pause without consuming a page
  number or inventing an empty store; partial evidence is sealed into an immutable snapshot and can
  be resumed by another explicit extension click.
- Added `%LOCALAPPDATA%/Proteus/supplier_scout.sqlite3` for saved sources, inspection audits and
  immutable inventory snapshots. It is independent from the category catalog. Run submission freezes selected
  category versions; unmatched, ambiguous, supplier-mismatched, identity-incomplete and
  budget-not-run offers stay visible in full and compact exports.
- Reused exact eBay demand, sellable-family resolution, Amazon query packs and family
  aggregation. An explicit zero-demand result stops Amazon spending. Complete Amazon evidence
  grades 0–5 clusters A, 6–8 A-, and 9+ rejected; incomplete low counts remain `PENDING`.
  These grades remain separate from supplier quality, price and purchase eligibility; the
  independent price stage can reject or hold back the final shortlist without rewriting A/A-.
- The supplied example URL normalized to
  `https://shop3w093345o1043.1688.com/page/offerlist.htm`. A live headless read-only canary
  returned `RISK_CONTROL`, one attempted/zero completed pages, zero observed offers and
  `inventory_complete=false` with `MANUAL_CHALLENGE_REQUIRED`; the authenticated local profile
  remained logged in afterward. No empty-inventory claim was emitted.
- Browser replay verified two-way navigation, read-only `PARTIAL` inspection, four observed
  offers with A=1, A-=1, unmatched=1 and identity-incomplete=1, evidence expansion, filters,
  both JSON exports, a 390px no-overflow layout and zero console warnings/errors. Both export
  endpoints returned HTTP 200 with attachment filenames. A fresh in-app-browser acceptance against
  the restarted real local API verified the new ordinary-Edge collector card, saved-supplier state,
  unusable failed-snapshot gating, disabled run action and zero console warnings/errors. Offline
  Playwright DOM acceptance exercises real content-script extraction; Node tests cover URL,
  challenge and pagination semantics. All 397 tests passed; Python compilation, dependency checks,
  six JavaScript syntax checks, four Node contract tests and 14 JSON parses also passed. The
  isolated 0.2.6 wheel contains and imports the installed capture module plus selector profile
  (`SHA-256 26D3CE6A63A8131291085036E0A89940000F42EE7E6CAA7A8CAC6DF21D2ACD9D`).
  The only test warning is Starlette's `TestClient` httpx deprecation notice. Loading the unpacked
  extension and exercising a live 1688 store remains a one-time user-assisted acceptance because
  extension installation and CAPTCHA
  interaction cannot be performed silently by the Agent.

## 2026-08-29 — V0.2.5 two-level category catalog and Amazon competition grades

- Replaced the frontend/runtime hard-coded choice list with a local single-user SQLite catalog.
  The policy now exposes active “拉线 / 塑料件 / 低责任金属件” groups and leaf versions; the
  UI uses two native dropdowns and disables an empty group instead of inventing an executable
  category.
- Added the `CategoryDefinition` JSON contract, packaged seed data and `proteus categories`
  workflow. Validation is offline, draft versions are immutable and invisible, and activation
  or archive is always explicit. A run freezes the active category version at submission and
  records it in the result and compact evidence export.
- Added configurable product-family competition grading. Complete Amazon evidence assigns A to
  0–5 substitute clusters and A- to 6–8; 9 or more is rejected. Incomplete evidence remains
  `PENDING` below 9 and can reject only when the observed lower bound is already 9 or more.
- Passed catalog aliases and supply keywords into the existing scope, Amazon relation and local
  1688 query paths, so an Agent-added executable category changes real collection behavior rather
  than only adding a display option.
- Recorded the broader “product direction → public exploded diagram/IPL → user-confirmed parts
  list” concept in `TODO.md` as a later upstream iteration. It is not coupled to this release.
- Verification: all 350 tests passed; Python compilation, dependency checks, JavaScript syntax,
  14 JSON parses and whitespace validation passed. The Agent CLI validate → DRAFT → activate smoke
  made zero external requests. The 0.2.5 wheel contains both new contracts and packaged seed data
  (`SHA-256 CCFECFC5226A717F3894AB62DE5237950CB953FFAEDEEB75768E34C0A1533B07`), and an
  installed-wheel validation used the installed package rather than the checkout. Browser replay
  verified group/leaf switching, empty-group disablement, ordered thresholds, one A plus one A-
  result, the default A/A- filter and zero console errors.

## 2026-08-28 — Add temporary 1688 prefilter disable switch

- Added the default-on `enable_1688_prefilter` request/UI switch. When disabled, the runner
  does not call `1688-cli`, including its local authenticated-profile check, and eligible
  families continue to Amazon market review.
- Disabled runs mark the 1688 stage `NOT_RUN`, add `1688_PREFILTER_DISABLED`, expose
  `supply_filter.enabled=false`, and remain `REVIEW_REQUIRED`; they cannot become supplier-
  qualified or automatic opportunity candidates.
- The UI automatically changes the result view from “有 1688 供应商” to “可复核” so Amazon
  results are not hidden, and displays the disabled state in the run notice and budget summary.

## 2026-08-28 — First live single-category run after 1688 prefilter

- Run `e7f0e998-e836-49bd-a720-f75767151bf9` completed with 13 candidates from 60 eBay
  results (`eligible_sold_listings=23`, `listings_with_part_number=13`). The run used the
  restored single `hood_latch_release_cable` category.
- The quota-first order behaved as intended: 13 families were checked by local `1688-cli`,
  2 had a supplier, 1 had an explicit no-supplier result, and 10 remained `REVIEW_REQUIRED`.
  Only the supplier-passed families reached Amazon; SerpApi used 5/20 requests and the local
  1688 budget used 13/20 checks.
- Final run status was 0 market shortlists, 12 `REVIEW_REQUIRED` and 1 rejected. The Amazon
  evidence was incomplete, so this run does not establish low competition or a zero-result
  conclusion.
- The Nissan family exposed the current query-precision issue. Its resolved fitment was
  polluted as `Nissan Maxima 4RA0A`; the query pack was exact `65621-4RA0A` followed by
  `hood latch release cable Nissan Maxima 4RA0A`. The exact request returned `HTTP_ERROR` and
  the fallback timed out. This is provider-incomplete evidence, not proof of 232 competitors.
- The Amazon screenshot query `nissan maxima hood release cable` was not present in this run's
  persisted query attempts. It is therefore treated as manual or another-path evidence until
  its JSON provenance is available. The separate MPN-fragment parser and broad-fallback issues
  remain open in `TODO.md`; no fix is claimed by this entry.

## 2026-08-28 — Implemented quota-first single-category funnel and 1688 prefilter

- Restored the public Northway request and UI to one required leaf `archetype`; the nine
  types remain available as grouped choices, while the two broad profiles are display groups.
- Moved the 1688 supplier check ahead of Amazon. A family must expose a valid offer ID, real
  1688 URL, supplier identity and matching title before Amazon queries are attempted. Successful
  no-supplier results are `REJECTED`; login, risk-control, timeout and parser failures remain
  `REVIEW_REQUIRED`; ineligible families are `NOT_RUN`.
- Added the read-only local `1688` CLI adapter using shallow `search --max` and at most one
  `offer` detail read. It never invokes deeppro, inquiry, cart, checkout or order commands.
  HioBuy remains a compatibility fallback when explicitly configured.
- Split `request_budget` (SerpApi) from `max_1688_checks`, added provider budget summaries and
  asynchronous phase progress to the run envelope. The compact export now includes both budgets,
  supplier summary and only the bounded supplier evidence needed for review.
- Updated the Claude/TradeEye-style operator surface with a single-category radio selection,
  supplier-status filters, 1688 evidence cards and live phase/progress text. Local replay and
  compact JSON export were exercised through the browser harness with no console errors.
- Verification: 333 offline tests passed, Python compilation passed, JSON schema parsing passed,
  JavaScript syntax check passed, `git diff --check` passed. The local CLI has since been
  installed and the default profile authenticated with read-only `whoami`/`doctor` checks;
  no product-search canary has been run yet.

## 2026-08-28 — Activated local 1688 profile

- Installed `1688-cli` 0.1.47 with Node 24 and authenticated the default profile by QR scan.
- Confirmed the daemon and cached session are healthy. The adapter now recognizes Windows npm
  `.cmd` shims and reports the local provider as `READY` after a read-only `whoami` check.
- No 1688 product search or SerpApi run was triggered during setup; the first canary remains
  an explicit operator action.

## 2026-08-28 — Approved quota-first category scan and 1688 supplier prefilter

- Confirmed the current project has no reusable local candidate database, so a local-first
  filter cannot reduce first-time discovery calls. The public Northway run will therefore
  select one of the nine leaf archetypes per run; the two broad profiles remain UI groups.
- Approved the quota-first funnel: eBay discovery → local scope/family/demand filtering →
  shallow 1688 supplier prefilter → Amazon only for supplier-qualified families.
- Defined supplier qualification as a matching 1688 offer with a real offer ID and URL plus
  a non-empty supplier name. Supplier presence is not inventory, MOQ, margin or purchase proof.
- Separated SerpApi `request_budget` from `max_1688_checks`. Same-profile 1688 work stays
  serialized and shallow; no deeppro, inquiry, cart, checkout or order action is in scope.
- Approved frontend changes: single-category selection, explicit supplier-stage filters,
  separate provider budgets and phase/current progress rather than an indefinite “scanning” label.
- Documentation checkpoint is recorded before implementation; the existing all-archetype
  behavior remains the code baseline until the next implementation commit.

## 2026-08-28 — Remove competition cap and add compact evidence export

- Removed the public `max_competitive_products` request/UI field. Complete Amazon
  family evidence now marks the competition stage `PASSED` regardless of the observed
  cluster count; the count remains in the report and ranking as a manual-review signal.
  Incomplete pages still remain `REVIEW_REQUIRED`, and the price floor threshold is
  unchanged.
- Added `/api/v1/northway/runs/{run_id}/export/compact` and made it the operator UI's
  default download. It keeps family identity, decisions, stage readings, budget and
  pagination state, relevant ASINs, and bounded relation samples, while the existing
  `/export` endpoint continues to provide the complete audit JSON.
- Reprojecting the inspected 3,798,063-byte run reduced the compact serialization to
  492,291 bytes (87.0% smaller). Amazon product URLs are normalized to short `/dp/ASIN`
  links in the compact view; raw query product arrays and diagnostics are summarized.
- Confirmed the live-call boundary: fresh SerpApi Amazon data still consumes provider
  quota. The local `_dev_server.py` replay harness is the no-call option, but it uses
  stub data and is not a fresh market scan.

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
