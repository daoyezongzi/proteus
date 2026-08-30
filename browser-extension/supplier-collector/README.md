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
