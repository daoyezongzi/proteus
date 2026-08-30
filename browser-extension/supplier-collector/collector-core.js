"use strict";

(function exposeCollectorCore(global) {
  function normalizeText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function offerIdFromUrl(value, baseUrl = "https://www.1688.com/") {
    try {
      const url = new URL(value, baseUrl);
      if (url.protocol !== "https:" || url.hostname.toLowerCase() !== "detail.1688.com") return "";
      const match = url.pathname.match(/^\/offer\/(\d+)\.html$/);
      return match ? match[1] : "";
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

  function closestCard(anchor, selectors) {
    for (const selector of selectors || []) {
      try {
        const card = anchor.closest(selector);
        if (card) return card;
      } catch (_error) {
        // Ignore a selector that is no longer valid on the current page.
      }
    }
    return anchor.parentElement || anchor;
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
    const anchors = queryAll(documentRoot, profile.offer_link_selectors || []);
    for (const anchor of anchors) {
      const offerUrl = canonicalOfferUrl(anchor.href || anchor.getAttribute?.("href"), pageUrl);
      const offerId = offerIdFromUrl(offerUrl, pageUrl);
      if (!offerId || seen.has(offerId)) continue;
      const card = closestCard(anchor, profile.card_selectors || []);
      const image = card.querySelector?.("img") || anchor.querySelector?.("img");
      const title = normalizeText(
        anchor.getAttribute?.("title")
        || firstText(card, profile.title_selectors || [])
        || image?.getAttribute?.("alt")
        || anchor.textContent,
      ).slice(0, 500);
      if (!title) continue;
      seen.add(offerId);
      const result = {
        offer_id: offerId,
        title,
        offer_url: offerUrl,
      };
      const imageValue = imageUrl(card, anchor);
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

  function paginationState(documentRoot, profile) {
    const controls = queryAll(documentRoot, profile.next_page_selectors || []);
    let disabledSeen = false;
    for (const raw of controls) {
      const control = raw.matches?.("a,button") ? raw : raw.querySelector?.("a,button") || raw;
      if (isDisabled(control)) {
        disabledSeen = true;
        continue;
      }
      const label = normalizeText([
        control.getAttribute?.("aria-label"),
        control.getAttribute?.("title"),
        control.textContent,
        control.className,
      ].filter(Boolean).join(" ")).toLowerCase();
      if (
        control.getAttribute?.("rel") === "next"
        || label.includes("下一页")
        || label.includes("next")
      ) {
        return { has_next_page: true, control };
      }
    }
    return { has_next_page: disabledSeen ? false : null, control: null };
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
    paginationState,
    resolveHasNext,
  };
})(globalThis);
