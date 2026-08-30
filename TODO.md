# Proteus Current Work

## 2026-08-30 V0.2.8 Shadow Root 结构探针（真实 Edge 复验待触发）

- [x] 为开放 Shadow Root 增加有界结构探针；只记录计数和宿主元数据，不把未确认内容当作商品。
- [x] 增加 API 严格校验和前端诊断摘要，保留原有 `PARSER_FAILED` / `EMPTY` 区分。
- [x] 增加顶层安全链接候选和身份属性名探针，避免把菜单链接与动态商品卡片混为一谈。
- [ ] 用户在普通 Edge `Reload` 扩展后重新点击采集，观察 `shadow_root_hints` 的宿主类型和内部候选数。
- [ ] 若 Shadow Root 不是商品层，再单独评估 iframe `all_frames` 方案；在证据前不扩大扩展权限或改用跨域抓取。

## 2026-08-30 V0.2.8 Edge 首页解析诊断（已实现，真实店铺复验待用户触发）

- [x] 扩大已渲染商品探测：支持店铺相对 `/offer/<id>.html`、offerId 查询参数、
  `data-href/data-url/data-offer-id` 等稳定身份字段，并统一生成规范 detail URL。
- [x] 扩大下一页探测：保留 profile 选择器，并补充 `下一页`、`next-page`、`›/»/→` 等
  已渲染控件的保守候选；只有明确可用/禁用状态才推进页号。
- [x] 页面无商品或分页不确定时提交有界 parser probe；服务端持久化页证据与诊断，前端
  在采集任务和最近快照中显示“未进入自动翻页”的具体原因。
- [x] 对诊断 URL、嵌入标记和探针数组做长度、域名、查询参数和数量限制，避免凭证或大段
  页面内容进入 SQLite。
- [x] 完成 Python 全量回归、Node/浏览器 DOM 合约、语法、编译、依赖检查和 PEP 517 wheel
  构建；仍待用户在普通 Edge Reload 扩展后用真实店铺产生一份新探针/成功快照。

## 2026-08-30 V0.2.7 Edge 旧标签页续采修复（已实现）

- [x] 将“店铺标签页早于扩展加载、没有内容脚本接收端”与普通扩展/API 错误分开处理；仅对
  `Receiving end does not exist` 类错误自动刷新当前店铺页，不增加扩展权限。
- [x] 允许同一店铺、同一短期令牌重新接管未过期 `CAPTURING` 任务，覆盖扩展重载导致
  `storage.session` 状态丢失的恢复路径，并保留此前页面证据。
- [x] 增加 popup 自动刷新和采集中任务重接管回归测试；真实店铺 offer/pagination 验收仍按
  下方 V0.2.6 条目由用户在普通 Edge 完成。

## 2026-08-30 V0.2.6 固定供应商反向选品（已实现）

- [x] 在导航栏增加独立“供应商反向选品”入口；不改变原有单叶子分类/eBay 正向扫描。
- [x] 保存单个 1688 供应商来源，归一化重复/带跟踪参数的 URL，并拒绝 HTTP、凭证、外站或
  两个不同来源混入同一输入。
- [x] 通过显式页数和商品数上限建立不可变店铺快照；完整、部分、明确空店、登录、滑块、
  超时、解析失败和采集器失败各自保留，不把失败或风控当成零商品。
- [x] 增加项目内 Manifest V3 Edge 扩展；它由用户在普通 Edge 工具栏显式触发，只读取当前
  已渲染页面并发送到本机 loopback，不申请 Cookie、debugger、proxy 或 webRequest 权限。
- [x] 增加短期令牌、店铺域名绑定、顺序/幂等页面提交、暂停恢复和版本化 selector profile；
  未证明为空的页面不消耗页号，未知分页会保留证据并暂停。
- [x] 使用独立 `supplier_scout.sqlite3` 保存供应商、只读检查审计与快照；提交时冻结所选
  ACTIVE 分类版本，所有已观察商品都保留分类、身份、市场预算和最终去向。
- [x] 对身份充分的商品复用精确 eBay 需求与 Amazon 产品家族 A/A-/PENDING/淘汰语义；
  明确零需求停止 Amazon，预算不足则后续商品为 `NOT_RUN_BUDGET`。
- [x] 提供独立 API、精简/完整 JSON、回放 harness 和响应式页面；真实示例店 headless
  canary 已正确返回 `RISK_CONTROL`，没有产生空店结论。
- [ ] 由用户首次在 `edge://extensions` 加载项目内扩展，并在该示例店正常显示后点击一次
  工具栏扩展，完成真实 ordinary-Edge offer/pagination 验收；登录或 CAPTCHA 必须继续由
  用户亲自处理，Agent 不静默安装扩展也不自动解验证。
- [ ] `1688-cli` 升级后重新核验 session/daemon 内部边界，再显式更新 bridge 版本门；在此
  之前非 0.1.47 版本保持 fail closed。
- [ ] 根据首个真实店铺快照补充中文车型/品牌与料号形态 fixture；身份不足继续人工复核，
  不用 LLM 猜测填充产品家族。

## 2026-08-29 V0.2.5 两级分类目录与 Amazon 竞争分级（已实现）

- [x] 用本机单用户 SQLite 目录替代运行时硬编码分类：一级分组为“拉线 / 塑料件 /
  低责任金属件”，单次运行仍只选择一个 ACTIVE 叶子小类。
- [x] 提供 Agent 可调用的 `proteus categories` 本地维护流程；定义先离线验证、创建不可变
  DRAFT，再显式启用或归档，维护动作不调用 provider。
- [x] 在运行提交时冻结分类版本快照，并在结果、扫描清单和精简导出中保存
  `category_version_id`，避免运行途中或历史结果受后续分类更新影响。
- [x] 按完整 Amazon 产品家族竞争证据分级：0–5 为 A、6–8 为 A-、9 以上淘汰；
  不完整证据在下界不足 9 时保持 `PENDING`，只有下界已达 9 才允许确定淘汰。
- [x] 前端改为数据库驱动的两级下拉框，显示 A/A-/待定/淘汰摘要、筛选和候选等级。
- [x] 保留当前九个叶子小类的行为；低责任金属件先为空分组，直到执行器具备并验证该类所需
  的尺寸、孔位或接口能力。

## 后续迭代：从产品方向和爆炸图生成零件目录（已落档，未实施）

- [ ] 支持用户多行输入“扫地机器人零件、割草机零件、雪地车零件、游艇零件”等产品方向；
  该输入用于发现品牌、型号、年份或序列号范围，不直接当作市场筛选叶子类型。
- [ ] 优先发现公开且获准使用的 OEM/品牌方爆炸图、IPL 和带标号的零件表；保存来源 URL、
  型号范围、总成、图中标号、OEM 零件号、提取方式、时间和覆盖状态。
- [ ] 只把“爆炸图标号能够与零件表对应”的结果作为可验证候选；仅凭图片视觉猜测的名称保持
  `REVIEW_REQUIRED`，资料缺失不能冒充完整目录。
- [ ] Agent 生成待确认零件列表，用户勾选后才进入当前分类目录或市场漏斗；确认结果沉淀到
  SQLite 复用，但不自动启用、不绕过登录/CAPTCHA，也不默认复制发布受版权保护的整张图。
- [ ] 第一版按来源可得性分批接入，先做具有官方 IPL/零件表的设备类型；资料覆盖不足的产品
  明确标注 `PARTIAL`，不为了统一体验伪造全量结果。

## 2026-08-28 配额优先分类扫描与 1688 供应商过滤（已批准，已实现）

- [x] 恢复 Northway 公开入口的单 `archetype` 选择；两个 profile 只作为前端分组，
  单次运行只消耗一个叶子类型的发现预算。
- [x] 将 Northway 漏斗改为 eBay 发现 → 本地范围/家族/需求 → 1688 轻量供应商预筛
  → Amazon；完整查询确认没有供应商时跳过 Amazon。
- [x] 接入本地 `1688-cli` 只读 provider：持久化登录态、轻量 search、必要时单个 offer
  详情；不做 deeppro、询价、购物车、结算或下单。
- [x] 将 `max_1688_checks` 与 SerpApi `request_budget` 分开统计，并在结果中记录
  provider、阶段、当前产品族、完成数、供应商通过数、预算和更新时间。
- [x] 让“有匹配 offer + 真实链接 + 非空供应商 + 产品族匹配”成为供应商阶段通过条件；
  无供应商、provider 失败和未查询必须分成 REJECTED / REVIEW_REQUIRED / NOT_RUN。
- [x] 前端恢复单分类选择，新增 1688 供应商阶段与“有供应商 / 待核验 / 无供应商”筛选，
  并显示可解释的分阶段进度。
- [x] 增加默认开启的 `enable_1688_prefilter` 开关；关闭时跳过 1688 调用并继续 Amazon，
  供应商阶段保留 `NOT_RUN` 和待复核语义。

本节已落地。本机已安装 `1688-cli` 0.1.47，默认 profile 已通过 QR 登录，并经
`whoami` / `doctor --no-launch` 只读检查；该安装阶段尚未执行真实商品搜索 canary，
后续首次真实运行已在本日志顶部记录。每次运行仍需显式控制 1688 检查预算，安装和登录
本身不会消耗 SerpApi 额度。
下面关于“移除单 archetype、九类统一扫描和供货仅人工复核”的条目只保留为已 supersede
的历史基线，不再代表本次默认产品行为。

## 2026-08-28 现场运行后续问题（未修复）

- [ ] 为 OEM/MPN 增加独立的形状校验；不要把连字符零件号拆出的片段写入车型，避免
  `Maxima 4RA0A`、`Atlas 3CN 823` 等污染 fitment 和 Amazon 描述查询。
- [ ] 收紧 Amazon 备用查询：HTTP 错误或超时只应保留为可重试的证据缺口，不应立即
  降级到宽泛品名搜索；只有精确查询明确返回 `ZERO_RESULTS` 或低精度信号时才评估
  备用查询，并记录查询过宽/结果总数信号而不把它直接当作竞品数量。
- [ ] 为手动打开的 Amazon 搜索链接补充可追溯的 run/query 来源，避免把浏览器页面总结果
  数误认为本次自动运行的竞争证据。

## V0.2.4 Northway product-family MVP — initial screening runnable

- [x] Replace “low exact-OEM result count” as the product objective with low
  competition across the complete sellable substitute-product family.
- [x] Use northwayautoparts as the product-shape reference rather than a fixed
  candidate source or an automatic pass label.
- [x] Freeze two first-batch profiles: `vehicle_specific_small_trim` and
  `vehicle_specific_cable`; explicitly exclude Universal-fit goods, chemicals,
  generic accessories, complex electronics, safety-critical systems, lamps,
  large body panels and heavy assemblies.
- [x] Freeze the reference-label roles: Northway listing/part examples are
  `NORTHWAY_GOLD`, `467903X100` is a Northway-like extension sample, and
  `00289-ACRKT` plus universal controls are negative samples.
- [x] Separate substitute product/ASIN count, seller offers per ASIN and the
  substitute-family price floor. OEM price cannot mask a cheap aftermarket
  substitute, and offer count cannot masquerade as product variety.
- [x] Freeze incomplete-evidence behavior: continue collecting independent
  evidence on `PARTIAL_SUCCESS` or missing fields; stop expensive downstream
  acquisition only after an explicit scope, identity or business-gate failure.
- [x] Freeze run bounds: remove `max_candidates` as an emitted-candidate cap but
  retain explicit scan pages/cursors, provider rate limits and run budgets.
- [x] Require complete JSON review export with every candidate, category
  profile, scan manifest, product family, query pack, rule readings, evidence,
  provider attempts, failure reasons and final rank.
- [x] Create versioned Northway gold/negative fixtures. Cover left/right
  (`25778388/25778389`, `25881881/25881882`), pair-versus-single
  (`25928247/25928248`), trim and cable archetypes, `467903X100`,
  `00289-ACRKT` and a Universal-fit control. The frozen cases live in
  `fixtures/northway_v0_2_4_product_family_cases.json`.
- [x] Add a provider-independent `sellable_product_family` schema with part
  type, fitment, engine/transmission qualifiers, position/side, critical specs,
  package quantity, identifiers, typed relations, confidence and evidence in
  `contracts/v0_2_4_product_family_resolution.schema.json`.
- [x] Implement deterministic scope classification before family-level market acquisition;
  years, vehicle names and generic title fragments must never become part
  numbers or candidates by themselves.
- [ ] Implement typed identity relations for `same_part`, `supersedes`,
  `replacement`, `compatible_part`, `left_right_counterpart` and
  `unknown_relation`; unresolved conflicts stay `REVIEW_REQUIRED`.
- [x] Generate and preserve a per-family Amazon query pack across exact IDs,
  verified replacements/cross-references and fitment-aware product names.
- [x] Aggregate Amazon results by ASIN and conservative interchangeable-product
  clusters; calculate `competitive_product_cluster_count`,
  `competitive_asin_count`, `offer_count_by_asin`, family offer
  lower bound and `family_price_floor_usd` with explicit completeness flags.
- [x] Bind the initial eBay demand lower bound to accepted source listings in
  each resolved family. Keep China non-OEM supply as a visible manual-review
  item for this one-credential initial-screening MVP.
- [x] Remove `max_candidates` from the V0.2.4 request/UI contract while leaving
  the V0.2.3 compatibility endpoint intact; process every unique candidate from
  the configured scan manifest until the explicit request budget is exhausted.
- [x] Remove the public single-archetype selector. One initial-screening run now
  covers all nine Northway archetypes and records per-archetype query/status
  metadata for later frontend work.
- [x] Rebuild the operator frontend around the merged all-archetype contract:
  expose the nine-type scope, per-archetype scan coverage and product-family
  evidence chain while keeping the existing async run, filters and JSON export.
- [ ] Rework Amazon family-query budget allocation so the default run does not
  exhaust its budget on early archetypes and leave later merged types entirely
  unsearched; reserve budget per resolved family or expose an explicit estimate.
- [ ] Decide how paginated Amazon fitment queries should reach a bounded
  complete state; current `has_next_page=true` correctly produces
  `REVIEW_REQUIRED`, but it prevents any family from passing when descriptive
  queries remain incomplete.
- [ ] Add an opt-in, timestamped local Amazon cache/replay mode so repeated
  investigations can avoid provider calls while keeping stale data explicitly
  marked as `REPLAY` rather than presenting it as a fresh scan.
- [x] Keep rejected candidates out of the default result view while preserving
  them under a dedicated status category and in the complete JSON export.
- [x] Add deterministic priority sorting with scope, identity and family
  competition as hard prerequisites, plus an original-order view.
- [x] Add full JSON export and validate it against
  `contracts/v0_2_4_northway_mvp_result.schema.json`.
- [x] Run deterministic replay/browser validation and one bounded live fog-light
  bezel probe. The live page examined 60 results, emitted 14 candidates and
  produced 3 market shortlists under a five-request probe budget.
- [ ] Finish relation extraction beyond the implemented `replacement` and
  `unknown_relation` baseline, especially `supersedes`, verified compatible
  parts and explicit left/right counterpart graph edges.
- [ ] Manually review the first live shortlist JSON for product identity,
  domestic aftermarket supply and margin; feed false merges/misses back into
  the versioned fixture before expanding beyond the two current profiles.

## V0.2.3 automatic MVP — implementation complete, live acceptance open

This section describes the current compatibility implementation. Its exact-OEM
and title-token readings do not satisfy the V0.2.4 Northway product-family
objective until the tasks above are complete.

- [x] Add a threshold-driven automatic path that discovers candidates and runs
  eBay recent sold, Amazon US exact competition/price/active-offer checks and
  eBay Product compatibility without Agent calls.
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
  estimated 23,375 model registrations. The adapter remains available for
  research but has been removed from the automatic-MVP decision path.
- [x] Separate discovery provider failures, explicit zero results and
  no-extracted-candidate outcomes in both the automatic-run summary and UI;
  failed requests no longer increment `pages_completed`.
- [x] Add frontend-editable Amazon minimum-price and active-offer saturation
  gates. Price defaults to `> $20`; the seller/offer ceiling defaults to `10`.
  Incomplete price/count evidence fails closed to `REVIEW_REQUIRED`, while a
  visible lower bound already over the ceiling is a decisive rejection.
- [x] Debug the successful `6028` / `auto parts` page that emitted no
  candidates. The page contained sold results but their titles lacked tokens
  accepted by the conservative part-number extractor; switch the editable
  default keyword to `OEM` and expose discovery funnel counts in the run/UI.
- [x] Change the editable eBay recent-sold default to `> 0` (at least one exact
  sold listing) and remove the NY vehicle-population gate and
  `min_us_active_vins` from the automatic MVP and frontend.
- [ ] Preserve the former broad 20-candidate benchmark as a compatibility test,
  but do not use it for product acceptance until V0.2.4 scope and family-
  identity precision pass on the Northway reference set.
- [ ] Re-run the SerpApi eBay canary after its search endpoint recovers or
  SerpApi support confirms the failure. The latest 2026-08-27 probe reached DNS,
  TCP 443 and the website, but `/search` consistently ended TLS with
  `UNEXPECTED_EOF_WHILE_READING`; the UI now reports this as provider failure,
  not zero demand.
- [ ] Replace the automatic recent-sold proxy with authorized 365-day evidence
  before treating its demand signal as strict. Acquire official VIO separately
  through the strict-screening profile before producing any
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
- [x] Keep the strict evaluator independent of HioBuy. The current V0.2.3
  automatic MVP no longer uses a vehicle-population gate; the anonymous NY
  DMV/NHTSA adapter remains research-only, while MarketCheck and HioBuy/receiver
  stay optional.
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
