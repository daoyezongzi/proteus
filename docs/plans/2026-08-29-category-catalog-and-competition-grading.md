# Working Plan: Category Catalog and Competition Grading

## Goal

Replace the runtime hard-coded Northway category list with a single-user,
versioned SQLite catalog that an Agent can maintain through reviewable JSON,
expose active categories as a two-level selector, and grade completed Amazon
product-family competition as A or A- before rejecting saturated families.

## Context and constraints

- A run still selects exactly one leaf category. The first selector is a
  business grouping, not a broad marketplace query.
- Preserve the current quota-first order: local scope/family/demand, optional
  1688 supplier prefilter, then Amazon for eligible families.
- A is `competitive_product_cluster_count <= 5`; A- is `6..8`; `>= 9` is
  rejected. Incomplete evidence can reject only when its observed lower bound
  is already at least 9; otherwise it remains pending.
- Category creation is conservative by default: import creates an immutable
  `DRAFT`, validation is offline and makes zero provider requests, and only an
  explicit activation changes the frontend choices.
- This is a local single-user feature. Do not add accounts, permissions, a
  web administration console, or a remote taxonomy dependency.
- Broad product-direction discovery from public exploded diagrams is a later
  upstream catalog-generation feature recorded in `TODO.md`; do not couple it
  to this release's category selector or marketplace run path.
- Existing active categories must be seeded without changing their screening
  behavior. Historical runs record the exact category version used.

## Design

- Store category groups, category identities, immutable definition versions,
  activation pointers, and validation reports in an embedded SQLite catalog.
- Use a versioned `CategoryDefinition` JSON contract as the Agent-facing
  interchange and review artifact.
- Provide local CLI operations to validate, create drafts, list/show versions,
  explicitly activate, and explicitly archive categories.
- Treat material/risk group, executable identity profile, aliases, discovery
  query, 1688 keywords, capabilities, risk metadata, and positive/negative
  examples as separate fields.
- Seed `拉线`, `塑料件`, and `低责任金属件` groups. Migrate the existing nine
  leaves into the first two groups; keep the metal group empty until a leaf has
  a validated executable definition.
- Load the active category version at run submission and pass a snapshot into
  the runner so later catalog edits cannot change an in-flight or historical
  run.

## Changes

1. Add the category definition schema, seed data, SQLite catalog, validation,
   CLI workflow, and Agent authoring documentation.
2. Refactor Northway scope/family/Amazon/1688 matching to consume a selected
   category snapshot and record its version.
3. Add configurable A/A- thresholds and evidence-safe competition grades to
   policy, API, reports, compact exports, ranking, and schemas.
4. Replace the category radio list with database-backed group and leaf
   dropdowns; show competition grades and dynamic category labels.
5. Add catalog, API, runner, provider, contract, and boundary tests; update
   README, LOG, and TODO to make V0.2.5 the current behavior.

## Verification

- Focused tests for catalog lifecycle and all competition-grade boundaries.
- Full pytest suite, Python compileall, pip check, JavaScript syntax checks,
  JSON/schema validation, CLI dry-run workflow, and `git diff --check`.
- Inspect the staged diff and run a self-review for evidence semantics,
  database safety, compatibility, secrets, and accidental external calls.
- Commit only task-owned files; do not push.
