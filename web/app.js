/* Proteus operator bench.
   Talks only to the local Proteus API. No third-party keys ever reach the browser.

   Mesh labels, operators, defaults and caveats hydrate from /api/v1/mvp/policy,
   so a backend provider swap (MarketCheck -> NY DMV, and whatever follows)
   changes this UI without an edit here. */

const API = "/api/v1";

/* Stage keys in funnel order; these match automatic_mvp.py report["stages"]. */
const MESHES = [
  {
    stage: "ebay_recent_sold_lower_bound",
    criterion: "ebay_recent_sold_lower_bound",
    field: "min_ebay_trailing_year_units_exclusive",
    name: "mesh.ebay",
    unit: "unit.sold",
  },
  {
    stage: "amazon_us_competition",
    criterion: "amazon_us_exact_competitors",
    field: "max_amazon_us_exact_competitors",
    name: "mesh.amazon",
    unit: "unit.competitors",
  },
  {
    stage: "ebay_compatibility",
    criterion: null,
    field: "max_fitment_listings",
    name: "mesh.fitment",
    unit: "unit.probe",
  },
  {
    stage: "us_active_vehicle_proxy",
    criterion: "us_active_vehicle_proxy",
    field: "min_us_active_vins",
    name: "mesh.vehicles",
    unit: "unit.vehicles",
  },
];

const els = {
  ribbon: document.getElementById("ribbon"),
  stack: document.getElementById("stack"),
  form: document.getElementById("runForm"),
  button: document.getElementById("runButton"),
  note: document.getElementById("actionNote"),
  results: document.getElementById("results"),
};

let policy = null;
let lastResult = null;   // kept so a language switch can re-render in place
let noteState = null;    // {key, args, tone}

/* ---------- helpers ---------- */

const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

const num = (v) =>
  typeof v === "number" && Number.isFinite(v) ? v.toLocaleString("en-US") : null;

/* Backend prose may arrive with line-wrap whitespace; collapse before lookup. */
const reason = (s) => (s ? t(String(s).replace(/\s+/g, " ").trim()) : "");

async function getJSON(path) {
  const res = await fetch(`${API}${path}`, { headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(String(res.status));
  return res.json();
}

function setNote(key, tone, ...args) {
  noteState = key ? { key, args, tone } : null;
  els.note.textContent = key ? t(key, ...args) : "";
  if (tone) els.note.dataset.tone = tone;
  else delete els.note.dataset.tone;
}

/* ---------- static copy ---------- */

function applyStaticCopy() {
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  document.title = currentLang() === "zh" ? "Proteus — 选品筛选" : "Proteus — parts screening";
  document.querySelectorAll("#lang .lang__opt").forEach((b) => {
    b.setAttribute("aria-pressed", String(b.dataset.lang === currentLang()));
  });
  if (noteState) setNote(noteState.key, noteState.tone, ...noteState.args);
}

/* ---------- masthead ribbon ---------- */

let ribbonState = null;

function renderRibbon() {
  if (!ribbonState) {
    els.ribbon.innerHTML = `<span class="ribbon__item">${esc(t("ribbon.loading"))}</span>`;
    return;
  }
  if (ribbonState.down) {
    els.ribbon.innerHTML =
      `<span class="ribbon__item" data-state="missing"><b>${esc(t("err.unreachable"))}</b></span>`;
    return;
  }
  const { version, profile, missing } = ribbonState;
  els.ribbon.innerHTML = [
    `<span class="ribbon__item">v<b>${esc(version)}</b></span>`,
    `<span class="ribbon__item">${esc(t("ribbon.profile"))} <b>${esc(profile)}</b></span>`,
    missing.length
      ? `<span class="ribbon__item" data-state="missing">${esc(t("ribbon.missing"))} <b>${missing
          .map(esc)
          .join(", ")}</b></span>`
      : `<span class="ribbon__item">${esc(t("ribbon.ready"))} <b>${esc(
          t("ribbon.readyval")
        )}</b></span>`,
  ].join("");
}

async function loadRibbon() {
  try {
    const [health, config] = await Promise.all([
      getJSON("/health"),
      getJSON("/config/status"),
    ]);
    const required = config.required_credentials || [];
    const missing = required.filter((n) => !config.credentials?.[n]?.configured);
    ribbonState = { version: health.version, profile: health.profile, missing };
    renderRibbon();
    if (missing.length) {
      setNote("err.missing", "flag", missing.join(", "));
      els.button.disabled = true;
    }
  } catch {
    ribbonState = { down: true };
    renderRibbon();
    setNote("err.startapi", "flag");
    els.button.disabled = true;
  }
}

/* ---------- the sieve stack ---------- */

function meshRow(mesh, index) {
  const crit = mesh.criterion ? policy?.criteria?.[mesh.criterion] : null;
  const op = crit?.operator;
  const dflt = crit?.default_threshold;
  const mustSet = crit?.threshold_required_per_run === true;
  const isProbe = mesh.criterion === null;

  /* Preserve a value the operator already typed across a language switch. */
  const typed = document.getElementById(mesh.field)?.value;
  const value =
    typed !== undefined && typed !== ""
      ? typed
      : dflt ?? (isProbe ? 3 : "");

  const prose = op ? t(`op.${op}`) : t("op.probe");

  const caveats = [];
  if (crit?.strict_365_day_metric === false) caveats.push(t("caveat.notannual"));
  if (crit?.official_vio === false) {
    const where = crit.state_code
      ? t("caveat.stateonly", crit.state_code)
      : t("caveat.proxy");
    caveats.push(t("caveat.notvio", where));
  }

  return `
    <li class="mesh" data-stage="${esc(mesh.stage)}">
      <div class="mesh__head">
        <span class="mesh__grade">${index + 1}</span>
        <span class="mesh__name">${esc(t(mesh.name))}</span>
        <span class="mesh__held" data-held="${esc(mesh.stage)}"></span>
      </div>
      <div class="mesh__control">
        <span class="mesh__op">${esc(prose)}</span>
        <input class="mesh__input"
               id="${esc(mesh.field)}"
               name="${esc(mesh.field)}"
               type="number"
               min="${isProbe ? 1 : 0}"
               value="${esc(value)}"
               ${mustSet ? "required" : ""}>
        <span class="mesh__op">${esc(t(mesh.unit))}</span>
        ${mustSet ? `<span class="mesh__required">${esc(t("mustset"))}</span>` : ""}
      </div>
      ${
        caveats.length
          ? `<em class="mesh__caveat${
              crit?.official_vio === false ? " mesh__caveat--flag" : ""
            }">${esc(caveats.join(" "))}</em>`
          : ""
      }
    </li>`;
}

function renderStack() {
  els.stack.innerHTML = MESHES.map(meshRow).join("");
}

async function loadPolicy() {
  try {
    policy = await getJSON("/mvp/policy");
  } catch {
    policy = null;
  }
  renderStack();
}

/* ---------- results ---------- */

function traceBars(stages) {
  return MESHES.map((m) => {
    const st = stages?.[m.stage]?.status || "NOT_RUN";
    return `<span class="trace__bar" data-status="${esc(st)}" title="${esc(
      t(m.name)
    )}"></span>`;
  }).join("");
}

function readingRow(mesh, stage) {
  if (!stage) return "";
  const status = stage.status || "NOT_RUN";
  const value = num(stage.value);
  const op = stage.operator ? t(`op.${stage.operator}`) : null;
  const threshold = num(stage.threshold);

  const reading =
    value === null
      ? esc(t("noreading"))
      : op && threshold !== null
      ? `${esc(value)} <span style="color:var(--soft)">${esc(
          t("needs", op, threshold)
        )}</span>`
      : esc(value);

  const src = [stage.provider_status, stage.retrieved_at].filter(Boolean).map(esc);

  return `
    <div class="reading">
      <span class="reading__gate">${esc(t(mesh.name))}</span>
      <span class="reading__value" data-status="${esc(status)}">${reading}</span>
      <span class="reading__why">${esc(reason(stage.reason))}</span>
      ${src.length ? `<span class="reading__src">${src.join(" · ")}</span>` : ""}
    </div>`;
}

function candidateRow(report) {
  const pn = report.part_number || {};
  const decision = report.decision || "REVIEW_REQUIRED";
  const stages = report.stages || {};
  const src = report.source || {};

  /* Surface the gate that actually decided this candidate's fate. */
  const decisive = MESHES.map((m) => stages[m.stage]).find(
    (s) => s && (s.status === "REJECTED" || s.status === "REVIEW_REQUIRED")
  );
  const why = decisive ? reason(decisive.reason) : t("passedall");

  return `
    <li class="catch__row" data-decision="${esc(decision)}">
      <div class="catch__head">
        <span class="catch__pn">${esc(pn.raw || "—")}</span>
        <span class="verdict" data-decision="${esc(decision)}">${esc(
          t(`verdict.${decision}`)
        )}</span>
        <span class="trace">${traceBars(stages)}</span>
      </div>
      ${
        src.source_listing_title
          ? `<p class="catch__title">${esc(src.source_listing_title)}</p>`
          : ""
      }
      <p class="catch__why">${esc(why)}</p>
      ${
        src.source_listing_url
          ? `<a class="catch__link" href="${esc(
              src.source_listing_url
            )}" target="_blank" rel="noopener noreferrer">${esc(t("srclisting"))}</a>`
          : ""
      }
      <details class="readings">
        <summary>${esc(t("readings"))}</summary>
        ${MESHES.map((m) => readingRow(m, stages[m.stage])).join("")}
      </details>
    </li>`;
}

function renderEmpty() {
  els.results.innerHTML = `
    <div class="empty">
      <h2 class="empty__title">${esc(t("empty.title"))}</h2>
      <p class="empty__body">${esc(t("empty.body"))}</p>
    </div>`;
}

function renderResult(result) {
  lastResult = result;
  const reports = Array.isArray(result.reports) ? result.reports : [];
  const s = result.summary || {};
  const disc = result.discovery || {};

  /* How many candidates each mesh actually held back. */
  MESHES.forEach((m) => {
    const held = reports.filter((r) => {
      const st = r.stages?.[m.stage]?.status;
      return st === "REJECTED" || st === "REVIEW_REQUIRED";
    }).length;
    const el = els.stack.querySelector(`[data-held="${m.stage}"]`);
    if (el) el.textContent = held ? t("held", held) : "";
  });

  /* Order: candidates first, ambiguity next, clean rejections last. */
  const rank = { MVP_OPPORTUNITY_CANDIDATE: 0, REVIEW_REQUIRED: 1, REJECTED: 2 };
  const sorted = [...reports].sort(
    (a, b) => (rank[a.decision] ?? 3) - (rank[b.decision] ?? 3)
  );

  const boundary = policy?.qualification_boundary;

  els.results.innerHTML = `
    <div class="tally">
      <p class="tally__lead">${esc(
        reports.length ? t("tally.screened", reports.length) : t("tally.none")
      )}</p>
      <span class="tally__stat" data-tone="pass"><b>${
        s.mvp_opportunity_candidates ?? 0
      }</b>${esc(t("stat.pass"))}</span>
      <span class="tally__stat" data-tone="review"><b>${
        s.review_required ?? 0
      }</b>${esc(t("stat.review"))}</span>
      <span class="tally__stat"><b>${s.rejected ?? 0}</b>${esc(
        t("stat.reject")
      )}</span>
    </div>

    ${
      boundary
        ? `<div class="notice">
             <h3 class="notice__title">${esc(t("notice.boundary.title"))}</h3>
             <p>${esc(reason(boundary))}</p>
           </div>`
        : ""
    }

    ${
      !reports.length
        ? `<div class="notice">
             <h3 class="notice__title">${esc(t("notice.empty.title"))}</h3>
             <p>${esc(
               t(
                 "notice.empty.body",
                 disc.pages_completed ?? 0,
                 disc.pages_requested ?? 0,
                 disc.category_id ?? "—",
                 disc.keyword ?? "—"
               )
             )}</p>
           </div>`
        : `<ul class="catch">${sorted.map(candidateRow).join("")}</ul>`
    }
  `;
}

/* ---------- run ---------- */

function collect() {
  const body = {
    ebay_category_id: document.getElementById("ebay_category_id").value.trim(),
    discovery_keyword: document.getElementById("discovery_keyword").value.trim(),
    max_candidates: Number(document.getElementById("max_candidates").value),
    discovery_pages: Number(document.getElementById("discovery_pages").value),
  };
  for (const m of MESHES) {
    const el = document.getElementById(m.field);
    if (el && el.value !== "") body[m.field] = Number(el.value);
  }
  return body;
}

async function submitRun(body) {
  const res = await fetch(`${API}/mvp/runs`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.status === 422) {
    const detail = await res.json().catch(() => null);
    const first = detail?.detail?.[0];
    throw new Error(
      first ? `${first.loc?.slice(-1)[0]}: ${first.msg}` : t("err.rejected")
    );
  }
  if (!res.ok) throw new Error(t("err.status", res.status));
  return res.json();
}

/* One run, one read. The backend executes on a single worker thread, so read
   until the record settles rather than leaving the operator guessing. */
async function awaitRun(runId) {
  for (;;) {
    const run = await getJSON(`/mvp/runs/${encodeURIComponent(runId)}`);
    if (run.status === "COMPLETED") return run;
    if (run.status === "FAILED") throw new Error(run.error?.message || t("err.runfailed"));
    await new Promise((r) => setTimeout(r, 1200));
  }
}

els.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!els.form.reportValidity()) return;

  els.button.disabled = true;
  els.button.textContent = t("run.busy");
  setNote("run.progress");

  try {
    const { run_id } = await submitRun(collect());
    const run = await awaitRun(run_id);
    renderResult(run.result || {});
    setNote(null);
  } catch (error) {
    els.note.textContent = error.message;
    els.note.dataset.tone = "flag";
    noteState = null;
  } finally {
    els.button.disabled = false;
    els.button.textContent = t("run");
  }
});

/* ---------- language ---------- */

/* Delegated from the document so a cached or partial DOM cannot throw here and
   abort the rest of boot — the form must stay usable either way. */
document.addEventListener("click", (event) => {
  const button = event.target.closest("#lang [data-lang]");
  if (!button || button.dataset.lang === currentLang()) return;
  setLang(button.dataset.lang);
  applyStaticCopy();
  renderStack();
  renderRibbon();
  if (lastResult) renderResult(lastResult);
  else renderEmpty();
});

/* ---------- boot ---------- */

setLang(currentLang());
applyStaticCopy();
renderRibbon();
renderEmpty();
loadPolicy().then(loadRibbon);
