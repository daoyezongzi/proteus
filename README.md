# Proteus V0.1

Proteus V0.1 是一个证据优先的汽车零件商机候选筛选器。只有 Amazon 低竞争、
eBay 已观察需求和 1688 可采购供应三个 gate 全部通过，才会输出
`OPPORTUNITY_CANDIDATE`。

当前自动化边界是 eBay 低频浏览器采集；Amazon 与 1688 使用可追溯的人工
证据。完整产品边界见 [V0_1_SCOPE_CONTRACT.md](V0_1_SCOPE_CONTRACT.md)。

## 安装

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## 合成工程验收

下面的输入全部明确标记为 synthetic，只用于验证程序和三门规则，不能作为
真实商机或产品验收结果：

```powershell
.\.venv\Scripts\python.exe -m proteus `
  --candidate-pool .\examples\synthetic_candidates.json `
  --manual-evidence .\examples\synthetic_manual_evidence.json `
  --ebay-evidence .\examples\synthetic_ebay_evidence.json `
  --max-moq 10 `
  --output .\synthetic_reports.json
```

预期摘要包含 `opportunities=1`。输出数组中的每份报告都会先通过
[opportunity report schema](contracts/v0_1_opportunity_report.schema.json)，
然后才原子写入目标文件。

## 真实运行

将候选池和 Amazon/1688 人工证据替换为当前、可追溯的真实证据；eBay 使用
实时 provider：

```powershell
.\.venv\Scripts\python.exe -m proteus `
  --candidate-pool .\candidates.json `
  --manual-evidence .\manual_evidence.json `
  --live-ebay `
  --browser-channel auto `
  --max-moq 10 `
  --output .\reports.json
```

Provider 不登录、不绕过 challenge，只查第一页并串行运行。HTTP 错误、
challenge、登录要求、区域不匹配和解析失败都会保留为显式失败，绝不会变成
零结果或通过。浏览器继承系统网络出口，但程序不切换 VPN/代理节点；出口地区
只能影响采集能否通过，不能替代页面对 `US 10001` 市场上下文的明确证明。
人工 evidence 必须使用 `source_method: "MANUAL"`，每条字段级
证据必须使用 `extraction_method: "MANUAL_REVIEW"`。Amazon 还必须保存实际
query，并用同 query 的 Amazon 搜索 URL 绑定 `relevant_result_count`；1688 的
`purchasable`、`price_cny`、`moq` 必须分别绑定到同一个真实 1688 offer URL。

运行测试：

```powershell
.\.venv\Scripts\python.exe -m pytest
```
