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

## 当前交付形态与接口

目前交付的是 **Python 命令行程序**：

- 已有 CLI：`python -m proteus ...`，适合本机执行、定时任务或由其他后端进程调用；
- **没有前端页面**，仓库内没有 React/Vue/桌面 GUI；
- **没有 HTTP/REST API**，也没有任务队列、运行状态查询、用户鉴权或结果数据库；
- 已预留的数据接口是
  [`contracts/v0_2_acquisition.schema.json`](contracts/v0_2_acquisition.schema.json)
  和
  [`contracts/v0_2_opportunity_report.schema.json`](contracts/v0_2_opportunity_report.schema.json)；
- 已预留的代码扩展点是 `proteus.providers` 中的 provider 函数和可注入 transport，
  但这还不是一个稳定的 Web API 或插件协议。

未来前端不应直接携带 Nexscope/HioBuy 密钥或收件地址调用第三方服务。正确边界应是
`前端 → Proteus 后端任务 API → 当前 Python 漏斗 → V0.2 report`；该后端任务 API
尚未实现。

## 安装

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m proteus --help
```

要求 Python 3.12 或更高版本。以上命令会安装项目、测试依赖和 V0.1 浏览器兼容路径
需要的 Playwright Python 包；只有使用 `--live-ebay` 时才需要可用的 Chrome/Edge。

## 一分钟运行：先验证程序

仓库自带一套合成数据，不需要账号、密钥、浏览器或网络：

```powershell
.\.venv\Scripts\python.exe -m proteus `
  --candidate-pool .\examples\synthetic_candidates.json `
  --manual-evidence .\examples\synthetic_manual_evidence.json `
  --ebay-evidence .\examples\synthetic_ebay_evidence.json `
  --max-moq 10 `
  --output .\synthetic_reports.json

Get-Content .\synthetic_reports.json -Raw
```

这条命令应生成一个 JSON 数组，其中示例结果为
`decision=OPPORTUNITY_CANDIDATE`、`automation_qualified=false`。它只证明程序和
三门规则可运行，不证明存在真实商机。

## 使用真实候选报告运行

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

CSV 至少需要：

- 一个候选标识列：`partNumber`/`MPN`、`modelNumber`、`EAN`、`UPC` 或 `ISBN`；
- 一个类目列：`category`、`categoryName` 或 `productCategory`；
- 可选的 `brand`、`itemName`/`productName`/`title` 用于来源追踪。

当前每行按 `partNumber → modelNumber → EAN → UPC → ISBN` 只选一个 primary
identifier；完整的多标识独立查询仍在产品验收待办中。

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

## 输出怎么看

`--output` 始终写入一个有序 JSON report 数组。先看每条 report 的四个位置：

- `candidate`：本次查询的原始与规范化零件号；
- `stages`：Amazon、eBay、1688 三门的状态、证据与原因；
- `decision`：`OPPORTUNITY_CANDIDATE`、`REJECTED` 或 `REVIEW_REQUIRED`；
- `automation_qualified`：是否满足当前、全自动、合规来源和时效要求。

`OPPORTUNITY_CANDIDATE` 表示三门规则通过；`REJECTED` 表示已有充分业务证据否决；
`REVIEW_REQUIRED` 表示来源失败、证据不足、字段歧义或时效不合格。现有 CSV replay、
manual 和 managed-provider 路径即使三门通过，也会保持
`automation_qualified=false`，不能当作产品验收完成。

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
