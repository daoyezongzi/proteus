# Proteus V0.2.2

Proteus 是证据优先的汽车零件商机筛选器。当前主目标不是“抓到需求”，而是对一个
明确零件号执行三项严格市场判定：

```text
eBay 美国站近 365 天销量 > 20
AND Amazon 美国站精确竞争对手 <= 5
AND 适配车型在美国的保有量 >= 本次运行显式阈值
→ MARKET_OPPORTUNITY_CANDIDATE
```

任何证据缺失、市场不匹配、时间窗口不完整或来源不可追溯，都返回
`REVIEW_REQUIRED`，不会把“没查到”当成零销量或低竞争。通过这三门只表示存在市场
商机，尚不证明货源、到岸成本、利润或可下单。

完整边界见 [V0_2_EXECUTION_PLAN.md](V0_2_EXECUTION_PLAN.md)，剩余产品工作见
[TODO.md](TODO.md)。

## 服务组合

| 能力 | 默认服务 | 选择原因 | 当前接入状态 |
| --- | --- | --- | --- |
| 候选发现、Amazon US 精确搜索 | [SerpApi](https://serpapi.com/amazon-search-api) | 一个 Key，现有 adapter 可复用，配置最少 | Amazon adapter 可用；eBay 发现链路仍需修复/基准测试 |
| eBay 近 365 天销量 | [eBay Product Research](https://www.ebay.com/help/selling/selling-tools/product-research?id=4853)（Terapeak）导出/规范化证据 | eBay 官方 Seller Hub 数据覆盖三年，能满足完整 365 天窗口 | 严格证据 API 已预留；导入器和真实样本待接入 |
| 美国适配车辆保有量 | [TecAlliance TecDoc VIO](https://www.tecalliance.net/products?highlight=vio-data&solution=data-insights) | 同时覆盖车辆/适配语义与 VIO，避免再拼一个车型映射服务 | provider-neutral contract 已预留；商业开通和真实 adapter 待完成 |
| VIO 备选 | [Experian Automotive VIO](https://www.experian.com/automotive/vehicles-in-operation-vio-data) | 美国 VIO 数据的替代来源 | 仅列为替换方案 |
| 1688 供货核验 | HioBuy（可选兼容） | 只在后续采购可行性阶段需要 | 不再阻塞市场筛选，也不再是默认配置项 |

这样把默认配置压到一枚 SerpApi Key；另外两项严格证据只在真正执行严格筛选时需要。
TecAlliance 的客户级 endpoint 和认证方式以商业合同为准，仓库不会猜测或硬编码未公开
接口。

## 当前可以做什么

- 保存并检查 SerpApi 配置；
- 复用现有 SerpApi Amazon/eBay managed adapters 和 provider registry；
- 通过稳定、供应商无关的 schema 接收 eBay 年销量、Amazon 竞争和美国 VIO 证据；
- 确定性执行三项规则并输出每一门的 `PASSED`、`REJECTED` 或
  `REVIEW_REQUIRED`；
- 通过 loopback HTTP API 向未来 React/Vue/桌面前端提供策略、配置、provider 状态和
  严格筛选结果；
- 保留旧的 SerpApi + HioBuy 自动供货验证链路，作为兼容接口而非当前主验收目标。

当前还不能声称“输入任意零件号即可全自动得到真实选品结果”：eBay Product Research
导入器、TecAlliance 生产 adapter、真实凭证以及 VIO 充足阈值尚未完成产品验收。

## 安装

要求 Python 3.12 或更高版本：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,api]"
.\.venv\Scripts\python.exe -m proteus --help
```

## 配置

默认只询问 SerpApi Key，并把它存入 Windows 凭证库：

```powershell
.\.venv\Scripts\python.exe -m proteus setup
.\.venv\Scripts\python.exe -m proteus setup --status
```

不要把 Key 写入 Git、JSON 或命令参数。CI 可以用环境变量
`SERPAPI_API_KEY` 覆盖本机凭证库。

只有需要测试旧的 1688 供货兼容链路时，才配置 HioBuy Key 和国内收件信息：

```powershell
.\.venv\Scripts\python.exe -m proteus setup --with-hiobuy
```

这不会创建订单、支付、联系供应商、自动登录、处理 CAPTCHA、切换 VPN 或使用代理池。

## 启动后端接口

```powershell
.\.venv\Scripts\python.exe -m proteus api --host 127.0.0.1 --port 8765
```

浏览器接口文档位于 `http://127.0.0.1:8765/api/docs`。当前没有前端页面，但以下接口
已可直接接前端：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/v1/health` | 版本和当前 profile |
| `GET` | `/api/v1/config/status` | 脱敏配置与各 profile readiness |
| `GET` | `/api/v1/providers` | provider 预检与严格筛选服务策略 |
| `GET` | `/api/v1/screening/policy` | 三项阈值、市场和服务选择 |
| `POST` | `/api/v1/screening/evaluate` | 对规范化证据执行严格筛选 |
| `POST` | `/api/v1/runs` | 旧两账号自动供货链路：异步提交 |
| `GET` | `/api/v1/runs/{run_id}` | 旧链路：查询状态和结果 |

严格筛选请求示例：

```powershell
$body = @{
  part_number = "53630-53010"
  min_us_vehicle_parc = 100000
  ebay_annual_sales = @{
    provider_id = "ebay-product-research-import"
    source_reference = "seller-hub-export:row-18"
    retrieved_at = "2026-08-27T08:00:00Z"
    marketplace_id = "EBAY_US"
    window_days = 365
    units_sold = 27
  }
  amazon_competition = @{
    provider_id = "serpapi-amazon"
    source_reference = "serpapi-search:example"
    retrieved_at = "2026-08-27T08:02:00Z"
    marketplace_id = "AMAZON_US"
    exact_competitor_count = 4
  }
  vehicle_parc = @{
    provider_id = "tecalliance-vio"
    source_reference = "vio-query:example"
    retrieved_at = "2026-08-27T08:05:00Z"
    country_code = "US"
    fitment_resolved = $true
    compatible_vehicle_count = 180000
  }
} | ConvertTo-Json -Depth 6

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8765/api/v1/screening/evaluate" `
  -ContentType "application/json" `
  -Body $body
```

`min_us_vehicle_parc` 必须由业务方显式给出。仓库不擅自把“保有量充足”定义成一个
看似精确但未经验证的默认数值。

## Provider 替换边界

业务规则只依赖 `Capability` 和规范化请求/证据，不直接依赖 SerpApi、TecAlliance 或
HioBuy。新 adapter 应实现 `preflight / acquire / estimate_cost`，然后在 registry 中按
能力注册。前端只调用 Proteus API，不能持有第三方凭证或直接调用第三方服务。

当前新能力包括：

- `EBAY_ANNUAL_SALES` + `AnnualSalesLookupRequest`；
- `US_VEHICLE_PARC` + `VehicleParcLookupRequest`。

因此后续可把 Product Research 导入替换为获准的年度销量 API，把 TecAlliance 替换为
Experian，而无需修改前端请求或三门决策规则。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pip check
git diff --check
```
