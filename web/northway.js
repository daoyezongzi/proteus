"use strict";

const API = "/api/v1";
const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[char]);

const labels = {
  fog_light_bezel: "雾灯框 / 雾灯装饰盖",
  tow_hook_cover: "牵引钩盖",
  bumper_reflector: "保险杠反光片",
  headlight_washer_cover: "大灯清洗盖",
  lower_air_deflector: "下部导流板",
  hood_latch_release_cable: "发动机盖锁拉索",
  accelerator_cable: "油门拉索",
  door_handle_bowden_cable: "门把手 Bowden 拉索",
  transmission_shift_control_cable: "换挡控制拉索",
};

const decisionMeta = {
  OPPORTUNITY_CANDIDATE: ["可优先复核", "pass"],
  MARKET_SHORTLIST_CANDIDATE: ["市场初筛通过", "pass"],
  REVIEW_REQUIRED: ["需要人工判断", "review"],
  REJECTED: ["已明确淘汰", "reject"],
};

const stageLabels = {
  scope: "小类范围",
  identity: "产品家族",
  demand: "eBay 需求",
  amazon_family_competition: "Amazon 平替",
  family_price_floor: "平替最低价",
  china_non_oem_supply: "国内供货",
};

let activeRunId = null;
let policy = null;
let lastResult = null;
let activeFilter = "reviewable";
let archetypeCount = 9;

const resultFilters = [
  ["reviewable", "可复核", (report) => report.decision !== "REJECTED"],
  ["priority", "优先候选", (report) => ["OPPORTUNITY_CANDIDATE", "MARKET_SHORTLIST_CANDIDATE"].includes(report.decision)],
  ["review", "待判断", (report) => report.decision === "REVIEW_REQUIRED"],
  ["rejected", "已淘汰", (report) => report.decision === "REJECTED"],
];

async function json(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { accept: "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    const validation = Array.isArray(detail) ? detail[0]?.msg : detail;
    throw new Error(validation || `本地接口返回 ${response.status}`);
  }
  return response.json();
}

function setFormStatus(message = "", state = "") {
  const element = $("#formStatus");
  element.textContent = message;
  if (state) element.dataset.state = state;
  else delete element.dataset.state;
}

function syncBudgetMinimum() {
  const pages = Math.max(1, Number($("#discovery_pages").value) || 1);
  const required = archetypeCount * pages;
  const input = $("#request_budget");
  input.min = String(required);
  input.setCustomValidity(Number(input.value) < required ? `总请求预算至少需要 ${required}` : "");
  $("#budgetHint").textContent = `至少 ${required} 次用于覆盖全部类型；用尽后保留缺口`;
}

async function boot() {
  const status = $("#systemStatus");
  try {
    const [health, config, nextPolicy] = await Promise.all([
      json("/health"),
      json("/config/status"),
      json("/northway/policy"),
    ]);
    policy = nextPolicy;
    archetypeCount = Object.keys(policy.archetypes || {}).length || 9;
    $("#archetypeCount").textContent = archetypeCount;
    syncBudgetMinimum();
    const configured = config.credentials?.SERPAPI_API_KEY?.configured === true;
    status.dataset.state = configured ? "ready" : "error";
    status.lastElementChild.textContent = configured
      ? `v${health.version} · SerpApi 已就绪`
      : `v${health.version} · 请先运行 proteus setup`;
    $("#runButton").disabled = !configured;
  } catch (error) {
    status.dataset.state = "error";
    status.lastElementChild.textContent = "本地服务不可用";
    $("#runButton").disabled = true;
    setFormStatus(`请先启动：python -m proteus api（${error.message}）`, "error");
  }
}

function collectForm() {
  const number = (id) => Number($(`#${id}`).value);
  return {
    discovery_pages: number("discovery_pages"),
    request_budget: number("request_budget"),
    max_amazon_queries_per_family: number("max_amazon_queries_per_family"),
    max_competitive_products: number("max_competitive_products"),
    min_family_price_usd: number("min_family_price_usd"),
    min_observed_ebay_demand: number("min_observed_ebay_demand"),
  };
}

async function waitForRun(runId) {
  for (;;) {
    const run = await json(`/northway/runs/${encodeURIComponent(runId)}`);
    if (run.status === "COMPLETED") return run.result;
    if (run.status === "FAILED") throw new Error(run.error?.message || "扫描失败");
    await new Promise((resolve) => setTimeout(resolve, 1100));
  }
}

function fitmentText(family) {
  const fitments = Array.isArray(family?.fitments) ? family.fitments : [];
  if (!fitments.length) return "车型信息待解析";
  const first = fitments[0];
  const years = first.year_from && first.year_to
    ? (first.year_from === first.year_to ? first.year_from : `${first.year_from}–${first.year_to}`)
    : "年份待核对";
  const extra = fitments.length > 1 ? ` 等 ${fitments.length} 组适配` : "";
  return `${years} ${first.make || ""} ${first.model || ""}${extra}`.trim();
}

function value(value, fallback = "—") {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString("en-US")
    : fallback;
}

function money(amount) {
  return typeof amount === "number" && Number.isFinite(amount)
    ? `$${amount.toFixed(2)}`
    : "待核对";
}

function sourceLinks(report) {
  return (report.source_listings || []).map((source, index) => {
    const href = String(source.source_listing_url || "");
    if (!/^https:\/\/(?:www\.)?ebay\.com\//i.test(href)) return "";
    return `<a href="${esc(href)}" target="_blank" rel="noreferrer">eBay 来源 ${index + 1} ↗</a>`;
  }).join("");
}

function candidateCard(report) {
  const family = report.family || {};
  const competition = report.competition || {};
  const demand = report.demand || {};
  const [verdict, tone] = decisionMeta[report.decision] || decisionMeta.REVIEW_REQUIRED;
  const identifiers = (family.identifiers || []).map((item) => item.raw).filter(Boolean);
  const gaps = report.evidence_gaps || [];
  const queries = report.query_pack || [];
  const relevantProducts = (competition.observations || []).filter((item) => item.relation === "INTERCHANGEABLE");
  const offers = competition.family_offer_count_lower_bound;

  return `<li class="candidate-card" data-decision="${esc(report.decision)}">
    <div class="candidate-head">
      <span class="rank">${esc(report.rank)}</span>
      <div class="candidate-title">
        <h3>${esc(labels[report.archetype] || family.part_type || "未解析产品")}</h3>
        <p>${esc(fitmentText(family))}${identifiers.length ? ` · ${esc(identifiers.join(" / "))}` : ""}</p>
      </div>
      <span class="verdict" data-tone="${esc(tone)}">${esc(verdict)}</span>
    </div>

    <div class="metric-grid">
      <div class="metric"><b>${esc(value(competition.competitive_product_cluster_count))}</b><span>平替产品种类</span></div>
      <div class="metric"><b>${esc(value(competition.competitive_asin_count))}</b><span>相关 ASIN</span></div>
      <div class="metric"><b>${esc(money(competition.aftermarket_family_price_floor_usd ?? competition.family_price_floor_usd))}</b><span>平替最低价</span></div>
      <div class="metric"><b>${esc(value(demand.observed_sold_count_lower_bound))}</b><span>eBay 可见销量下界</span></div>
      <div class="metric"><b>${esc(value(offers))}</b><span>seller offers 下界</span></div>
    </div>

    <div class="stage-strip">
      ${Object.entries(report.stages || {}).map(([key, stage]) => `
        <span class="stage-pill" data-status="${esc(stage.status)}" title="${esc(stage.reason || "")}">
          ${esc(stageLabels[key] || key)} · ${esc(stage.status === "PASSED" ? "通过" : stage.status === "REJECTED" ? "失败" : stage.status === "NOT_RUN" ? "未运行" : "待复核")}
        </span>
      `).join("")}
    </div>

    <details class="card-details">
      <summary>查看查询、商品和证据缺口</summary>
      <div class="detail-body">
        <section class="detail-section">
          <h4>Amazon 查询包</h4>
          <ul>${queries.length ? queries.map((item) => `<li><code>${esc(item.query)}</code></li>`).join("") : "<li>未生成查询</li>"}</ul>
        </section>
        <section class="detail-section">
          <h4>确认相关的 Amazon 商品</h4>
          <ul>${relevantProducts.length ? relevantProducts.map((item) => `<li><a href="${esc(item.url)}" target="_blank" rel="noreferrer">${esc(item.asin)}</a> · ${esc(money(item.price_usd))} · ${esc(item.title)}</li>`).join("") : "<li>当前查询未确认可互换商品</li>"}</ul>
        </section>
        <section class="detail-section">
          <h4>证据缺口</h4>
          <p>${esc(gaps.length ? gaps.join(" · ") : "无关键缺口")}</p>
        </section>
        <div class="source-links">${sourceLinks(report)}</div>
      </div>
    </details>

    <div class="manual-check" aria-label="人工复核清单">
      <span>核对左右侧、单件/套装和关键接口</span>
      <span>在 1688/国内供应商确认非原厂对应品</span>
      <span>计算采购、物流、平台费和真实利润</span>
    </div>
  </li>`;
}

function renderCandidateList() {
  const reports = lastResult?.reports || [];
  const selected = resultFilters.find(([key]) => key === activeFilter) || resultFilters[0];
  const visible = reports.filter(selected[2]);
  $("#candidateList").innerHTML = visible.map(candidateCard).join("");
  $("#filterEmpty").hidden = visible.length > 0;
  $("#resultFilters").innerHTML = resultFilters.map(([key, label, predicate]) => {
    const count = reports.filter(predicate).length;
    const pressed = key === activeFilter;
    return `<button class="filter-button" type="button" data-filter="${esc(key)}" aria-controls="candidateList" aria-pressed="${pressed}">${esc(label)} <span>${count}</span></button>`;
  }).join("");
}

function renderResult(result) {
  lastResult = result;
  activeFilter = "reviewable";
  $("#emptyState").hidden = true;
  $("#resultContent").hidden = false;
  $("#exportButton").hidden = false;
  const summary = result.summary || {};
  const budget = result.request_budget || {};
  const discovery = result.discovery || {};

  $("#runSummary").innerHTML = [
    [summary.candidate_count, "全部候选"],
    [(summary.opportunity_candidates || 0) + (summary.market_shortlist_candidates || 0), "优先复核"],
    [summary.review_required, "需要判断"],
    [summary.rejected, "明确淘汰"],
    [`${value(budget.used)}/${value(budget.limit)}`, "请求预算"],
  ].map(([number, label]) => `<div class="summary-cell"><b>${esc(value(number, String(number ?? "—")))}</b><span>${esc(label)}</span></div>`).join("");

  const notice = $("#runNotice");
  const reports = result.reports || [];
  if (!reports.length) {
    notice.hidden = false;
      notice.textContent = `发现阶段状态：${discovery.status || "UNKNOWN"}。本次没有生成可复核候选；这不等于市场没有需求，可增加扫描页数后重试。`;
  } else if (budget.remaining === 0) {
    notice.hidden = false;
    notice.textContent = "本次请求预算已用尽。所有已经发现的候选仍被保留，未完成的 Amazon 查询已标记为证据缺口。";
  } else {
    notice.hidden = true;
    notice.textContent = "";
  }
  renderCandidateList();
  const typeCount = result.scan_manifest?.archetypes?.length ?? 0;
  $("#resultSubtitle").textContent = `${typeCount} 类共扫描 ${result.scan_manifest?.pages_completed ?? 0} 页，处理 ${reports.length} 个去重产品家族；默认不展示明确淘汰项。`;
}

$("#resultFilters").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-filter]");
  if (!button || !lastResult) return;
  activeFilter = button.dataset.filter;
  renderCandidateList();
});

$("#discovery_pages").addEventListener("input", syncBudgetMinimum);
$("#request_budget").addEventListener("input", syncBudgetMinimum);

$("#runForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  if (!form.reportValidity()) return;
  const button = $("#runButton");
  button.disabled = true;
  button.firstElementChild.textContent = "正在扫描…";
  setFormStatus("正在扫描全部零件小类、解析产品家族并搜索 Amazon。请不要关闭本页。");
  $("#emptyState").innerHTML = $("#skeletonTemplate").innerHTML;

  try {
    const submitted = await json("/northway/runs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(collectForm()),
    });
    activeRunId = submitted.run_id;
    const result = await waitForRun(activeRunId);
    renderResult(result);
    setFormStatus(`扫描完成：${result.summary?.candidate_count || 0} 个候选已进入排序。`);
  } catch (error) {
    setFormStatus(error.message, "error");
    $("#emptyState").innerHTML = `<span class="empty-state__mark">!</span><h3>本次扫描没有完成</h3><p>${esc(error.message)}</p>`;
  } finally {
    button.disabled = false;
    button.firstElementChild.textContent = "开始选品扫描";
  }
});

$("#exportButton").addEventListener("click", () => {
  if (!activeRunId) return;
  window.location.href = `${API}/northway/runs/${encodeURIComponent(activeRunId)}/export`;
});

boot();
