# Proteus V0.1 — Minimum Opportunity Finder Contract

> 状态：`CORRECTED_AND_FROZEN_FOR_IMPLEMENTATION`
> 修订日期：2026-08-25
> 上位企划：[proteus.md](proteus.md)
> 数据源边界：[DATA_SOURCE_RECONNAISSANCE.md](DATA_SOURCE_RECONNAISSANCE.md)

## 1. 产品底线

V0.1 必须至少能够从一个小型 OEM / MPN 候选池中产出
`OPPORTUNITY_CANDIDATE`。只获取 eBay demand evidence 的能力是内部技术
里程碑，不是可以交付的第一版产品。

V0.1 保留原企划的三个必要商业判据：

```text
Amazon low-competition evidence
AND eBay observed-demand evidence
AND 1688 purchasable-supply evidence
→ OPPORTUNITY_CANDIDATE
```

`OPPORTUNITY_CANDIDATE` 表示“值得人工继续验证的商机候选”，不表示已经
证明利润、销量、供应商可靠性或最终可经营性。

## 2. 最小闭环

当前 provider 可行性不支持三平台全自动采集，所以首版收缩自动化方式，
不收缩商业结果：

```text
small candidate pool
→ deterministic part-number normalization
→ eBay US automated observed-demand check
→ Amazon competition evidence import / approved provider
→ 1688 supply evidence import / approved provider
→ deterministic three-gate evaluation
→ traceable opportunity-candidate JSON
```

执行顺序改为 eBay-first，是因为它是目前唯一通过低频技术验证的数据路径，
可先淘汰无 demand evidence 的候选，减少后续人工工作。最终判定仍要求三个
gate 全部通过；顺序变化不改变商机定义。

## 3. 固定范围

### 3.1 In scope

- CLI 接收一个小型 OEM / MPN JSON 候选池，并顺序处理。
- eBay 组件执行自动化、低频、第一页 evidence acquisition。
- Amazon 与 1688 在授权自动 provider 不可用时接受人工录入的结构化
  evidence；录入必须保留来源 URL、retrieved time、原始片段与录入方法。
- 使用透明三门规则输出 `OPPORTUNITY_CANDIDATE`、`REJECTED` 或
  `REVIEW_REQUIRED`。
- 输出 JSON 必须符合
  [contracts/v0_1_opportunity_report.schema.json](contracts/v0_1_opportunity_report.schema.json)。
- eBay acquisition 必须符合
  [contracts/v0_1_acquisition.schema.json](contracts/v0_1_acquisition.schema.json)。
- 所有平台失败必须显式表示；缺失、阻塞和歧义不能转成零结果或通过。

### 3.2 Out of scope

- Amazon 与 1688 的未授权自动抓取、登录自动化或 challenge bypass。
- 三个平台的生产级全自动 provider、10,000 OEM 压测与并发调度。
- Opportunity ranking、精确利润、物流、关税、退货率和车辆保有量。
- CSV、SQLite、Dashboard、SaaS、缓存集群和分布式任务。
- LLM 主路径、自动 cross-reference 认定和自动商业决策。
- 自动联系供应商、采购、刊登或执行交易。

## 4. Provider 与人工证据边界

### 4.1 eBay

首版使用已验证可行的低频 browser evidence path：

| Field | Required value |
|---|---|
| `marketplace_id` | `EBAY_US` |
| `site` | `www.ebay.com` |
| `locale` | `en-US` |
| `ship_to_country` | `US` |
| `ship_to_postal_code` | `10001`（非个人测试邮编） |
| `currency` | `USD` |

只访问搜索结果第一页，并发为 `1`。单次查询至多对 `TIMEOUT`、连接错误或
HTTP `5xx` 重试一次；HTTP `4xx`、challenge、login 和 market mismatch
不重试。

### 4.2 Amazon

在 Creators API 资格与用途确认完成前，系统不实现自动 Amazon provider。
首版接受用户通过合法访问路径取得的 manual evidence bundle，至少包含：

```text
query
marketplace_id = AMAZON_US
locale = en-US
ship_to_country = US
relevant_result_count
relevance_reviewed = true
source_url
retrieved_at
raw_evidence
```

系统只负责验证输入完整性并执行透明阈值，不把人工录入伪装成自动采集。

### 4.3 1688

在买家侧关键词 API / solution 获得明确授权前，系统不自动搜索、登录或处理
challenge。首版接受 manual supply evidence bundle，至少包含：

```text
matched_part_number
match_type
supplier
offer_url
purchasable
price_cny
moq
retrieved_at
raw_evidence
```

人工证据缺失或来源不完整时，该 stage 必须为 `REVIEW_REQUIRED`。

## 5. 三个商机 Gate

### 5.1 Amazon competition gate

固定初始规则沿用原企划：

```text
acquisition_status IN {SUCCESS, PARTIAL_SUCCESS}
AND US market context is exact
AND relevance_reviewed == true
AND relevant_result_count <= 5
→ PASSED
```

- 有效证据显示 `relevant_result_count > 5` → `REJECTED`。
- 访问失败、证据缺失或 relevance 未复核 → `REVIEW_REQUIRED`。
- Generic total-result count 不能冒充 manually reviewed relevant count。

### 5.2 eBay demand gate

只有同时满足以下条件的唯一 listing 才进入 observed-demand 汇总：

```text
market context exact
AND match_type IN {EXACT, NORMALIZED_EXACT}
AND condition == NEW
AND sold_count is an explicitly parsed integer > 0
```

至少存在一个 eligible listing 且 `aggregate_observed_sold >= 1` → `PASSED`。
明确成功页面但没有 eligible sold evidence → `REJECTED`；market mismatch、
parser failure、challenge、login 或歧义 → `REVIEW_REQUIRED`。

`aggregate_observed_sold` 只汇总唯一 listing ID。Listing lifetime sold count
只能称作 `Observed Demand`，不能称作市场销量。

### 5.3 1688 supply gate

每次运行必须提供 `max_acceptable_moq`；V0.1 不擅自设定全局商业阈值。

```text
acquisition_status IN {SUCCESS, PARTIAL_SUCCESS}
AND match_type IN {EXACT, NORMALIZED_EXACT}
AND matched_part_number is present
AND purchasable == true
AND moq <= max_acceptable_moq
AND supplier, offer_url and price_cny are present
→ PASSED
```

- 有效证据显示不可采购或 MOQ 超阈值 → `REJECTED`。
- cross-reference、replacement、left/right 或 unknown relation →
  `REVIEW_REQUIRED`，不能自动形成 supply pass。
- price 必须作为 evidence 保存，但 V0.1 不做精确 margin 判断。

## 6. 最终决策

```text
all three stages PASSED
→ OPPORTUNITY_CANDIDATE

any stage REJECTED
→ REJECTED

otherwise
→ REVIEW_REQUIRED
```

`REVIEW_REQUIRED` 包括 provider unavailable、manual evidence 未录入、字段
缺失、解析失败或 relation ambiguity。它既不是通过，也不是否定商机。

## 7. Evidence 与失败模型

字段级 `Evidence` 必须包含 metric、value、source、URL、retrieved time、
extraction method、最小 raw evidence 与 `0.0–1.0` confidence。

Acquisition status 固定为：

```text
SUCCESS
PARTIAL_SUCCESS
ZERO_RESULTS
HTTP_ERROR
TIMEOUT
CHALLENGE
AUTH_REQUIRED
BLOCKED_BY_CREDENTIALS
PROVIDER_UNAVAILABLE
MARKET_CONTEXT_MISMATCH
PARSER_FAILED
```

任何 failure status 都不能转换为 `ZERO_RESULTS`。人工证据使用
`source_method = MANUAL` 和 `extraction_method = MANUAL_REVIEW`，使来源在
最终 report 中可见。

## 8. Fixtures 与验收

- [fixtures/ebay_v0_1_cases.json](fixtures/ebay_v0_1_cases.json) 验证 eBay
  acquisition、normalization、matching、sold parsing 和 failure classification。
- [fixtures/opportunity_v0_1_cases.json](fixtures/opportunity_v0_1_cases.json)
  验证三门全过、各门拒绝、证据缺失和歧义路径。

V0.1 的验收分为两层：

1. **Engineering pass**：所有离线 fixtures 通过，每个输出符合 JSON Schema，
   且失败不会被误判为零结果或通过。
2. **Product pass**：对一个带当前、可追溯三平台证据的真实小型候选池运行后，
   至少输出一个 `OPPORTUNITY_CANDIDATE`。如果只证明程序能运行却没有真实
   商机候选，V0.1 不算产品验收通过。

候选仍需人工验证利润、物流、合规与供应商质量；“商机候选”不是盈利保证。

## 9. 相对原企划的正确收缩方式

| Dimension | Original Proteus V0 | V0.1 | Contraction |
|---|---|---|---:|
| Core product outcome | Three-gate opportunity candidate | Three-gate opportunity candidate | `0%` |
| Business hypotheses | H1 + H2 + H3 | H1 + H2 + H3 | `0%` |
| Automated platform acquisition | 3 platforms intended | eBay automated; Amazon/1688 manual-assisted | `66.7%` automation |
| Operating scale | Candidate pool / 10,000-item design target | Small sequential candidate pool | 不适合百分比 |
| Delivery surfaces | CLI + JSON + CSV + SQLite | CLI + JSON | `50%` |
| Ranking / economics | Explainable score and future margin proxy | Boolean three-gate candidate decision | 大幅延后 |

因此，**首版不再收缩核心商业边界**。被收缩的是自动化比例、运行规模、输出
形式和评分深度。eBay-only evidence slice 保留为实现阶段，而不是产品终点。
