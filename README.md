# Proteus V0.2.1

Proteus 是证据优先的汽车零件商机发现器。默认 MVP 只需要两个上游账号，并自动执行：

```text
SerpApi eBay 已售类目发现候选
→ SerpApi Amazon 精确搜索验证低竞争
→ SerpApi eBay 精确查询验证已观察销量
→ HioBuy 1688 精确商品、SKU、MOQ 和只读订单预检
→ OPPORTUNITY_CANDIDATE / REJECTED / REVIEW_REQUIRED
```

eBay 只是候选入口；候选仍必须同时通过 Amazon 竞争、eBay 成交、1688 可采购三门，
因此不会退化成单纯需求抓取。正常路径不调用 Agent/LLM，不自动登录，不解 CAPTCHA，
也不切换代理、VPN 或创建/支付订单。

完整执行边界见 [V0_2_EXECUTION_PLAN.md](V0_2_EXECUTION_PLAN.md)。

## 当前已经实现

- 两账号默认 profile：一枚 SerpApi Key 覆盖候选发现、Amazon 和 eBay，一枚
  HioBuy Key 覆盖 1688；
- eBay Motors `Auto Parts & Accessories` 已售类目候选发现，默认 category `6028`；
- 保守零件号抽取：只接受新品、明确正整数 sold count 和 part-shaped title token；
- SerpApi Amazon adapter：固定 `amazon.com`、US 邮编、禁用缓存；存在下一页、字段
  缺失或市场错位时不能证明低竞争；
- SerpApi eBay exact-sold adapter 和 HioBuy
  `search → detail → order preview` adapter；
- Amazon → eBay → 1688 串行短路，上游未通过时不访问下游；
- provider-neutral contract、显式 registry、可注入 transport 和逐阶段 provider 选择；
- `proteus setup`：把两个 Key 和国内收件地址一次性存入 Windows 凭证库；
- loopback HTTP API：配置状态、provider 状态、异步提交与运行结果查询；
- Amazon B2B CSV、Nexscope 和 V0.1 离线输入继续兼容。

当前没有前端页面，但后端接口已经可以由 React/Vue/桌面壳直接调用。

## 尚未完成的真实产品验收

- 本机尚未配置 SerpApi/HioBuy 生产凭证和真实国内 receiver；
- 尚未运行真实 20-item benchmark，因此不能宣称当前已经找到真实商机；
- HioBuy 只适用于确实会把合格 SKU 导向采购的用途，账号用途审批仍需人工完成；
- eBay title token 是候选信号，不直接成为商机证据；每个 token 都会重新经过 exact
  eBay demand gate；
- `automation_qualified` 仍保留“官方来源级验收”的旧严格含义。两账号 profile 的
  `execution.mode=AUTOMATED_MANAGED` 表示执行已自动化，但 managed evidence 不会冒充
  official evidence，因此 report 仍可能为 `automation_qualified=false`。

## 安装

要求 Python 3.12 或更高版本：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,api]"
.\.venv\Scripts\python.exe -m proteus --help
```

只有使用旧的 `--live-ebay` 浏览器兼容路径时才需要本机 Chrome/Edge。Amazon
SP-API 兼容研究依赖可单独安装：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[amazon]"
```

## 第一次配置

先分别申请 [SerpApi](https://serpapi.com/users/sign_up) 和
[HioBuy Developer](https://developers.hiobuy.com) 账号。HioBuy 审核通过后还需要
渠道授权和一个真实的 1688 国内收货地址。

不要把 Key 发到聊天、命令参数、JSON 或 Git。运行一次交互式配置：

```powershell
.\.venv\Scripts\python.exe -m proteus setup
```

Key 和 receiver 会以服务名 `proteus-opportunity-finder` 写入操作系统凭证库。查看
脱敏状态不会显示 Key、手机号或地址：

```powershell
.\.venv\Scripts\python.exe -m proteus setup --status
```

环境变量仍可临时覆盖凭证库，便于 CI；不建议把带 Key 的 PowerShell 命令留在历史中：

```powershell
$env:SERPAPI_API_KEY = "..."
$env:HIOBUY_API_KEY = "..."
```

## 先跑 provider canary

```powershell
New-Item -ItemType Directory -Path .\.private -Force | Out-Null

.\.venv\Scripts\python.exe -m proteus providers check `
  --part-number "53630-53010" `
  --max-moq 10 `
  --output .\.private\provider_canary.json
```

默认检查四个能力，但只读取两个账号：

- `serpapi-ebay-discovery`；
- `serpapi-amazon`；
- `serpapi-ebay`；
- `hiobuy-1688`。

缺 Key 或 receiver 时不会发 live 请求，结果为 `BLOCKED`；`--offline` 只检查本地
readiness。命令存在 blocked/failed 项时返回退出码 `3`，同时仍写出脱敏 JSON。

2026-08-25 本机无凭证实测：`passed=0 / blocked=4 / live_attempted=false`；这确认
当前阻断是账号凭证和 HioBuy receiver，不是日本 IP/VPN。

## 自动选品

配置完成后只需：

```powershell
.\.venv\Scripts\python.exe -m proteus `
  --discover-ebay-sold `
  --max-candidates 20 `
  --max-moq 10 `
  --output .\.private\managed_run.json
```

可选参数：

- `--ebay-category-id 6028`：候选发现类目；
- `--discovery-pages 1`：最多扫描的 sold 结果页，允许 `1..10`；
- `--max-candidates 20`：进入三门漏斗的最大去重候选数；
- `--hiobuy-receiver <json>`：显式本地 receiver 文件，优先于凭证库。

自动入口写出一个 run envelope：

- `profile`：固定为 `two-account-managed`；
- `execution`：自动化模式、账号数和实际 provider IDs；
- `discovery`：类目、页数、候选数和脱敏 diagnostics；
- `reports`：逐候选 V0.2 opportunity reports；
- `summary`：商机、拒绝和待复核计数。

## 前端预留 API

安装 `api` 依赖后启动：

```powershell
.\.venv\Scripts\python.exe -m proteus api --port 8765
```

服务只绑定 `127.0.0.1`，默认没有跨域开放，也没有接收或回显上游 Key 的 HTTP
接口。OpenAPI 文档位于 `http://127.0.0.1:8765/api/docs`。

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/api/v1/health` | 版本与存活状态 |
| `GET` | `/api/v1/config/status` | 两账号和 receiver 的脱敏配置状态 |
| `GET` | `/api/v1/providers` | 四个能力的 provider readiness |
| `POST` | `/api/v1/runs` | 异步提交自动选品任务 |
| `GET` | `/api/v1/runs/{run_id}` | 查询任务状态和完成结果 |

提交示例：

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8765/api/v1/runs `
  -ContentType application/json `
  -Body '{"max_candidates":20,"max_moq":10,"ebay_category_id":"6028","discovery_pages":1}'
```

当前任务记录在单进程内存中，服务重启后不会保留。未来接数据库/队列时只需替换
`FrontendService`/`InMemoryRunManager`，HTTP 路径和业务 provider contract 不需要改。

## 无账号的合成验证

```powershell
.\.venv\Scripts\python.exe -m proteus `
  --candidate-pool .\examples\synthetic_candidates.json `
  --manual-evidence .\examples\synthetic_manual_evidence.json `
  --ebay-evidence .\examples\synthetic_ebay_evidence.json `
  --max-moq 10 `
  --output .\synthetic_reports.json
```

这只证明程序和三门规则可运行，不证明真实商机。旧入口输出有序 report 数组；新的
`--discover-ebay-sold` 自动入口输出包含 `reports` 的 run envelope。

## 兼容入口和接口替换

Amazon B2B CSV、Nexscope 和逐阶段 provider 参数仍可使用。例如：

```powershell
.\.venv\Scripts\python.exe -m proteus `
  --amazon-b2b-report .\b2b_not_yet_on_amazon.csv `
  --managed-providers `
  --amazon-provider serpapi-amazon `
  --ebay-provider serpapi-ebay `
  --supply-provider hiobuy-1688 `
  --max-moq 10 `
  --output .\reports_v0_2.json
```

Provider 可替换接口位于 `proteus.providers.base`、`ProviderRegistry` 和薄 adapter。
业务漏斗只依赖 `FunnelProviders`；将 Amazon 换成 Keepa/DataForSEO 或将任务存储换成
数据库，不需要修改三门 gate。

## 判定边界

- Amazon 只统计 deterministic exact/normalized-exact；存在下一页或解析缺口时为
  `REVIEW_REQUIRED`，不能把不完整页当作低竞争；
- eBay 只接受 exact/normalized-exact、新品、显式正整数 sold count；
- 1688 listing、展示价、库存或 MOQ 不能单独证明可下单；
- 只有绑定同一 offer、SKU、数量的成功 order preview 才能通过供应门；
- provider failure、凭证失败、市场错位、字段缺失和歧义都 fail closed；
- HioBuy 代码只允许商品搜索、详情和订单预检，没有 create/pay 调用路径。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pip check
```

真实产品验收仍需：两个获准生产账号、真实 receiver、20-item benchmark，以及至少
一条三门全过的当前 `OPPORTUNITY_CANDIDATE`。
