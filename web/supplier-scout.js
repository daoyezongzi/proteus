"use strict";

const API = "/api/v1";
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[character]);

const sourceStatus = {
  SUCCESS: ["读取完成", "pass", "已观察到的商品列表到达末页。"],
  EMPTY: ["已证实空店", "pass", "店铺明确报告 0 件商品且没有下一页。"],
  PARTIAL: ["部分读取", "review", "已保存可见商品，但店铺仍有下一页或触及读取上限。"],
  RISK_CONTROL: ["需要人工验证", "review", "1688 返回滑块或访问验证；这不是零商品。"],
  AUTH_REQUIRED: ["需要重新登录", "review", "本地 1688 profile 当前无法进入该店。"],
  TIMEOUT: ["读取超时", "error", "店铺页面未在边界内完成响应。"],
  PARSER_FAILED: ["页面无法确认", "error", "没有足够结构化证据证明商品清单或空店。"],
  CLI_ERROR: ["本地采集器失败", "error", "请检查 1688 CLI 与浏览器运行环境。"],
  NOT_CONFIGURED: ["采集器未配置", "error", "需要本机 1688 CLI 0.1.47 与已登录 profile。"],
};

const categoryStatusLabels = {
  MATCHED: "目录已匹配",
  CATEGORY_UNMATCHED: "未匹配目录",
  CATEGORY_AMBIGUOUS: "分类有冲突",
  SUPPLIER_MISMATCH: "供应商不一致",
};

const marketStatusLabels = {
  COMPLETED: "市场检查完成",
  PARTIAL_BUDGET: "预算内部分完成",
  NOT_RUN_BUDGET: "预算未运行",
  IDENTITY_INCOMPLETE: "身份不完整",
  CATEGORY_UNMATCHED: "未匹配目录",
  CATEGORY_AMBIGUOUS: "分类有冲突",
  SUPPLIER_MISMATCH: "供应商不一致",
  INVALID_OFFER: "商品记录无效",
  DEMAND_REJECTED: "需求明确不足",
};

const decisionLabels = {
  MARKET_SHORTLIST_CANDIDATE: ["市场候选", "pass"],
  REVIEW_REQUIRED: ["需要复核", "review"],
  REJECTED: ["已明确淘汰", "reject"],
};

const filters = [
  ["all", "全部", () => true],
  ["a", "A 级", (report) => report.competition_grade === "A"],
  ["a-minus", "A- 级", (report) => report.competition_grade === "A-"],
  ["pending", "竞争待定", (report) => report.competition_grade === "PENDING"],
  ["unmatched", "未匹配目录", (report) => report.category_match?.status === "CATEGORY_UNMATCHED"],
  ["identity", "身份待补", (report) => report.market_status === "IDENTITY_INCOMPLETE"],
  ["budget", "预算未运行", (report) => ["NOT_RUN_BUDGET", "PARTIAL_BUDGET"].includes(report.market_status)],
  ["rejected", "已淘汰", (report) => report.decision === "REJECTED"],
];

let policy = null;
let suppliers = [];
let lastResult = null;
let activeRunId = null;
let activeFilter = "all";
let runBusy = false;

async function json(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: { accept: "application/json", ...(options.headers || {}) },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    const message = Array.isArray(detail) ? detail[0]?.msg : detail;
    throw new Error(message || `本地接口返回 ${response.status}`);
  }
  return response.json();
}

function number(id) {
  return Number($(`#${id}`).value);
}

function setStatus(message = "", tone = "") {
  const element = $("#formStatus");
  element.textContent = message;
  if (tone) element.dataset.state = tone;
  else delete element.dataset.state;
}

function setBusy(busy) {
  runBusy = busy;
  const button = $("#runButton");
  button.disabled = busy || !$("#supplier_id").value || selectedCategories().length === 0;
  $(".button__label", button).textContent = busy ? "筛选中…" : "读取并筛选";
  button.dataset.state = busy ? "busy" : "idle";
}

function selectedCategories() {
  return $$("input[name='supplier_category']:checked").map((input) => input.value);
}

function syncRunAvailability() {
  setBusy(runBusy);
}

function renderCategories() {
  const root = $("#categoryGrid");
  const categories = policy?.categories || {};
  const groups = policy?.category_catalog?.groups;
  let grouped = [];
  if (Array.isArray(groups) && groups.length) {
    grouped = groups.map((group) => ({
      group_id: group.group_id,
      label: group.label_zh || group.label_en || group.group_id,
      categories: (group.categories || []).filter((item) => categories[item.category_id]),
    }));
  } else {
    const byGroup = new Map();
    Object.values(categories).forEach((category) => {
      const groupId = category.group_id || "other";
      if (!byGroup.has(groupId)) byGroup.set(groupId, []);
      byGroup.get(groupId).push(category);
    });
    grouped = [...byGroup].map(([groupId, items]) => ({ group_id: groupId, label: groupId, categories: items }));
  }
  root.innerHTML = grouped.map((group) => `<section class="supplier-category-group">
    <h3>${esc(group.label)} · ${group.categories.length}</h3>
    <div class="supplier-category-options">
      ${group.categories.length ? group.categories.map((category) => `<label class="supplier-category-option">
        <input type="checkbox" name="supplier_category" value="${esc(category.category_id)}" checked>
        <span>${esc(category.label_zh || category.label_en || category.category_id)}<small>${esc(category.label_en || category.part_type || category.category_id)}</small></span>
      </label>`).join("") : `<span class="scope-loading">暂无已启用小类</span>`}
    </div>
  </section>`).join("") || `<p class="scope-loading">当前没有可执行的 ACTIVE 小类。</p>`;
  $$("input[name='supplier_category']", root).forEach((input) => input.addEventListener("change", () => {
    syncToggleLabel();
    syncRunAvailability();
  }));
  syncToggleLabel();
}

function syncToggleLabel() {
  const inputs = $$("input[name='supplier_category']");
  $("#toggleCategories").textContent = inputs.length && inputs.every((item) => item.checked) ? "全部取消" : "全部选择";
}

function renderSuppliers(preferredId = null) {
  const select = $("#supplier_id");
  const previous = preferredId || select.value;
  select.innerHTML = `<option value="">请选择已保存供应商</option>${suppliers.map((supplier) => `<option value="${esc(supplier.supplier_id)}">${esc(supplier.label)} · ${esc(supplier.shop_host || new URL(supplier.canonical_url).hostname)}</option>`).join("")}`;
  if (suppliers.some((supplier) => supplier.supplier_id === previous)) select.value = previous;
  else if (suppliers.length === 1) select.value = suppliers[0].supplier_id;
  syncRunAvailability();
}

async function refreshSuppliers(preferredId = null) {
  const payload = await json("/supplier-scout/suppliers");
  suppliers = Array.isArray(payload.suppliers) ? payload.suppliers : [];
  renderSuppliers(preferredId);
}

function currentTarget() {
  const typed = $("#supplier_target").value.trim();
  if (typed) return typed;
  const selected = suppliers.find((supplier) => supplier.supplier_id === $("#supplier_id").value);
  return selected?.canonical_url || "";
}

function showSourceVerdict(outcome) {
  const element = $("#sourceVerdict");
  const [label, tone, description] = sourceStatus[outcome.acquisition_status] || [outcome.acquisition_status || "未知状态", "error", "没有可解释的采集状态。"];
  const observed = Number(outcome.observed_offer_count || 0);
  const available = Number.isInteger(outcome.available_offer_count) ? outcome.available_offer_count : "?";
  element.hidden = false;
  element.dataset.tone = tone;
  element.innerHTML = `<strong>${esc(label)}</strong>${esc(description)} <span>${observed} 件已观察 / ${esc(available)} 件报告总量；${Number(outcome.pages_completed || 0)} 页完成。</span>`;
}

async function inspectSupplier() {
  const target = currentTarget();
  if (!target) {
    setStatus("请先输入店铺 URL，或选择一个已保存供应商。", "error");
    return;
  }
  const button = $("#inspectButton");
  button.disabled = true;
  setStatus($("#headed").checked ? "已打开人工验证模式；如出现窗口，请由你亲自完成滑块。" : "正在做 1 页只读检查…");
  try {
    const outcome = await json("/supplier-scout/suppliers/inspect", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        target,
        max_pages: 1,
        max_offers: 20,
        headed: $("#headed").checked,
        challenge_timeout_seconds: 180,
      }),
    });
    showSourceVerdict(outcome);
    const tone = ["SUCCESS", "EMPTY"].includes(outcome.acquisition_status) ? "success" : "error";
    setStatus(`只读检查完成：${sourceStatus[outcome.acquisition_status]?.[0] || outcome.acquisition_status}`, tone);
  } catch (error) {
    setStatus(`检查失败：${error.message}`, "error");
  } finally {
    button.disabled = false;
  }
}

async function saveSupplier() {
  const label = $("#supplier_label").value.trim();
  const target = $("#supplier_target").value.trim();
  if (!label || !target) {
    setStatus("保存供应商需要显示名称和店铺商品列表 URL。", "error");
    return;
  }
  const button = $("#saveSupplierButton");
  button.disabled = true;
  try {
    const saved = await json("/supplier-scout/suppliers", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ label, target }),
    });
    await refreshSuppliers(saved.supplier_id);
    setStatus(`已保存「${saved.label}」；运行时会重新读取并冻结店铺快照。`, "success");
  } catch (error) {
    setStatus(`保存失败：${error.message}`, "error");
  } finally {
    button.disabled = false;
  }
}

function runRequest() {
  return {
    supplier_id: $("#supplier_id").value,
    selected_category_ids: selectedCategories(),
    max_pages: number("max_pages"),
    max_offers: number("max_offers"),
    headed: $("#headed").checked,
    challenge_timeout_seconds: 180,
    market_request_budget: number("market_request_budget"),
    max_amazon_queries_per_family: number("max_amazon_queries_per_family"),
    grade_a_max_competitors: number("grade_a_max_competitors"),
    grade_a_minus_max_competitors: number("grade_a_minus_max_competitors"),
    min_family_price_usd: number("min_family_price_usd"),
    min_observed_ebay_demand: number("min_observed_ebay_demand"),
  };
}

function renderProgress(progress) {
  if (!progress) return;
  $("#emptyState").hidden = true;
  $("#resultContent").hidden = false;
  const notice = $("#runNotice");
  notice.hidden = false;
  const phases = {
    supplier_inventory: "正在读取供应商店铺",
    classifying: "正在匹配分类与产品身份",
    ebay_demand: "正在核对 eBay 需求",
    amazon_competition: "正在聚合 Amazon 产品族竞争",
    completed: "筛选已完成",
  };
  notice.textContent = `${phases[progress.phase] || progress.phase || "处理中"} · ${progress.current || 0}/${progress.total || "?"} · 市场请求 ${progress.budget_used || 0}`;
}

async function waitForRun(runId) {
  for (;;) {
    const run = await json(`/supplier-scout/runs/${encodeURIComponent(runId)}`);
    renderProgress(run.progress);
    if (run.status === "COMPLETED") return run.result;
    if (run.status === "FAILED") throw new Error(run.error?.message || "筛选运行失败");
    await new Promise((resolve) => setTimeout(resolve, 1100));
  }
}

function formatNumber(value, fallback = "—") {
  return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("zh-CN") : fallback;
}

function summaryCell(label, value, note) {
  return `<div class="summary-cell"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`;
}

function renderSummary(result) {
  const inventory = result.inventory || {};
  const summary = result.summary || {};
  const grades = summary.competition_grades || {};
  const available = Number.isInteger(inventory.available_offer_count) ? inventory.available_offer_count : "?";
  $("#runSummary").innerHTML = [
    summaryCell("店铺覆盖", `${formatNumber(inventory.observed_offer_count, 0)} / ${available}`, inventory.inventory_complete ? "已到商品末页" : "边界内观察，尚未证明全店完整"),
    summaryCell("完成页面", formatNumber(inventory.pages_completed, 0), `${formatNumber(inventory.pages_attempted, 0)} 页尝试`),
    summaryCell("A / A-", `${grades.A || 0} / ${grades["A-"] || 0}`, `${grades.PENDING || 0} 个竞争待定`),
    summaryCell("市场预算", `${result.market_budget?.used || 0} / ${result.market_budget?.limit || 0}`, `${result.market_budget?.remaining || 0} 次剩余`),
    summaryCell("快照状态", sourceStatus[inventory.acquisition_status]?.[0] || inventory.acquisition_status || "未知", result.status === "PARTIAL_SOURCE" ? "结果仅覆盖已观察商品" : "当前运行已封存"),
  ].join("");
  const notice = $("#runNotice");
  if (result.status === "SOURCE_BLOCKED") {
    notice.hidden = false;
    notice.dataset.tone = "review";
    notice.textContent = sourceStatus[inventory.acquisition_status]?.[2] || "店铺来源被阻断；没有把它解释成零商品。";
  } else if (!inventory.inventory_complete) {
    notice.hidden = false;
    notice.dataset.tone = "review";
    notice.textContent = `当前仅观察 ${inventory.observed_offer_count || 0} 件；仍有下一页或触及读取上限，未观察部分不参与淘汰。`;
  } else {
    notice.hidden = true;
  }
}

function gradeTone(grade) {
  if (["A", "A-"].includes(grade)) return "pass";
  if (grade === "REJECTED") return "reject";
  return "review";
}

function reportCard(report, index) {
  const offer = report.offer || {};
  const category = report.category_match || {};
  const resolution = report.resolution || {};
  const family = resolution.family || {};
  const competition = report.competition || {};
  const demand = report.demand || {};
  const observed = demand.observed_demand?.aggregate_observed_sold;
  const [decisionLabel, decisionTone] = decisionLabels[report.decision] || [report.decision || "需要复核", "review"];
  const grade = report.competition_grade || "未分级";
  const identifiers = Array.isArray(report.identifiers) ? report.identifiers : [];
  const gaps = Array.isArray(report.evidence_gaps) ? report.evidence_gaps : [];
  const categoryLabel = category.status === "MATCHED"
    ? policy?.categories?.[category.category_id]?.label_zh || category.category_id
    : categoryStatusLabels[category.status] || category.status || "未分类";
  return `<li class="candidate-card" data-decision="${esc(report.decision || "REVIEW_REQUIRED")}">
    <div class="candidate-head">
      <span class="rank">${String(index + 1).padStart(2, "0")}</span>
      <div class="candidate-title">
        <div class="candidate-eyebrow">1688 OFFER · ${esc(offer.offer_id || "UNKNOWN")}</div>
        <h3 class="supplier-offer-title">${esc(offer.title || "标题缺失")}</h3>
        ${offer.offer_url ? `<a class="supplier-offer-link" href="${esc(offer.offer_url)}" target="_blank" rel="noopener noreferrer">打开 1688 商品 ↗</a>` : ""}
        <div class="candidate-identifiers">${identifiers.length ? identifiers.map((item) => `<code>${esc(item)}</code>`).join("") : `<span>未提取到可用 OEM / MPN</span>`}</div>
      </div>
      <div class="candidate-verdict">
        <span class="competition-grade" data-tone="${gradeTone(report.competition_grade)}">${esc(grade)}</span>
        <span class="verdict" data-tone="${decisionTone}">${esc(decisionLabel)}</span>
      </div>
    </div>
    <div class="supplier-card-meta">
      <div><span>目录去向</span><strong>${esc(categoryLabel)}</strong></div>
      <div><span>产品身份</span><strong>${esc(resolution.identity_status || marketStatusLabels[report.market_status] || report.market_status || "—")}</strong></div>
      <div><span>eBay 可见销量</span><strong>${formatNumber(observed)}</strong></div>
      <div><span>Amazon 产品簇</span><strong>${formatNumber(competition.competitive_product_cluster_count)}</strong></div>
    </div>
    <details class="card-details">
      <summary>查看证据去向 <span class="detail-summary-meta">${esc(marketStatusLabels[report.market_status] || report.market_status || "未运行")}</span></summary>
      <div class="detail-body">
        <section class="detail-section"><div class="detail-section__head"><span class="detail-section__index">01</span><h4>产品家族</h4></div>
          <div class="fact-list"><div><span>零件类型</span><strong>${esc(family.part_type || "未解析")}</strong></div><div><span>家族键</span><strong>${esc(family.family_key || "—")}</strong></div><div><span>包装</span><strong>${esc(family.package_type || "—")}</strong></div><div><span>最低平替价</span><strong>${competition.family_price_floor_usd == null ? "—" : `$${competition.family_price_floor_usd}`}</strong></div></div>
        </section>
        <section class="detail-section"><div class="detail-section__head"><span class="detail-section__index">02</span><h4>证据缺口</h4></div>
          ${gaps.length ? `<ul>${gaps.map((gap) => `<li class="detail-gap">${esc(gap)}</li>`).join("")}</ul>` : `<p>当前自动步骤没有记录额外缺口；仍需人工核对适配、责任与采购条件。</p>`}
        </section>
        <section class="detail-section detail-section--wide"><div class="detail-section__head"><span class="detail-section__index">03</span><h4>Provider 尝试</h4></div>
          <div class="supplier-evidence-line">${(report.provider_attempts || []).length ? report.provider_attempts.map((attempt) => `<code>${esc(attempt.provider || "NOT_RUN")} · ${esc(attempt.status || "UNKNOWN")} · ${esc(attempt.query || "")}</code>`).join("") : `<code>未消耗市场请求</code>`}</div>
        </section>
      </div>
    </details>
  </li>`;
}

function renderFilters() {
  const root = $("#resultFilters");
  const reports = lastResult?.reports || [];
  root.innerHTML = filters.map(([key, label, predicate]) => {
    const count = reports.filter(predicate).length;
    return `<button class="filter-button" type="button" data-filter="${esc(key)}" aria-pressed="${key === activeFilter}">${esc(label)} <span>${count}</span></button>`;
  }).join("");
  $$("button", root).forEach((button) => button.addEventListener("click", () => {
    activeFilter = button.dataset.filter;
    renderFilters();
    renderReports();
  }));
}

function renderReports() {
  const reports = lastResult?.reports || [];
  const filter = filters.find(([key]) => key === activeFilter) || filters[0];
  const visible = reports.filter(filter[2]);
  $("#candidateList").innerHTML = visible.map(reportCard).join("");
  $("#filterEmpty").hidden = visible.length > 0;
}

function renderResult(result) {
  lastResult = result;
  activeFilter = "all";
  $("#emptyState").hidden = true;
  $("#resultContent").hidden = false;
  renderSummary(result);
  renderFilters();
  renderReports();
  $("#compactExport").href = `${API}/supplier-scout/runs/${encodeURIComponent(activeRunId)}/export/compact`;
  $("#fullExport").href = `${API}/supplier-scout/runs/${encodeURIComponent(activeRunId)}/export`;
  $("#compactExport").hidden = false;
  $("#fullExport").hidden = false;
}

async function submitRun(event) {
  event.preventDefault();
  const request = runRequest();
  if (!request.supplier_id || request.selected_category_ids.length === 0) {
    setStatus("请选择已保存供应商，并至少保留一个 ACTIVE 小类。", "error");
    return;
  }
  if (request.grade_a_minus_max_competitors <= request.grade_a_max_competitors) {
    setStatus("A- 上限必须大于 A 级上限。", "error");
    return;
  }
  setBusy(true);
  setStatus(request.headed ? "运行已开始；若出现验证窗口，请由你亲自完成滑块。" : "正在创建有界店铺快照…");
  $("#emptyState").hidden = true;
  $("#resultContent").hidden = false;
  $("#runNotice").hidden = false;
  $("#runNotice").textContent = "正在排队读取供应商店铺…";
  try {
    const submission = await json("/supplier-scout/runs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(request),
    });
    activeRunId = submission.run_id;
    const result = await waitForRun(activeRunId);
    renderResult(result);
    setStatus("店铺快照与筛选结果已封存；请先看覆盖状态，再看 A / A-。", "success");
  } catch (error) {
    $("#runNotice").hidden = false;
    $("#runNotice").dataset.tone = "review";
    $("#runNotice").textContent = error.message;
    setStatus(`运行失败：${error.message}`, "error");
  } finally {
    setBusy(false);
  }
}

async function boot() {
  const status = $("#systemStatus");
  try {
    const [health, nextPolicy] = await Promise.all([
      json("/health"),
      json("/supplier-scout/policy"),
    ]);
    policy = nextPolicy;
    renderCategories();
    await refreshSuppliers();
    const defaults = policy.default_thresholds || {};
    ["grade_a_max_competitors", "grade_a_minus_max_competitors", "min_family_price_usd", "min_observed_ebay_demand"].forEach((id) => {
      if (defaults[id] != null) $(`#${id}`).value = String(defaults[id]);
    });
    status.dataset.state = "ready";
    $(".system-status__label", status).textContent = `v${health.version} · 本地接口已就绪`;
    syncRunAvailability();
  } catch (error) {
    status.dataset.state = "error";
    $(".system-status__label", status).textContent = "本地服务不可用";
    setStatus(`请先启动：python -m proteus api（${error.message}）`, "error");
  }
}

$("#inspectButton").addEventListener("click", inspectSupplier);
$("#saveSupplierButton").addEventListener("click", saveSupplier);
$("#supplier_id").addEventListener("change", syncRunAvailability);
$("#headed").addEventListener("change", (event) => {
  $("#headedLabel").textContent = event.currentTarget.checked ? "等待人工验证" : "不打开";
});
$("#toggleCategories").addEventListener("click", () => {
  const inputs = $$("input[name='supplier_category']");
  const next = !inputs.every((item) => item.checked);
  inputs.forEach((input) => { input.checked = next; });
  syncToggleLabel();
  syncRunAvailability();
});
$("#runForm").addEventListener("submit", submitRun);

boot();
