# Proteus V0 — Implementation Brief

> **Evidence-driven cross-platform automotive parts opportunity scanner**

**Codename:** Proteus
**Stage:** V0 / Proof of Concept
**Primary Market:** 北美汽配 × 中国供应链

---

## 0. 项目定义

Proteus 是一个面向北美汽配市场的**低成本跨平台机会发现系统**。

系统输入一批汽车零件的 OEM / MPN 候选，通过 Amazon、eBay、1688 以及公开 Web 数据依次判断：

1. Amazon 是否存在较低竞争；
2. eBay 是否存在真实市场需求；
3. 1688 是否存在可采购的中国供应链；
4. 是否值得进入人工复核。

最终输出：

> **少量具有“北美存在需求 + Amazon 竞争较低 + 中国存在供应”的汽配候选。**

Proteus V0 的首要目标不是自动替人完成选品决策，而是：

> **以尽可能低的数据成本，把大量 OEM 候选压缩成少量值得人进一步调查的候选。**

---

# 1. 项目背景

现有 Browser Agent 工作流已经证明以下方法在实践中可以运行：

```text
汽配 OEM 候选池
        ↓
Amazon 精确搜索
        ↓
判断竞争程度
        ↓
通过者进入 eBay
        ↓
验证实际成交
        ↓
通过者进入 1688
        ↓
确认中国供应
        ↓
人工复核
```

已经观察到类似案例：

```text
OEM: 53630-53010

Amazon:
  exact results ≈ 2
  price ≈ $22.68 / $37.05

eBay:
  exact OEM listing exists
  sold = 32

1688:
  exact part number
  MOQ = 1
  stock displayed
  direct supplier exists
```

以及：

```text
OEM: A18-67004-004
Product:
  Freightliner Cascadia 左侧外门把手

Amazon:
  exact/relevant results ≈ 4
  $37.86–$143.97

eBay:
  exact OEM listings exist
  observable sold counts

1688:
  exact model supply exists
  ¥40
  MOQ = 10
  stock available
```

因此，V0 不需要重新证明：

> “LLM 能不能操作浏览器查这些东西？”

已有流程已经证明可以。

真正需要解决的是：

> **能否把 Agent 正在进行的大量浏览器操作替换成更廉价的 API、HTTP、Search 和 Parser，并只把真正存在歧义的问题交给 LLM。**

---

# 2. 核心工程原则

Proteus 必须遵守以下优先级：

```text
0. 已授权且用途兼容的数据路径
        ↓
1. 免费官方 API
        ↓
2. 公开结构化 Web 数据
        ↓
3. 普通 HTTP 请求 + Parser
        ↓
4. Search Engine
        ↓
5. Browser Automation
        ↓
6. LLM semantic judgment
        ↓
7. 付费 API / 商业数据
```

核心原则：

> **Never use an expensive layer when a cheaper deterministic layer can solve the same problem reliably.**

但“更便宜”不能覆盖授权边界。任何 Provider 在进入优先级比较前，必须先确认：

```text
ACCESS_AUTHORIZED
+ PURPOSE_COMPATIBLE
+ REQUIRED_FIELDS_AVAILABLE
```

如果官方 API 不可用，不允许自动升级到未经许可的 HTTP 或 Browser 路径。

例如：

如果网页 HTML 中已经存在：

```text
32 sold
```

则 Parser 应直接读取。

不允许默认：

```text
打开 Browser
→ 截图
→ LLM 看页面
→ LLM 判断 sold = 32
```

同理，如果官方免费 API 已经提供某字段，不允许为了开发方便而使用 LLM Search 获取同一字段。

---

# 3. V0 核心假设

Proteus V0 验证三个商业假设。

## H1 — Amazon Competition

对于确定的 OEM / MPN：

如果 Amazon 精确搜索得到的**高度相关商品数量较少**，则将其作为低竞争候选。

初始规则：

```text
amazon_relevant_results <= 5
```

注意：

这里判断的是：

```text
Amazon relevant product results
```

而不是严格意义上的：

```text
Amazon seller count
```

两者不得混淆。

V0 暂不购买 Keepa 等商业数据获取精确 Offer/Seller 信息。

---

## H2 — eBay Demand

对于通过 Amazon 筛选的 OEM：

如果 eBay 存在高度相关的新品 listing，并具有明确的 sold evidence，则认为存在北美市场需求证据。

例如：

```text
OEM: 53630-53010

Listing:
  exact OEM match
  condition: new
  sold: 32
```

则形成一条 demand evidence。

但必须区分：

```text
single listing sold
```

和：

```text
aggregate observed sold
```

例如：

```text
Listing A → 3 sold
Listing B → 5 sold
Listing C → 11 sold
```

应该记录：

```json
{
  "max_single_listing_sold": 11,
  "aggregate_observed_sold": 19
}
```

不得简单把：

```text
11 sold
```

描述成：

```text
这个 OEM 销量为 11
```

因为 listing sold count 并不等价于市场完整销量。

V0 所使用的指标应该称为：

```text
Observed Demand
```

而不是：

```text
True Market Sales
```

---

## H3 — 1688 Supply

对于已经证明存在需求的候选：

检查 1688 是否存在相同或高度对应商品。

重点提取：

```text
supplier
title
OEM / MPN
price
MOQ
stock
lead time
variant
vehicle compatibility
URL
```

满足：

```text
OEM/MPN match
+
purchasable
+
acceptable MOQ
+
reasonable supply evidence
```

即可认为存在供应链。

V0 不需要自动判断供应商是否“绝对可靠”。

供应商质量最终由人工复核。

---

# 4. 为什么叫 Proteus

Proteus 来自希腊神话中的普罗透斯。

其核心特征是：

> **不断改变自己的形态。**

这与项目核心问题高度对应。

同一个汽车零件：

```text
OEM: A18-67004-004
```

在不同平台可能表现为：

```text
Amazon:
Freightliner Cascadia Exterior Door Handle...

eBay:
A18-67004-004 Freightliner Left Driver Door Handle...

1688:
适用卡斯卡迪亚外拉手 A18-67004-004/A18-67004-006
```

标题、语言、SKU、描述、品牌甚至型号书写方式都可能变化。

Proteus 的任务就是：

> **识别这些不同形态背后的同一个商品实体。**

因此 Cross-platform Entity Resolution 是项目长期核心能力之一。

---

# 5. V0 Pipeline

完整流程：

```text
                OEM Candidate Pool
                        │
                        ▼
              ┌──────────────────┐
              │ Normalization    │
              │ OEM / MPN clean  │
              └────────┬─────────┘
                       │
                       ▼
              ┌──────────────────┐
              │ Amazon Fast Pass │
              └────────┬─────────┘
                       │
               competition <= T ?
                  │            │
                 NO           YES
                  │            │
                reject         ▼
                       ┌────────────────┐
                       │ eBay Demand    │
                       │ Verification   │
                       └───────┬────────┘
                               │
                       demand >= T ?
                         │          │
                        NO         YES
                         │          │
                       reject       ▼
                              ┌──────────────┐
                              │ 1688 Supply  │
                              │ Verification │
                              └──────┬───────┘
                                     │
                                     ▼
                              Candidate Score
                                     │
                                     ▼
                               Human Review
```

重要：

**不要同时对所有候选查询三个平台。**

必须使用漏斗式执行。

例如：

```text
10,000 OEM
    ↓ Amazon
1,000 low-competition candidates
    ↓ eBay
100 demand-positive candidates
    ↓ 1688
20 supply-positive candidates
    ↓
Human Review
```

这样可以显著减少 Browser、Search 和 LLM 调用。

---

# 6. Data Source Strategy

V0 不购买商业数据。

但系统必须从第一天就允许未来替换数据源。

统一定义：

```text
DataProvider
```

例如：

```text
AmazonProvider
EBayProvider
Alibaba1688Provider
```

每个平台内部允许存在：

```text
APIProvider
HTTPProvider
SearchProvider
BrowserProvider
```

调用逻辑：

```text
authorization / purpose gate
        ↓ passed
cheap deterministic provider
        ↓ failure
approved fallback provider
        ↓ ambiguity
LLM
```

不要把某个平台的数据获取逻辑直接耦合进业务评分代码。

当前数据源实测状态、证据和明确边界见：

> [DATA_SOURCE_RECONNAISSANCE.md](DATA_SOURCE_RECONNAISSANCE.md)

---

# 7. Amazon Module

## 7.1 输入

```text
OEM / MPN
aliases
optional product name
```

例如：

```text
A18-67004-004
```

---

## 7.2 搜索策略

优先精确 OEM：

```text
"A18-67004-004"
```

必要时：

```text
A18 67004 004
A1867004004
```

但不同 query 的结果必须记录来源，不能直接混在一起。

---

## 7.3 输出

至少：

```json
{
  "query": "A18-67004-004",
  "result_count": 4,
  "relevant_result_count": 4,
  "min_price": 37.86,
  "max_price": 143.97,
  "currency": "USD",
  "products": [],
  "evidence": [],
  "confidence": 0.0
}
```

---

## 7.4 V0 Competition Rule

默认：

```text
relevant_result_count <= 5
```

进入下一阶段。

阈值必须配置化。

---

# 8. eBay Module

这是 V0 最重要的数据模块之一。

已经验证普通 Web Search 可以发现包含：

```text
price
condition
location
OEM
MPN
sold
available
compatibility
```

等字段的公开 eBay listing。

因此 V0 必须首先研究：

```text
official free API
HTML
JSON-LD
embedded JSON
XHR / JSON endpoint
search index
```

不得默认使用 Browser Automation。

---

## 8.1 Query

优先：

```text
exact OEM
```

例如：

```text
A18-67004-004
```

---

## 8.2 Listing Extraction

每个 listing 保存：

```json
{
  "url": "",
  "title": "",
  "price": null,
  "currency": "USD",
  "condition": "",
  "sold_count": null,
  "available_count": null,
  "seller": "",
  "location": "",
  "oem": [],
  "mpn": [],
  "compatibility": [],
  "retrieved_at": "",
  "source_method": "",
  "raw_evidence": ""
}
```

---

# 9. Cross-platform Product Matching

这是 Proteus 最重要的技术模块之一。

匹配优先级：

```text
1. Exact OEM
2. Exact MPN
3. Cross-reference part number
4. normalized part number
5. vehicle compatibility
6. product attributes
7. title semantic similarity
8. LLM judgment
```

必须：

> **deterministic first, semantic second.**

例如：

```text
A18-67004-004
A18 67004 004
A1867004004
```

应该首先通过 normalization 判断为同一个编号。

不得调用 LLM。

---

# 10. OEM Normalization

建立统一函数：

```text
normalize_part_number()
```

例如：

```text
A18-67004-004
A18 67004 004
A18_67004_004
A1867004004
```

生成 canonical representation：

```text
A1867004004
```

同时保留原始值。

数据结构：

```json
{
  "raw": "A18-67004-004",
  "canonical": "A1867004004"
}
```

不得丢失原始 OEM。

---

# 11. Cross-reference Discovery

允许从公开汽配网站、catalog、listing 等发现：

```text
OEM aliases
MPN aliases
interchange numbers
left/right counterpart
replacement numbers
superseded numbers
```

例如：

```text
A18-67004-004
A18-67004-006
HLK2882
```

但必须区分：

```text
same_part
compatible_part
left_right_pair
replacement
unknown_relation
```

不得因为两个编号同时出现在一个 listing 就直接判断：

```text
OEM A == OEM B
```

---

# 12. 1688 Module

1688 是漏斗最后阶段。

原因：

Amazon 和 eBay 已经淘汰大量候选，因此无需对所有 OEM 查询 1688。

输入：

```text
OEM
aliases
product name
vehicle
```

搜索顺序：

```text
exact OEM
↓
OEM alias
↓
OEM + Chinese product name
↓
semantic search
```

---

## 12.1 输出

```json
{
  "supplier": "",
  "title": "",
  "matched_part_numbers": [],
  "price_cny": null,
  "moq": null,
  "stock": null,
  "lead_time": null,
  "variants": [],
  "url": "",
  "match_type": "",
  "confidence": 0.0,
  "evidence": []
}
```

---

# 13. Evidence-first Architecture

Proteus 不允许只有结论没有证据。

每一个关键字段都应该尽可能具有：

```text
value
source
URL
retrieved_at
extraction_method
raw evidence
confidence
```

例如：

```json
{
  "metric": "ebay_listing_sold",
  "value": 32,
  "source": "ebay",
  "url": "...",
  "retrieved_at": "2026-08-25T...",
  "method": "html_parser",
  "raw_evidence": "32 sold",
  "confidence": 0.98
}
```

因此任何最终结论都可以反向追踪：

```text
Candidate
   ↓
Score
   ↓
Metric
   ↓
Evidence
   ↓
Source URL
```

---

# 14. LLM 的职责

LLM **不是默认数据采集器**。

允许 LLM 做：

### A. Semantic Matching

例如判断：

```text
“Freightliner Cascadia Driver Exterior Handle”

是否与：

“Cascadia 左外门拉手”

描述同类商品。
```

### B. Ambiguity Resolution

例如：

```text
A18-67004-004
A18-67004-006
```

究竟是：

```text
same part
replacement
left/right pair
```

### C. Unstructured Extraction

当某网页无法稳定 parser 时，从少量文本中提取结构。

### D. Candidate Explanation

给最终人工 reviewer 生成：

```text
为什么这个商品被推荐？
风险是什么？
哪些证据最重要？
```

---

## LLM 禁止事项

如果 deterministic code 可以解决，则不得调用 LLM。

例如：

```text
"32 sold" → 32
```

不需要 LLM。

```text
"$59.99" → 59.99
```

不需要 LLM。

```text
A18-67004-004
→ A1867004004
```

不需要 LLM。

---

# 15. Browser Automation

Browser Automation 是 fallback，不是默认方案。

只有以下情况允许使用：

```text
普通 HTTP 无法访问
AND
免费 API 不提供
AND
Search cache 不足
AND
该字段对判断重要
AND
平台允许该自动访问方式
```

才允许调用 Browser。

Browser 层建议：

```text
Playwright
```

但必须实现：

```text
rate limit
retry
timeout
cache
```

不得无限重试。

不得实现：

```text
CAPTCHA bypass
anti-bot bypass
stealth fingerprint evasion
```

如果平台明确阻止自动访问：

```text
mark unavailable
→ fallback
```

而不是升级对抗。

---

# 16. Search Engine 的职责

Search Engine 是：

> **Discovery Layer**

而不是最终数据库。

典型：

```text
"A18-67004-004" site:ebay.com
```

获得：

```text
candidate URLs
```

然后：

```text
URL
↓
HTTP Fetch
↓
Parser
↓
Evidence
```

Search snippet 本身可以作为弱证据，但必须标记：

```text
confidence < direct page evidence
```

---

# 17. Opportunity Model

V0 不要建立复杂 ML 模型。

先使用透明规则。

例如：

```text
Amazon Competition
        ↓
eBay Demand
        ↓
1688 Supply
        ↓
Opportunity Candidate
```

允许简单 score：

```text
OpportunityScore =
    CompetitionScore
  + DemandScore
  + SupplyScore
  + MarginProxy
```

但所有组成项必须可解释。

---

# 18. Confidence

每个判断必须包含：

```text
HIGH
MEDIUM
LOW
```

或者：

```text
0.0–1.0
```

例如：

```text
Exact OEM
+ exact listing
+ direct HTML sold count

confidence = HIGH
```

而：

```text
Google snippet
+ approximate title match

confidence = LOW
```

低 confidence 不等于 reject。

应该：

```text
LOW confidence
→ Human Review
```

---

# 19. Candidate State Machine

候选必须具有明确状态。

建议：

```text
NEW

AMAZON_CHECKING
AMAZON_REJECTED
AMAZON_PASSED

EBAY_CHECKING
EBAY_REJECTED
EBAY_PASSED

SUPPLY_CHECKING
SUPPLY_REJECTED
SUPPLY_PASSED

REVIEW_REQUIRED

APPROVED
REJECTED
```

这样任务中断后可以继续。

不得每次重新从 Amazon 开始。

---

# 20. Cache

所有外部查询必须缓存。

Cache Key 至少包含：

```text
platform
query
normalized OEM
query type
```

例如：

```text
amazon:A1867004004:exact
```

TTL 配置化。

目标：

> 同一个 OEM 在短时间内不得因为不同 Agent / Worker 重复访问同一个平台。

---

# 21. Failure Handling

外部数据获取失败不得等价于：

```text
result = 0
```

必须区分：

```text
ZERO_RESULTS
REQUEST_FAILED
BLOCKED
TIMEOUT
PARSER_FAILED
AMBIGUOUS
NOT_CHECKED
```

例如 Amazon 页面加载失败：

错误：

```text
amazon_results = 0
```

正确：

```text
amazon_status = REQUEST_FAILED
```

这是 V0 的强制要求。

---

# 22. 数据库

V0 推荐：

```text
SQLite
```

即可。

不要一开始引入：

```text
Kafka
Kubernetes
distributed database
microservices
```

未来需要时再迁移 PostgreSQL。

建议核心表：

```text
parts
aliases
platform_queries
listings
suppliers
evidence
candidates
runs
```

---

# 23. 推荐技术栈

V0：

```text
Python 3.12+

HTTP:
httpx

Parsing:
BeautifulSoup / selectolax
JSON / JSON-LD parser

Browser fallback:
Playwright

Database:
SQLite
SQLAlchemy

Validation:
Pydantic

CLI:
Typer

LLM:
provider abstraction

Testing:
pytest
```

V0 **不要求前端**。

先输出：

```text
CLI
+
JSON
+
CSV
+
SQLite
```

即可。

---

# 24. Provider Architecture

建议：

```text
proteus/
├── core/
│   ├── models.py
│   ├── pipeline.py
│   ├── scoring.py
│   └── normalization.py
│
├── providers/
│   ├── amazon/
│   ├── ebay/
│   ├── alibaba1688/
│   ├── search/
│   └── llm/
│
├── matching/
│   ├── deterministic.py
│   ├── semantic.py
│   └── cross_reference.py
│
├── evidence/
│   ├── models.py
│   └── store.py
│
├── storage/
│   ├── database.py
│   └── cache.py
│
├── pipeline/
│   ├── amazon_stage.py
│   ├── ebay_stage.py
│   └── supply_stage.py
│
├── cli/
│   └── main.py
│
└── tests/
```

这只是推荐组织方式。

如果实现过程中存在更简单且合理的结构，可以调整。

不要为了严格遵循目录而过度工程化。

---

# 25. V0 开发顺序

## Phase 0 — Data Source Reconnaissance

首先不要写完整系统。

拿已知 OEM：

```text
53630-53010
A18-67004-004
```

作为 fixture。

分别调查：

### Amazon

确定：

```text
搜索请求
HTML
embedded JSON
result count
price
是否需要 JS
是否需要 Browser
```

### eBay

确定：

```text
listing discovery
sold count 来源
price
condition
seller
location
OEM
compatibility
```

优先调查：

```text
official API
HTML
JSON-LD
embedded state
```

### 1688

确定：

```text
search
offer
price
MOQ
stock
lead time
OEM
supplier
```

目标不是：

> 找到最聪明的绕过方式。

目标是：

> 找到最简单、稳定、低成本、允许正常访问的数据获取路径。

必须记录 reconnaissance 结果。

---

# 26. Phase 1 — eBay Vertical Slice

首先实现：

```text
OEM
↓
Search / API
↓
listing
↓
sold
↓
structured JSON
```

输入：

```text
A18-67004-004
```

应能够输出类似：

```json
{
  "oem": "A18-67004-004",
  "listings": [
    {
      "price": 59.99,
      "sold": 3
    }
  ]
}
```

具体数值以运行时数据为准。

---

# 27. Phase 2 — Amazon Fast Filter

实现：

```text
OEM
↓
Amazon Search
↓
Relevant Products
↓
Competition Classification
```

目标：

```text
LOW
MEDIUM
HIGH
```

以及原始 evidence。

---

# 28. Phase 3 — Funnel

连接：

```text
Candidate Pool
↓
Amazon
↓
eBay
```

确保：

Amazon rejected candidate

**绝不进入 eBay 阶段。**

---

# 29. Phase 4 — 1688

只有：

```text
Amazon Passed
AND
eBay Passed
```

才调用 1688。

---

# 30. Phase 5 — LLM Fallback

最后才加入 LLM。

先统计：

> 有多少 case deterministic matching 无法判断？

然后只针对这些 case 实现 semantic fallback。

不要提前把 LLM 放进主路径。

---

# 31. Phase 6 — Evaluation

使用一组固定 OEM benchmark。

至少包含：

```text
known positive
known negative
ambiguous
no Amazon result
no eBay demand
no 1688 supply
```

评估：

```text
Precision
False Positive
False Negative

requests / candidate
browser calls / candidate
LLM calls / candidate
processing time / candidate
estimated cost / candidate
```

其中：

> **LLM calls / candidate**

和：

> **browser calls / candidate**

是 V0 的重要工程指标。

目标不是零。

目标是尽可能低。

---

# 32. V0 Success Criteria

V0 成功不意味着：

> 找到了一个一定赚钱的商品。

V0 成功意味着：

### Functional

能够完成：

```text
OEM Pool
→ Amazon Competition
→ eBay Demand
→ 1688 Supply
→ Candidate Report
```

### Evidence

任何推荐都可以追溯到原始来源。

### Cost

绝大多数候选不需要 LLM。

### Efficiency

失败候选尽可能早被淘汰。

### Reliability

网络错误不能被误判成：

```text
0 results
```

### Human Usability

最终输出的信息足以让人快速决定：

```text
值得进一步研究
/
不值得
```

---

# 33. V0 明确不实现

不要实现：

* Keepa 商业 API；
* S&P Global Mobility VIO；
* Experian VIO；
* 精确美国车辆保有量；
* 自动下单；
* 自动联系供应商；
* 自动发布 Amazon/eBay listing；
* 完整物流模型；
* 完整关税模型；
* 精确利润预测；
* ML Ranking Model；
* Kubernetes；
* Microservices；
* 分布式爬虫；
* CAPTCHA 绕过；
* 代理池对抗；
* 全站 Amazon/eBay/1688 爬取；
* SaaS 用户系统；
* Dashboard。

这些全部不是 V0。

---

# 34. Future Direction

只有 V0 证明商业筛选逻辑有效后，才考虑：

```text
V0
公开数据
+
免费 API
+
Scraping
+
少量 LLM
```

↓

```text
V0.5
更稳定的 Provider
+
更多 OEM 数据源
+
更好的 Entity Resolution
```

↓

```text
V1
付费 API
+
Keepa
+
商业 eBay 数据
```

↓

```text
V2
Vehicle Parc / VIO
+
物流
+
平台费用
+
关税
+
退货率
```

↓

```text
Opportunity Ranking
```

最终可以计算：

```text
Demand
×
Competition
×
Margin
×
Vehicle Parc
×
Supply Quality
×
Risk
```

但在 V0 中禁止提前实现这些复杂模型。

---

# 35. Agent Execution Instructions

你负责实现 Proteus V0。

工作原则：

1. **先调查，再编码。**
2. 不假设某个平台必须使用 Browser。
3. 不假设某个平台必须使用 API。
4. 优先使用最低成本、最简单、稳定的数据获取方式。
5. 不为了“AI”而调用 LLM。
6. 所有外部数据必须保存 evidence。
7. 所有失败必须显式表示，不允许把失败解释成零结果。
8. 所有 expensive operations 必须尽量位于漏斗后端。
9. 阈值必须配置化。
10. 不过度工程化。

第一项实际任务：

> 使用 `53630-53010` 和 `A18-67004-004` 作为 fixtures，对 Amazon、eBay、1688 执行 Data Source Reconnaissance。

调查每个平台：

```text
API availability
HTTP accessibility
HTML structure
JSON-LD
embedded JSON
XHR/network data
Search discoverability
Browser requirement
fields obtainable
stability
limitations
```

将调查结果记录下来。

然后选择 V0 最简单的数据获取方案。

**不要在完成 reconnaissance 之前直接构建完整 pipeline。**

当前进度（2026-08-25）：已完成首轮匿名 HTTP、普通浏览器与官方文档侦察，
并完成 V0.1 最小商机闭环的实现前契约。eBay US evidence acquisition 是首个
自动化阶段；Amazon Creators API 和 1688 Open Platform 仍受凭据/授权 gate
阻塞，因此 V0.1 通过可追溯 manual evidence 输入补齐这两个商业 gate。

V0.1 只有在 Amazon low competition、eBay observed demand 与 1688
purchasable supply 三项全部通过时，才能输出 `OPPORTUNITY_CANDIDATE`。
固定模型、阈值、fixtures、验收条件及正确的边界收缩方式见
[V0_1_SCOPE_CONTRACT.md](V0_1_SCOPE_CONTRACT.md)。完整侦察结果见
[DATA_SOURCE_RECONNAISSANCE.md](DATA_SOURCE_RECONNAISSANCE.md)，当前执行项见
[TODO.md](TODO.md)。原 V0 的核心商机目标没有被首版收缩。

---

# 36. 最终原则

Proteus 的核心不是：

> “让 AI 替人不停逛三个购物网站。”

而是：

> **把原本昂贵的 Agent Research 转化为廉价、确定性、可批量执行的数据流水线，只把真正需要理解的问题留给模型。**

换言之：

```text
Code handles scale.
Data provides evidence.
LLM handles ambiguity.
Human makes the final decision.
```

这就是 Proteus V0。
