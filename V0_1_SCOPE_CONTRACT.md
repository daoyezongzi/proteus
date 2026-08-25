# Proteus V0.1 — eBay Evidence Slice Contract

> 状态：`FROZEN_FOR_IMPLEMENTATION`
> 冻结日期：2026-08-25
> 上位企划：[proteus.md](proteus.md)
> 可行性依据：[DATA_SOURCE_RECONNAISSANCE.md](DATA_SOURCE_RECONNAISSANCE.md)

## 1. 版本定义

V0.1 是原 Proteus V0 的第一个可执行技术切片，不是完整的跨平台选品系统。

固定主路径：

```text
single raw OEM / MPN
→ deterministic normalization
→ eBay US first-result-page acquisition
→ listing match and sold-evidence classification
→ traceable JSON
```

这个版本只回答：

> 在固定的美国站市场上下文中，能否为一个零件号稳定地产出可追溯的
> eBay listing-level observed-demand evidence？

它不回答该零件是否值得采购、是否低竞争、是否存在中国供应，也不输出
“值得做 / 不值得做”的商业结论。

## 2. 固定范围

### 2.1 In scope

- 每次运行输入一个原始 OEM / MPN；fixtures 可以顺序运行，但不是批处理系统。
- 最小 CLI 接收该编号，并只输出符合契约的 JSON；不提供交互界面。
- 保留原始编号，并生成仅含大写字母和数字的 canonical part number。
- 只访问 eBay 美国站搜索结果第一页；并发固定为 `1`，不翻页。
- 只让 `NEW` listing 形成 observed-demand evidence。
- 保存 listing ID、URL、标题、condition、price、sold raw label、sold count、
  part-number match、提取时间、方法与字段级 evidence。
- 对唯一 listing ID 计算 `max_single_listing_sold` 与
  `aggregate_observed_sold`；二者都只是观测值，不是时间窗口销量。
- 输出必须符合
  [contracts/v0_1_acquisition.schema.json](contracts/v0_1_acquisition.schema.json)。
- 单次查询至多对 `TIMEOUT`、连接错误或 HTTP `5xx` 重试一次；HTTP `4xx`
  以及其他失败不重试。

### 2.2 Out of scope

- Amazon、1688、三平台 funnel 与 Opportunity Score。
- eBay 其他 marketplace、其他 ship-to context、多语言解析和分页。
- API 凭据申请、批量调度、SQLite、CSV、缓存层和 10,000 OEM 压测。
- 自动确认 replacement、cross-reference 或 left/right pair 为同一零件。
- LLM、语义匹配、自动商业推荐和供应商判断。
- 登录自动化、CAPTCHA/anti-bot 绕过、代理池或 stealth。
- 保存完整网页响应；V0.1 只保存支持字段判断所需的最小原始片段。

## 3. 固定市场上下文

| Field | Required value |
|---|---|
| `marketplace_id` | `EBAY_US` |
| `site` | `www.ebay.com` |
| `locale` | `en-US` |
| `ship_to_country` | `US` |
| `ship_to_postal_code` | `10001`（非个人测试邮编） |
| `currency` | `USD` |

Provider 必须在解析 sold evidence 前验证这些字段。实际页面只要出现其他
marketplace、locale、currency 或 ship-to context，就返回
`MARKET_CONTEXT_MISMATCH`，不得继续累计 sold count。

## 4. 共享模型

机器可读定义以 JSON Schema 为准。首版只实现下列三个核心对象：

### 4.1 `AcquisitionOutcome`

一次 provider 查询的完整结果，包含 query、market context、显式 status、
listings、observed-demand summary 和 diagnostics。

状态固定为：

| Status | Meaning |
|---|---|
| `SUCCESS` | 页面与上下文有效，并解析出至少一个 listing。 |
| `PARTIAL_SUCCESS` | 至少一个 listing 有效，但也有被显式记录的解析异常。 |
| `ZERO_RESULTS` | 有效结果页明确为零结果；不是错误页、挑战页或解析失败。 |
| `HTTP_ERROR` | HTTP/页面加载失败。 |
| `TIMEOUT` | 获取超时。 |
| `CHALLENGE` | 出现 CAPTCHA 或反自动化挑战。 |
| `AUTH_REQUIRED` | 需要登录。 |
| `BLOCKED_BY_CREDENTIALS` | 官方路径存在，但本地缺少已批准凭据。 |
| `PROVIDER_UNAVAILABLE` | 没有符合授权与用途要求的 provider。 |
| `MARKET_CONTEXT_MISMATCH` | marketplace、locale、currency 或 ship-to 不符合固定值。 |
| `PARSER_FAILED` | 页面有效，但必要结构或字段无法按契约解释。 |

`AMBIGUOUS` 不属于 acquisition failure；它是 listing 的 match classification。

### 4.2 `ListingEvidence`

一个 eBay listing 的结构化观测。`match_type` 固定为：

```text
EXACT
NORMALIZED_EXACT
CROSS_REFERENCE
REPLACEMENT
LEFT_RIGHT_PAIR
SIDE_MISMATCH
AMBIGUOUS
IRRELEVANT
UNKNOWN
```

listing decision 固定为：

```text
ACCEPT_DEMAND_EVIDENCE
HUMAN_REVIEW
REJECT
```

### 4.3 `Evidence`

字段级证据必须包含 metric、value、source、URL、retrieved time、extraction
method、最小 raw evidence 与 `0.0–1.0` confidence。结论不得只保留数值而
丢失来源。

## 5. 决策规则

只有同时满足以下条件的 listing 才能进入 observed-demand 汇总：

```text
market context exact
AND match_type IN {EXACT, NORMALIZED_EXACT}
AND condition == NEW
AND sold_count is an explicitly parsed integer > 0
```

- `CROSS_REFERENCE`、`REPLACEMENT`、`LEFT_RIGHT_PAIR`、`AMBIGUOUS`、
  `UNKNOWN` → `HUMAN_REVIEW`。
- `SIDE_MISMATCH`、`IRRELEVANT` 或非 `NEW` listing → `REJECT`。
- sold label 缺失或无法解析不等于 `sold_count = 0`，应进入
  `HUMAN_REVIEW` 或显式 parser diagnostic。
- `aggregate_observed_sold` 只汇总唯一 listing ID，不能把同一 listing 的
  搜索卡片与详情页重复相加。
- 没有 eligible listing 时，summary 必须为 `count = 0`、`max = null`、
  `aggregate = 0`；非 success status 同样不得保留 demand aggregate。
- 存在 eligible listings 时，`max_single_listing_sold` 必须大于 `0`，且
  `aggregate_observed_sold >= max_single_listing_sold`。
- listing lifetime sold count 只能称作 `Observed Demand`，不能称作市场销量。

## 6. Sold label 边界

V0.1 只接受 `en-US` 下的整数英文标签：

```text
32 sold
1 sold
1,234 sold
10+ sold
```

允许数字中的千位逗号和数字后的 `+`；不解释 `K/M` 缩写，不从
“watchers”“available”“last one”等文本推导 sold count。原侦察中看到的
日文 `5点販売済み` 作为 locale-mismatch fixture 保存，但 V0.1 不实现日文
解析；必须先返回 `MARKET_CONTEXT_MISMATCH`。

所有情况下都保留 `sold_label_raw`。解析失败不得静默返回 `0`。

## 7. 固定 fixtures

[fixtures/ebay_v0_1_cases.json](fixtures/ebay_v0_1_cases.json) 是实现前基准，
覆盖：

- 两个已侦察的 live positive queries；
- 可区分 zero results、HTTP error、timeout、challenge、login、market mismatch
  与 parser failure 的 acquisition-status cases；
- exact 与 normalized-number；
- negative、ambiguous、cross-reference；
- synthetic replacement 和 left/right side mismatch；
- used-condition rejection；
- en-US sold parsing、无 sold signal 和 locale mismatch。

Synthetic fixture 只验证规则，不声明真实汽配关系。Live fixture 的结果数量、
价格和 sold count 都是动态值；测试只能断言显式状态、市场上下文、证据结构
和“失败不等于零结果”。

## 8. 首版实现验收门

实现开始前，本文件、JSON Schema 与 fixture 集合必须保持一致。实现完成时：

1. 所有 offline fixtures 通过 deterministic normalization、match、condition
   和 sold-label tests。
2. 每个运行结果都能通过 JSON Schema 校验。
3. live 运行先核验 market context，再解析字段。
4. 两个 live queries 顺序执行；不把动态数值写成固定断言。
5. 任一挑战、登录、上下文错误或 parser failure 都产生显式 status，并停止
   demand aggregation。

满足以上条件才算完成 V0.1；Amazon 与 1688 provider gate 不属于它的验收项。

## 9. 相对原企划的边界收缩

这里按结构数量衡量，不把不同模块假装成等量工时：

| Dimension | Original Proteus V0 | V0.1 first slice | Boundary reduction |
|---|---|---|---:|
| Active platforms | Amazon + eBay + 1688（3） | eBay（1） | `66.7%` |
| Business-hypothesis paths active | H1 + H2 + H3（3） | H2 的 evidence-acquisition prerequisite（1，尚未验证 H2） | `66.7%` deferred |
| Core build phases after reconnaissance | Phase 1–5（5） | Phase 1（1） | `80%` |
| Delivery surfaces | CLI + JSON + CSV + SQLite（4） | CLI + JSON（2） | `50%` |
| Operating scale | Candidate pool / 10,000-item design target | Single query / low-volume fixtures | 不适合百分比 |
| Product conclusion | Opportunity candidate for human review | Listing-level observed-demand evidence | 商业结论全部延后 |

Phase 6 evaluation 以最小 fixture 验证保留，因此没有计入 core build phase
分母。最诚实的表述是：**首版的核心产品边界比原 V0 收缩约 67%–80%**；
它是一个数据获取与证据契约切片，不代表原企划已经完成 20%–33%。原企划
仍是后续 roadmap，只有 provider gate 通过后才恢复 Amazon、1688 与完整
funnel。
