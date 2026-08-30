"use strict";

(function runProteusCollector() {
  if (window.top !== window || !globalThis.Proteus1688CollectorCore) return;

  const core = globalThis.Proteus1688CollectorCore;
  let running = false;

  function message(payload) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(payload, (response) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
        } else if (!response?.ok) {
          reject(new Error(response?.error || "Proteus 扩展通信失败。"));
        } else {
          resolve(response.value);
        }
      });
    });
  }

  function statusBubble(text, tone = "working") {
    let element = document.getElementById("proteus-supplier-capture-status");
    if (!element) {
      element = document.createElement("div");
      element.id = "proteus-supplier-capture-status";
      Object.assign(element.style, {
        position: "fixed",
        right: "18px",
        bottom: "18px",
        zIndex: "2147483647",
        maxWidth: "320px",
        padding: "12px 14px",
        borderRadius: "10px",
        boxShadow: "0 12px 36px rgba(0,0,0,.2)",
        color: "#fff",
        font: "13px/1.5 system-ui, sans-serif",
      });
      document.documentElement.appendChild(element);
    }
    element.style.background = tone === "error" ? "#a33b32" : tone === "done" ? "#32745a" : "#473f39";
    element.textContent = text;
  }

  function sleep(milliseconds) {
    return new Promise((resolve) => setTimeout(resolve, milliseconds));
  }

  async function settlePage(profile) {
    const settings = profile.scroll || {};
    const maxRounds = Math.max(1, Math.min(20, Number(settings.max_rounds) || 12));
    const settleMs = Math.max(250, Math.min(2000, Number(settings.settle_ms) || 700));
    const stableNeeded = Math.max(1, Math.min(5, Number(settings.stable_rounds) || 2));
    let previous = "";
    let stable = 0;
    for (let round = 0; round < maxRounds; round += 1) {
      const offers = core.extractOffers(document, profile, location.href);
      const height = Math.max(document.body?.scrollHeight || 0, document.documentElement.scrollHeight || 0);
      const marker = `${offers.length}:${height}`;
      stable = marker === previous ? stable + 1 : 0;
      previous = marker;
      if (stable >= stableNeeded) break;
      window.scrollTo({ top: height, behavior: "auto" });
      await sleep(settleMs);
    }
  }

  async function sha256(value) {
    const bytes = new TextEncoder().encode(value);
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return [...new Uint8Array(digest)].map((item) => item.toString(16).padStart(2, "0")).join("");
  }

  function safeNextUrl(control) {
    const value = control?.href || control?.getAttribute?.("href") || "";
    if (!value || value.toLowerCase().startsWith("javascript:")) return "";
    try {
      const next = new URL(value, location.href);
      return next.protocol === "https:" && next.hostname === location.hostname ? next.href : "";
    } catch (_error) {
      return "";
    }
  }

  function pageMarker(profile) {
    const ids = core.extractOffers(document, profile, location.href)
      .slice(0, 8)
      .map((offer) => offer.offer_id)
      .join(",");
    return `${location.href}|${document.title}|${ids}`;
  }

  async function waitForPageTransition(before, profile) {
    for (let attempt = 0; attempt < 30; attempt += 1) {
      await sleep(500);
      if (pageMarker(profile) !== before) return true;
    }
    return false;
  }

  async function captureCurrentPage(state) {
    if (running || !state?.profile || state.shop_host !== location.hostname.toLowerCase()) return;
    running = true;
    const profile = state.profile;
    try {
      const initialBlock = core.detectBlock(document, location.href, profile);
      if (initialBlock) {
        statusBubble("Proteus 已暂停：请先由你完成当前登录或验证。", "error");
        await message({ type: "collector:pause", reason: initialBlock, pageUrl: location.href });
        return;
      }
      statusBubble(`Proteus 正在读取第 ${state.next_page_number} 页…`);
      await settlePage(profile);
      const block = core.detectBlock(document, location.href, profile);
      if (block) {
        statusBubble("Proteus 已暂停：页面出现登录或风险验证。", "error");
        await message({ type: "collector:pause", reason: block, pageUrl: location.href });
        return;
      }

      const offers = core.extractOffers(document, profile, location.href);
      const emptyState = core.detectEmptyState(document, profile);
      const available = core.availableOfferCount(document);
      const pagination = core.paginationState(document, profile);
      const hasNext = core.resolveHasNext({
        paginationHasNext: pagination.has_next_page,
        emptyState,
        availableOfferCount: available,
        priorObservedCount: state.observed_offer_count,
        currentOfferCount: offers.length,
      });
      const evidenceText = [
        location.href,
        document.title,
        document.documentElement.outerHTML,
      ].join("\n");
      const result = await message({
        type: "collector:ingest",
        page: {
          page_number: state.next_page_number,
          page_url: location.href,
          has_next_page: hasNext,
          available_offer_count: available,
          empty_state: emptyState,
          offers,
          evidence: {
            dom_sha256: await sha256(evidenceText),
            document_title: document.title.slice(0, 300),
            profile_id: profile.profile_id,
          },
        },
      });

      if (result.status === "COMPLETED") {
        statusBubble(`Proteus 已封存 ${result.observed_offer_count || 0} 件商品。`, "done");
        return;
      }
      if (result.status === "PAUSED") {
        statusBubble("Proteus 已保留当前证据；请检查页面后再继续。", "error");
        return;
      }
      if (!pagination.control || hasNext !== true) {
        statusBubble("Proteus 无法确认下一页，已保守暂停。", "error");
        return;
      }
      const nextUrl = safeNextUrl(pagination.control);
      statusBubble(`第 ${state.next_page_number} 页已保存，正在进入下一页…`);
      if (nextUrl) location.assign(nextUrl);
      else {
        const before = pageMarker(profile);
        pagination.control.click();
        const changed = await waitForPageTransition(before, profile);
        if (!changed) {
          await message({ type: "collector:pause", reason: "TIMEOUT", pageUrl: location.href });
          statusBubble("下一页没有在边界内完成加载，已保存部分快照。", "error");
          return;
        }
        running = false;
        const nextState = await message({ type: "collector:state" });
        await captureCurrentPage(nextState);
      }
    } catch (error) {
      statusBubble(`Proteus 采集失败：${error.message}`, "error");
    } finally {
      running = false;
    }
  }

  chrome.runtime.onMessage.addListener((incoming, _sender, sendResponse) => {
    if (incoming?.type !== "collector:start") return undefined;
    message({ type: "collector:state" })
      .then((state) => captureCurrentPage(state))
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  });

  message({ type: "collector:state" })
    .then((state) => {
      if (state?.status === "CAPTURING" && state.shop_host === location.hostname.toLowerCase()) {
        return captureCurrentPage(state);
      }
      return null;
    })
    .catch(() => null);
})();
