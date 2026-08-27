# Proteus V0.2.3

Proteus 是证据优先的汽车零件商机筛选器。V0.2.3 新增了可直接运行的自动 MVP：

```text
SerpApi eBay Motors 已售结果自动发现零件号
→ eBay 精确已售结果数 > 可配置阈值（默认 20）
→ Amazon 美国站精确竞争对手 <= 可配置阈值（默认 5）
→ eBay Product 车型适配
→ NY DMV 活跃注册 + NHTSA VIN 解码的车型估算 >= 本次阈值
→ MVP_OPPORTUNITY_CANDIDATE（必须人工复核）
```

这条链路的目标是自动缩小人工选品范围，不需要 HioBuy，也不需要 Agent 逐项搜索。
第三方采集器由明确的 collector 接口注入，后续可替换 SerpApi、NY DMV/NHTSA 或 MarketCheck 而不改
阈值编排和前端任务接口。

仓库同时保留更严格的市场判定：

```text
eBay 美国站近 365 天销量 > 20
AND Amazon 美国站精确竞争对手 <= 5
AND 适配车型在美国的保有量 >= 本次运行显式阈值
→ MARKET_OPPORTUNITY_CANDIDATE
```

严格链路中，任何证据缺失、市场不匹配、时间窗口不完整或来源不可追溯，都返回
`REVIEW_REQUIRED`，不会把“没查到”当成零销量或低竞争。通过这三门只表示存在市场
商机，尚不证明货源、到岸成本、利润或可下单。

完整边界见 [V0_2_EXECUTION_PLAN.md](V0_2_EXECUTION_PLAN.md)，剩余产品工作见
[TODO.md](TODO.md)。

## 服务组合

| 能力 | 默认服务 | 选择原因 | 当前接入状态 |
| --- | --- | --- | --- |
| 候选发现、eBay 已售粗筛、Amazon US 精确搜索、eBay 车型适配 | [SerpApi](https://serpapi.com/ebay-search-api) | 一枚 Key 覆盖四个自动步骤 | 已接入异步 eBay submit/poll、Amazon 和 eBay Product adapter；真实批量基准仍待完成 |
| 美国车型规模自动代理量 | [NY DMV Socrata](https://data.ny.gov/Transportation/Vehicle-Snowmobile-and-Boat-Registrations/w4pv-hbkt/data) + [NHTSA vPIC](https://vpic.nhtsa.dot.gov/api/) | 两个匿名公共 API；NY DMV 提供年份/品牌注册总量，NHTSA 对有界 VIN 样本解码车型 | 自动 MVP 已接入；是纽约州车型注册估算，不是全国官方 VIO；MarketCheck 仅作可选增强 |
| eBay 近 365 天销量 | [eBay Product Research](https://www.ebay.com/help/selling/selling-tools/product-research?id=4853)（Terapeak）导出/规范化证据 | eBay 官方 Seller Hub 数据覆盖三年，能满足完整 365 天窗口 | 严格证据 API 已预留；导入器和真实样本待接入 |
| 美国适配车辆保有量 | [TecAlliance TecDoc VIO](https://www.tecalliance.net/products?highlight=vio-data&solution=data-insights) | 同时覆盖车辆/适配语义与 VIO，避免再拼一个车型映射服务 | provider-neutral contract 已预留；商业开通和真实 adapter 待完成 |
| VIO 备选 | [Experian Automotive VIO](https://www.experian.com/automotive/vehicles-in-operation-vio-data) | 美国 VIO 数据的替代来源 | 仅列为替换方案 |
| 1688 供货核验 | HioBuy（可选兼容） | 只在后续采购可行性阶段需要 | 不再阻塞市场筛选，也不再是默认配置项 |

自动 MVP 默认只需要 SerpApi 一枚 Key；NY DMV 和 NHTSA 不需要账号。严格 Product
Research/VIO 证据只在真正执行严格筛选时需要。MarketCheck 可选，不再阻塞自动 MVP。
纽约车辆指标仅覆盖 NY，模型数由确定性有限 VIN 样本估算，不声称全国 VIO 或统计置信区间。
TecAlliance 的客户级 endpoint 和认证方式以商业合同为准，仓库不会猜测或硬编码未公开
接口。

## 当前可以做什么

- 保存并脱敏检查 SerpApi 配置；MarketCheck 仍可作为可选增强配置；
- 设置三项阈值后异步启动自动候选发现和粗筛；
- 通过 eBay Product compatibility 自动取得车型适配，再用 NY DMV 活跃注册总量和
  NHTSA VIN 样本估算车型规模；
- 复用现有 SerpApi Amazon/eBay managed adapters 和 provider registry；
- 通过稳定、供应商无关的 schema 接收 eBay 年销量、Amazon 竞争和美国 VIO 证据；
- 确定性执行三项规则并输出每一门的 `PASSED`、`REJECTED` 或
  `REVIEW_REQUIRED`；
- 通过 loopback HTTP API 向未来 React/Vue/桌面前端提供策略、配置、provider 状态和
  严格筛选结果；
- 保留旧的 SerpApi + HioBuy 自动供货验证链路，作为兼容接口而非当前主验收目标。

自动 MVP 的通过结果只能声称“值得人工复核”，不能声称已经严格证明近 365 天销量或
官方美国保有量。严格版本仍缺 eBay Product Research 导入器、TecAlliance 生产
adapter、相应真实凭证和 20-item 产品验收。

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

不要把 Key 写入 Git、JSON 或命令参数。CI 可以用环境变量 `SERPAPI_API_KEY` 覆盖本机
凭证库。NY DMV Socrata 和 NHTSA vPIC 不需要注册或 Key；MarketCheck 可从其
[Get Started](https://docs.marketcheck.com/docs/get-started/api/introduction) 页面申请并作为
可选增强。没有 MarketCheck 时自动任务仍可运行。

只有需要测试旧的 1688 供货兼容链路时，才配置 HioBuy Key 和国内收件信息：

```powershell
.\.venv\Scripts\python.exe -m proteus setup --with-hiobuy
```

这不会创建订单、支付、联系供应商、自动登录、处理 CAPTCHA、切换 VPN 或使用代理池。

## 启动前端

双击 `start-web.bat`，或手动执行：

```powershell
.\.venv\Scripts\python.exe -m proteus api --port 8765
```

操作台位于 `http://127.0.0.1:8765/`，浏览器接口文档位于
`http://127.0.0.1:8765/api/docs`。前端只调用本机接口，任何第三方 provider 凭证都
不会进入浏览器。界面默认跟随浏览器语言，可在右上角切换中英文。

页面的阈值、算子和边界说明由 `/api/v1/mvp/policy` 下发，换 provider 不需要改前端。
以下接口构成这套界面的全部数据来源：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/v1/health` | 版本和当前 profile |
| `GET` | `/api/v1/config/status` | 脱敏配置与各 profile readiness |
| `GET` | `/api/v1/providers` | provider 预检与严格筛选服务策略 |
| `GET` | `/api/v1/mvp/policy` | 自动 MVP 的三项阈值、provider 和代理量边界 |
| `POST` | `/api/v1/mvp/runs` | 设置阈值并异步启动自动选品粗筛 |
| `GET` | `/api/v1/mvp/runs/{run_id}` | 查询自动粗筛状态和候选报告 |
| `GET` | `/api/v1/screening/policy` | 三项阈值、市场和服务选择 |
| `POST` | `/api/v1/screening/evaluate` | 对规范化证据执行严格筛选 |
| `POST` | `/api/v1/runs` | 旧两账号自动供货链路：异步提交 |
| `GET` | `/api/v1/runs/{run_id}` | 旧链路：查询状态和结果 |

自动 MVP 使用示例：

```powershell
$request = @{
  max_candidates = 20
  ebay_category_id = "6028"
  discovery_pages = 1
  min_ebay_trailing_year_units_exclusive = 20
  max_amazon_us_exact_competitors = 5
  min_us_active_vins = 5000
  max_fitment_listings = 3
} | ConvertTo-Json

$job = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8765/api/v1/mvp/runs" `
  -ContentType "application/json" `
  -Body $request

# min_us_active_vins is kept for frontend compatibility; V0.2.3 compares a NY model-registration estimate.

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8765/api/v1/mvp/runs/$($job.run_id)"
```

任务状态依次为 `QUEUED`、`RUNNING`、`COMPLETED` 或 `FAILED`。完成后读取
`result.reports`；只有 `MVP_OPPORTUNITY_CANDIDATE` 进入人工复核。进程重启会清空当前
内存任务记录，前端不应直接持有或调用第三方 Key。

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

自动 MVP 额外通过五个命名 collector 边界注入 discovery、eBay demand、Amazon、
compatibility 和 vehicle proxy。阈值编排只读取规范化结果；替换接口时保持这些结果
字段即可，不需要改 `/api/v1/mvp/runs` 请求。

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
