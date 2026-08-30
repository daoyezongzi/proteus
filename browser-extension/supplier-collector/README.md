# Proteus 1688 Supplier Collector

This local Manifest V3 Edge extension captures normally rendered offer cards
from one saved 1688 supplier store and submits normalized page evidence to the
loopback Proteus API.

## Install once

1. Open `edge://extensions` in the user's ordinary Edge profile.
2. Enable Developer mode.
3. Choose **Load unpacked**.
4. Select this `browser-extension/supplier-collector` directory.
5. Pin “Proteus 1688 店铺采集器” to the toolbar.

After an Agent updates the extension files, click **Reload** on the same Edge
extensions page. Do not move the directory after loading it.

If the store tab was already open before installation or reload, the first
collector click reloads that store tab once. The content script then resumes
the same unexpired Proteus capture automatically. A lost extension-session
state can reattach to the matching in-progress capture instead of stranding it.

The collector also records a bounded parser probe when no offer is recognized
or pagination is ambiguous. Proteus shows the probe in the capture status and
keeps the page at `PARSER_FAILED` until a user reloads/repairs the normal page;
it never treats an unproven page as an empty store. Probe URLs are sanitized to
HTTPS 1688 paths with numeric paging or offer-ID parameters only.

When an open Shadow Root is present, the probe also records bounded structure
counters (host tag/class, child and link counts, selector/candidate counts,
nested-root count and text length). It does not persist Shadow Root text,
cookies, tokens or cross-origin frame contents; these counters are diagnostic
evidence, not collected offers. The same probe records only sanitized HTTPS
1688 link candidates and identity-attribute names from the top-level DOM.
It also records bounded top-level product-structure hints and iframe
accessibility/size metadata; cross-origin iframe content and foreign URLs are
not persisted. Finally, it records only page-state counters (ready state, body
text/image counts, resource URL class counts, top-level data-attribute names,
and inline-handler count). For 1688 resource entries it may also record a
route-shaped host/path fingerprint and numeric offer IDs found in an offer URL;
query values and opaque path segments are removed. Raw resource URLs and page
text are not persisted.

## Boundary

- The user creates a bounded capture in Proteus and explicitly clicks the
  extension on the matching store page.
- The user handles all login and CAPTCHA interaction.
- The extension reads rendered offer fields, deterministic pagination state and
  a SHA-256 page-evidence digest. It does not read or export cookies.
- Authentication, risk control and unknown pagination pause the session and
  preserve a partial or blocked immutable snapshot.
- There is no remote code, proxy control, stealth behavior, shopping or supplier
  contact capability.
