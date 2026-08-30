"use strict";

(function exposeCollectorCore(global) {
  const OFFER_VALUE_ATTRIBUTES = [
    "href",
    "data-href",
    "data-url",
    "data-link",
    "data-offer-url",
  ];
  const OFFER_ID_ATTRIBUTES = ["data-offer-id", "data-offerid", "data-item-id"];

  function normalizeText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function is1688Host(hostname) {
    const value = String(hostname || "").toLowerCase();
    return value === "1688.com" || value.endsWith(".1688.com");
  }

  function offerIdFromUrl(value, baseUrl = "https://www.1688.com/") {
    try {
      const url = new URL(value, baseUrl);
      if (url.protocol !== "https:" || !is1688Host(url.hostname)) return "";
      const match = url.pathname.match(/(?:^|\/)offer\/(\d+)\.html\/?$/);
      if (match) return match[1];
      for (const key of ["offerId", "offer_id", "offerid"]) {
        const candidate = url.searchParams.get(key) || "";
        if (/^\d{1,30}$/.test(candidate)) return candidate;
      }
      return "";
    } catch (_error) {
      return "";
    }
  }

  function canonicalOfferUrl(value, baseUrl) {
    const offerId = offerIdFromUrl(value, baseUrl);
    return offerId ? `https://detail.1688.com/offer/${offerId}.html` : "";
  }

  function queryAll(root, selectors) {
    const result = [];
    const seen = new Set();
    for (const selector of selectors || []) {
      let matches = [];
      try {
        matches = root.querySelectorAll(selector);
      } catch (_error) {
        matches = [];
      }
      for (const element of matches) {
        if (!seen.has(element)) {
          seen.add(element);
          result.push(element);
        }
      }
    }
    return result;
  }

  function offerIdFromElement(element, pageUrl) {
    for (const attribute of OFFER_VALUE_ATTRIBUTES) {
      const value = attribute === "href" ? element.href || element.getAttribute?.(attribute) : element.getAttribute?.(attribute);
      const offerId = offerIdFromUrl(value, pageUrl);
      if (offerId) return offerId;
    }
    for (const attribute of OFFER_ID_ATTRIBUTES) {
      const value = normalizeText(element.getAttribute?.(attribute));
      if (/^\d{1,30}$/.test(value)) return value;
    }
    return "";
  }

  function offerElements(documentRoot, profile) {
    return queryAll(documentRoot, [
      ...(profile.offer_link_selectors || []),
      "[href*='/offer/']",
      "[href*='offerId=']",
      "[href*='offerid=']",
      "[href*='offer_id=']",
      "[data-href]",
      "[data-url]",
      "[data-link]",
      "[data-href*='/offer/']",
      "[data-url*='/offer/']",
      "[data-link*='/offer/']",
      "[data-offer-url]",
      "[data-offer-id]",
      "[data-offerid]",
      "[data-item-id]",
    ]);
  }

  function closestCard(anchor, selectors) {
    for (const selector of selectors || []) {
      try {
        const card = anchor.closest(selector);
        if (card) return card;
      } catch (_error) {
        // Ignore a selector that is no longer valid on the current page.
      }
    }
    // Do not fall back to a page-level parent: a data-only item beside another
    // card would otherwise inherit that card's image/price/MOQ evidence.
    return anchor;
  }

  function firstText(root, selectors) {
    for (const element of queryAll(root, selectors)) {
      const value = normalizeText(element.getAttribute?.("title") || element.textContent);
      if (value) return value;
    }
    return "";
  }

  function imageUrl(card, anchor) {
    const image = card.querySelector?.("img") || anchor.querySelector?.("img");
    if (!image) return "";
    const value = image.currentSrc
      || image.getAttribute?.("src")
      || image.getAttribute?.("data-src")
      || image.getAttribute?.("data-lazyload-src")
      || "";
    if (value.startsWith("//")) return `https:${value}`;
    return value.startsWith("https://") ? value : "";
  }

  function priceValue(card, profile) {
    const text = firstText(card, profile.price_selectors || []);
    const match = text.match(/[¥￥]\s*([0-9]+(?:\.[0-9]+)?)/) || text.match(/^([0-9]+(?:\.[0-9]+)?)$/);
    return match ? Number(match[1]) : null;
  }

  function moqValue(card) {
    const elements = card.querySelectorAll?.("*") || [];
    for (const element of elements) {
      const match = normalizeText(element.textContent).match(/^(\d+)\s*(?:件|个|套|只|盒|条)\s*起(?:批|订)/);
      if (match) return Number(match[1]);
    }
    return null;
  }

  function extractOffers(documentRoot, profile, pageUrl) {
    const offers = [];
    const seen = new Set();
    for (const element of offerElements(documentRoot, profile)) {
      const offerId = offerIdFromElement(element, pageUrl);
      if (!offerId || seen.has(offerId)) continue;
      const offerUrl = `https://detail.1688.com/offer/${offerId}.html`;
      const card = closestCard(element, profile.card_selectors || []);
      const image = card.querySelector?.("img") || element.querySelector?.("img");
      const title = normalizeText(
        element.getAttribute?.("data-title")
        || element.getAttribute?.("data-name")
        || element.getAttribute?.("title")
        || element.getAttribute?.("aria-label")
        || firstText(card, profile.title_selectors || [])
        || image?.getAttribute?.("alt")
        || element.textContent,
      ).slice(0, 500);
      if (!title) continue;
      seen.add(offerId);
      const result = {
        offer_id: offerId,
        title,
        offer_url: offerUrl,
      };
      const imageValue = imageUrl(card, element);
      const price = priceValue(card, profile);
      const moq = moqValue(card);
      if (imageValue) result.image_url = imageValue;
      if (price !== null) result.price_cny = price;
      if (moq !== null) result.moq = moq;
      offers.push(result);
    }
    return offers;
  }

  function detectBlockFromText(text, pageUrl, profile) {
    const normalized = normalizeText(text);
    let path = "";
    try {
      const url = new URL(pageUrl);
      path = `${url.hostname}${url.pathname}`.toLowerCase();
    } catch (_error) {
      path = "";
    }
    if (/login|passport/.test(path)) return "AUTH_REQUIRED";
    if (/captcha|punish|security/.test(path)) return "RISK_CONTROL";
    if ((profile.auth_text || []).some((value) => normalized.includes(value))) return "AUTH_REQUIRED";
    if ((profile.risk_text || []).some((value) => normalized.includes(value))) return "RISK_CONTROL";
    return null;
  }

  function isRendered(element) {
    if (!element || typeof element.getClientRects !== "function") return true;
    const style = element.ownerDocument?.defaultView?.getComputedStyle?.(element);
    if (style && (style.display === "none" || style.visibility === "hidden")) return false;
    return element.getClientRects().length > 0;
  }

  function detectBlock(documentRoot, pageUrl, profile) {
    if (queryAll(documentRoot, profile.risk_selectors || []).some(isRendered)) {
      return "RISK_CONTROL";
    }
    return detectBlockFromText(documentRoot.body?.innerText || "", pageUrl, profile);
  }

  function detectEmptyState(documentRoot, profile) {
    const text = normalizeText(documentRoot.body?.innerText || "");
    return (profile.empty_text || []).some((value) => text.includes(value));
  }

  function availableOfferCount(documentRoot) {
    const text = normalizeText(documentRoot.body?.innerText || "");
    const patterns = [
      /共\s*([0-9,]+)\s*(?:件|个)商品/,
      /商品总数\s*[:：]?\s*([0-9,]+)/,
    ];
    for (const pattern of patterns) {
      const match = text.match(pattern);
      if (match) return Number(match[1].replace(/,/g, ""));
    }
    return null;
  }

  function isDisabled(element) {
    const target = element?.matches?.("a,button") ? element : element?.closest?.("a,button") || element;
    const classes = normalizeText(target?.className).toLowerCase();
    return Boolean(
      target?.disabled
      || target?.getAttribute?.("aria-disabled") === "true"
      || classes.includes("disabled")
      || classes.includes("disable"),
    );
  }

  function controlLabel(control) {
    return normalizeText([
      control?.getAttribute?.("aria-label"),
      control?.getAttribute?.("title"),
      control?.textContent,
      typeof control?.className === "string" ? control.className : "",
    ].filter(Boolean).join(" ")).toLowerCase();
  }

  function looksLikeNextControl(control) {
    const label = controlLabel(control);
    return Boolean(
      control?.getAttribute?.("rel") === "next"
      || label.includes("下一页")
      || label.includes("下页")
      || /(^|[\s_-])next([\s_-]|$)/.test(label)
      || /[›»→]/.test(label)
    );
  }

  function paginationState(documentRoot, profile) {
    const configured = queryAll(documentRoot, profile.next_page_selectors || []);
    const fallback = queryAll(documentRoot, ["a", "button", "[role='button']"])
      .filter(looksLikeNextControl);
    const controls = [...configured, ...fallback.filter((item) => !configured.includes(item))];
    let disabledSeen = false;
    for (const raw of controls) {
      const control = raw.matches?.("a,button") ? raw : raw.querySelector?.("a,button") || raw;
      if (isDisabled(control)) {
        disabledSeen = true;
        continue;
      }
      if (looksLikeNextControl(control)) {
        return { has_next_page: true, control };
      }
    }
    return { has_next_page: disabledSeen ? false : null, control: null };
  }

  function safeDiagnosticUrl(value, pageUrl) {
    try {
      const url = new URL(value, pageUrl);
      if (url.protocol !== "https:" || !is1688Host(url.hostname)) return "";
      const allowed = new URLSearchParams();
      for (const key of ["pageNum", "pageNo", "page", "beginPage", "offerId", "offer_id", "offerid"]) {
        const item = url.searchParams.get(key);
        if (item && /^\d{1,30}$/.test(item)) allowed.set(key, item);
      }
      const query = allowed.toString();
      return `${url.origin}${url.pathname}${query ? `?${query}` : ""}`.slice(0, 700);
    } catch (_error) {
      return "";
    }
  }

  function elementHint(element, pageUrl) {
    let rawUrl = "";
    for (const attribute of OFFER_VALUE_ATTRIBUTES) {
      rawUrl = attribute === "href" ? element.href || element.getAttribute?.(attribute) : element.getAttribute?.(attribute);
      if (rawUrl) break;
    }
    if (!rawUrl && element.tagName?.toLowerCase() === "iframe") {
      rawUrl = element.src || element.getAttribute?.("src") || "";
    }
    const url = safeDiagnosticUrl(rawUrl, pageUrl);
    const dataOfferId = offerIdFromElement(element, pageUrl);
    if (!url && !dataOfferId) return null;
    const hint = { tag: String(element.tagName || "unknown").toLowerCase().slice(0, 20) };
    if (url) hint.url = url;
    const text = normalizeText(element.getAttribute?.("data-title") || element.getAttribute?.("title") || element.textContent).slice(0, 160);
    const className = normalizeText(typeof element.className === "string" ? element.className : "").slice(0, 240);
    const ariaLabel = normalizeText(element.getAttribute?.("aria-label")).slice(0, 120);
    if (text) hint.text = text;
    if (className) hint.class_name = className;
    if (ariaLabel) hint.aria_label = ariaLabel;
    if (dataOfferId) hint.data_offer_id = dataOfferId;
    return hint;
  }

  function shadowRootHints(documentRoot, profile) {
    const hints = [];
    const queue = [documentRoot];
    const seenRoots = new Set();
    while (queue.length && hints.length < 8) {
      const root = queue.shift();
      for (const host of queryAll(root, ["*"])) {
        let shadowRoot = null;
        try {
          shadowRoot = host.shadowRoot || null;
        } catch (_error) {
          shadowRoot = null;
        }
        if (!shadowRoot || seenRoots.has(shadowRoot)) continue;
        seenRoots.add(shadowRoot);
        const rootElements = queryAll(shadowRoot, ["*"]);
        const candidateElements = offerElements(shadowRoot, profile);
        const className = normalizeText(typeof host.className === "string" ? host.className : "").slice(0, 240);
        hints.push({
          tag: String(host.tagName || "unknown").toLowerCase().slice(0, 20),
          ...(className ? { class_name: className } : {}),
          child_count: Number(shadowRoot.children?.length || 0),
          anchor_count: queryAll(shadowRoot, ["a"]).length,
          configured_offer_match_count: queryAll(shadowRoot, profile.offer_link_selectors || []).length,
          offer_candidate_count: candidateElements.length,
          nested_shadow_host_count: rootElements.filter((element) => Boolean(element.shadowRoot)).length,
          text_length: Math.min(1_000_000, normalizeText(shadowRoot.textContent).length),
        });
        queue.push(shadowRoot);
        if (hints.length >= 8) break;
      }
    }
    return hints;
  }

  function lightDomStructureHints(elements) {
    const identityAttributes = [
      "data-href",
      "data-url",
      "data-link",
      "data-offer-url",
      "data-offer-id",
      "data-offerid",
      "data-item-id",
      "data-id",
      "data-product-id",
    ];
    const candidates = [];
    for (const element of elements) {
      const className = normalizeText(typeof element.className === "string" ? element.className : "").slice(0, 240);
      const idName = normalizeText(element.getAttribute?.("id")).slice(0, 120);
      const role = normalizeText(element.getAttribute?.("role")).slice(0, 80);
      const signal = `${className} ${idName} ${role}`.toLowerCase();
      if (!/(offer|product|goods|item|card|sku|list|商品|产品|货品)/i.test(signal)) continue;
      const childCount = Number(element.children?.length || 0);
      const anchorCount = queryAll(element, ["a"]).length;
      const imageCount = queryAll(element, ["img"]).length;
      const identityNames = identityAttributes.filter((attribute) => element.hasAttribute?.(attribute));
      let visible = false;
      try {
        const rect = element.getBoundingClientRect?.();
        visible = Boolean(rect && rect.width > 0 && rect.height > 0);
      } catch (_error) {
        visible = false;
      }
      const score = Number(/(offer|product|goods|sku|card)/i.test(signal)) * 4
        + Number(/(item|list|商品|产品|货品)/i.test(signal)) * 2
        + Number(anchorCount > 0 || imageCount > 0 || identityNames.length > 0);
      candidates.push({
        score,
        hint: {
          tag: String(element.tagName || "unknown").toLowerCase().slice(0, 20),
          ...(idName ? { id_name: idName } : {}),
          ...(className ? { class_name: className } : {}),
          ...(role ? { role } : {}),
          child_count: childCount,
          anchor_count: anchorCount,
          image_count: imageCount,
          visible,
          identity_attribute_names: identityNames,
          text_length: Math.min(1_000_000, normalizeText(element.textContent).length),
        },
      });
    }
    return candidates
      .sort((left, right) => right.score - left.score)
      .slice(0, 24)
      .map((item) => item.hint);
  }

  function iframeHints(documentRoot, profile, pageUrl) {
    return queryAll(documentRoot, ["iframe"]).slice(0, 8).map((element) => {
      const rawUrl = element.src || element.getAttribute?.("src") || "";
      let parsed = null;
      try {
        parsed = new URL(rawUrl, pageUrl);
      } catch (_error) {
        parsed = null;
      }
      const host = String(parsed?.hostname || "").toLowerCase();
      const hostClass = !rawUrl || host === "about:blank" ? "blank" : is1688Host(host) ? "1688" : "foreign";
      const safeUrl = safeDiagnosticUrl(rawUrl, pageUrl);
      const idName = normalizeText(element.getAttribute?.("id")).slice(0, 120);
      const className = normalizeText(typeof element.className === "string" ? element.className : "").slice(0, 240);
      const title = normalizeText(element.getAttribute?.("title")).slice(0, 120);
      let visible = false;
      let width = 0;
      let height = 0;
      try {
        const rect = element.getBoundingClientRect?.();
        width = Math.min(10_000, Math.max(0, Math.round(rect?.width || 0)));
        height = Math.min(10_000, Math.max(0, Math.round(rect?.height || 0)));
        visible = Boolean(rect && rect.width > 0 && rect.height > 0);
      } catch (_error) {
        // Keep the frame metadata bounded if layout is unavailable.
      }
      let sameOriginAccessible = false;
      let anchorCount = 0;
      let offerCandidateCount = 0;
      let textLength = 0;
      try {
        const frameDocument = element.contentDocument;
        if (frameDocument) {
          sameOriginAccessible = true;
          anchorCount = queryAll(frameDocument, ["a"]).length;
          offerCandidateCount = offerElements(frameDocument, profile).length;
          textLength = Math.min(1_000_000, normalizeText(frameDocument.body?.textContent).length);
        }
      } catch (_error) {
        // Cross-origin frames expose no readable document to the top page.
      }
      return {
        host_class: hostClass,
        ...(safeUrl ? { url: safeUrl } : {}),
        ...(idName ? { id_name: idName } : {}),
        ...(className ? { class_name: className } : {}),
        ...(title ? { title } : {}),
        visible,
        width,
        height,
        same_origin_accessible: sameOriginAccessible,
        anchor_count: anchorCount,
        offer_candidate_count: offerCandidateCount,
        text_length: textLength,
      };
    });
  }

  function pageStateHints(documentRoot) {
    let documentReadyState = "unknown";
    try {
      if (["loading", "interactive", "complete"].includes(documentRoot.readyState)) {
        documentReadyState = documentRoot.readyState;
      }
    } catch (_error) {
      // Keep the state bounded when a document-like test double omits readyState.
    }
    let bodyTextLength = 0;
    try {
      bodyTextLength = Math.min(1_000_000, normalizeText(documentRoot.body?.textContent).length);
    } catch (_error) {
      // Keep the diagnostic optional for a detached document.
    }
    let visibleImageCount = 0;
    try {
      visibleImageCount = queryAll(documentRoot, ["img"]).filter(isRendered).length;
    } catch (_error) {
      // Keep the diagnostic optional when layout is unavailable.
    }
    const dataAttributeNames = new Set();
    let onclickCount = 0;
    try {
      const elements = queryAll(documentRoot, ["*"]);
      for (const element of elements) {
        if (element.hasAttribute?.("onclick")) onclickCount += 1;
        for (const name of element.getAttributeNames?.() || []) {
          if (/^data-[A-Za-z0-9_-]{1,40}$/.test(name)) dataAttributeNames.add(name);
          if (dataAttributeNames.size >= 24) break;
        }
        if (dataAttributeNames.size >= 24) break;
      }
    } catch (_error) {
      // Keep the diagnostic bounded when attribute enumeration is unavailable.
    }
    let resourceCount = 0;
    let offerishResourceCount = 0;
    let apiishResourceCount = 0;
    try {
      const performance = documentRoot.defaultView?.performance;
      const entries = performance?.getEntriesByType?.("resource") || [];
      resourceCount = Math.min(100_000, entries.length);
      for (const entry of entries) {
        const name = String(entry?.name || "");
        if (/(offer|product|goods|item|sku|detail|商品|货品)/i.test(name)) offerishResourceCount += 1;
        if (/(\/api(?:\/|[?])|ajax|search|query|data|graphql|jsonp)/i.test(name)) apiishResourceCount += 1;
      }
      offerishResourceCount = Math.min(100_000, offerishResourceCount);
      apiishResourceCount = Math.min(100_000, apiishResourceCount);
    } catch (_error) {
      // Performance entries are not guaranteed in all content-script contexts.
    }
    return {
      document_ready_state: documentReadyState,
      body_text_length: bodyTextLength,
      visible_image_count: visibleImageCount,
      resource_count: resourceCount,
      offerish_resource_count: offerishResourceCount,
      apiish_resource_count: apiishResourceCount,
      light_dom_data_attribute_names: [...dataAttributeNames].sort().slice(0, 24),
      onclick_count: Math.min(100_000, onclickCount),
    };
  }

  function parserProbe(documentRoot, profile, pageUrl) {
    const allElements = queryAll(documentRoot, ["*"]);
    const configuredOffers = queryAll(documentRoot, profile.offer_link_selectors || []);
    const configuredNext = queryAll(documentRoot, profile.next_page_selectors || []);
    const offerCandidates = offerElements(documentRoot, profile)
      .map((element) => elementHint(element, pageUrl))
      .filter(Boolean)
      .slice(0, 24);
    const paginationCandidates = queryAll(documentRoot, ["a", "button", "[role='button']"])
      .filter(looksLikeNextControl)
      .map((element) => elementHint(element, pageUrl) || {
        tag: String(element.tagName || "unknown").toLowerCase().slice(0, 20),
        text: normalizeText(element.textContent).slice(0, 160),
        class_name: normalizeText(typeof element.className === "string" ? element.className : "").slice(0, 240),
      })
      .slice(0, 12);
    const frameCandidates = queryAll(documentRoot, ["iframe[src]"])
      .map((element) => elementHint(element, pageUrl))
      .filter(Boolean)
      .slice(0, 12);
    const linkCandidates = queryAll(documentRoot, ["a[href]"])
      .map((element) => elementHint(element, pageUrl))
      .filter(Boolean)
      .slice(0, 24);
    const identityMarkers = [
      "data-href",
      "data-url",
      "data-link",
      "data-offer-url",
      "data-offer-id",
      "data-offerid",
      "data-item-id",
      "data-id",
      "data-product-id",
    ].filter((attribute) => queryAll(documentRoot, [`[${attribute}]`]).length > 0);
    const embeddedMarkers = [];
    const markerNames = ["__page__data__", "offerList", "offerId", "offerListData"];
    for (const script of queryAll(documentRoot, ["script:not([src])"]).slice(0, 100)) {
      const value = String(script.textContent || "");
      for (const marker of markerNames) {
        if (value.includes(marker) && !embeddedMarkers.includes(marker)) embeddedMarkers.push(marker);
      }
    }
    return {
      anchor_count: queryAll(documentRoot, ["a"]).length,
      iframe_count: queryAll(documentRoot, ["iframe"]).length,
      shadow_host_count: allElements.filter((element) => Boolean(element.shadowRoot)).length,
      configured_offer_match_count: configuredOffers.length,
      configured_next_match_count: configuredNext.length,
      offer_candidates: offerCandidates,
      pagination_candidates: paginationCandidates,
      frame_candidates: frameCandidates,
      shadow_root_hints: shadowRootHints(documentRoot, profile),
      link_candidates: linkCandidates,
      light_dom_identity_markers: identityMarkers,
      light_dom_structure_hints: lightDomStructureHints(allElements),
      iframe_hints: iframeHints(documentRoot, profile, pageUrl),
      embedded_data_markers: embeddedMarkers.slice(0, 12),
      ...pageStateHints(documentRoot),
    };
  }

  function resolveHasNext({
    paginationHasNext,
    emptyState,
    availableOfferCount: available,
    priorObservedCount,
    currentOfferCount,
  }) {
    if (emptyState) return false;
    if (paginationHasNext === true || paginationHasNext === false) {
      return paginationHasNext;
    }
    if (
      Number(priorObservedCount || 0) === 0
      && Number.isInteger(available)
      && available >= 0
      && Number(currentOfferCount || 0) === available
    ) {
      return false;
    }
    return null;
  }

  global.Proteus1688CollectorCore = {
    availableOfferCount,
    canonicalOfferUrl,
    detectBlock,
    detectBlockFromText,
    detectEmptyState,
    extractOffers,
    isDisabled,
    normalizeText,
    offerIdFromUrl,
    parserProbe,
    paginationState,
    resolveHasNext,
  };
})(globalThis);
