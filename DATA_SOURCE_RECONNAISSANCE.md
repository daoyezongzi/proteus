# Proteus V0 — Data Source Reconnaissance

> Snapshot date: 2026-08-25
> Scope: Phase 0 initial feasibility boundary
> Fixtures: `53630-53010`, `A18-67004-004`

## 1. Executive conclusion

Proteus remains feasible as a constrained, human-in-the-loop proof of concept.
The current evidence does **not** support building the complete three-platform,
anonymous, HTTP-first funnel yet.

Current go/hold boundary:

| Path | Status | Boundary |
|---|---|---|
| eBay browser vertical slice | **GO** | Both fixtures are discoverable and listing-level sold evidence is reproducible. Use only for a low-volume PoC until an approved API path is available. |
| eBay plain HTTP parser | **NO-GO in current environment** | Both search requests returned HTTP 403. A normal browser worked, so HTTP failure must not be interpreted as zero results. |
| Amazon Creators API | **CONDITIONAL / BLOCKED BY CREDENTIALS** | The official API supports keyword search and total result count, but no approved account or credentials are available locally, and the intended use must be checked against the Associates/Creators API purpose restrictions. |
| Amazon public Web acquisition | **NO-GO in current environment** | Both HTTP and normal-browser tests returned the same Amazon error page rather than search results. |
| 1688 authorized Open Platform | **CONDITIONAL / BLOCKED BY ACCESS** | The official Open Platform and product API catalog exist, but no AppKey/access token or buyer-side keyword-search permission is available for testing. |
| 1688 anonymous HTTP/browser search | **NO-GO in current environment** | HTTP returned a CAPTCHA payload; a normal browser redirected both searches to a login page. No product evidence was obtained. |
| Fully automated 10,000-OEM run | **NOT YET SUPPORTED** | Provider access, rate limits, field accuracy and repeated-run stability have not passed a benchmark. |

This is an engineering feasibility result, not legal advice. “NO-GO in current
environment” means a specific acquisition path failed under the stated test
conditions; it does not mean that the platform or project is impossible.

## 2. Evidence status vocabulary

| Status | Meaning |
|---|---|
| `CONFIRMED` | Reproduced in the current environment or stated in current official documentation. |
| `CONDITIONAL` | A documented route exists, but account eligibility, permission or credentials are unresolved. |
| `BLOCKED` | The test could not run because a required credential, approval or login was absent. |
| `UNVERIFIED` | A claim exists in the implementation brief but was not reproduced in this snapshot. |
| `OUT_OF_SCOPE` | Deliberately not tested in this phase. |

External acquisition failures must use explicit statuses such as
`HTTP_ERROR`, `CHALLENGE`, `AUTH_REQUIRED`, `BLOCKED_BY_CREDENTIALS` or
`PARSER_FAILED`. None of these statuses may be converted to `ZERO_RESULTS`.

## 3. Test boundary and environment

### 3.1 Included

- Current official API documentation, access requirements and published limits.
- Search-engine discoverability for the two fixtures.
- One low-frequency, unauthenticated HTTP request per platform and fixture.
- Normal browser navigation for both fixtures without signing in.
- Visible fields, JSON-LD and embedded application JSON where a page loaded.
- Presence of target-platform environment-variable names and repository
  credential files. Values were not inspected or printed.

### 3.2 Excluded

- CAPTCHA solving or bypass.
- Proxy pools, stealth fingerprints or anti-bot evasion.
- Account creation, login, API-key creation or use of personal credentials.
- Paid APIs and commercial datasets.
- Repeated-day stability, rate-limit saturation and 10,000-item load tests.
- Full legal review, data-retention approval and production certification.
- Supplier contact, sample purchase or physical product validation.

### 3.3 Local credential result

No environment-variable names or repository files indicating Amazon Creators
API, eBay API or 1688 Open Platform credentials were found. Therefore official
API execution is `BLOCKED_BY_CREDENTIALS`, not `API_UNAVAILABLE`.

### 3.4 Reproducible HTTP probe

Run from the repository root:

```powershell
py -3.12 .\scripts\probe_public_http.py --delay 0.5
```

The probe deliberately uses no authentication, cookies, retries or browser
fingerprint. It stores no response bodies. Response hashes make same-page/error
comparisons possible without retaining platform content.

## 4. HTTP probe results

| Platform | Query | Status | Bytes | Title / marker | Outcome |
|---|---|---:|---:|---|---|
| Amazon | `53630-53010` | 503 | 2,671 | `Sorry! Something went wrong!` | `HTTP_ERROR` |
| Amazon | `A18-67004-004` | 503 | 2,671 | Same title and same body hash as the first query | `HTTP_ERROR` |
| eBay | `53630-53010` | 403 | 1,986 | `Error Page \| eBay` | `HTTP_ERROR` |
| eBay | `A18-67004-004` | 403 | 1,986 | `Error Page \| eBay` | `HTTP_ERROR` |
| 1688 | `53630-53010` | 200 | 2,349 | CAPTCHA marker; query absent | `CHALLENGE` |
| 1688 | `A18-67004-004` | 200 | 2,349 | CAPTCHA marker; query absent | `CHALLENGE` |

An HTTP 200 response from 1688 is therefore not a successful product result.
Status code alone is insufficient; response classification is mandatory.

## 5. Browser results

### 5.1 Amazon

Both fixture searches opened in a normal browser and produced:

```text
title: Sorry! Something went wrong!
result cards: 0
JSON-LD scripts: 0
visible product data: none
```

Result: public Web acquisition is not usable in this environment. This does not
test or invalidate the official Creators API.

The prior brief values such as “exact results ≈ 2” and “relevant results ≈ 4”
remain `UNVERIFIED_CURRENT_SNAPSHOT`.

### 5.2 eBay

The normal browser loaded both searches without a login or challenge:

| Query | Visible result count | Reproduced evidence |
|---|---:|---|
| `53630-53010` | 16 | Exact/new listings, prices, sellers and multiple sold labels, including 32 and 38 sold in the visible result text. |
| `A18-67004-004` | 15 | Exact and normalized-number listings, `A18-67004-006` co-occurrences and the cross-reference `HLK2882`. |

The inspected `A18-67004-004` listing also exposed:

- price;
- condition;
- available quantity;
- `5 sold`;
- seller information;
- listing ID and last-update time;
- 229 vehicle-compatibility rows;
- Product/Offer JSON-LD;
- approximately 0.8 MB of embedded application JSON.

Important parser finding: the sold value was not exposed under a stable semantic
key such as `quantitySold`. It appeared inside an `availabilitySignal` localized
display string (`5点販売済み` in the current locale). Browser parsing is therefore
feasible but sensitive to language and page-contract changes.

The browser session resolved to Japanese UI and a Japan delivery postcode.
Consequently, the observed counts are evidence of technical availability, not a
valid North-American market benchmark. A production provider must explicitly
fix marketplace, locale and buyer/shipping context (for example `EBAY_US`).

### 5.3 1688

Both fixture searches redirected to `login.taobao.com` and exposed only the
password/SMS/QR login page:

```text
offer links: 0
JSON-LD scripts: 0
product fields: none
```

The unauthenticated Web path is therefore `AUTH_REQUIRED`. No conclusion about
the existence of the two products can be made from this result.

The public [1688 Open Platform](https://open.1688.com/) loaded successfully and
advertises API, SDK, sandbox and a “商品” API category. The publicly visible
[product API catalog](https://open.1688.com/api/apidocdetail.htm?aopApiCategory=product_new)
showed product-management operations such as obtaining a product and querying a
seller's product list. The inspected operation required a request signature and
`access_token`, and its solution was marked as targeted recruitment. No general,
anonymous buyer-side keyword-search API was established in this snapshot.

Official 1688 rules also state that automated collection or simulated operation
without permission is restricted. Browser automation cannot be treated as an
automatic fallback around missing Open Platform access.

## 6. Official API boundary

### 6.1 Amazon Creators API

Confirmed from current official documentation:

- PA-API 5 is deprecated in favor of Creators API.
- `SearchItems` supports keyword search, returns up to 10 items per request and
  includes `totalResultCount`; pages 1–10 are supported.
- Registration requires an accepted Amazon Associates account.
- Initial allocation is up to 1 TPS and 8,640 transactions/day for the first
  30-day period; later access/allocation depends on attributed shipped revenue,
  and access can be lost after 30 days without qualifying referring sales.
- Amazon states that Creators API applications should direct sales to Amazon.

Engineering conclusion:

1. H1 has a technically plausible official path.
2. A 10,000-OEM one-day run already exceeds the initial daily allocation if
   every OEM requires even one call.
3. Proteus's internal cross-platform opportunity-research use is not obviously
   the same as an affiliate application that directs sales to Amazon. Written
   purpose/usage confirmation is required before treating this provider as
   production-compatible.

Official references:

- [Creators API SearchItems](https://affiliate-program.amazon.com/creatorsapi/docs/en-us/api-reference/operations/search-items)
- [Creators API rates](https://affiliate-program.amazon.com/creatorsapi/docs/en-us/concepts/api-rates)
- [Creators API registration](https://affiliate-program.amazon.com/creatorsapi/docs/en-us/onboarding/register-for-creators-api)
- [Creators API best practices](https://affiliate-program.amazon.com/creatorsapi/docs/en-us/concepts/best-programming-practices)
- [PA-API 5 deprecation](https://affiliate-program.amazon.com/creatorsapi/docs/en-us/paapiv5-deprecation)

### 6.2 eBay APIs

Confirmed from current official documentation:

- Browse API supports keyword and compatibility search.
- Production Buy API access is intended for approved partners and requires an
  application/review process and contracts.
- Default Browse API allowance is 5,000 calls/day.
- Marketplace Insights, the official sales-history API, is restricted and not
  open to new users.
- Trading API `GetItem` documents `QuantitySold` as the listing-lifetime total;
  for multi-variation listings the item-level value is the total across all
  variations.

Engineering conclusion:

1. H2 is technically supported at listing-evidence level.
2. Browser-visible sold evidence is cumulative, not time-windowed market sales.
3. Approved API access is preferred; browser extraction is a measured fallback,
   not the scale path.
4. A 10,000-OEM one-day run also exceeds the default 5,000-call allowance if
   every candidate requires one Browse call.

Official references:

- [Browse API](https://developer.ebay.com/api-docs/buy/api-browse.html)
- [Buy API production requirements](https://developer.ebay.com/api-docs/buy/buy-requirements.html)
- [API call limits](https://developer.ebay.com/develop/get-started/api-call-limits)
- [Marketplace Insights restriction](https://developer.ebay.com/api-docs/buy/static/ref-buy-browse-filters.html)
- [Trading API GetItem](https://developer.ebay.com/devzone/xml/docs/Reference/ebay/GetItem.html)

### 6.3 1688 Open Platform

Confirmed:

- An official Open Platform and product API catalog exist.
- Public product search redirects to login in the normal browser.
- The public product API documentation includes authenticated seller/product
  management operations; the tested page required a signature and access token.
- No applicable buyer-side keyword-search permission was demonstrated.
- Unauthorized scraping/browser automation is outside the permitted V0 path.

Engineering conclusion: H3 remains unverified. Until an authorized search API or
approved logged-in access path is demonstrated, the V0 supply stage must be
manual-assisted or return `PROVIDER_UNAVAILABLE`.

Official references:

- [1688 Open Platform](https://open.1688.com/)
- [Product API catalog](https://open.1688.com/api/apidocdetail.htm?aopApiCategory=product_new)
- [Application onboarding](https://open.1688.com/doc/appJoin.htm)
- [1688 legal statement](https://terms.alicdn.com/legal-agreement/terms/suit_bu1_b2b/suit_bu1_b2b201802011532_36855.html)

## 7. Claims supported by this snapshot

### Supported

- Exact OEM/MPN search can produce useful eBay listings.
- Listing-level sold evidence can be visible and extracted in a normal browser.
- Deterministic part-number normalization is valuable: eBay exposed hyphenated,
  compact and related identifiers in the same result set.
- HTTP failure and zero results must be separate states.
- Provider choice must be capability-, permission- and context-aware.

### Not supported yet

- Current Amazon relevant-result counts for either fixture.
- Current 1688 supply, price, MOQ, stock or supplier evidence for either fixture.
- Stable direct HTTP parsing for any of the three platform search pages.
- A general free official API route that is immediately usable for all three
  platforms.
- Accurate North-American demand/competition metrics from the current browser
  sample.
- 10,000-candidate cost, latency, recall or precision.

## 8. Required provider gate

A provider is eligible for the pipeline only if all of the following are known:

```text
ACCESS_AUTHORIZED
AND PURPOSE_COMPATIBLE
AND REQUIRED_FIELDS_AVAILABLE
AND MARKET_CONTEXT_FIXED
AND FAILURE_CLASSIFICATION_TESTED
AND CACHE_RETENTION_ALLOWED
```

Provider selection must never perform this transition automatically:

```text
official API denied
→ unauthorized HTTP/browser collection
```

Instead:

```text
official API denied
→ approved fallback exists?
    YES → use and record method
    NO  → PROVIDER_UNAVAILABLE / HUMAN_REVIEW
```

## 9. Next executable tests

Credential values must be supplied through local environment variables or a
local secret store; they must not be committed or pasted into reports.

1. **eBay vertical slice now:** implement one fixture-to-evidence path using the
   normal browser result contract, with fixed US market context and fixture
   snapshots. Treat it as a low-volume research adapter.
2. **eBay API gate:** obtain/confirm a production key and approved use, then test
   Browse search plus the appropriate item-detail path.
3. **Amazon gate:** confirm accepted Associates/Creators API eligibility and
   purpose compatibility before adding credentials; then call `SearchItems` for
   both fixtures and compare `totalResultCount` with manually relevant results.
4. **1688 gate:** identify the exact Open Platform solution/API that authorizes
   buyer-side keyword discovery. If unavailable, formalize a manual input step
   rather than automating login or challenges.
5. Expand the benchmark beyond two positives: include negative, ambiguous,
   no-result, left/right, replacement and normalized-number cases.
6. Repeat the same benchmark on multiple dates before making stability claims.

## 10. Phase decision

For **automated acquisition**, proceed only with an eBay-first evidence vertical
slice and the shared evidence/failure model. Do not yet implement automated
Amazon or 1688 acquisition. Those platforms remain provider gates, not coding
assumptions.

At the **product level**, V0.1 may combine the automated eBay result with
traceable, user-supplied manual Amazon/1688 evidence and a deterministic
three-gate evaluator. This preserves the opportunity-finding outcome without
claiming that the blocked provider paths are technically available.
