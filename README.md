# Proteus V0.2

Proteus 是证据优先的汽车零件商机发现器。V0.2 不再要求人工先选出 OEM/MPN：
它可从 Amazon B2B Product Opportunities 报告中确定性生成候选，再按固定顺序
执行：

```text
Amazon 低竞争 → eBay 已观察销量 → 1688 精确供应 + 只读下单预检
```

只有三门都通过才输出 `OPPORTUNITY_CANDIDATE`。正常运行路径不调用 Agent、LLM，
也不做 CAPTCHA、登录、代理池、VPN 切换或反爬绕过。完整执行边界见
[V0_2_EXECUTION_PLAN.md](V0_2_EXECUTION_PLAN.md)。

## 当前实现边界

已实现：

- Amazon B2B CSV 的候选发现、标识符优先级、规范化、去重和行级来源追踪；
- Amazon → eBay → 1688 串行短路；上游不通过时不调用下游；
- Nexscope Amazon/eBay/1688 托管 REST adapters，失败保持显式状态；
- HioBuy 1688 `search → detail → order preview` 只读验证；代码没有 create/pay 路径；
- V0.2 schemas、`automation_qualified` 与 V0.1 JSON 输入兼容。

尚未完成产品验收：

- 当前 `--amazon-b2b-report` 是已下载报告的自动解析，不是 SP-API 自动拉取；
- 当前 parser 每行只选择一个 primary identifier；保留 MPN/model/UPC 并按冻结优先级
  分别查询，仍属于产品验收前的开放项；
- 本机没有 Amazon、Nexscope、HioBuy 的获准生产凭证和真实 20-item benchmark；
- Nexscope 的实时覆盖、数据来源、freshness 和价格尚未通过本项目的 provider gate；
- 因此当前托管/回放报告会明确输出 `automation_qualified: false`，不得宣称已找到
  真实、全自动、产品验收合格的商机。

## 安装

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## V0.2 商机发现运行

将密钥放入环境变量，不要写进参数、JSON、日志或 Git：

```powershell
$env:NEXSCOPE_API_KEY = "..."
$env:HIOBUY_API_KEY = "..."
```

准备 Amazon B2B `Not Yet on Amazon` CSV 和一个仅保存在本机的 1688 国内收货地址
JSON，然后运行最多 20 个候选：

```powershell
.\.venv\Scripts\python.exe -m proteus `
  --amazon-b2b-report .\b2b_not_yet_on_amazon.csv `
  --nexscope `
  --hiobuy-receiver .\private\hiobuy_receiver.json `
  --max-candidates 20 `
  --max-moq 10 `
  --output .\reports_v0_2.json
```

报告输入默认只接收 `category=Automotive`；若 Seller Central 导出的 US 类目名称
不同，可重复传入 `--amazon-category "实际类目名"`，匹配规则为不区分大小写的
精确匹配，不能用模糊语义自动扩类。

receiver 文件需包含 `name`、`mobile`、`province`、`city`、`district` 和
`address`。仓库已忽略根目录的 `private/` 与 `.private/`；地址只进入 HioBuy
preview 请求，不会写进报告或 diagnostics，也不应放在其他可提交路径。

不提供 `--hiobuy-receiver` 时，Nexscope 1688 搜索仍会保存供应线索，但
listing 不能证明可下单，供应门必然保持 `REVIEW_REQUIRED`。HioBuy 文档明确把
[商品搜索](https://hiobuy.com/en/api-docs/product-search)、
[商品详情](https://hiobuy.com/en/api-docs/product-detail)和
[订单预检](https://hiobuy.com/en/api-docs/order-preview)分成三个接口；Proteus 只
使用这三步，不会调用创建或支付订单。

## V0.1 兼容运行

既有候选池、Amazon/1688 人工 evidence 和 eBay acquisition bundle 仍可直接输入，
但输出统一升级为 V0.2，并标记 `automation_qualified: false`：

```powershell
.\.venv\Scripts\python.exe -m proteus `
  --candidate-pool .\examples\synthetic_candidates.json `
  --manual-evidence .\examples\synthetic_manual_evidence.json `
  --ebay-evidence .\examples\synthetic_ebay_evidence.json `
  --max-moq 10 `
  --output .\synthetic_reports.json
```

这些 examples 全部是合成工程数据，只能验证程序与规则，不能证明真实商机。

## 判定边界

- Amazon 只统计确定性 exact/normalized-exact 结果；不完整 API 页不能证明低竞争；
- eBay 只接受 exact/normalized-exact、新品、显式正整数 sold evidence；
- 1688 listing、展示价格、库存或 MOQ 都不能单独证明 `purchasable=true`；
- 只有绑定同一 offer、SKU、数量的成功 order preview 才能通过供应门；
- 全自动资格还要求候选报告不超过 8 天、阶段证据不超过 24 小时、订单预检不超过
  15 分钟；陈旧数据可以留作回放，但不能继续标记为自动化商机；
- provider failure、凭证失败、市场错位、字段缺失和歧义都进入
  `REVIEW_REQUIRED`，不会伪装成零结果或通过。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest
```

产品验收仍要求：最新 US Amazon B2B 候选源、获准 provider、真实 20-item 运行，
以及至少一条无需人工 evidence、三门全过且 `automation_qualified=true` 的当前商机。
