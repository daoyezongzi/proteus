# Supplier-first Store Scout Working Plan — JSON import revision

## Goal

Add a separate “供应商反向选品” workspace that pins one 1688 supplier, imports
a user/Agent-produced JSON inventory snapshot, classifies the imported offers
against the current ACTIVE low-risk category catalog, and then reuses Proteus
market evidence to identify A / A- product-family candidates.

This is a new candidate-source direction. It must not replace or silently alter
the existing category/eBay-first Northway workflow.

## 2026-08-30 acquisition revision — JSON import is the only product path

The Edge/Playwright acquisition path is withdrawn from the product workflow.
The browser extension and capture API are retained only as legacy compatibility
code for existing local evidence; the UI must not create capture tasks and a new
run must never acquire a store implicitly.

The supported path is a local JSON file produced by the user or the user's own
Agent. The Agent may use any permitted 1688 workflow, handle login/CAPTCHA, and
write the stable import contract below. Proteus only validates the file, binds it
to the selected saved supplier, seals an immutable snapshot, and runs the
existing market analysis. No browser credentials, cookies or external collector
are needed by Proteus.

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
- Import size and offer-count bounds are explicit. An incomplete imported file
  produces `PARTIAL`, not a false complete-store claim.
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

### 2. Supplier inventory JSON import

Define a stable public `proteus.supplier_inventory` version-1 contract. The
top-level document contains the supplier URL/identity, capture metadata and an
`offers` array. Each offer must have a numeric `offer_id`, non-empty `title`,
canonical HTTPS 1688 detail URL and may carry image, price, MOQ, attributes or
other bounded metadata.

The importer must:

- validate the format/version and bounded JSON size/offer count;
- normalize the supplier URL and require it to match the selected saved source;
- reject a conflicting member ID or offer ID/detail URL;
- deduplicate by offer ID without silently dropping the duplicate count;
- preserve valid rows, invalid-row diagnostics and a canonical document hash;
- derive `SUCCESS`, `PARTIAL` or `EMPTY` only from explicit completeness metadata;
- never accept `supplier_id` from the file, execute file content, or fetch URLs.

The public import document is converted to the existing internal immutable
snapshot schema. This keeps the current classifier, family resolver, eBay/Amazon
providers and exports unchanged. An imported partial snapshot can be analyzed
when it contains offers, but it must remain visibly partial; an empty or blocked
file cannot be interpreted as a successful empty store.

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
POST /api/v1/supplier-scout/suppliers/{supplier_id}/snapshots/import
POST /api/v1/supplier-scout/runs
GET  /api/v1/supplier-scout/runs/{run_id}
GET  /api/v1/supplier-scout/runs/{run_id}/export/compact
GET  /api/v1/supplier-scout/runs/{run_id}/export
```

Add “供应商反向选品” to the sidebar as a separate static page/module rather
than further coupling the existing Northway form. The view includes supplier
selection, a JSON file picker, validation/preview status, imported coverage,
ACTIVE category scope, market budgets, progress, evidence warnings, result
filters and JSON exports. It must state observations such as “60 imported / the
source declared PARTIAL” plainly. A market run must reference a same-supplier
immutable imported snapshot and must never reacquire the store.

## Scope

### In scope

- one saved/selected supplier per run;
- explicit user/Agent JSON inventory import;
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

1. Freeze URL, supplier, import document and snapshot contracts with fixtures
   and failing tests.
2. Implement and test JSON validation, supplier binding, deduplication, file
   hashing and immutable snapshot sealing.
3. Require an imported snapshot before supplier-first runs and remove implicit
   collector acquisition from the service path.
4. Connect imported snapshots to the existing supplier-first market runner.
5. Implement supplier-first classification and market runner using reusable
   Northway/provider helpers.
6. Add API models, async manager integration and bounded exports.
7. Add the separate navigation workspace and dynamic JSON import/result states.
8. Run unit/contract/full-suite tests, package checks and local API/browser
   acceptance; no real 1688 browser acceptance is required for this path.
9. Update `README.md`, `LOG.md` and `TODO.md`, inspect the complete diff, then
   commit task-owned changes without pushing.

## Verification

- URL tests cover the duplicated user input, tracking removal, allowed hosts,
  credentials, schemes and multiple-URL ambiguity.
- Import fixtures cover complete, partial, empty, malformed payload, duplicate
  offer, supplier mismatch, URL/ID mismatch, invalid rows and oversized files.
- Import tests prove file hashing, immutable snapshots, explicit completeness and
  same-supplier snapshot reuse; no run may trigger a collector without a snapshot.
- Persistence tests prove immutable snapshots and no category-database impact.
- Runner tests prove category unmatched/ambiguous, identity incomplete,
  market-budget preservation, A/A-/pending/rejected semantics and complete
  evidence export.
- API tests cover request bounds, inactive categories, source snapshot binding,
  status polling and both exports.
- Import API/CLI acceptance must make no network request, seal only after
  contract validation, and must not claim completeness unless the JSON metadata
  proves it.
- Browser acceptance covers navigation, supplier verification, JSON picker,
  validation preview, partial coverage, filters, errors, exports and zero console
  errors.
- Final gates: full pytest suite, Python compilation, dependency check,
  JavaScript syntax, JSON parse/schema checks, `git diff --check`, build/install
  smoke and staged-diff self-review.

## Risks and rollback

- User/Agent export formats may drift. Version the import contract, validate it
  before persistence and retain the original file hash and bounded diagnostics.
- A store card may represent variants or several product families. Never infer
  one family per offer when SKU/fitment evidence conflicts.
- Market cost can grow with store size. Separate source bounds from market
  request budgets and preserve resumable not-run items.
- The feature is additive. Rollback removes only the JSON import route/page and
  provider while leaving existing Northway, category data and historical
  snapshots untouched. Legacy Edge capture code may remain unreachable for
  compatibility, but it must not be advertised or invoked by new runs.
