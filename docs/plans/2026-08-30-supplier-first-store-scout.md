# Supplier-first Store Scout Working Plan

## Goal

Add a separate “供应商反向选品” workspace that pins one 1688 supplier, takes a
bounded and auditable snapshot of that supplier's store offers, classifies the
observed offers against the current ACTIVE low-risk category catalog, and then
reuses Proteus market evidence to identify A / A- product-family candidates.

This is a new candidate-source direction. It must not replace or silently alter
the existing category/eBay-first Northway workflow.

## 2026-08-30 acquisition revision

Live acceptance showed that the dependency-owned Playwright profile can pass an
initial login but is still placed into layered Alibaba Captcha 2.0 challenges.
Three bounded runs ended as `TIMEOUT` with zero observed offers and
`STORE_BRIDGE_FAILED`. The installed CLI session also enables a stealth plugin
internally, which conflicts with this plan's explicit no-stealth boundary.

The primary acquisition path is therefore revised to a user-triggered local
Manifest V3 Edge extension running inside the user's ordinary signed-in Edge
tab. The user handles login and any CAPTCHA. After the page is normally visible,
the extension may deterministically scroll, extract visible offer cards and
navigate ordinary pagination within explicit limits. It must stop and preserve
partial evidence whenever authentication, risk control or an unrecognized page
appears. It never reads or exports cookies and never attempts CAPTCHA solving.

The existing Playwright bridge remains a fail-closed compatibility path at the
API layer during this revision, but the product UI no longer presents it as the
normal way to clear verification.

## Baseline and current evidence

- Revision baseline is clean at `b1fdda5`; local `main` is two commits ahead of
  `origin/main` before the Edge-collector task starts.
- Example source:
  `https://shop3w093345o1043.1688.com/page/offerlist.htm`.
- The user-supplied Markdown URL duplicated the full URL and included tracking
  parameters. The product must canonicalize this input and reject ambiguous
  multi-URL text instead of treating it as two stores.
- Local `1688-cli` is version `0.1.47`, and its default profile is logged in.
  It supports supplier inspect/search/research but does not expose a supplier
  catalog command. `supplier inspect <offerlist-url>` currently returns
  `BAD_INPUT`; company-search zero results for the shop hostname are not store
  inventory evidence.
- Direct browser navigation to the store list is redirected to a separate login
  session. Store collection therefore needs an explicit provider capability;
  keyword search must not masquerade as a complete store scan.

## Constraints

- Local single-user and loopback-only; no provider cookies, credentials or
  account details enter frontend payloads or Git.
- Read-only acquisition only. No inquiry, 旺旺 message, favorite, cart,
  checkout, order, CAPTCHA bypass, proxy rotation or stealth automation.
- One run pins exactly one canonical supplier identity. Every accepted offer
  must bind back to that supplier identity.
- Page and offer bounds are explicit. Reaching a bound produces `PARTIAL`, not
  a false complete-store claim.
- Provider failure, authentication required, risk control, parser failure,
  partial acquisition and genuine empty inventory remain distinct.
- All offers observed within the source boundary remain in the result. Market
  budget exhaustion marks unprocessed offers `NOT_RUN_BUDGET`; it does not drop
  them.
- Amazon A / A- remains a product-family competition grade independent of
  supplier quality, price and final opportunity qualification.

## Design

### 1. Supplier source and URL normalization

Introduce a supplier-source model keyed by an internal ID and stable 1688
identity (`memberId` when available). V0.2.6 accepts a store offer-list URL and
preserves the submitted value as evidence while executing only a canonical
HTTPS 1688 URL without tracking parameters. A raw member ID or offer URL is not
accepted as a runnable store source until a stable supplier-resolution provider
exists; keyword or hostname search must not impersonate that resolution.

The URL boundary must:

- accept only `1688.com` and its subdomains;
- reject embedded credentials, non-HTTPS execution URLs and unrelated hosts;
- detect concatenated/repeated `http(s)://` values;
- normalize the supplied example to its single `/page/offerlist.htm` URL;
- never trust the shop hostname alone as the final supplier identity when a
  stronger `memberId` can be observed.

### 2. Bounded supplier catalog provider

Add a provider-neutral `SupplierCatalogProvider` contract with two read-only
operations:

1. `inspect_supplier(target)` returns normalized identity/trust evidence.
2. `collect_store_offers(source, max_pages, max_offers)` returns a normalized
   inventory snapshot with page-completeness evidence.

Use a project-owned, locally sideloaded MV3 Edge extension as the primary
collector. A Proteus capture session binds one saved supplier, one short-lived
opaque token, one page limit and one offer limit. After an explicit toolbar
click, the extension claims the newest matching pending session, extracts only
the normally rendered supplier-list page and posts normalized page evidence to
the loopback API. The backend validates supplier/page binding, sequential page
numbers and offer IDs, deduplicates across pages, and alone decides whether the
snapshot is complete, partial or blocked.

The extension is plain packaged HTML/CSS/JavaScript under
`browser-extension/supplier-collector/` with no remote code and narrowly scoped
permissions for `https://*.1688.com/*` and the loopback Proteus API. Selector
profiles are non-executable JSON served by Proteus so an Agent can update page
structure matching without changing evidence semantics.

Retain explicit JSON/CSV or saved-page import as a later fallback; do not label
an imported or bounded observation as a complete store unless end-of-pagination
evidence proves it.

Normalized snapshot fields include supplier identity, submitted/canonical URL,
retrieval time, pages attempted/completed, observed/available offer counts,
next-page evidence, acquisition status, completeness, warnings, and offers with
offer ID, title, URL, image, price/MOQ when observed, attributes/SKUs when
observed, and supplier identity.

### 3. Local persistence and immutable run snapshot

Use a separate `%LOCALAPPDATA%/Proteus/supplier_scout.sqlite3` so this feature
does not migrate or overload the existing category database. Persist:

- saved supplier sources;
- supplier inspection evidence;
- immutable inventory snapshots and observed offers;
- hashes/timestamps needed to reuse unchanged observations.

Each run records its supplier source, inventory snapshot, ACTIVE category
versions and configured bounds. Initial asynchronous run envelopes can reuse
the existing in-memory manager; the expensive source snapshot itself must
survive a service restart.

### 4. Supplier-first screening runner

Run the following bounded sequence:

```text
supplier identity
-> bounded store snapshot
-> exact supplier binding and offer deduplication
-> match against all selected ACTIVE leaf categories
-> product-family identity resolution
-> exact eBay demand evidence
-> Amazon family-query aggregation and A/A- grading
-> complete review/export result
```

Reuse category definitions, family resolution, SerpApi provider adapters,
Amazon query/aggregation logic, grade thresholds and evidence semantics. Do not
reuse the entire Northway runner because its candidate source and demand flow
start from eBay.

Offers matching no ACTIVE leaf remain `CATEGORY_UNMATCHED`; multiple matches
remain `CATEGORY_AMBIGUOUS`. Offers without a usable part number or sufficiently
resolved part type/fitment remain `IDENTITY_INCOMPLETE` and do not consume
market requests. Explicit market-check bounds preserve remaining items as
`NOT_RUN_BUDGET` for a later continuation.

### 5. API and frontend workspace

Add an independent API namespace:

```text
GET  /api/v1/supplier-scout/policy
GET  /api/v1/supplier-scout/suppliers
POST /api/v1/supplier-scout/suppliers/inspect
POST /api/v1/supplier-scout/suppliers
POST /api/v1/supplier-scout/captures
GET  /api/v1/supplier-scout/captures/pending
GET  /api/v1/supplier-scout/captures/{capture_id}
POST /api/v1/supplier-scout/captures/{capture_id}/claim
POST /api/v1/supplier-scout/captures/{capture_id}/pages
POST /api/v1/supplier-scout/captures/{capture_id}/pause
POST /api/v1/supplier-scout/runs
GET  /api/v1/supplier-scout/runs/{run_id}
GET  /api/v1/supplier-scout/runs/{run_id}/export/compact
GET  /api/v1/supplier-scout/runs/{run_id}/export
```

Add “供应商反向选品” to the sidebar as a separate static page/module rather
than further coupling the existing Northway form. The view includes supplier
verification, an Edge-collector setup/status panel, source/page/offer and market
budgets, ACTIVE category scope, progress, inventory completeness, evidence
warnings, result filters and JSON exports. It must state observations such as
“60 observed / source still has a next page: PARTIAL” plainly. A market run may
reference a same-supplier immutable captured snapshot and must not reacquire the
store when that snapshot is supplied.

## Scope

### In scope

- one saved/selected supplier per run;
- bounded store inventory capture or explicit import fallback;
- all currently executable ACTIVE low-risk automotive leaf categories;
- deterministic identity/scope triage before provider spending;
- existing eBay/Amazon evidence and A/A- semantics;
- local persistence, API, native HTML/CSS/JS, contracts, tests and exports.

### Out of scope

- unbounded/full-site crawling;
- contacting or scoring suppliers into an automatic reject decision;
- automatic category activation;
- LLM-only product identity claims;
- unit economics, purchasing, messaging or order operations;
- claiming unobserved store inventory has no candidates.

## Execution steps

1. Freeze URL, supplier, inventory snapshot and result contracts with fixtures
   and failing tests.
2. Implement and test short-lived capture sessions, sequential page ingestion,
   supplier binding, deduplication and immutable snapshot sealing.
3. Implement the local MV3 Edge extension and selector-profile contract.
4. Connect captured snapshots to the existing supplier-first market runner.
5. Implement supplier-first classification and market runner using reusable
   Northway/provider helpers.
6. Add API models, async manager integration and bounded exports.
7. Add the separate navigation workspace and dynamic result states.
8. Run unit/contract/full-suite tests, package checks, static extension checks
   and a local browser fixture acceptance; real 1688 acceptance still requires
   the user's ordinary signed-in Edge session.
9. Update `README.md`, `LOG.md` and `TODO.md`, inspect the complete diff, then
   commit task-owned changes without pushing.

## Verification

- URL tests cover the duplicated user input, tracking removal, allowed hosts,
  credentials, schemes and multiple-URL ambiguity.
- Catalog fixtures cover complete, partial, empty, authentication, risk-control,
  timeout, malformed payload, duplicate offer and supplier-mismatch outcomes.
- Capture tests cover token rejection, expiry, same-host claim, sequential and
  idempotent pages, duplicate offers, explicit empty evidence, page/offer bounds,
  blocked-page pause and same-supplier snapshot reuse.
- Persistence tests prove immutable snapshots and no category-database impact.
- Runner tests prove category unmatched/ambiguous, identity incomplete,
  market-budget preservation, A/A-/pending/rejected semantics and complete
  evidence export.
- API tests cover request bounds, inactive categories, source snapshot binding,
  status polling and both exports.
- A live read-only canary must make no write command and must not claim
  completeness unless pagination evidence proves it.
- Browser acceptance covers navigation, supplier verification, partial coverage,
  extension setup, capture creation/progress, filters, errors, exports and zero
  console errors. The extension fixture verifies offer extraction, risk-control
  detection and next-page discovery without contacting 1688.
- Final gates: full pytest suite, Python compilation, dependency check,
  JavaScript syntax, JSON parse/schema checks, `git diff --check`, build/install
  smoke and staged-diff self-review.

## Risks and rollback

- 1688 store payloads and login/risk-control behavior may drift. Isolate the
  collector, version-gate fragile integration and retain raw bounded evidence.
- A store card may represent variants or several product families. Never infer
  one family per offer when SKU/fitment evidence conflicts.
- Market cost can grow with store size. Separate source bounds from market
  request budgets and preserve resumable not-run items.
- The feature is additive. Rollback removes the supplier-scout routes/page and
  provider while leaving existing Northway and its category database untouched.
