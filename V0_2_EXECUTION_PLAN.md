# Proteus V0.2.4 — Northway Product-Family Screening Execution Plan

> 状态：`NORTHWAY_INITIAL_SCREENING_MVP_RUNNABLE / MANUAL_REVIEW_REQUIRED / V0.2.3_COMPATIBLE`
> 更新：2026-08-28
> 上位企划：[proteus.md](proteus.md)
> V0.1 基线：[V0_1_SCOPE_CONTRACT.md](V0_1_SCOPE_CONTRACT.md)

## 0. 2026-08-28 权威执行边界

本节覆盖后文以“精确 OEM 竞争数”为主要产品身份口径的旧描述。V0.2.3 自动 MVP、
严格三门 evaluator 和历史供货 profile 继续保留为兼容实现，但在产品家族竞争完成前，
它们不能单独产出“真正低竞争、缺少平替”的选品结论。

### 0A. 产品目标和范围

当前研究问题固定为：

> 在 Northway 风格的车型专用小型替换件中，哪些产品同时存在需求、整个平替产品家族
> 竞争较少、家族价格下限可接受，并且国内可以供应非原厂替代品？

首批只允许两个独立 category profile：

| Profile | Included archetypes | Critical identity fields |
| --- | --- | --- |
| `vehicle_specific_small_trim` | fog-light bezel, tow-hook cover, bumper reflector, headlight-washer cover, lower air deflector | make/model/year, position, left/right, finish, single/pair |
| `vehicle_specific_cable` | hood-latch, accelerator, door-handle Bowden and transmission shift-control cables | make/model/year, engine/transmission qualifier, route/end connector, position |

硬性排除 `Universal fit`、清洁剂/化学品、通用装饰、复杂电子件、灯具总成、制动/转向/
气囊等安全核心件、大型钣金、重型总成和无法解析到明确车型/位置的泛化商品。范围判定
发生在昂贵市场采集之前，不能再通过整个 eBay `6028` 类目配合宽泛 `OEM` 关键词来
定义产品空间。

### 0B. 黄金样本体系

黄金标准来自 northwayautoparts 的产品结构，而不是单个预设“必过”零件：

```text
NORTHWAY_GOLD
  25778388 / 25778389
  25881881 / 25881882
  25928246 / 25928247 / 25928248
  23397792
  5363089114 / 78180-35260 / 3U0837085 / 2048800859

NORTHWAY_LIKE
  467903X100

OUT_OF_SCOPE_NEGATIVE
  00289-ACRKT
  universal mud flap and other Universal-fit controls
```

`NORTHWAY_GOLD` 用于检查产品类型、车型、左右侧、位置、套装数量、Replacement/Replaces
和交叉号能否正确解析；它不保证对应商品当前仍低竞争。`NORTHWAY_LIKE` 检查规则能否
泛化到店铺之外的同形态产品；负样本必须在范围或家族竞争阶段被拒绝。所有标签由人工
复核并版本化，不能硬编码到正常运行逻辑。

### 0C. 产品家族和查询契约

系统必须先构造 `sellable_product_family`：

```json
{
  "part_type": "transmission shift-control cable",
  "fitment": {
    "make": ["Hyundai"],
    "model": ["Elantra"],
    "year_from": 2011,
    "year_to": 2013,
    "engine": [],
    "transmission": ["automatic"]
  },
  "position": null,
  "side": null,
  "critical_specs": [],
  "package_quantity": 1,
  "identifiers": [],
  "relations": [],
  "confidence": null,
  "evidence": []
}
```

编号关系必须区分 `same_part`、`supersedes`、`replacement`、`compatible_part`、
`left_right_counterpart` 和 `unknown_relation`。不同左右侧、单件与左右套装、关键接口或
变速箱配置不一致时不得合并。

每个家族按固定 query pack 搜索 Amazon US，并逐条保存 query 与来源：

```text
1. exact OEM / MPN and normalized variants
2. Replacement/Replaces and verified cross-reference numbers
3. part type + make + model + year range
4. part type + fitment + side/position
5. part type + fitment + critical specification
```

不同 query 的结果先独立保存，再按 ASIN 和可互换产品身份合并。不能因为标题包含同一
OEM 就认定相关，也不能因为标题未包含 OEM 就忽略明显的可互换平替。

### 0D. 竞争、价格、报价和供应读数

Amazon 输出至少分离：

```text
competitive_product_count   # 家族内不同平替产品/ASIN 数
offer_count_by_asin         # 每个 ASIN 的 active seller offers
family_offer_count_lower_bound
family_price_floor_usd      # 所有相关平替产品中的最低可见价
```

OEM 原厂件价格不能掩盖廉价非原厂替代品；seller offers 不能冒充产品种类。只有家族结果
页完整，或已观察到的下界足以明确越过阈值时，才能形成确定性竞争结论。阈值继续配置化，
最终值由 Northway gold benchmark 冻结。

国内供应验证面向对应的非原厂产品家族，至少绑定产品类型、车型、左右/位置、关键规格、
供应商、offer/SKU、MOQ 和来源证据。只发现原厂件、通用近似品或规格不一致商品不能
证明可供应。

### 0E. 采集、排序和导出语义

- 一次公开初筛运行固定覆盖两个 profile 下的全部九个 archetype；用户不先选择零件类型，
  每类分别保存实际关键词、页数、状态和统计，随后统一去重与排序；
- 取消候选产出的 `max_candidates` 截断：处理本次显式扫描页范围内发现的全部去重候选；
- 保留 `discovery_pages`、provider rate limit、预算和可恢复游标，不能把“不限候选”
  解释成无界扫描整个类目；
- `PARTIAL_SUCCESS`、缺字段或 provider 暂时失败时继续采集其他独立证据；只有明确范围
  淘汰、身份冲突或已有确定性业务 gate 失败时才跳过昂贵后续步骤；
- 页面先排没有明确失败的候选，再按通过项降序、缺失证据升序、平替产品数升序排序；
  产品范围、家族身份和家族竞争是排名硬前提，不能让关键证据缺失的 `4/5` 假机会置顶；
- 页面默认不展示明确淘汰项，通过状态分类可以单独查看；这只是展示过滤，完整结果仍保留；
- JSON 导出保存全部通过、拒绝和待复核候选，以及实际 profile、扫描页/游标、query pack、
  家族身份、三个竞争读数、阈值、逐字段证据、provider attempts、失败原因和最终排序。

### 0F. 实施顺序和停止条件

```text
Phase 1  versioned Northway gold/negative fixtures and category profiles
Phase 2  sellable product-family resolver and relation graph
Phase 3  family query pack and Amazon substitute-product aggregation
Phase 4  family-bound eBay demand and China non-OEM supply verification
Phase 5  full-candidate JSON export, ranking and operator UI
Phase 6  replay/live benchmark and threshold approval
```

先用店铺参考集验证产品身份，不先扩大 provider、VIO 或年度销量集成。若左右件/套装、
Replacement/Replaces 或通用负样本无法稳定区分，就停止进入 live 批量搜索并修复 identity
层；provider 能运行、页面有候选或旧五道门通过都不能替代该验收。

当前已实现独立 V0.2.4 初筛路径：范围分类、产品家族解析、Amazon query pack、平替
聚合、价格/ASIN/offer 分离、排序和完整 JSON 导出均可运行；V0.2.3 旧路径继续保留为
兼容接口。按照 2026-08-28 的 MVP 收敛决定，本版只要求 SerpApi，国内非原厂供货和
利润显示为人工复核清单，不再为初筛引入第二套必需凭证。当前输出是待人工复核的市场
shortlist，不是采购或上架结论。公开运行入口已经固定为九类统一扫描，并输出
`per_archetype` 和 `discovery_queries` 供后续前端美化直接使用。

## 0. 2026-08-27 V0.2.3 兼容执行历史

本节保留为 V0.2.3 兼容实现和决策历史，不再代表当前主产品验收。

### 0A. 自动 MVP（当前可运行的 V0.2.3 兼容面）

用户已接受“机器先粗筛、后续人工复核”的阶段性边界，因此 V0.2.3 新增独立 profile：

```text
SerpApi eBay sold-category 自动发现
→ SerpApi eBay exact sold 可见结果数 > 阈值
→ SerpApi Amazon US 完整精确竞争数 <= 阈值
→ SerpApi eBay Product compatibility
→ NY DMV active registrations + NHTSA VIN model estimate >= 阈值
→ MVP_OPPORTUNITY_CANDIDATE + human_review_required=true
```

该链路是自动商机候选缩圈，不是需求抓取器，也不冒充严格证据：

- eBay 指标是 provider 当前可见的精确已售结果下界，不是 Product Research 365 天销量；
- 车辆指标是 NY DMV 活跃注册总量结合 NHTSA 有界 VIN 样本得到的车型估算，不是全国官方 VIO；
- 采样为无排序固定偏移窗口，不声明统计置信区间；样本或解码不完整时返回
  `PARTIAL_SUCCESS`，自动车辆门只能 `REVIEW_REQUIRED`；
- Amazon 只有完整精确计数高于阈值时才能确定性拒绝；
- eBay 可见销量不足或 vehicle proxy 不足均为 `REVIEW_REQUIRED`，不能据此否定全年销量
  或真实保有量；
- 所有通过项仍强制人工检查零件同一性、适配覆盖、左右件/套装关系和数据新鲜度。

自动 profile 默认只需要 `SERPAPI_API_KEY`；NY DMV Socrata 和 NHTSA vPIC 匿名可用。通过
`POST /api/v1/mvp/runs` 提交；五段 collector 可独立替换。严格 profile 和下文三项
不可降级 gate 保持不变。
MarketCheck 保留为可选增强，不再是自动 MVP 的阻塞依赖。

当前目标是寻找“市场商机”，不是只抓需求，也不是把 1688 可采购性混入市场需求判定：

```text
SerpApi：候选发现 + Amazon US 精确竞争
                    AND
eBay Product Research：EBAY_US 近 365 天销量 > 20
                    AND
TecAlliance TecDoc VIO：已解析适配车型的美国保有量 >= 显式业务阈值
                    ↓
          MARKET_OPPORTUNITY_CANDIDATE
                    ↓
    可选供货、到岸成本、利润和下单能力核验
```

### 0.1 三项不可降级的 gate

1. eBay 必须是 `EBAY_US`、精确 365 天窗口、销量严格大于 20。20 本身不通过。
2. Amazon 必须是 `AMAZON_US` 的精确竞争对手计数，最多 5 个。
3. VIO 必须是已解析到零件适配关系的美国 compatible vehicle count，并达到本次运行
   显式提供的 `min_us_vehicle_parc`。在业务阈值冻结前不设置拍脑袋默认值。
4. 每份证据必须有 provider、source reference 和带时区 retrieval time。缺失、字段
   歧义、市场错位或窗口不完整统一为 `REVIEW_REQUIRED`，不得当成零值。
5. 三门全过只输出 `MARKET_OPPORTUNITY_CANDIDATE`；它不等于供货可得、利润合格或
   可下单的产品推荐。

### 0.2 兼顾覆盖与配置成本的服务选择

| 能力 | 主服务 | 配置与边界 |
| --- | --- | --- |
| 候选发现、Amazon US 竞争 | SerpApi | 共用现有一枚 Key；Amazon adapter 已可用 |
| eBay 年销量 | eBay Product Research 导出/规范化证据 | Seller Hub 授权；先实现确定性导入，不抓登录页面 |
| 车辆适配 + 美国 VIO | TecAlliance TecDoc VIO | 一家服务覆盖车辆语义与 VIO；商业合同决定真实 endpoint/auth |
| VIO 备选 | Experian Automotive VIO | TecAlliance 覆盖或合同不合适时替换 |
| 1688 供货 | HioBuy 兼容 adapter | 严格市场筛选之后可选，不是默认配置和 gate |

SerpApi 继续承担它能稳定证明的搜索任务；年度销量和美国保有量不从搜索 snippet 或
当前 listing 数量推导。DataForSEO/Keepa 可替换 Amazon 搜索，但会增加账号且不能补齐
另外两项关键证据，因此不作为默认依赖。

### 0.3 当前实现和前端契约

- `GET /api/v1/screening/policy` 返回阈值、市场、服务策略和资格边界；
- `POST /api/v1/screening/evaluate` 接收三份供应商无关的规范化证据并确定性判定；
- `GET /api/v1/config/status` 区分 SerpApi 基础可用、严格 profile 未就绪和可选供货
  profile；
- `GET /api/v1/providers` 返回脱敏 provider 状态与当前服务策略；
- 前端只能调用 Proteus loopback API，第三方 Key、Seller Hub 文件路径和商业 provider
  凭证不得进入浏览器；
- `POST /api/v1/runs` 与 `GET /api/v1/runs/{run_id}` 暂时保留旧 SerpApi + HioBuy
  异步链路，后续可在不破坏前端的情况下把 acquisition manager 接到同一任务模型。

业务规则依赖 `EBAY_ANNUAL_SALES`、`AMAZON_COMPETITION`、`US_VEHICLE_PARC` 能力，
不导入 TecAlliance/Product Research vendor payload。新 provider 通过
`preflight/acquire/estimate_cost` 和规范化证据 schema 接入。

### 0.4 尚未通过的产品验收

1. Product Research 的授权导出样本、字段/timezone 语义和导入器；
2. TecAlliance 商业开通、客户级 API 说明、真实 adapter 和 fitment/VIO canary；
3. 业务方批准的最小美国保有量阈值；
4. SerpApi eBay discovery `HTTP_ERROR` 和 exact 查询 `TIMEOUT` 的修复/基准；
5. 20 个真实零件 benchmark，以及至少一条三门全过的当前真实商机。

因此当前完成的是可替换 provider contract、匿名车辆代理、简化配置和前端接口预留，
不是“全国 VIO 和 eBay 365 天销量均已自动验收”。

## 0B. V0.2.1 历史兼容落点

2026-08-25 曾批准两账号 managed MVP，替代“Amazon Seller 账号必须先就绪”的
默认前置条件。当时默认链路为：

```text
SerpApi eBay Motors sold-category discovery
→ SerpApi Amazon exact competition
→ SerpApi eBay exact sold demand
→ HioBuy 1688 exact detail + order preview
```

它只需要 SerpApi 和 HioBuy 两个账号。该链路现在保留为下游供货验证兼容路径，不再
定义严格市场商机，因为 1688 可采购性不能替代“美国车辆保有量充足”。

本仓库现已实现 V0.2 engineering preview：Amazon B2B CSV 候选发现、V0.2
contracts、Amazon → eBay → 1688 短路、Nexscope managed REST adapters、HioBuy
1688 `search → detail → order preview` 只读 adapter、V0.1 输入兼容和
`automation_qualified` 隔离。随后补齐了 provider-neutral protocol、显式 registry、
SerpApi eBay sold adapter、逐阶段 provider profile 和 `providers check` canary。

这不是产品验收完成。当前尚缺两个获准生产账号、真实 receiver、provider
readiness/freshness/cost 的真实 20-item benchmark，以及至少一条当前真实、三门全过的
managed 商机。`execution.mode=AUTOMATED_MANAGED` 表示运行无需人工候选；旧字段
`automation_qualified` 继续表示更严格的 official-tier provenance，二者不得混淆。

因此，本轮把“可复用的非 Agent 自动执行骨架”做成可运行版本，同时保留原企划的
商机目标；没有把产品目标收缩为人工需求抓取，也不把工程通过冒充真实商机。

## 1. 版本目标

V0.2.2 的目标不是把人工输入的 OEM 逐个查完，也不是继续扩大“需求抓取器”。
它必须从真实候选中收集当前、可追溯的三类市场证据，并自动收缩为商机：

```text
candidate source
→ eBay US trailing-365-day sales verification
→ Amazon US exact-competition verification
→ US fitment-resolved vehicle-parc verification
→ MARKET_OPPORTUNITY_CANDIDATE
```

目标形态不要求人工逐个搜索或判读，Agent/LLM 也不进入 gate。人工只负责初次服务
授权、Product Research 合规导出（若尚无获准 API）、阈值批准、benchmark gold labels
和最终商业复核。只有三项证据完整通过才能称为
`MARKET_OPPORTUNITY_CANDIDATE`。

产品验收底线：自动运行一个 20-candidate 小池，至少得到一条无需 Agent、三项证据
均为当前且来源绑定的真实 `MARKET_OPPORTUNITY_CANDIDATE`。程序能运行、合成证据
通过或单个 provider canary 通过，都不能替代这条产品验收。Product Research 导出
仍含一次人工获取动作，因此全自动 acquisition 是其后的独立验收项。

## 2. 冻结原则

1. 正常 gate 固定为 eBay 年销量、Amazon 竞争和美国 VIO；可按成本优化采集顺序，
   但最终结论必须同时包含三项独立证据。供货/利润属于后续阶段。
2. Provider 先过授权、用途、凭证、字段、市场、freshness 和成本 gate，再比较
   技术便利性。官方 API 优先，但“官方”不能覆盖缺字段或用途不兼容。
3. SerpApi、eBay Product Research 与 TecAlliance 是当前主服务，Experian 是 VIO
   备选，HioBuy/Nexscope 是兼容 adapter；所有服务都不进入业务模型，也不享有隐式
   信任。来源、覆盖、freshness、成本和字段语义必须由 live probe 证明。
4. 任何 provider failure、凭证缺失或字段歧义都进入 `REVIEW_REQUIRED`；不得转换
   为零结果、拒绝或通过。陈旧数据可保留回放时的 gate 结论，但必须
   `automation_qualified=false`，不得计入当前产品验收。
5. 不实现登录自动化、CAPTCHA/challenge bypass、stealth、指纹规避、代理池或
   自动切换 VPN 地区。官方路径不可用时，只能使用明确获准的 adapter，否则
   `PROVIDER_UNAVAILABLE`。
6. V0.1 的离线 evidence、manual Amazon/1688 evidence 和现有 CLI 保持可用，
   但不能冒充 V0.2.2 严格市场证据或计入自动产品验收。

## 3. 兼容候选源：eBay Motors sold discovery

默认以 eBay Motors `Auto Parts & Accessories` category `6028` 的新品已售结果生成
候选。只有 listing identity、US market、新品状态和明确正整数 sold count 完整时，
才从 title 中提取保守 part-shaped token。Token 只是候选，不是最终需求证据：每个
token 必须重新执行 exact eBay query，未能证明 exact/normalized-exact 的结果进入
`REVIEW_REQUIRED`。

发现请求固定 US、`show_only=Sold`、new condition、`no_cache=true`，默认一页、最多
20 个去重候选。结果使用独立 candidate-discovery schema，并保留 listing URL、ID、
title、position、sold count 和 retrieval time。登录、挑战绕过和代理池仍不在边界内。

## 3A. 兼容候选源：Amazon B2B Not Yet on Amazon

### 3A.1 来源

兼容的 official-tier 候选源是 Amazon Seller Central 的 B2B Selection Recommendations 中
`List products not yet on Amazon` 可下载报告。Amazon 官方说明该列表来自企业
买家的搜索、请求等需求信号，按周更新，并可包含 title、brand、category、MPN、
UPC 和 model number。访问该工具需要具备相应 Seller Central / Professional
selling plan 权限：

- [Amazon B2B Selection Recommendations](https://sell.amazon.com/blog/amazon-business-products)

该路径在具备 Seller 权限时可通过获准的 official report/API adapter 获取最新报告。
人工下载文件只作为开发、回放和 V0.1 兼容输入，不计为自动发现。

### 3A.2 候选生成规则

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

## 4. 历史兼容链路：Amazon → eBay → 1688

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
│   ├── serpapi_ebay_discovery.py
│   ├── serpapi_amazon.py
│   ├── serpapi_ebay.py
│   ├── hiobuy.py
│   └── adapters.py             # provider-neutral wrappers and registry build
├── managed.py                  # discovery + Amazon → eBay → 1688 service
├── credentials.py              # environment override + OS keyring
├── api.py                      # loopback frontend/task API
├── benchmark.py                # future metrics and acceptance report
└── cli.py                      # V0.1 compatibility + setup/api/discovery dispatch
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

V0.2.1 使用轻量 loopback API 和单 worker 内存任务队列，不引入数据库、持久任务
队列或多用户服务。正常漏斗顺序执行，单 provider 并发默认为 1；进程重启会清空
任务记录，后续可在不改变 HTTP contract 的前提下替换持久化实现。

## 7. CLI 设计

既有 V0.1 输入继续可用；V0.2.1 新增自动 discovery、一次性 setup 和 loopback API。
密钥默认从 OS keyring 读取，环境变量作为显式 CI override。以下是历史供货兼容链路，
因此必须显式配置 HioBuy：

```powershell
# 历史两账号兼容路径
proteus setup --with-hiobuy
proteus `
  --discover-ebay-sold `
  --max-candidates 20 `
  --max-moq 10 `
  --output .\managed_run.json
```

如果未配置 HioBuy receiver，自动 profile 在发请求前失败。receiver 只进入 preview
请求，不写入报告；代码不暴露任何 create/pay endpoint。

`providers check` 已实现；它区分本地阻断、live acquisition 状态和 contract validity，
但一次 canary 通过不等于 provider/product acceptance。SP-API 自动报告拉取和独立
`benchmark` 命令仍未实现。Managed run 通过 `execution.mode` 与 official-tier
`automation_qualified` 分开表达。

显式逐阶段选择示例：

```powershell
proteus --amazon-b2b-report .\b2b.csv --managed-providers `
  --amazon-provider serpapi-amazon `
  --ebay-provider serpapi-ebay `
  --supply-provider hiobuy-1688 `
  --max-moq 10 --output .\reports.json
```

## 8. 20-candidate provider benchmark（指标沿用，provider 集合已更新）

### 8.1 样本

从同一 eBay Motors sold-category discovery manifest 中按固定顺序抽取 20 个去重后的
automotive 候选。样本必须覆盖 exact MPN、normalized MPN、明确无结果、
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

严格市场 benchmark 必须分别记录 Product Research 年度窗口、SerpApi Amazon 完整
结果语义和 VIO fitment resolution。若另行启用供货 profile，1688 的 `PASSED` 样本
仍必须拥有同一运行内成功的 order preview，并确认没有任何 create-order 请求。

### 8.3 两层验收

1. **Provider engineering pass**：上述全部指标达线，fixture/replay 和 live
   benchmark 都通过，且没有 failure 被转成零结果或通过。
2. **Strict product pass**：对 20 个候选完成 eBay 365 天销量、Amazon US 精确竞争和
   美国 fitment-resolved VIO 三项采集，并至少输出一个当前、三门全过的真实
   `MARKET_OPPORTUNITY_CANDIDATE`。供货/利润 profile 单独验收。

若 engineering pass 成立但没有真实 opportunity，V0.2 只能报告“provider 可用，
产品假设尚未通过”，不能回退为人工需求抓取并宣称完成。

## 9. 实现阶段

### Phase 0 — Access proof and live acceptance after offline adapters

- 使用已配置的 SerpApi key，修复并验证 discovery/Amazon exact search 的 quota、
  字段、freshness 和失败语义。
- 取得 eBay Product Research 的合规访问和一份脱敏导出样本，验证 365 天窗口、市场、
  timezone 和 sold units 字段。
- 完成 TecAlliance 商业接洽，拿到客户级 API/auth 文档并验证 US coverage、零件适配
  解析和 VIO count。若覆盖不满足要求，再 canary Experian VIO。
- HioBuy、Nexscope 和 Amazon B2B 只在显式兼容 profile 中验证。
- 输出 provider readiness JSON。任一关键 gate 未过，就停止对应 adapter 的业务
  实现，不用未授权 browser 补齐。

### Phase 1 — Contracts, evaluator and frontend boundary（已完成）

- 新增年度销量/VIO capabilities、provider protocol、strict evaluator 和 registry 边界。
- 为阈值边界、市场绑定、证据来源、secret redaction 和缺失证据编写 contract tests。
- 冻结 policy/evaluate HTTP schema，前端不持有 provider secrets。
- 保留 V0.1 schemas、API 和 CLI 回归测试。

### Phase 2 — Candidate discovery and Amazon gate

- 修复 SerpApi eBay discovery，保留搜索只生成候选、不产生年度销量结论的边界。
- 复用 SerpApi Amazon adapter，验证 exact query、US market、完整结果和去重语义。
- 验证 candidate identity、query、source reference 和结果的完整链路。

### Phase 3 — eBay trailing-year sales

- 实现 Product Research 脱敏导出导入器和规范化 annual-sales evidence。
- 拒绝小于 365 天、非 EBAY_US、无法精确绑定零件号或缺失来源的记录。
- 只有未来获得用途获准、同语义 API 时，才用自动 acquisition adapter 替换导入器。

### Phase 4 — US fitment and vehicle parc

- 按客户合同实现 TecAlliance adapter，不在仓库猜测 endpoint/auth。
- 规范化零件到适配车型解析、US country binding、compatible vehicle count 与来源时间。
- 覆盖无适配、歧义 cross-reference、coverage gap、auth、rate-limit 和 schema drift。

### Phase 5 — Benchmark and product run

- 冻结同一份 20-item manifest 和 gold labels。
- 先运行 replay，再运行 live provider benchmark；输出逐项和汇总指标。
- 指标达线后运行严格市场筛选，检查至少一条真实自动商机候选。
- 对通过者再选择性执行供货、到岸成本和利润验证。
- 只有两层验收都通过，才把 V0.2 标记为产品可用。

## 10. 验证清单

- JSON Schema：所有输入、provider outcome、run manifest 和 final report 均验证。
- Unit：normalization、identity、freshness、cost、provider selection、short circuit。
- Contract：Product Research import、SerpApi 和 VIO adapter 运行各自的供应商无关输出测试。
- Replay：固定脱敏 payload 覆盖 success、zero、auth、stale、rate limit、schema drift。
- Safety：secret/address redaction；challenge 不重试；无 login、bypass、order create。
- Integration：V0.1 完整回归；V0.2 synthetic 三门闭环；异常不写 partial output。
- Live canary：每个 provider 先 1 item，再 5 items，最后 20-item benchmark。
- Product：最新证据、严格三门、至少一个自动市场商机候选。

## 11. V0.2 产品目标范围

以下是 V0.2 产品验收的完整边界，不代表当前 engineering preview 已全部实现；
official retrieval/adapters、readiness/cost gate 和 benchmark 仍是开放项。

In scope：

- eBay Motors/search 自动候选源与 Amazon US 精确竞争；
- eBay Product Research 365 天销量规范化证据；
- TecAlliance/可替换 VIO provider 的美国适配车辆保有量；
- provider readiness/freshness/cost gate；
- 严格三门 evaluator、HTTP contracts、replay 和 20-item benchmark；
- 可选供货/经济性验证，以及 V0.1/V0.2.1 兼容链路。

Out of scope：

- Agent/LLM 正常路径、语义自动裁决；
- CAPTCHA、challenge、登录、stealth、指纹或代理池绕过；
- 10,000-item 规模、多用户服务、当前版本的前端页面、持久任务队列、SQLite/云数据库；
- 复杂 ranking、精确利润、物流、关税、退货率和供应商质量评分；
- 自动 cross-reference 合并、供应商联系、创建订单、采购、刊登或交易；
- 未经 contract/canary 审核的其他候选源。

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

下一步不继续横向增加搜索 provider，按三个硬 gate 依次补齐 acquisition：

1. 用已配置的 SerpApi 修复 eBay discovery，并冻结 Amazon US exact-count benchmark；
2. 取得一份授权 Product Research 导出样本并完成 365 天导入器；
3. 完成 TecAlliance onboarding、adapter 和一个真实 fitment/VIO canary；
4. 用户批准 `min_us_vehicle_parc` 后运行同一份 20-item benchmark；
5. 得到至少一个严格 `MARKET_OPPORTUNITY_CANDIDATE` 后，再接可选供货和利润验证。

严格 evaluator 和前端 contract 已实现；只有三类 acquisition 与 benchmark 同时通过，
才进入产品验收。否则明确报告被哪一个 provider/evidence gate 阻塞，不把人工搜索、
需求抓取或合成样例包装成商机。
