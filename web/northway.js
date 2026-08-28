"use strict";

const API = "/api/v1";
const $ = (selector, root = document) => root.querySelector(selector);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
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

const fallbackKeywords = {
  fog_light_bezel: "fog light bezel OEM",
  tow_hook_cover: "tow hook cover OEM",
  bumper_reflector: "bumper reflector OEM",
  headlight_washer_cover: "headlight washer cover OEM",
  lower_air_deflector: "lower air deflector OEM",
  hood_latch_release_cable: "hood release cable OEM",
  accelerator_cable: "accelerator cable OEM",
  door_handle_bowden_cable: "door handle cable OEM",
  transmission_shift_control_cable: "shift control cable OEM",
};

const fallbackProfiles = {
  fog_light_bezel: "vehicle_specific_small_trim",
  tow_hook_cover: "vehicle_specific_small_trim",
  bumper_reflector: "vehicle_specific_small_trim",
  headlight_washer_cover: "vehicle_specific_small_trim",
  lower_air_deflector: "vehicle_specific_small_trim",
  hood_latch_release_cable: "vehicle_specific_cable",
  accelerator_cable: "vehicle_specific_cable",
  door_handle_bowden_cable: "vehicle_specific_cable",
  transmission_shift_control_cable: "vehicle_specific_cable",
};

const profileLabels = {
  vehicle_specific_small_trim: "车型专用小饰件",
  vehicle_specific_cable: "车型专用拉索",
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

const stageOrder = [
  "scope",
  "identity",
  "demand",
  "amazon_family_competition",
  "family_price_floor",
  "china_non_oem_supply",
];

const resultFilters = [
  ["reviewable", "可复核", (report) => report.decision !== "REJECTED"],
  ["priority", "优先候选", (report) => ["OPPORTUNITY_CANDIDATE", "MARKET_SHORTLIST_CANDIDATE"].includes(report.decision)],
  ["review", "待判断", (report) => report.decision === "REVIEW_REQUIRED"],
  ["rejected", "已淘汰", (report) => report.decision === "REJECTED"],
];

const statusLabels = {
  PASSED: "通过",
  REJECTED: "未通过",
  REVIEW_REQUIRED: "待复核",
  NOT_RUN: "未运行",
};

const operatorSymbols = { GT: ">", LTE: "≤", GTE: "≥" };
const sideLabels = { LEFT: "左侧", RIGHT: "右侧", BOTH: "左右两侧" };
const packageLabels = { SINGLE: "单件", PAIR: "一对" };
const discoveryFailures = new Set([
  "HTTP_ERROR",
  "TIMEOUT",
  "AUTH_REQUIRED",
  "BLOCKED_BY_CREDENTIALS",
  "MARKET_CONTEXT_MISMATCH",
  "PARSER_FAILED",
]);

const reasonLabels = {
  "Sellable product family resolved.": "可售产品家族已解析。",
  "Observed source listings provide a family-bound sold-count lower bound.": "来源 listing 提供了绑定到该产品族的销量下界。",
  "Complete family search found competition within the configured limit.": "完整的产品族搜索结果在设定上限内。",
  "Observed substitute-product clusters exceed the configured limit.": "观察到的平替产品种类超过设定上限。",
  "The substitute-family price floor remains above the configured limit.": "平替产品族最低价高于设定阈值。",
  "The substitute-family price floor is at or below the configured limit.": "平替产品族最低价低于或等于设定阈值。",
  "China non-OEM supply verification is not configured.": "尚未配置国内非原厂供货核验。",
  "Amazon family search incomplete; low competition cannot be proven.": "Amazon 产品族搜索不完整，无法证明低竞争。",
  "Listing title is missing.": "listing 标题缺失。",
};

let activeRunId = null;
let policy = null;
let lastResult = null;
let activeFilter = "reviewable";
let archetypeCount = Object.keys(labels).length;

async function json(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: { accept: "application/json", ...(options.headers || {}) },
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

function setRunBusy(busy) {
  const button = $("#runButton");
  const label = $(".button__label", button);
  button.dataset.state = busy ? "busy" : "idle";
  button.disabled = busy;
  label.textContent = busy ? "扫描中…" : "开始扫描";
}

function syncBudgetMinimum() {
  const pages = Math.max(1, Number($("#discovery_pages").value) || 1);
  const required = archetypeCount * pages;
  const input = $("#request_budget");
  input.min = String(required);
  input.setCustomValidity(Number(input.value) < required ? `总请求预算至少需要 ${required}` : "");
  $("#budgetHint").textContent = `至少 ${required} 次用于覆盖全部类型；用尽后保留缺口`;
}

function archetypeEntries() {
  const configured = policy?.archetypes;
  if (configured && Object.keys(configured).length) return Object.entries(configured);
  return Object.keys(labels).map((key) => [key, {
    category_profile: fallbackProfiles[key],
    discovery_keyword: fallbackKeywords[key],
  }]);
}

function profileLabel(profile) {
  return profileLabels[profile] || profile || "未分类";
}

function renderScopeList() {
  const root = $("#scopeList");
  const entries = archetypeEntries();
  archetypeCount = entries.length || Object.keys(labels).length;
  $("#archetypeCount").textContent = archetypeCount;
  $("#emptyArchetypeCount").textContent = archetypeCount;

  const groups = new Map();
  entries.forEach(([key, value]) => {
    const profile = value?.category_profile || fallbackProfiles[key] || "other";
    if (!groups.has(profile)) groups.set(profile, []);
    groups.get(profile).push({
      key,
      label: labels[key] || value?.part_type || key,
      keyword: value?.discovery_keyword || fallbackKeywords[key] || "",
    });
  });

  const orderedProfiles = [
    ...["vehicle_specific_small_trim", "vehicle_specific_cable"].filter((profile) => groups.has(profile)),
    ...[...groups.keys()].filter((profile) => !["vehicle_specific_small_trim", "vehicle_specific_cable"].includes(profile)),
  ];
  root.innerHTML = orderedProfiles.map((profile) => {
    const items = groups.get(profile) || [];
    return `<section class="scope-group" data-profile="${esc(profile)}">
      <div class="scope-group__head"><span>${esc(profileLabel(profile))}</span><span class="scope-group__count">${items.length} 类</span></div>
      <div class="scope-items">
        ${items.map((item) => `<div class="scope-item" data-profile="${esc(profile)}" title="${esc(item.keyword)}">
          <span class="scope-item__dot" aria-hidden="true"></span>
          <span class="scope-item__label">${esc(item.label)}</span>
          <span class="scope-item__keyword" aria-hidden="true">OEM</span>
        </div>`).join("")}
      </div>
    </section>`;
  }).join("");
}

async function boot() {
  const status = $("#systemStatus");
  renderScopeList();
  syncBudgetMinimum();
  try {
    const [health, config, nextPolicy] = await Promise.all([
      json("/health"),
      json("/config/status"),
      json("/northway/policy"),
    ]);
    policy = nextPolicy;
    renderScopeList();
    syncBudgetMinimum();
    const configured = config.credentials?.SERPAPI_API_KEY?.configured === true;
    status.dataset.state = configured ? "ready" : "error";
    $(".system-status__label", status).textContent = configured
      ? `v${health.version} · SerpApi 已就绪`
      : `v${health.version} · 请先运行 proteus setup`;
    $("#runButton").disabled = !configured;
  } catch (error) {
    status.dataset.state = "error";
    $(".system-status__label", status).textContent = "本地服务不可用";
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

function value(raw, fallback = "—") {
  if (typeof raw === "number" && Number.isFinite(raw)) return raw.toLocaleString("en-US");
  if (raw !== null && raw !== undefined && String(raw) !== "") return String(raw);
  return fallback;
}

function money(raw, fallback = "待核对") {
  const amount = typeof raw === "number" ? raw : Number(raw);
  return Number.isFinite(amount) ? `$${amount.toFixed(2)}` : fallback;
}

function confidence(raw) {
  const amount = Number(raw);
  return Number.isFinite(amount) ? `${Math.round(amount * 100)}%` : "待核对";
}

function localizeReason(raw) {
  const reason = String(raw || "").replace(/\s+/g, " ").trim();
  if (!reason) return "—";
  if (reasonLabels[reason]) return reasonLabels[reason];
  const archetype = reason.match(/^Title matches the (.+) Northway archetype\.$/i);
  if (archetype) return `标题匹配「${archetype[1]}」Northway 小类。`;
  if (/^Observed source listings provide a family-bound/.test(reason)) return reasonLabels["Observed source listings provide a family-bound sold-count lower bound."];
  return reason;
}

function fitmentText(family) {
  const fitments = Array.isArray(family?.fitments) ? family.fitments : [];
  if (!fitments.length) return "车型信息待解析";
  const first = fitments[0] || {};
  const years = first.year_from && first.year_to
    ? (first.year_from === first.year_to ? first.year_from : `${first.year_from}–${first.year_to}`)
    : "年份待核对";
  const vehicle = [first.make, first.model].filter(Boolean).join(" ");
  const sides = (family.sides || []).map((side) => sideLabels[side] || side).join(" / ");
  const packageType = packageLabels[family.package_type] || family.package_type;
  const qualifiers = [sides, packageType].filter(Boolean).join(" · ");
  const extra = fitments.length > 1 ? `等 ${fitments.length} 组适配` : "";
  return [years, vehicle, qualifiers, extra].filter(Boolean).join(" · ") || "车型信息待解析";
}

function familyIdentifiers(family) {
  return (family?.identifiers || [])
    .map((item) => item?.raw || item?.canonical)
    .filter(Boolean);
}

function validExternalUrl(raw, pattern) {
  const href = String(raw || "");
  return pattern.test(href) ? href : "";
}

function sourceLinks(report) {
  const sources = Array.isArray(report.source_listings) ? report.source_listings : [];
  return sources.map((source, index) => {
    const href = validExternalUrl(source.source_listing_url, /^https:\/\/(?:www\.)?ebay\.com\//i);
    return href
      ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">eBay 来源 ${index + 1} ↗</a>`
      : "";
  }).join("");
}

function sourceListingRows(report) {
  const sources = Array.isArray(report.source_listings) ? report.source_listings : [];
  if (!sources.length) return "<li>暂无绑定的 eBay 来源 listing。</li>";
  return sources.map((source) => `<li>
    <strong>${esc(source.source_listing_title || "未命名 listing")}</strong>
    <span>${esc(source.source_listing_id || "未记录 ID")} · 可见销量 ${esc(value(source.source_sold_count))}</span>
  </li>`).join("");
}

function stageTone(status) {
  if (status === "PASSED") return "pass";
  if (status === "REJECTED") return "reject";
  if (status === "REVIEW_REQUIRED") return "review";
  return "";
}

function stageReading(stage) {
  if (!stage || stage.status === "NOT_RUN") return "未运行";
  let reading = stage.value === "IN_SCOPE" ? "范围内" : stage.value === "RESOLVED" ? "已解析" : value(stage.value, "无读数");
  if (stage.operator && stage.threshold !== null && stage.threshold !== undefined) {
    const threshold = stage.threshold === "IN_SCOPE" ? "范围内" : stage.threshold === "RESOLVED" ? "已解析" : value(stage.threshold);
    reading += ` ${operatorSymbols[stage.operator] || stage.operator} ${threshold}`;
  }
  return reading;
}

function stagePill(key, stage) {
  const status = stage?.status || "NOT_RUN";
  return `<span class="stage-pill" data-status="${esc(status)}" title="${esc(localizeReason(stage?.reason))}">
    <span class="stage-pill__dot" aria-hidden="true"></span>
    <span class="stage-pill__name">${esc(stageLabels[key] || key)}</span>
    <span class="stage-pill__status">${esc(statusLabels[status] || "待复核")}</span>
  </span>`;
}

function stageReadingRows(stages) {
  return stageOrder.map((key) => {
    const stage = stages?.[key] || { status: "NOT_RUN" };
    return `<div class="reading-row" data-status="${esc(stage.status || "NOT_RUN")}">
      <span class="reading-row__name">${esc(stageLabels[key] || key)}</span>
      <span class="reading-row__value">${esc(stageReading(stage))}</span>
      <span class="reading-row__reason">${esc(localizeReason(stage.reason))}</span>
    </div>`;
  }).join("");
}

function familyFacts(family) {
  const positions = (family?.positions || []).join(" / ") || "未解析";
  const sides = (family?.sides || []).map((side) => sideLabels[side] || side).join(" / ") || "未解析";
  const packageText = [packageLabels[family?.package_type] || family?.package_type, family?.package_quantity ? `${family.package_quantity} 件` : ""].filter(Boolean).join(" · ") || "未解析";
  const specs = (family?.critical_specs || []).join(" / ") || "无额外规格";
  return [
    ["产品语义", family?.part_type || "未解析"],
    ["车型适配", fitmentText(family)],
    ["位置 / 侧别", `${positions} · ${sides}`],
    ["包装方式", packageText],
    ["关键规格", specs],
    ["身份置信度", confidence(family?.confidence)],
  ].map(([label, content]) => `<div><span>${esc(label)}</span><strong>${esc(content)}</strong></div>`).join("");
}

function queryPack(queryPack) {
  const items = Array.isArray(queryPack) ? queryPack : [];
  return items.length
    ? items.map((item) => `<span class="query-chip" title="${esc(item.query)}">${esc(item.query)}</span>`).join("")
    : "<span class=\"detail-muted\">未生成查询。</span>";
}

function relevantProducts(competition) {
  const observations = Array.isArray(competition?.observations) ? competition.observations : [];
  const products = observations.filter((item) => item.relation === "INTERCHANGEABLE");
  if (!products.length) return "<p class=\"detail-muted\">当前查询未确认可互换商品。</p>";
  return `<div class="product-list">${products.map((item) => {
    const href = validExternalUrl(item.url, /^https:\/\/(?:www\.)?amazon\.com\//i);
    const title = href ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(item.asin || "ASIN")}</a>` : `<span>${esc(item.asin || "ASIN")}</span>`;
    return `<div class="product-row">
      ${title}
      <span class="product-row__title" title="${esc(item.title)}">${esc(item.title || "未命名商品")}</span>
      <span class="product-row__price">${esc(money(item.price_usd))}</span>
    </div>`;
  }).join("")}</div>`;
}

function evidenceGaps(gaps) {
  const items = Array.isArray(gaps) ? gaps : [];
  return items.length
    ? `<ul>${items.map((gap) => `<li class="detail-gap">${esc(gap)}</li>`).join("")}</ul>`
    : "<p class=\"detail-muted\">没有记录关键证据缺口。</p>";
}

function candidateCard(report) {
  const family = report.family || report.resolution?.family || {};
  const competition = report.competition || {};
  const demand = report.demand || {};
  const stages = report.stages || {};
  const [verdict, tone] = decisionMeta[report.decision] || decisionMeta.REVIEW_REQUIRED;
  const identifiers = familyIdentifiers(family);
  const gaps = report.evidence_gaps || [];
  const profile = profileLabel(report.category_profile || report.resolution?.category_profile);
  const title = labels[report.archetype] || family.part_type || "未解析产品家族";
  const competitionStage = stages.amazon_family_competition || {};
  const priceStage = stages.family_price_floor || {};
  const demandStage = stages.demand || {};
  const offerValue = competition.family_offer_count_lower_bound;
  const offerStage = competition.offer_stage || {};
  const detailMeta = gaps.length ? `${gaps.length} 个证据缺口` : "证据链可查看";
  const metricHint = (stage) => stage?.threshold !== null && stage?.threshold !== undefined
    ? `${operatorSymbols[stage.operator] || ""} ${value(stage.threshold)}`.trim()
    : "";

  return `<li class="candidate-card" data-decision="${esc(report.decision)}">
    <header class="candidate-head">
      <span class="rank" aria-label="排序第 ${esc(report.rank)} 位">${esc(String(report.rank || "—").padStart(2, "0"))}</span>
      <div class="candidate-title">
        <div class="candidate-eyebrow">${esc(profile)} · ${esc(report.archetype || "Northway")}</div>
        <h3>${esc(title)}</h3>
        <p class="candidate-fitment">${esc(fitmentText(family))}</p>
        <div class="candidate-identifiers">
          ${identifiers.length ? `<code>OEM ${esc(identifiers.join(" / "))}</code>` : `<code>料号待核对</code>`}
          <span>${esc(packageLabels[family.package_type] || family.package_type || "包装待核对")}</span>
          <span>·</span>
          <span>${esc(family.family_key || report.candidate_id || "family")}</span>
        </div>
      </div>
      <div class="candidate-verdict">
        <span class="verdict" data-tone="${esc(tone)}">${esc(verdict)}</span>
        <span class="candidate-rank-note">${esc(detailMeta)}</span>
      </div>
    </header>

    <div class="metric-grid" aria-label="候选核心读数">
      <div class="metric" data-tone="${esc(stageTone(competitionStage.status))}">
        <span>平替种类</span>
        <strong>${esc(value(competition.competitive_product_cluster_count))}</strong>
        <small>${esc(metricHint(competitionStage))}</small>
      </div>
      <div class="metric" data-tone="${esc(stageTone(competitionStage.status))}">
        <span>相关 ASIN</span>
        <strong>${esc(value(competition.competitive_asin_count))}</strong>
        <small>${esc(value(competition.aftermarket_asin_count, ""))}${competition.aftermarket_asin_count !== undefined ? " 个 aftermarket" : ""}</small>
      </div>
      <div class="metric" data-tone="${esc(stageTone(priceStage.status))}">
        <span>平替最低价</span>
        <strong>${esc(money(competition.aftermarket_family_price_floor_usd ?? competition.family_price_floor_usd))}</strong>
        <small>${esc(metricHint(priceStage))}</small>
      </div>
      <div class="metric" data-tone="${esc(stageTone(demandStage.status))}">
        <span>eBay 销量下界</span>
        <strong>${esc(value(demand.observed_sold_count_lower_bound))}</strong>
        <small>${esc(metricHint(demandStage))}</small>
      </div>
      <div class="metric" data-tone="${esc(stageTone(offerStage.status))}">
        <span>报价下界</span>
        <strong>${esc(value(offerValue))}</strong>
        <small>${offerValue === undefined ? "按 ASIN 汇总" : "seller offers"}</small>
      </div>
    </div>

    <div class="stage-strip" aria-label="筛选阶段">
      ${stageOrder.map((key) => stagePill(key, stages[key])).join("")}
    </div>

    <details class="card-details">
      <summary><span>查看证据链</span><span class="detail-summary-meta">${esc(detailMeta)}</span></summary>
      <div class="detail-body">
        <section class="detail-section">
          <div class="detail-section__head"><span class="detail-section__index">01</span><h4>产品家族</h4></div>
          <div class="fact-list">${familyFacts(family)}</div>
        </section>
        <section class="detail-section">
          <div class="detail-section__head"><span class="detail-section__index">02</span><h4>Amazon 查询包</h4></div>
          <div class="query-list">${queryPack(report.query_pack)}</div>
        </section>
        <section class="detail-section">
          <div class="detail-section__head"><span class="detail-section__index">03</span><h4>确认相关商品</h4></div>
          ${relevantProducts(competition)}
        </section>
        <section class="detail-section">
          <div class="detail-section__head"><span class="detail-section__index">04</span><h4>来源 listing</h4></div>
          <ul class="source-list">${sourceListingRows(report)}</ul>
          <div class="source-links">${sourceLinks(report)}</div>
        </section>
        <section class="detail-section detail-section--wide">
          <div class="detail-section__head"><span class="detail-section__index">05</span><h4>六层读数与判定理由</h4></div>
          <div class="reading-list">${stageReadingRows(stages)}</div>
        </section>
        <section class="detail-section detail-section--wide">
          <div class="detail-section__head"><span class="detail-section__index">06</span><h4>证据缺口</h4></div>
          ${evidenceGaps(gaps)}
        </section>
      </div>
    </details>

    <div class="manual-check" aria-label="人工复核清单">
      <span>核对左右侧、单件 / 套装和关键接口</span>
      <span>在 1688 / 国内供应商确认非原厂对应品</span>
      <span>计算采购、物流、平台费和真实利润</span>
    </div>
  </li>`;
}

function renderCandidateList() {
  const reports = Array.isArray(lastResult?.reports) ? lastResult.reports : [];
  const selected = resultFilters.find(([key]) => key === activeFilter) || resultFilters[0];
  const visible = reports.filter(selected[2]);
  $("#candidateList").innerHTML = visible.map(candidateCard).join("");
  const filterEmpty = $("#filterEmpty");
  filterEmpty.hidden = visible.length > 0;
  filterEmpty.textContent = `${selected[1]}没有候选。`;
  $("#resultFilters").innerHTML = resultFilters.map(([key, label, predicate]) => {
    const count = reports.filter(predicate).length;
    const pressed = key === activeFilter;
    return `<button class="filter-button" type="button" data-filter="${esc(key)}" aria-controls="candidateList" aria-pressed="${pressed}">${esc(label)} <span>${count}</span></button>`;
  }).join("");
}

function coverageStatusText(entry) {
  const status = entry.status || "UNKNOWN";
  const count = entry.candidates_emitted ?? entry.stats?.candidates_emitted ?? 0;
  if (status === "SUCCESS") return count ? `产出 ${count}` : "已完成";
  if (status === "ZERO_RESULTS") return "零结果";
  if (discoveryFailures.has(status)) return "provider 失败";
  return status === "PARTIAL_SUCCESS" ? "部分完成" : "未完成";
}

function renderCoverage(result) {
  const discovery = result.discovery || {};
  const manifest = result.scan_manifest || {};
  const entries = Array.isArray(discovery.per_archetype) && discovery.per_archetype.length
    ? discovery.per_archetype
    : (manifest.discovery_queries || []).map((query) => ({ ...query, status: "NOT_RUN" }));
  const root = $("#coverageList");
  if (!entries.length) {
    root.innerHTML = `<p class="detail-muted">本次结果没有返回按类型拆分的扫描状态。</p>`;
    $("#coverageMeta").textContent = "暂无清单数据";
    return;
  }

  const candidateTypes = entries.filter((entry) => Number(entry.candidates_emitted ?? entry.stats?.candidates_emitted ?? 0) > 0).length;
  const attempted = entries.reduce((total, entry) => total + Number(entry.pages_attempted ?? 0), 0);
  const completed = entries.reduce((total, entry) => total + Number(entry.pages_completed ?? 0), 0);
  $("#coverageMeta").textContent = `${candidateTypes}/${entries.length} 类产出候选 · ${completed}/${attempted || entries.length} 页完成`;
  root.innerHTML = entries.map((entry) => {
    const status = entry.status || "UNKNOWN";
    const profile = profileLabel(entry.category_profile);
    const key = entry.archetype || "unknown";
    const count = entry.candidates_emitted ?? entry.stats?.candidates_emitted ?? 0;
    const pages = entry.pages_attempted !== undefined
      ? `${entry.pages_completed ?? 0}/${entry.pages_attempted ?? 0} 页`
      : "页数待回传";
    return `<div class="coverage-item" data-status="${esc(status)}" data-tone="${discoveryFailures.has(status) ? "error" : ""}">
      <div class="coverage-item__head">
        <span class="coverage-item__dot" aria-hidden="true"></span>
        <span class="coverage-item__label">${esc(labels[key] || key)}</span>
        <span class="coverage-item__status">${esc(coverageStatusText(entry))}</span>
      </div>
      <span class="coverage-item__keyword" title="${esc(entry.keyword || "")}">${esc(profile)} · ${esc(entry.keyword || "关键词待回传")}</span>
      <span class="coverage-item__meta"><span>${esc(pages)}</span><span>${esc(value(count, "0"))} 个候选</span></span>
    </div>`;
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
  const reports = Array.isArray(result.reports) ? result.reports : [];
  const priority = (summary.opportunity_candidates || 0) + (summary.market_shortlist_candidates || 0);
  const cells = [
    [summary.candidate_count ?? reports.length, "全部候选", ""],
    [priority, "优先复核", "pass"],
    [summary.review_required || 0, "需要判断", "review"],
    [summary.rejected || 0, "明确淘汰", "reject"],
    [`${value(budget.used, "0")}/${value(budget.limit, "—")}`, "请求预算", ""],
  ];
  $("#runSummary").innerHTML = cells.map(([number, label, tone]) => `<div class="summary-cell" data-tone="${esc(tone)}"><span>${esc(label)}</span><strong>${esc(value(number))}</strong></div>`).join("");

  const notice = $("#runNotice");
  const messages = [];
  if (!reports.length) {
    messages.push(`发现阶段状态：${result.discovery?.status || "UNKNOWN"}。本次没有生成可复核候选；这不等于市场没有需求，可增加扫描页数后重试。`);
  }
  if (budget.remaining === 0) {
    messages.push("本次请求预算已用尽。已经发现的候选仍被保留，未完成的 Amazon 查询已标记为证据缺口。");
  }
  notice.hidden = !messages.length;
  notice.textContent = messages.join(" ");

  renderCoverage(result);
  renderCandidateList();
  const manifest = result.scan_manifest || {};
  const typeCount = manifest.archetypes?.length ?? archetypeCount;
  const pagesCompleted = manifest.pages_completed ?? 0;
  const pagesAttempted = manifest.pages_attempted ?? pagesCompleted;
  $("#resultSubtitle").textContent = `${typeCount} 类 · ${pagesCompleted}/${pagesAttempted || typeCount} 页完成 · ${reports.length} 个去重产品家族；默认不展示明确淘汰项。`;
}

function showLoading() {
  $("#resultContent").hidden = true;
  $("#exportButton").hidden = true;
  const empty = $("#emptyState");
  empty.hidden = false;
  empty.innerHTML = $("#skeletonTemplate").innerHTML;
}

function showError(message) {
  const empty = $("#emptyState");
  empty.hidden = false;
  $("#resultContent").hidden = true;
  empty.innerHTML = `<div class="empty-state__diagram empty-state__diagram--error" aria-hidden="true"><i>!</i></div><h3>本次扫描没有完成</h3><p>${esc(message)}</p>`;
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
  setRunBusy(true);
  setFormStatus("正在扫描全部零件小类、解析产品家族并搜索 Amazon。请不要关闭本页。");
  showLoading();

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
    showError(error.message);
  } finally {
    setRunBusy(false);
  }
});

$("#exportButton").addEventListener("click", () => {
  if (!activeRunId) return;
  window.location.href = `${API}/northway/runs/${encodeURIComponent(activeRunId)}/export`;
});

boot();
