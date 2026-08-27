# Proteus V0.2.4

Proteus 是按可售产品家族筛选低竞争汽车零件的本地操作台。当前 V0.2.4 MVP 以
northwayautoparts 的车型专用小饰件和机械拉索为产品形态参考，只需要 SerpApi：

```text
一次扫描全部 9 个车型专用小零件 archetype
→ 在每类显式 eBay 页范围内发现全部候选
→ 先拒绝 Universal-fit、化学品和错误产品形态
→ 解析车型、年份、左右侧、套装数量和零件号为 sellable_product_family
→ 生成 OEM + 车型描述 Amazon query pack
→ 分开统计平替产品种类、ASIN、seller offers 和平替最低价
→ 按通过项、证据缺口和家族竞争排序
→ MARKET_SHORTLIST_CANDIDATE + 完整 JSON 人工复核
```

本版是初筛器，不是自动采购决策器。国内非原厂供货、利润和最终适配作为候选卡上的
人工检查项，不要求第二套凭证，也不会把缺少供货凭证误判成无货。V0.2.3 精确 OEM
链路继续保留为兼容 API，但不再是默认页面或当前产品验收标准。

## V0.2.4 当前可以做什么

- 一次运行自动扫描全部九个 Northway 风格小类，无需先选择零件类型；
- 不使用 `max_candidates` 截断，处理已扫描页面中发现的全部候选；
- 将左右件、单件/套装、车型和年份解析为不同产品家族；
- 使用多个 Amazon 查询统计平替产品种类、ASIN、报价和最低价；
- 默认展示可复核候选，按“优先候选 / 待判断 / 已淘汰”分类切换；
- 下载包含规则读数、来源、查询、证据缺口、失败原因和排序的完整 JSON。

当前真实一页雾灯框探针检查了 60 条结果，生成 14 个候选；在总请求预算为 5、每家族
仅执行一个 Amazon 查询的保守探针下，3 个进入市场 shortlist、3 个待复核、8 个明确
淘汰。该探针证明链路可运行，不代表这些候选已完成供货和利润复核。

## V0.2.3 兼容链路

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
| 美国车型规模实验代理量 | [NY DMV Socrata](https://data.ny.gov/Transportation/Vehicle-Snowmobile-and-Boat-Registrations/w4pv-hbkt/data) + [NHTSA vPIC](https://vpic.nhtsa.dot.gov/api/) | 两个匿名公共 API；仅能形成纽约州车型估算 | adapter 保留供研究，不再是自动 MVP 的筛选门，也不替代严格 VIO |
| eBay 近 365 天销量 | [eBay Product Research](https://www.ebay.com/help/selling/selling-tools/product-research?id=4853)（Terapeak）导出/规范化证据 | eBay 官方 Seller Hub 数据覆盖三年，能满足完整 365 天窗口 | 严格证据 API 已预留；导入器和真实样本待接入 |
| 美国适配车辆保有量 | [TecAlliance TecDoc VIO](https://www.tecalliance.net/products?highlight=vio-data&solution=data-insights) | 同时覆盖车辆/适配语义与 VIO，避免再拼一个车型映射服务 | provider-neutral contract 已预留；商业开通和真实 adapter 待完成 |
| VIO 备选 | [Experian Automotive VIO](https://www.experian.com/automotive/vehicles-in-operation-vio-data) | 美国 VIO 数据的替代来源 | 仅列为替换方案 |
| 1688 供货核验 | HioBuy（可选兼容） | 只在后续采购可行性阶段需要 | 不再阻塞市场筛选，也不再是默认配置项 |

自动 MVP 默认只需要 SerpApi 一枚 Key。严格 Product Research/VIO 证据只在真正执行
严格筛选时需要。MarketCheck 可选，不再阻塞自动 MVP；NY DMV/NHTSA 实验 adapter 也不
参与 automatic MVP 判定。
TecAlliance 的客户级 endpoint 和认证方式以商业合同为准，仓库不会猜测或硬编码未公开
接口。

## V0.2.3 兼容能力

- 保存并脱敏检查 SerpApi 配置；MarketCheck 仍可作为可选增强配置；
- 设置可编辑发现关键词与五层筛选参数后异步启动自动候选发现和粗筛；
- 通过 eBay Product compatibility 自动确认至少一个精确已售 listing 暴露车型适配；
- 复用现有 SerpApi Amazon/eBay managed adapters 和 provider registry；
- 通过稳定、供应商无关的 schema 接收 eBay 年销量、Amazon 竞争和美国 VIO 证据；
- 确定性执行五道筛选并输出每一门的 `PASSED`、`REJECTED` 或
  `REVIEW_REQUIRED`；
- 通过 loopback HTTP API 向未来 React/Vue/桌面前端提供策略、配置、provider 状态和
  严格筛选结果；
- 保留旧的 SerpApi + HioBuy 自动供货验证链路，作为兼容接口而非当前主验收目标。

自动 MVP 的通过结果只能声称“值得人工复核”，不能声称已经严格证明近 365 天销量，
也没有评估官方美国保有量。严格版本仍缺 eBay Product Research 导入器、TecAlliance 生产
adapter、相应真实凭证和 20-item 产品验收。

## 安装

要求 Python 3.12 或更高版本：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,api]"
.\.venv\Scripts\python.exe -m proteus --help
```

## 最短使用流程

1. 运行 `.\.venv\Scripts\python.exe -m proteus setup`，按提示保存 SerpApi Key。
2. 双击 `start-web.bat`；也可运行
   `.\.venv\Scripts\python.exe -m proteus api --port 8765`。
3. 打开 `http://127.0.0.1:8765/`，保留默认参数，点击“开始选品扫描”。
4. 一次运行会自动扫描全部九类零件。右侧默认隐藏明确淘汰项，可通过状态分类切换查看。
5. 下载完整 JSON 做最终复核；JSON 始终包含全部候选、规则读数、来源、缺口、失败原因和排名。

`eBay 扫描页数`按每个零件类型计算。例如 1 页会产生至少 9 次发现请求，2 页至少
18 次。因此总请求预算不得低于 `9 × 扫描页数`；默认预算 80 会把剩余请求用于 Amazon
产品家族搜索。扫描范围内的候选不设数量上限，但页面数和总请求预算仍控制成本。

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
不会进入浏览器。当前操作台是中文优先的 Northway 初筛界面。

页面的九类范围、阈值和边界由 `/api/v1/northway/policy` 下发。
以下接口构成这套界面的全部数据来源：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/v1/health` | 版本和当前 profile |
| `GET` | `/api/v1/config/status` | 脱敏配置与各 profile readiness |
| `GET` | `/api/v1/providers` | provider 预检与严格筛选服务策略 |
| `GET` | `/api/v1/northway/policy` | Northway 小类、默认阈值和运行边界 |
| `POST` | `/api/v1/northway/runs` | 异步启动产品家族初筛 |
| `GET` | `/api/v1/northway/runs/{run_id}` | 查询任务状态、候选和排序 |
| `GET` | `/api/v1/northway/runs/{run_id}/export` | 下载完整 V0.2.4 JSON |
| `GET/POST` | `/api/v1/mvp/*` | V0.2.3 精确 OEM 兼容链路 |
| `GET` | `/api/v1/screening/policy` | 三项阈值、市场和服务选择 |
| `POST` | `/api/v1/screening/evaluate` | 对规范化证据执行严格筛选 |
| `POST` | `/api/v1/runs` | 旧两账号自动供货链路：异步提交 |
| `GET` | `/api/v1/runs/{run_id}` | 旧链路：查询状态和结果 |

Northway MVP 使用示例：

```powershell
$request = @{
  discovery_pages = 1
  request_budget = 80
  max_amazon_queries_per_family = 3
  max_competitive_products = 3
  min_family_price_usd = 20
  min_observed_ebay_demand = 1
} | ConvertTo-Json

$job = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8765/api/v1/northway/runs" `
  -ContentType "application/json" `
  -Body $request

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8765/api/v1/northway/runs/$($job.run_id)"
```

任务状态依次为 `QUEUED`、`RUNNING`、`COMPLETED` 或 `FAILED`。完成后读取
`result.reports`；`MARKET_SHORTLIST_CANDIDATE` 表示值得优先人工复核，不表示可以直接
采购或上架。`result.discovery.per_archetype` 保存九类各自的采集状态，
`result.scan_manifest.discovery_queries` 保存实际查询；这些字段也是后续前端改造的稳定
接口。进程重启会清空当前内存任务记录，前端不持有或调用第三方 Key。

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

自动 MVP 额外通过四个命名 collector 边界注入 discovery、eBay demand、Amazon 和
compatibility。阈值编排只读取规范化结果；替换接口时保持这些结果
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
