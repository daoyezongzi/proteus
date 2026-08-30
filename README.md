# Proteus V0.2.7

> 当前执行版本提供两个并列入口：**分类/eBay 正向初筛**与**固定 1688 供应商反向选品**。
> 两者共用 ACTIVE 分类版本和 Amazon A / A- 竞争语义，但候选来源、读取边界和结果快照互不混淆。

Proteus 是按可售产品家族筛选低竞争汽车零件的本地操作台。当前 Northway MVP 以
northwayautoparts 的车型专用小饰件和机械拉索为产品形态参考。公开入口从本机 SQLite
分类目录选择一个一级分组和一个已启用的叶子零件类型；1688 供应商检查作为 Amazon
前置过滤，以节省 SerpApi 配额：

```text
选择一级类别 → 一个已启用的叶子小类
→ 在该类型的显式 eBay 页范围内发现全部候选
→ 先拒绝 Universal-fit、化学品和错误产品形态
→ 解析车型、年份、左右侧、套装数量和零件号为 sellable_product_family
→ 默认用 1688 轻量查询确认匹配商品存在供应商
→ 只把有供应商的产品族送入 Amazon 核验
→ 生成 OEM + 车型描述 Amazon query pack
→ 分开统计平替产品种类、ASIN、seller offers 和平替最低价
→ 完整竞争证据：0–5 个平替为 A、6–8 个为 A-、9 个以上淘汰
→ 不完整证据：不足 9 个保持 PENDING，已观察到 9 个以上才可安全淘汰
→ 按竞争等级、通过项、证据缺口和家族竞争排序
→ 供应商和市场证据都满足的候选 + 完整 JSON 人工复核
```

本版是初筛器，不是自动采购决策器。1688 的通过条件是“存在匹配 offer 和明确供应商”，
不等于库存、MOQ、利润或可下单；供应商阶段失败、风控和未查询会分别保留为可解释状态。
V0.2.3 精确 OEM 链路和 HioBuy 1688 兼容路径继续保留，但不再是默认页面。

## V0.2.7 Edge 续采修复

如果 1688 店铺标签页早于扩展安装或“重新加载”就已打开，首次点击采集按钮会自动刷新
该店铺页，再由内容脚本续接已经认领的任务；不再显示底层的 `Receiving end does not exist`
错误。扩展本地会话因重载而丢失时，同一店铺的未过期 `CAPTURING` 任务也可以安全重接管，
无需把失败误当作空店或丢弃已传回的页面。该修复没有新增扩展权限。

## V0.2.6 供应商反向选品

导航栏中的“供应商反向选品”固定一家本机保存的 1688 店铺，以有边界的店铺快照替代
eBay 发现作为候选来源：

```text
保存一个规范化 1688 店铺 URL
→ 创建一个短期、绑定该店铺域名的 Edge 采集任务
→ 用户在普通 Edge 的已登录店铺页点击项目扩展
→ 扩展在显式页数/商品数上限内自动滚动、翻页并读取可见 offer
→ 每个 offer 回绑同一 supplier identity，并将快照写入独立 SQLite
→ 用本次提交时的 ACTIVE 叶子版本匹配商品标题
→ 未匹配 / 分类冲突 / 料号或车型不足的商品原样保留，不消耗市场请求
→ 对身份足够明确的产品先查精确 eBay 需求，再聚合 Amazon 产品家族竞争
→ 完整证据 0–5 为 A、6–8 为 A-、9+ 淘汰；不完整低下界保持 PENDING
→ 导出全部已观察商品及其去向
```

店铺读取和市场判断是两条独立证据轴。触及页数/商品数上限会得到 `PARTIAL`；登录跳转、
滑块、超时和解析失败分别得到 `AUTH_REQUIRED`、`RISK_CONTROL`、`TIMEOUT`、
`PARSER_FAILED`，都不会被解释成空店。只有页面明确报告 0 件、没有下一页且完整度成立时，
才会输出 `EMPTY`。未观察到的店铺商品不参与淘汰。

本功能使用独立的 `%LOCALAPPDATA%\Proteus\supplier_scout.sqlite3` 保存供应商来源、只读
检查审计与不可变店铺快照，不迁移分类数据库。反向入口的主采集路径是项目内的 Manifest V3
Edge 扩展 `browser-extension/supplier-collector`：它只在用户点击后读取普通 Edge 当前页已经渲染的
商品字段，并把规范化页面证据发送给 `127.0.0.1:8765`。扩展不读取 Cookie；遇到登录、滑块或
未知分页会暂停并保留当前证据，用户处理完成后再次点击即可继续。Proteus 不识别、拖动或绕过
CAPTCHA，也不进行询价、消息、收藏、购物车、结算或下单。A / A- 只表示 Amazon 平替产品族
竞争数量，不是供应商评分或采购建议。

## V0.2.5 当前可以做什么

- 用“拉线 / 塑料件 / 低责任金属件”一级下拉框和动态二级下拉框选择一个末级类型；
- 从本机 SQLite 读取 ACTIVE 分类版本，并在提交时把版本快照冻结到该次运行；
- 通过 Agent 友好的 JSON + CLI 创建 DRAFT、离线验证、显式启用或归档分类；
- 不使用 `max_candidates` 截断，处理已扫描页面中发现的全部候选；
- 将左右件、单件/套装、车型和年份解析为不同产品家族；
- 默认在 Amazon 前先用本地 `1688-cli` 或兼容 HioBuy 做供应商存在性预筛；风控时可按次关闭，继续做 Amazon 市场复核；
- 使用多个 Amazon 查询统计平替产品种类、ASIN、报价和最低价，按可配置的 A / A- 上限分级；
- 默认展示已有完整证据的 A / A- 产品；Amazon 不完整结果单独列为竞争待定；
- 展示 eBay、1688、Amazon 各阶段的当前进度和独立预算；
- 下载包含规则读数、来源、查询、证据缺口、失败原因和排序的完整 JSON。

最近一次本机受控运行（2026-08-28，单分类 `hood_latch_release_cable`）检查了 60 条 eBay
结果，生成 13 个候选；1688 检查 13 个，其中 2 个有供应商、10 个待复核、1 个明确无供应商。
只有通过供应商阶段的候选进入 Amazon，SerpApi 实际使用 5/20 次；最终为 0 个市场 shortlist、
12 个待复核、1 个淘汰。该运行验证的是配额优先顺序和失败状态保留，不代表候选已经完成市场、供货
或利润验收。具体证据和运行 ID 见 `LOG.md`。

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
| 1688 供应商预筛 / 固定店铺快照 | 正向入口：本地 `1688-cli`；反向入口：项目内 Edge 扩展 | 正向入口确认供应商存在；反向入口从一家店的有界货盘产生候选 | 扩展只读普通 Edge 已渲染页面并回传 loopback；不自动处理 CAPTCHA，不做消息、购物或下单 |

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
3. 打开 `http://127.0.0.1:8765/`。使用“产品族初筛”走原有正向漏斗，或从导航进入
   `supplier-scout.html` 使用固定供应商反向入口。
4. 选择一个末级零件类型；系统先做本地范围/家族过滤，再进行 1688 供应商预筛和 Amazon 核验。
   如果 1688 暂时风控，可取消“1688 供应商前置筛选”；本次不访问 1688，但候选最终只能是待复核。
5. 右侧默认显示有供应商且市场证据完整的候选，其他状态可通过筛选查看。
6. 下载精简或完整 JSON 做最终复核；JSON 始终包含全部候选、规则读数、来源、缺口、失败原因和排名。

供应商反向入口先保存店铺名称与商品列表 URL，再设置店铺页数、商品观察上限和市场请求预算。
首次使用按页面提示从 `edge://extensions` 加载项目内扩展；“复制路径”会给出当前项目中可直接
粘贴到文件选择器的绝对目录。之后点击“创建 Edge 采集任务”，在打开的已登录店铺页点击工具栏
扩展即可。采集完成后页面自动启用“使用快照筛选”。若状态为
`PARTIAL`，只能筛选已经观察到的商品；若状态为 `RISK_CONTROL` 或 `AUTH_REQUIRED`，用户完成
对应页面操作后再次点击扩展继续，失败或阻断不会被当成空店。若店铺标签页是在加载或重载扩展
之前打开，首次点击会自动刷新一次并继续，不需要手动重建任务。

`eBay 扫描页数`只按当前选择的零件类型计算。因此总 SerpApi 请求预算最低为
`1 × 扫描页数`；1688 检查使用独立的 `max_1688_checks`，不会占用 SerpApi 预算。
扫描范围内的候选不设数量上限，但页面数、两个 provider 的边界和运行预算仍控制成本。

查询状态和导出精简 JSON：

```powershell
$runId = $job.run_id
do {
  Start-Sleep -Seconds 2
  $state = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8765/api/v1/northway/runs/$runId"
  $state.status
} while ($state.status -in @("QUEUED", "RUNNING"))

Invoke-WebRequest `
  -Uri "http://127.0.0.1:8765/api/v1/northway/runs/$runId/export/compact" `
  -OutFile ".\northway-$runId.compact.json"
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

如果使用旧的 HioBuy 供货兼容链路，才配置 HioBuy Key 和国内收件信息：

```powershell
.\.venv\Scripts\python.exe -m proteus setup --with-hiobuy
```

这不会创建订单、支付、联系供应商、自动登录、处理 CAPTCHA、切换 VPN 或使用代理池。

如果使用首选的本地 1688 CLI，需要单独安装并登录一次（Node 20+）：

```powershell
npm i -g 1688-cli@0.1.47
1688 doctor --no-launch
1688 login
```

`1688-cli` 是 Node CLI，不安装进 Proteus 的 Python `.venv`；Proteus 通过系统 `PATH`
调用 `1688`，而 Python `.venv` 继续只负责后端服务和依赖隔离。

Northway 正向入口只调用 `search --max`，必要时读取一个 `offer` 详情。供应商反向入口不依赖
CLI 的隐藏浏览器 profile，而是由用户在普通 Edge 中加载项目扩展一次：打开 `edge://extensions`，
开启“开发人员模式”，选择“加载解压缩的扩展”，再选中 `browser-extension/supplier-collector`。
以后 Agent 更新扩展文件时只需在同一页面点“重新加载”。旧的版本锁定只读 bridge 仅保留为
兼容 API；更新后的首次采集若发现店铺页仍运行旧内容脚本，会自动刷新当前店铺页并重接管
未过期任务。bridge 版本或内部布局变化时会 fail closed；当前页面不会调用它。本项目不会调用询价、
消息、收藏、购物车、结算或下单命令。

如果启动时提示 Windows `10048` 或“端口 8765 已被占用”，先查看占用进程：

```powershell
Get-NetTCPConnection -LocalPort 8765 -State Listen |
  Select-Object LocalAddress, LocalPort, OwningProcess
Get-Process -Id <PID>
```

确认是旧的 Proteus 实例后再关闭它，或改用未占用端口手动启动：

```powershell
Stop-Process -Id <PID>
.\.venv\Scripts\python.exe -m proteus api --port 8766
```

然后打开 `http://127.0.0.1:8766/`。关闭 `start-web.bat` 窗口会停止由该窗口启动的服务。

## 启动前端

双击 `start-web.bat`，或手动执行：

```powershell
.\.venv\Scripts\python.exe -m proteus api --port 8765
```

操作台位于 `http://127.0.0.1:8765/`，浏览器接口文档位于
`http://127.0.0.1:8765/api/docs`。前端只调用本机接口，任何第三方 provider 凭证都
不会进入浏览器。当前操作台是中文优先的 Northway 初筛界面。

页面的 ACTIVE 分类分组、叶子版本、价格/需求阈值、A/A- 分级、1688 供应商条件和运行边界
由 `/api/v1/northway/policy` 下发。默认 A 级上限为 5，A- 级上限为 8；两者均可按次调整，
但 A- 上限必须严格大于 A 级上限。
以下接口构成这套界面的全部数据来源：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/v1/health` | 版本和当前 profile |
| `GET` | `/api/v1/config/status` | 脱敏配置与各 profile readiness |
| `GET` | `/api/v1/providers` | provider 预检与严格筛选服务策略 |
| `GET` | `/api/v1/northway/policy` | 两级 ACTIVE 分类、版本、默认阈值和运行边界 |
| `POST` | `/api/v1/northway/runs` | 异步启动单分类产品家族初筛 |
| `GET` | `/api/v1/northway/runs/{run_id}` | 查询任务状态、候选和排序 |
| `GET` | `/api/v1/northway/runs/{run_id}/export/compact` | 下载精简 JSON（默认） |
| `GET` | `/api/v1/northway/runs/{run_id}/export` | 下载完整证据 JSON |
| `GET` | `/api/v1/supplier-scout/policy` | 供应商反向入口的 ACTIVE 分类、阈值和双重预算边界 |
| `GET/POST` | `/api/v1/supplier-scout/suppliers` | 列出或保存本机供应商来源 |
| `GET` | `/api/v1/supplier-scout/collector/profile` | 下发版本化、非可执行的 1688 DOM 选择器和滚动边界 |
| `POST` | `/api/v1/supplier-scout/captures` | 为一家已保存店铺创建短期有界 Edge 采集任务 |
| `GET` | `/api/v1/supplier-scout/captures/pending` | 让扩展按当前店铺域名发现待领取任务 |
| `GET` | `/api/v1/supplier-scout/captures/{capture_id}` | 查询采集页数、商品数、暂停原因和快照 ID |
| `POST` | `/api/v1/supplier-scout/captures/{capture_id}/claim`<br>`/api/v1/supplier-scout/captures/{capture_id}/pages`<br>`/api/v1/supplier-scout/captures/{capture_id}/pause` | 扩展用短期令牌领取、提交页面或暂停任务 |
| `GET` | `/api/v1/supplier-scout/suppliers/{supplier_id}/snapshots/latest` | 查询该供应商最近的不可变快照摘要 |
| `POST` | `/api/v1/supplier-scout/suppliers/inspect` | 旧只读 bridge 兼容入口；不把阻断当空店 |
| `POST` | `/api/v1/supplier-scout/runs` | 绑定已封存快照，异步执行供应商反向筛选 |
| `GET` | `/api/v1/supplier-scout/runs/{run_id}` | 查询进度与全部已观察商品去向 |
| `GET` | `/api/v1/supplier-scout/runs/{run_id}/export/compact` | 下载供应商反向精简 JSON |
| `GET` | `/api/v1/supplier-scout/runs/{run_id}/export` | 下载供应商反向完整证据 JSON |
| `GET/POST` | `/api/v1/mvp/*` | V0.2.3 精确 OEM 兼容链路 |
| `GET` | `/api/v1/screening/policy` | 三项阈值、市场和服务选择 |
| `POST` | `/api/v1/screening/evaluate` | 对规范化证据执行严格筛选 |
| `POST` | `/api/v1/runs` | 旧两账号自动供货链路：异步提交 |
| `GET` | `/api/v1/runs/{run_id}` | 旧链路：查询状态和结果 |

Northway MVP 使用示例：

```powershell
$request = @{
  archetype = "fog_light_bezel"
  discovery_pages = 1
  request_budget = 20
  max_amazon_queries_per_family = 3
  grade_a_max_competitors = 5
  grade_a_minus_max_competitors = 8
  max_1688_checks = 20
  enable_1688_prefilter = $true
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

任务状态依次为 `QUEUED`、`RUNNING`、`COMPLETED` 或 `FAILED`。运行中还会返回
`phase`、`current`、`total`、`last_query`、`provider`、`budget_used` 和 `updated_at`。
完成后读取 `result.reports`。`competition_grade` 是 `A`、`A-`、`PENDING`、`REJECTED`
或 `NOT_RUN`；它只表示 Amazon 产品家族竞争等级，不表示可以直接采购或上架。
`result.discovery` 保存所选类型状态，`result.scan_manifest` 保存实际查询和分类版本；1688
供应商证据和独立计数也会保留。精简导出保留决策、产品家族、关键读数、
分页/预算状态、供应商摘要、相关 ASIN 和有限关系样本；需要完整 provider 证据时使用
`/export`。进程重启会清空当前内存任务记录，前端不持有或调用第三方 Key。

`enable_1688_prefilter` 默认为 `$true`。设为 `$false` 或在页面取消勾选时，本次运行不会
调用 1688，也不会执行本地登录态检查；满足本地范围、家族和需求条件的候选仍可进入 Amazon。
对应记录的 1688 阶段为 `NOT_RUN`，证据缺口包含 `1688_PREFILTER_DISABLED`，最终决策不会
成为供应商通过或自动商机，只能人工复核。

真实运行中的 eBay/Amazon provider 请求会计入 SerpApi 配额；`request_budget` 是单次运行
的硬上限，不能把新鲜 Amazon 数据变成零调用。若只需要检查页面或复用已有结果，可运行
`python web/_dev_server.py` 的本地回放 harness，它使用 stub 数据、不访问 provider，但不代表
实时市场结果。后续如需正式复用历史结果，应增加带时间戳和明确 `REPLAY` 标记的本地缓存，
不能把过期数据伪装成新鲜扫描。

供应商反向 API 的最小示例：

```powershell
$supplier = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8765/api/v1/supplier-scout/suppliers" `
  -ContentType "application/json" `
  -Body (@{
    label = "示例供应商"
    target = "https://shop3w093345o1043.1688.com/page/offerlist.htm"
  } | ConvertTo-Json)

$capture = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8765/api/v1/supplier-scout/captures" `
  -ContentType "application/json" `
  -Body (@{
    supplier_id = $supplier.supplier_id
    max_pages = 3
    max_offers = 100
  } | ConvertTo-Json)

# 在该供应商的普通 Edge 店铺页点击项目扩展；等页面显示完成或已有可用的部分快照后继续。
$captureState = Invoke-RestMethod `
  -Uri "http://127.0.0.1:8765/api/v1/supplier-scout/captures/$($capture.capture_id)"
if (-not $captureState.snapshot_id) { throw "店铺快照尚不可用" }

$job = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8765/api/v1/supplier-scout/runs" `
  -ContentType "application/json" `
  -Body (@{
    supplier_id = $supplier.supplier_id
    inventory_snapshot_id = $captureState.snapshot_id
    max_pages = 3
    max_offers = 100
    market_request_budget = 20
  } | ConvertTo-Json)
```

运行 envelope 仍在内存中，服务重启后不能继续轮询旧 `run_id`；已经采集的店铺快照保留在
独立 SQLite 中。市场预算耗尽只会把后续商品标为 `NOT_RUN_BUDGET`，不会从结果删除。

## 分类目录维护

分类目录是本机单用户 SQLite 数据库，默认位置可由下列命令查看：

```powershell
.\.venv\Scripts\python.exe -m proteus categories path
.\.venv\Scripts\python.exe -m proteus categories list
```

分类定义遵循 [`contracts/v0_2_5_category_definition.schema.json`](contracts/v0_2_5_category_definition.schema.json)，
可从 [`examples/northway_category_definition.example.json`](examples/northway_category_definition.example.json)
复制一份作为起点。Agent 或用户可以先参考现有定义，再按保守流程增加或更新一个小类：

```powershell
.\.venv\Scripts\python.exe -m proteus categories show fog_light_bezel
.\.venv\Scripts\python.exe -m proteus categories validate --file .\new-category.json
.\.venv\Scripts\python.exe -m proteus categories draft --file .\new-category.json
.\.venv\Scripts\python.exe -m proteus categories activate <category_id> --version <version_id>
```

`validate`、`draft` 和 `activate` 都只访问本地文件与数据库，不消耗 marketplace/provider
额度。导入只创建不可变 `DRAFT`；只有离线验证通过并执行显式 `activate`，分类才会出现在
两个下拉框中。更新已有小类会创建新版本，不会原地覆盖历史定义；运行提交时记录并冻结
当时的 `category_version_id`。不再使用的小类可显式归档：

```powershell
.\.venv\Scripts\python.exe -m proteus categories archive <category_id>
```

当前执行器只支持已有的车型专用小饰件和机械拉索身份能力。`低责任金属件` 分组因此先作为
空分组展示；在增加可靠的孔位、尺寸或接口能力前，带未知能力缺口的定义可以保存为草稿，
但不能启用。

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
