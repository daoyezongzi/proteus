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
      embedded_data_markers: embeddedMarkers.slice(0, 12),
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
