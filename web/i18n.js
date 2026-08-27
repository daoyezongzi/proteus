/* Proteus copy, both languages.
   Backend reason strings are keyed by their exact English text so evidence
   prose switches too, not just the chrome. If a backend string changes, the
   English falls through unmodified rather than showing a missing-key marker. */

const COPY = {
  zh: {
    "thesis": "把一堆零件号筛到少数值得你花时间的。每个读数都留着来源。",
    "sample.title": "样本",
    "sample.note": "倒进筛网的东西。候选来自eBay Motors近期已售listing。",
    "field.category": "eBay类目",
    "field.category.hint": "6028是汽车零件",
    "field.keyword": "检索关键词",
    "field.keyword.hint": "搜索引擎不能只按类目浏览，样本取自类目内的这个关键词，不是整个类目。",
    "field.candidates": "候选数",
    "field.pages": "读取页数",
    "stack.title": "筛网组",
    "stack.note": "五层筛网，从粗到细。候选必须全部通过。",
    "run": "开始筛选",
    "run.busy": "筛选中…",
    "run.progress": "正在把候选倒进筛网组，这会花一些时间。",
    "empty.title": "还没有运行",
    "empty.body": "设好五层筛孔，然后开始筛选。结果会出现在这里，每一道门都带读数和来源。",
    "unit.sold": "个精确已售listing",
    "unit.competitors": "个精确竞品",
    "unit.usd": "美元",
    "unit.offers": "个在售报价",
    "unit.probe": "个listing",
    "mesh.ebay": "eBay需求",
    "mesh.amazon": "Amazon竞争",
    "mesh.amazonProducts": "Amazon精确商品",
    "mesh.amazonPrice": "Amazon最低价",
    "mesh.amazonOffers": "Amazon卖家/报价",
    "mesh.fitment": "车型适配",
    "op.GT": "大于",
    "op.LTE": "不超过",
    "op.GTE": "不少于",
    "op.probe": "最多查",
    "mustset": "必须填",
    "caveat.notannual": "这是provider能看到的近期子集，不是真正的365天销量。",
    "caveat.offerproxy": "按精确商品卡片显示的在售报价衡量拥挤度；带“+”的读数只是下界，不能用来证明低饱和。",
    "held": (n) => `拦下 ${n}`,
    "tally.screened": (n) => `筛了 ${n} 个候选`,
    "tally.none": "没有发现候选",
    "stat.pass": "值得一看",
    "stat.review": "要你亲自看",
    "stat.reject": "已筛掉",
    "verdict.MVP_OPPORTUNITY_CANDIDATE": "值得一看",
    "verdict.REVIEW_REQUIRED": "要你亲自看",
    "verdict.REJECTED": "已筛掉",
    "notice.boundary.title": "通过意味着什么、不意味着什么",
    "notice.discovery.failed.title": "发现阶段失败",
    "notice.discovery.failed.body": (status, attempted, done, req, cat, kw) =>
      `在类目 ${cat} 内以关键词「${kw}」请求 ${req} 页，尝试 ${attempted} 页，成功读取 ${done} 页。Provider状态：${status}。这不是“没有需求”。`,
    "notice.discovery.zero.title": "发现阶段返回零条结果",
    "notice.discovery.zero.body": (done, req, cat, kw) =>
      `在类目 ${cat} 内以关键词「${kw}」请求 ${req} 页，成功读取 ${done} 页，但provider明确返回零条结果。可以更换关键词后重试。`,
    "notice.discovery.filtered.title": "没有提取出可用候选",
    "notice.discovery.filtered.body": (done, req, cat, kw, seen, sold, withPart, emitted) =>
      `在类目 ${cat} 内以关键词「${kw}」请求 ${req} 页，成功读取 ${done} 页。检查 ${seen} 条结果：${sold} 条有明确销量，${withPart} 条标题含可提取零件号，最终产出 ${emitted} 个候选。`,
    "readings": "读数与来源",
    "needs": (op, t) => `（需要${op} ${t}）`,
    "noreading": "无读数",
    "passedall": "五层全过。动手之前请核对证据。",
    "srclisting": "来源listing ↗",
    "err.unreachable": "接口连不上",
    "err.startapi": "先启动后端：python -m proteus api",
    "err.missing": (names) => `${names} 未配置 — 先运行proteus setup。`,
    "err.rejected": "请求被拒绝。",
    "err.status": (code) => `接口返回 ${code}。`,
    "err.runfailed": "运行失败。",
    "ribbon.ready": "凭证",
    "ribbon.readyval": "就绪",
    "ribbon.missing": "缺少",
    "ribbon.profile": "档位",
    "ribbon.loading": "正在检查配置…",

    /* Backend reason strings, keyed by exact English. */
    "Observed distinct exact sold listings exceed the configured MVP threshold.":
      "观察到的精确已售listing数超过设定阈值。",
    "Provider did not return a valid distinct exact sold-listing count.":
      "Provider没有返回有效的精确已售listing计数。",
    "The provider-visible recent subset does not prove the trailing-year threshold; it is not treated as a rejection.":
      "provider可见的近期子集不足以证明全年阈值；这不算否决。",
    "Complete Amazon US exact competitor count is within the threshold.":
      "完整的Amazon US精确竞品数在阈值内。",
    "Complete Amazon US exact competitor count exceeds the threshold.":
      "完整的Amazon US精确竞品数超过阈值。",
    "Amazon exact-result count is incomplete or unavailable.":
      "Amazon精确结果数不完整或不可用。",
    "Amazon minimum exact-result price is incomplete or unavailable.":
      "Amazon精确结果的最低价不完整或不可用。",
    "Amazon minimum exact-result price is at or below the threshold.":
      "Amazon精确结果最低价等于或低于阈值。",
    "Amazon minimum exact-result price is above the threshold.":
      "Amazon精确结果最低价高于阈值。",
    "Amazon active-offer count is unavailable.":
      "Amazon在售报价数不可用。",
    "Amazon active-offer count lower bound exceeds the seller saturation limit.":
      "Amazon在售报价数下界超过卖家饱和上限。",
    "Amazon active-offer count is only a lower bound and cannot prove the seller limit.":
      "Amazon在售报价数只是下界，无法证明未超过卖家上限。",
    "Complete Amazon active-offer count is within the seller saturation limit.":
      "完整的Amazon在售报价数在卖家饱和上限内。",
    "At least one exact sold listing exposed normalized YMMT fitment.":
      "至少一个精确已售listing给出了规范化的YMMT适配。",
    "No exact sold listing exposed usable automotive compatibility.":
      "没有精确已售listing给出可用的车型适配。",
    "transport URL error": "连接provider搜索端点失败。",
    "transport timed out": "连接provider搜索端点超时。",
    "transport raised an unexpected exception": "连接provider搜索端点时发生异常。",
    "SerpApi returned an API error": "SerpApi返回了API错误。",
    "Not evaluated": "未评估",

    /* Policy boundary text, keyed by its exact committed English. */
    "This heuristic MVP finds review candidates. Amazon price and active-offer gates use provider-visible exact search-card data and fail closed when incomplete. It does not prove strict 365-day eBay units, so every candidate still requires human review.":
      "这条启发式MVP找的是待人工复核的候选。Amazon价格和在售报价门使用provider可见的精确商品卡片数据，数据不完整时不会放行。它不能证明严格的365天eBay销量，因此每个候选仍需人工复核。",
  },

  en: {
    "thesis": "Narrows a pile of part numbers to the few worth your time. Every reading keeps its source.",
    "sample.title": "The sample",
    "sample.note": "What gets poured into the stack. Candidates come from recently sold eBay Motors listings.",
    "field.category": "eBay category",
    "field.category.hint": "6028 is Motors parts",
    "field.keyword": "Search keyword",
    "field.keyword.hint": "The engine cannot browse a category alone. The sample is drawn from this keyword inside the category, not the whole category.",
    "field.candidates": "Candidates",
    "field.pages": "Pages to read",
    "stack.title": "The sieve stack",
    "stack.note": "Five meshes, coarsest first. A candidate has to pass every one.",
    "run": "Run the sieve",
    "run.busy": "Running…",
    "run.progress": "Pouring candidates through the stack. This can take a while.",
    "empty.title": "Nothing has run yet",
    "empty.body": "Set the five apertures, then run the sieve. Results land here with the reading and the source behind every gate.",
    "unit.sold": "distinct sold listings",
    "unit.competitors": "exact competitors",
    "unit.usd": "USD",
    "unit.offers": "active offers",
    "unit.probe": "listings to probe",
    "mesh.ebay": "eBay demand",
    "mesh.amazon": "Amazon competition",
    "mesh.amazonProducts": "Amazon exact products",
    "mesh.amazonPrice": "Amazon minimum price",
    "mesh.amazonOffers": "Amazon sellers / offers",
    "mesh.fitment": "Vehicle fitment",
    "op.GT": "more than",
    "op.LTE": "at most",
    "op.GTE": "at least",
    "op.probe": "check up to",
    "mustset": "must be set",
    "caveat.notannual": "A recent visible subset, not a true 365-day count.",
    "caveat.offerproxy": "Uses active offers shown on exact product cards as a saturation proxy. A '+' reading is only a lower bound and cannot prove low saturation.",
    "held": (n) => `held ${n}`,
    "tally.screened": (n) => `Screened ${n} candidate${n === 1 ? "" : "s"}`,
    "tally.none": "No candidates were discovered",
    "stat.pass": "worth a look",
    "stat.review": "need your eyes",
    "stat.reject": "screened out",
    "verdict.MVP_OPPORTUNITY_CANDIDATE": "Worth a look",
    "verdict.REVIEW_REQUIRED": "Needs your eyes",
    "verdict.REJECTED": "Screened out",
    "notice.boundary.title": "What a pass does and doesn't mean",
    "notice.discovery.failed.title": "Discovery failed",
    "notice.discovery.failed.body": (status, attempted, done, req, cat, kw) =>
      `Requested ${req} page(s) in category ${cat} for "${kw}"; attempted ${attempted} and completed ${done}. Provider status: ${status}. This is not evidence of no demand.`,
    "notice.discovery.zero.title": "Discovery returned zero results",
    "notice.discovery.zero.body": (done, req, cat, kw) =>
      `Requested ${req} page(s) in category ${cat} for "${kw}" and completed ${done}; the provider explicitly returned zero results. Try another keyword.`,
    "notice.discovery.filtered.title": "No usable candidates were extracted",
    "notice.discovery.filtered.body": (done, req, cat, kw, seen, sold, withPart, emitted) =>
      `Requested ${req} page(s) in category ${cat} for "${kw}" and completed ${done}. Checked ${seen} result(s): ${sold} had explicit sales, ${withPart} had an extractable part number in the title, and ${emitted} candidate(s) were emitted.`,
    "readings": "readings and sources",
    "needs": (op, t) => `(needs ${op} ${t})`,
    "noreading": "no reading",
    "passedall": "Passed every mesh. Verify the evidence before acting.",
    "srclisting": "source listing ↗",
    "err.unreachable": "API unreachable",
    "err.startapi": "Start the backend: python -m proteus api",
    "err.missing": (names) => `${names} is not configured — run 'proteus setup' first.`,
    "err.rejected": "The request was rejected.",
    "err.status": (code) => `The API returned ${code}.`,
    "err.runfailed": "The run failed.",
    "ribbon.ready": "credentials",
    "ribbon.readyval": "ready",
    "ribbon.missing": "missing",
    "ribbon.profile": "profile",
    "ribbon.loading": "Checking what's configured…",
  },
};

const STORE_KEY = "proteus.lang";

/* Default to Chinese for zh-* browsers, English otherwise. */
function initialLang() {
  try {
    const saved = localStorage.getItem(STORE_KEY);
    if (saved === "zh" || saved === "en") return saved;
  } catch {}
  return String(navigator.language || "").toLowerCase().startsWith("zh") ? "zh" : "en";
}

let LANG = initialLang();

function setLang(next) {
  LANG = next;
  try { localStorage.setItem(STORE_KEY, next); } catch {}
  document.documentElement.lang = next === "zh" ? "zh-Hans" : "en";
  document.documentElement.dataset.lang = next;
}

/* A Latin run set solid against Han reads cramped, so Chinese copy is written
   without hand-placed spaces and the gap is inserted here instead. Doing it by
   hand double-spaces whenever an interpolated value ends in Han itself. */
const HAN = "\\u3400-\\u4DBF\\u4E00-\\u9FFF\\uF900-\\uFAFF";
const LATIN = "0-9A-Za-z";
const HAN_THEN_LATIN = new RegExp(`([${HAN}])([${LATIN}])`, "g");
const LATIN_THEN_HAN = new RegExp(`([${LATIN}])([${HAN}])`, "g");

function space(text) {
  return text
    .replace(HAN_THEN_LATIN, "$1 $2")
    .replace(LATIN_THEN_HAN, "$1 $2");
}

/* Look up a key; fall through to English, then to the key itself so an
   untranslated backend string still reads correctly. */
function t(key, ...args) {
  const hit = COPY[LANG]?.[key] ?? COPY.en?.[key] ?? key;
  const text = typeof hit === "function" ? hit(...args) : hit;
  return LANG === "zh" ? space(String(text)) : text;
}

function currentLang() { return LANG; }
