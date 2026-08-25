# Proteus V0.2 — Automatic Opportunity Discovery Execution Plan

> 状态：`ENGINEERING_PREVIEW_IMPLEMENTED / PRODUCT_ACCEPTANCE_OPEN`
> 日期：2026-08-25
> 上位企划：[proteus.md](proteus.md)
> V0.1 基线：[V0_1_SCOPE_CONTRACT.md](V0_1_SCOPE_CONTRACT.md)

## 0. 本次迭代落点

本仓库现已实现 V0.2 engineering preview：Amazon B2B CSV 候选发现、V0.2
contracts、Amazon → eBay → 1688 短路、Nexscope managed REST adapters、HioBuy
1688 `search → detail → order preview` 只读 adapter、V0.1 输入兼容和
`automation_qualified` 隔离。随后补齐了 provider-neutral protocol、显式 registry、
SerpApi eBay sold adapter、逐阶段 provider profile 和 `providers check` canary。

这不是产品验收完成。当前尚缺获准生产凭证、Amazon SP-API 报告自动拉取、provider
readiness/freshness/cost 的真实 20-item benchmark，以及至少一条当前真实
`automation_qualified=true` 商机。已下载 CSV 属于 report replay；它能自动生成
候选但仍有人工下载步骤。Nexscope listing 也不能替代 1688 order preview。

因此，本轮把“可复用的非 Agent 自动执行骨架”做成可运行版本，同时保留原企划的
商机目标；没有把产品目标收缩为人工需求抓取，也不把工程通过冒充真实商机。

## 1. 版本目标

V0.2 的目标不是把人工输入的 OEM 逐个查完，也不是继续扩大“需求抓取器”。
它必须从一个真实、当前的需求源中自动产生候选，并沿三平台漏斗自动收缩为商机：

```text
Amazon B2B demand-gap candidate source
→ Amazon competition verification
→ eBay observed-demand verification
→ 1688 exact supply + order-preview verification
→ OPPORTUNITY_CANDIDATE
```

正常路径不要求人工预先提供 OEM 候选池，不调用 Agent、LLM 或人工判读。人工只
负责配置授权、准备 benchmark gold labels，以及最终商业复核。只有当前、可追溯
且三个 gate 全部通过的结果才能称为 `OPPORTUNITY_CANDIDATE`。

V0.2 产品验收底线：从最新 Amazon B2B 候选源自动运行一个 20-candidate 小池，
至少得到一条无需 manual evidence、无需 Agent、带 1688 order preview 的真实
`OPPORTUNITY_CANDIDATE`。程序能运行或 provider benchmark 通过，都不能替代这
条产品验收。

## 2. 冻结原则

1. 正常执行顺序固定为 `Amazon → eBay → 1688`，未通过上游 gate 的候选不访问
   下游平台。
2. Provider 先过授权、用途、凭证、字段、市场、freshness 和成本 gate，再比较
   技术便利性。官方 API 优先，但“官方”不能覆盖缺字段或用途不兼容。
3. Nexscope 是可替换的 managed adapter，不是业务模型的一部分，也不享有默认
   信任。其来源、覆盖、freshness、成本和字段语义都必须由 live probe 证明。
4. 任何 provider failure、凭证缺失或字段歧义都进入 `REVIEW_REQUIRED`；不得转换
   为零结果、拒绝或通过。陈旧数据可保留回放时的 gate 结论，但必须
   `automation_qualified=false`，不得计入当前产品验收。
5. 不实现登录自动化、CAPTCHA/challenge bypass、stealth、指纹规避、代理池或
   自动切换 VPN 地区。官方路径不可用时，只能使用明确获准的 adapter，否则
   `PROVIDER_UNAVAILABLE`。
6. V0.1 的离线 eBay evidence、manual Amazon/1688 evidence 和现有 CLI 保持可用，
   但任何 `MANUAL` 证据都不能计入 V0.2 自动产品验收。

## 3. 候选源：Amazon B2B Not Yet on Amazon

### 3.1 正常来源

第一优先候选源是 Amazon Seller Central 的 B2B Selection Recommendations 中
`List products not yet on Amazon` 可下载报告。Amazon 官方说明该列表来自企业
买家的搜索、请求等需求信号，按周更新，并可包含 title、brand、category、MPN、
UPC 和 model number。访问该工具需要具备相应 Seller Central / Professional
selling plan 权限：

- [Amazon B2B Selection Recommendations](https://sell.amazon.com/blog/amazon-business-products)

V0.2 正常路径通过获准的官方 report/API adapter 获取最新报告。人工下载文件只
作为开发、回放和 V0.1 兼容输入，不计为自动发现。

### 3.2 候选生成规则

`AmazonB2BNotYetCandidateProvider` 输出 `CandidateSeed`：

```json
{
  "source": "AMAZON_B2B_NOT_YET_ON_AMAZON",
  "marketplace": "US",
  "report_id": "...",
  "report_generated_at": "...",
  "raw_title": "...",
  "brand": "...",
  "category": "...",
  "manufacturer_part_number": "...",
  "model_number": "...",
  "upc": "...",
  "b2b_opportunity": "...",
  "raw_evidence": "..."
}
```

候选必须满足：

- 最新报告，`report_generated_at` 距运行时间不超过 8 天；
- 美国 marketplace；
- 属于配置的 automotive category allowlist；
- MPN、model number 或 UPC 至少一个可用；
- 原始行、report ID、生成时间和解析版本可追溯；
- 对标识符做确定性 normalization 和去重，同时保留原值；
- 同一 UPC/标准化 MPN 的重复行合并，不自动认定 cross-reference。

报告中的 “not yet on Amazon” 是候选信号，不是最终竞争结论。Amazon 也提示可能
因标题不同而存在对应 ASIN，因此每个候选仍必须经过独立 Amazon gate。

## 4. 三阶段自动漏斗

### 4.1 Amazon competition gate

输入为 `CandidateSeed`，查询优先级为 `UPC → exact MPN → exact model number`；
每个实际 query 独立记录，结果不能混算。

Provider 顺序：

```text
approved official Amazon API
→ explicitly enabled Nexscope managed adapter
→ PROVIDER_UNAVAILABLE
```

可评估结果必须包含 US marketplace、实际 query、候选标识符匹配、结果列表、
`relevant_result_count`、source URL/record ID、retrieved time 和 raw evidence。
继续沿用透明阈值：

```text
relevant_result_count <= 5 → PASSED
relevant_result_count > 5  → REJECTED
missing / stale / ambiguous → REVIEW_REQUIRED
```

Nexscope adapter 只映射为统一 `AmazonCompetitionProvider`。当前公开文档证明其
Bearer API 和 Amazon search/product endpoints 存在，但没有普遍保证数据源、
freshness、覆盖率或估算方法；这些缺口必须由 provider gate 和 benchmark 解决，
不能靠名称推断：

- [Nexscope API documentation](https://www.nexscope.ai/api-docs)
- [Nexscope Amazon Market Product Search](https://www.nexscope.ai/api-docs/amazon-market-product-search)

### 4.2 eBay observed-demand gate

只接收 Amazon `PASSED` 的候选。Provider 顺序：

```text
approved official eBay API combination with required sold evidence
→ approved managed adapter with equivalent fields
→ explicitly selected V0.1 low-volume browser compatibility adapter
→ PROVIDER_UNAVAILABLE
```

官方 API 若无法提供 listing-level sold evidence，就不能仅因“官方优先”而通过
`REQUIRED_FIELDS_AVAILABLE`。V0.1 的精确/标准化精确、新品、显式正整数 sold
规则保持不变；唯一 listing ID 去重，market context 必须是 `EBAY_US / en-US /
US 10001 / USD`。

```text
eligible listing exists AND aggregate_observed_sold >= 1 → PASSED
valid zero/no eligible sold evidence                       → REJECTED
blocked / stale / mismatch / ambiguous                    → REVIEW_REQUIRED
```

V0.1 Playwright adapter不是 V0.2 默认正常路径；只有访问方式仍获准、20-item
benchmark 合格并在配置中显式启用时，才可作为兼容 adapter。它不允许增加任何
challenge 或地区对抗逻辑。

### 4.3 1688 purchasable-supply gate

只接收 eBay `PASSED` 的候选。正常 provider 必须是获准的 1688 Open Platform /
solution adapter，并分三步产生证据：

```text
exact identifier discovery
→ offer/SKU detail
→ order preview for selected SKU and acceptable quantity
```

搜索结果页、offer 存在、展示价格、库存文字或 MOQ 本身都不能证明
`purchasable=true`。只有当前运行中针对同一 offer、SKU、数量和配置的业务收货
地区成功完成 order preview，才可形成 purchasable pass。

Gate 必须绑定：

- exact/normalized-exact part number；
- supplier、offer ID/URL、SKU/variant；
- preview quantity，且 `quantity <= max_acceptable_moq`；
- preview 返回的商品价、运费和币种；
- preview ID、retrieved time、provider/request ID；
- order preview 与 offer/SKU/quantity 的一致性。

有效 preview 明确表示不可交易、缺货或 MOQ 超阈值时为 `REJECTED`；授权失败、
凭证失败、preview 不可用或关系歧义时为 `REVIEW_REQUIRED`。V0.2 只调用 preview，
绝不提交 create-order、支付、联系供应商或其他交易动作。

若尚未确认包含 buyer-side discovery、offer detail 和 order preview 权限的具体
1688 solution，整个自动 supply provider 保持 `BLOCKED_BY_ACCESS`，不得用登录
浏览器补洞。官方入口：[1688 Open Platform](https://open.1688.com/)。

## 5. Provider contract 与进入条件

所有 official 和 managed adapter 实现同一协议：

```text
preflight() -> ProviderReadiness
acquire(request) -> AcquisitionOutcome
estimate_cost(request) -> CostEstimate
```

`ProviderReadiness` 必须全部满足才能被正常 pipeline 选择：

```text
ACCESS_AUTHORIZED
AND PURPOSE_COMPATIBLE
AND CREDENTIALS_AVAILABLE
AND CREDENTIALS_VALID
AND REQUIRED_FIELDS_AVAILABLE
AND MARKET_CONTEXT_FIXED
AND FRESHNESS_KNOWN
AND FAILURE_CLASSIFICATION_TESTED
AND CACHE_RETENTION_ALLOWED
AND COST_KNOWN
```

初始 freshness 上限：

| Evidence | Maximum age at decision time |
|---|---:|
| Amazon B2B candidate report | 8 days |
| Amazon competition evidence | 24 hours |
| eBay demand evidence | 24 hours |
| 1688 offer/SKU detail | 24 hours |
| 1688 order preview | 15 minutes, same run only |

阈值进入 run policy 并可配置，但每次输出必须保存实际阈值和 evidence age。超过
阈值必须重新获取才能计入自动产品验收；若只做历史回放，可保留原 gate 结论，但
必须 `automation_qualified=false`，不能把陈旧缓存声明为当前商机。

凭证只从环境变量、OS secret store 或明确配置的本地 secret backend 读取；不得
放在 CLI 参数、JSON 配置、日志、raw evidence 或 Git 中。日志只保存 provider、
credential alias 和不可逆短 fingerprint，不保存 token/cookie/address。1688
preview 所需地址在请求边界内使用，报告只保留非个人地区和脱敏 fingerprint。

Provider 选择必须由配置 allowlist 决定，不做运行时未经确认的自动降级：

```text
selected provider not ready
→ next provider explicitly allowed and ready?
    yes → record fallback reason and use it
    no  → PROVIDER_UNAVAILABLE / REVIEW_REQUIRED
```

## 6. 构架

本次已落地的最小运行面：

```text
src/proteus/
├── discovery.py               # Amazon B2B CSV replay candidate source
├── providers/
│   ├── base.py                # protocol, readiness and cost contract
│   ├── registry.py            # explicit allowlisted selection
│   ├── adapters.py            # thin vendor objects + FunnelProviders
│   ├── canary.py              # redacted one-item provider checks
│   ├── nexscope.py            # Amazon/eBay/1688 managed search
│   ├── serpapi_ebay.py        # eBay US sold-search adapter
│   └── hiobuy.py              # 1688 detail + read-only order preview
├── evaluation.py              # Amazon → eBay → 1688 gates
├── io.py                      # V0.1 input compatibility + V0.2 validation
└── cli.py                     # direct pool/report replay execution
```

为满足接口可替换要求，轻量 protocol/registry 已提前落地。Provider live benchmark
通过后，只增量增加下列尚缺 adapter 与 benchmark，不进行仓库重写：

```text
src/proteus/
├── providers/
│   ├── amazon_b2b_report.py    # official candidate source + offline replay
│   ├── amazon_official.py
│   ├── ebay_official.py
│   ├── alibaba1688_official.py
│   └── ...                     # current managed adapters stay replaceable
├── candidate_source.py         # normalize, dedupe, automotive filter
├── pipeline_v0_2.py            # Amazon → eBay → 1688 short circuit
├── benchmark.py                # metrics and acceptance report
└── cli.py                      # retain V0.1 invocation; add subcommands
```

新增的 V0.2 JSON contracts 至少覆盖：

- `CandidateSeed` and source-report provenance；
- `ProviderReadiness` and selected/fallback adapter；
- per-call cost、latency、freshness 和 diagnostics；
- 1688 order-preview binding；
- `OpportunityReport 0.2` 的 `automation_qualified` 字段。

正常业务判断只读取规范化 contract，不直接读取 Nexscope、Amazon、eBay 或 1688
原始 payload。每个 adapter 保存最小必要 raw evidence，并将 provider/version、
source method、request ID 和 retrieved time 写入输出。

V0.2 只需轻量本地 run artifacts 和 TTL cache；本轮不引入数据库、队列、并发
worker 或服务化。正常漏斗顺序执行，单 provider 并发默认为 1。

## 7. CLI 设计

本次保持单一参数式 CLI，既有 V0.1 输入仍可用；V0.2 新增 report replay 和 managed
REST 入口。密钥只从指定环境变量读取：

```powershell
# 当前已实现的 V0.2 engineering-preview 路径
$env:NEXSCOPE_API_KEY = "..."
$env:HIOBUY_API_KEY = "..."
proteus `
  --amazon-b2b-report .\b2b_not_yet_on_amazon.csv `
  --nexscope `
  --hiobuy-receiver .\private\receiver.json `
  --max-candidates 20 `
  --max-moq 10 `
  --output .\reports_v0_2.json
```

如果不配置 HioBuy receiver，Nexscope 1688 只形成 listing 线索，供应 gate 必须
`REVIEW_REQUIRED`。receiver 只进入 preview 请求，不写入报告；代码不暴露任何
create/pay endpoint。

`providers check` 已实现；它区分本地阻断、live acquisition 状态和 contract validity，
但一次 canary 通过不等于 provider/product acceptance。SP-API 自动报告拉取和独立
`benchmark` 命令仍未实现。离线/manual 与 report replay 输出均为
`automation_qualified=false`，不能混入自动产品验收统计。

显式逐阶段选择示例：

```powershell
proteus --amazon-b2b-report .\b2b.csv --managed-providers `
  --amazon-provider nexscope-amazon `
  --ebay-provider serpapi-ebay `
  --supply-provider hiobuy-1688 `
  --hiobuy-receiver .\private\receiver.json `
  --max-moq 10 --output .\reports.json
```

## 8. 20-candidate provider benchmark

### 8.1 样本

从同一份最新 US Amazon B2B report 中按固定 seed 抽取 20 个去重后的 automotive
候选。样本必须覆盖 exact MPN、normalized MPN、UPC/model fallback、明确无结果、
replacement/cross-reference、left/right 和歧义情况。gold labels 由人工一次性复核
并版本化；benchmark 执行本身不调用 Agent。

正常 pipeline 仍严格漏斗短路。只有 `benchmark` 模式为了分别测量 provider，
才允许对 20 项运行各 provider probe；这些调用必须受预算和授权控制，不能写入
正常产品报告。

### 8.2 指标定义与通过线

| Metric | Definition | V0.2 gate |
|---|---|---:|
| Explicit outcome rate | every attempted call has a schema-valid terminal status | `100%` |
| Usable acquisition rate | decisive success/valid negative, excluding provider failure/review | `>= 90%` per provider (`>=18/20`) |
| Critical-field completeness | all fields/evidence required by a PASSED or REJECTED stage | `100%` |
| Overall required-field completeness | present required fields / applicable required fields | `>= 95%` per provider |
| Exact-match precision | gold-true exact matches / all accepted exact matches | `>= 95%` |
| Critical relation false positives | side mismatch, replacement or cross-reference accepted as exact | `0` |
| Provider-caused review rate | access/parser/stale/field failures / attempts | `<= 20%` per provider (`<=4/20`) |
| End-to-end review rate | `REVIEW_REQUIRED` / 20 in normal funnel run | `<= 25%` (`<=5/20`) |
| Freshness compliance | decisions within configured evidence age | `100%` |
| Marginal external cost | metered provider spend for the 20-item benchmark | `<= US$10 total` and `<= US$0.50/input candidate` |

固定订阅费、Seller plan 和 trial credits 不能藏在零成本声明中：benchmark 同时记录
`marginal_cost_usd`、provider credits、当前 plan 和折算依据。若 provider 无法给出
可审计的价格或 credit-to-currency 映射，则 `COST_KNOWN` 不通过。

1688 的 `PASSED` 样本必须全部拥有同一运行内成功的 order preview；没有 preview
的 offer 即使其他字段完整，也只能 `REVIEW_REQUIRED`。Benchmark 必须确认没有
任何 create-order 请求。

### 8.3 两层验收

1. **Provider engineering pass**：上述全部指标达线，fixture/replay 和 live
   benchmark 都通过，且没有 failure 被转成零结果或通过。
2. **Product pass**：正常自动发现路径从最新 report 自动产生 20 个候选，并
   至少输出一个当前、三门全过、`automation_qualified=true` 的真实
   `OPPORTUNITY_CANDIDATE`。

若 engineering pass 成立但没有真实 opportunity，V0.2 只能报告“provider 可用，
产品假设尚未通过”，不能回退为人工需求抓取并宣称完成。

## 9. 实现阶段

### Phase 0 — Access proof before adapters

- 确认 Amazon B2B report 的账号、marketplace、report/API 权限与用途；取得一份
  脱敏 20-row schema sample。
- 对计划使用的 Amazon/eBay 官方 API 完成 role、quota 和 required-field probe。
- 对 Nexscope 完成 key、endpoint、字段、source/freshness、费率和条款 probe。
- 确认具体 1688 solution 同时授权 buyer-side discovery、offer detail 和 order
  preview；只验证 preview，不创建订单。
- 输出 provider readiness JSON。任一关键 gate 未过，就停止对应 adapter 的业务
  实现，不用未授权 browser 补齐。

### Phase 1 — Contracts and provider core

- 新增 V0.2 schemas、provider protocol、readiness/freshness/cost policy 和 registry。
- 为所有失败状态、secret redaction、TTL 和显式 fallback 编写离线 contract tests。
- 保留 V0.1 schemas、API 和 CLI 回归测试。

### Phase 2 — Candidate discovery and Amazon gate

- 实现 official report acquisition、offline replay parser、automotive filter、
  normalization 和 dedupe。
- 实现官方 Amazon competition adapter；再实现 Nexscope adapter，使用同一 contract
  test suite。
- 验证 report row、query、结果和 candidate identity 的完整链路。

### Phase 3 — eBay demand

- 实现获准的 official/managed adapter 及 listing-level sold capability probe。
- 复用 V0.1 matching、dedupe、market/failure 语义。
- V0.1 browser 只保留为显式 compatibility adapter。

### Phase 4 — 1688 supply

- 实现 discovery、offer/SKU detail、order preview 三步 adapter。
- 覆盖不可交易、缺货、MOQ、SKU 错配、地址/运费错误、auth 和 rate-limit cases。
- 通过测试保证代码中不存在 create-order 调用路径。

### Phase 5 — Benchmark and product run

- 冻结同一份 20-item manifest 和 gold labels。
- 先运行 replay，再运行 live provider benchmark；输出逐项和汇总指标。
- 指标达线后运行正常漏斗，检查至少一条真实自动商机候选。
- 只有两层验收都通过，才把 V0.2 标记为产品可用。

## 10. 验证清单

- JSON Schema：所有输入、provider outcome、run manifest 和 final report 均验证。
- Unit：normalization、identity、freshness、cost、provider selection、short circuit。
- Contract：official 与 Nexscope adapter 运行同一组输入输出测试。
- Replay：固定脱敏 payload 覆盖 success、zero、auth、stale、rate limit、schema drift。
- Safety：secret/address redaction；challenge 不重试；无 login、bypass、order create。
- Integration：V0.1 完整回归；V0.2 synthetic 三门闭环；异常不写 partial output。
- Live canary：每个 provider 先 1 item，再 5 items，最后 20-item benchmark。
- Product：最新 report、正常漏斗、至少一个自动三门商机候选。

## 11. V0.2 产品目标范围

以下是 V0.2 产品验收的完整边界，不代表当前 engineering preview 已全部实现；
official retrieval/adapters、readiness/cost gate 和 benchmark 仍是开放项。

In scope：

- Amazon B2B report 自动候选源；
- provider readiness/freshness/cost gate；
- Amazon、eBay、1688 official API adapters；
- 可替换 Nexscope managed adapter；
- 1688 order-preview purchasability；
- Amazon → eBay → 1688 自动漏斗；
- V0.2 CLI、JSON contracts、replay、20-item benchmark；
- V0.1 offline/manual 兼容。

Out of scope：

- Agent/LLM 正常路径、语义自动裁决；
- CAPTCHA、challenge、登录、stealth、指纹或代理池绕过；
- 10,000-item 规模、并发调度、服务化、Dashboard、SQLite/云数据库；
- 复杂 ranking、精确利润、物流、关税、退货率和供应商质量评分；
- 自动 cross-reference 合并、供应商联系、创建订单、采购、刊登或交易；
- Amazon B2B 报告之外的新候选源。

## 12. 回滚与停止条件

- V0.2 通过 `--amazon-b2b-report` 与 `--nexscope` 显式 opt-in；V0.1 的
  `--candidate-pool`、`--manual-evidence`、`--ebay-evidence` 参数组合继续可用。
- 新 schemas 使用 `0.2`，不覆盖 `0.1`；不做破坏性数据迁移。
- 每个 provider 可由 registry/config 单独禁用。条款、字段、价格或 freshness 变化
  时将 readiness 置为失败，不自动切换到未授权路径。
- Live canary 任一阶段发生 secret 泄露、意外写操作、非 preview 交易请求、
  challenge 对抗、无法分类异常或 evidence 假通过，立即停止该 provider。
- 若 benchmark 未达线，保留 replay artifacts 和失败状态，回退到 V0.1 兼容模式；
  不把 manual evidence 包装成 V0.2 自动结果。
- 回滚只移除/禁用 V0.2 adapter 和参数入口，不删除 V0.1 evidence、reports 或用户
  输入；外部系统没有订单或交易需要撤销。

## 13. 下一实施动作

engineering preview 已有两个 managed adapters；下一步不要继续增加 provider client。
先完成 Phase 0 的四份 live provider readiness 结果，尤其是：

1. 取得最新 US `Not Yet on Amazon` 报告/API 的真实字段样本；
2. 证明至少一个 Amazon competition provider 能绑定 query 与 current results；
3. 证明 eBay provider 能合法返回 listing-level sold evidence；
4. 证明获准的 1688 solution 能对 exact offer/SKU 执行 order preview。

自动漏斗的 engineering preview 已实现；只有这四项同时存在并通过 live canary
与 20-item benchmark，才进入产品验收。否则明确报告被哪一个 provider gate
阻塞，而不是把目标收缩成人工需求抓取或把工程样例当成商机。
