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
    "field.candidates": "候选数",
    "field.pages": "读取页数",
    "stack.title": "筛网组",
    "stack.note": "四层筛网，从粗到细。候选必须全部通过。",
    "run": "开始筛选",
    "run.busy": "筛选中…",
    "run.progress": "正在把候选倒进筛网组，这会花一些时间。",
    "empty.title": "还没有运行",
    "empty.body": "设好四层筛孔，然后开始筛选。结果会出现在这里，每一道门都带读数和来源。",
    "unit.sold": "个精确已售listing",
    "unit.competitors": "个精确竞品",
    "unit.probe": "个listing",
    "unit.vehicles": "辆在册车辆",
    "mesh.ebay": "eBay需求",
    "mesh.amazon": "Amazon竞争",
    "mesh.fitment": "车型适配",
    "mesh.vehicles": "路上的车",
    "op.GT": "大于",
    "op.LTE": "不超过",
    "op.GTE": "不少于",
    "op.probe": "最多查",
    "mustset": "必须填",
    "caveat.notannual": "这是provider能看到的近期子集，不是真正的365天销量。",
    "caveat.notvio": (where) => `由${where}估算 — 不是官方全美保有量。`,
    "caveat.stateonly": (code) => `${code}一个州`,
    "caveat.proxy": "代理指标",
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
    "notice.empty.title": "发现阶段没有返回结果",
    "notice.empty.body": (done, req, cat) =>
      `在类目 ${cat} 读了 ${req} 页中的 ${done} 页。空结果不等于没有需求 — 也可能是provider失败了。`,
    "readings": "读数与来源",
    "needs": (op, t) => `（需要${op} ${t}）`,
    "noreading": "无读数",
    "passedall": "四层全过。动手之前请核对证据。",
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
    "At least one exact sold listing exposed normalized YMMT fitment.":
      "至少一个精确已售listing给出了规范化的YMMT适配。",
    "No exact sold listing exposed usable automotive compatibility.":
      "没有精确已售listing给出可用的车型适配。",
    "Complete New York registration model estimate meets the MVP threshold.":
      "完整的纽约州在册车型估算达到阈值。",
    "Complete New York registration model estimate is unavailable.":
      "纽约州在册车型估算不可用。",
    "New York registration estimate is below threshold, but one-state sampled coverage cannot decisively reject nationwide vehicle population.":
      "纽约州在册估算低于阈值，但单州抽样覆盖不足以否决全美保有量。",
    "Not evaluated": "未评估",

    /* Policy boundary text, keyed by its exact committed English. */
    "This heuristic MVP finds review candidates. It does not prove strict 365-day eBay units or official nationwide vehicles-in-operation. The vehicle gate is a New York model estimate and requires human review.":
      "这条启发式MVP找的是待人工复核的候选。它不能证明严格的365天eBay销量，也不能证明官方全美保有量。车辆这一门是纽约州的车型估算，必须人工复核。",
  },

  en: {
    "thesis": "Narrows a pile of part numbers to the few worth your time. Every reading keeps its source.",
    "sample.title": "The sample",
    "sample.note": "What gets poured into the stack. Candidates come from recently sold eBay Motors listings.",
    "field.category": "eBay category",
    "field.category.hint": "6028 is Motors parts",
    "field.candidates": "Candidates",
    "field.pages": "Pages to read",
    "stack.title": "The sieve stack",
    "stack.note": "Four meshes, coarsest first. A candidate has to pass every one.",
    "run": "Run the sieve",
    "run.busy": "Running…",
    "run.progress": "Pouring candidates through the stack. This can take a while.",
    "empty.title": "Nothing has run yet",
    "empty.body": "Set the four apertures, then run the sieve. Results land here with the reading and the source behind every gate.",
    "unit.sold": "distinct sold listings",
    "unit.competitors": "exact competitors",
    "unit.probe": "listings to probe",
    "unit.vehicles": "registered vehicles",
    "mesh.ebay": "eBay demand",
    "mesh.amazon": "Amazon competition",
    "mesh.fitment": "Vehicle fitment",
    "mesh.vehicles": "Vehicles on the road",
    "op.GT": "more than",
    "op.LTE": "at most",
    "op.GTE": "at least",
    "op.probe": "check up to",
    "mustset": "must be set",
    "caveat.notannual": "A recent visible subset, not a true 365-day count.",
    "caveat.notvio": (where) => `Estimated from ${where} — not official nationwide VIO.`,
    "caveat.stateonly": (code) => `${code} only`,
    "caveat.proxy": "a proxy",
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
    "notice.empty.title": "Discovery returned nothing",
    "notice.empty.body": (done, req, cat) =>
      `Read ${done} of ${req} page(s) in category ${cat}. An empty result is not evidence of no demand — the provider may have failed.`,
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
