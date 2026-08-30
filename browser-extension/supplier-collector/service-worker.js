"use strict";

const API_BASE = "http://127.0.0.1:8765/api/v1";
const STATE_KEY = "proteusSupplierCapture";

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      accept: "application/json",
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = Array.isArray(payload?.detail) ? payload.detail[0]?.msg : payload?.detail;
    throw new Error(detail || `Proteus 返回 ${response.status}`);
  }
  return payload;
}

async function getState() {
  const stored = await chrome.storage.session.get(STATE_KEY);
  return stored[STATE_KEY] || null;
}

async function setState(value) {
  if (value) await chrome.storage.session.set({ [STATE_KEY]: value });
  else await chrome.storage.session.remove(STATE_KEY);
}

function hostFromUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname.endsWith(".1688.com")
      ? url.hostname.toLowerCase()
      : "";
  } catch (_error) {
    return "";
  }
}

async function claimCapture(tabUrl) {
  const shopHost = hostFromUrl(tabUrl);
  if (!shopHost || shopHost === "detail.1688.com") {
    throw new Error("请先打开已保存供应商的 1688 店铺商品列表页。");
  }
  const existing = await getState();
  if (existing?.status === "CAPTURING" && existing.shop_host === shopHost) {
    return existing;
  }
  const [{ capture }, profile] = await Promise.all([
    api(`/supplier-scout/captures/pending?shop_host=${encodeURIComponent(shopHost)}`),
    api("/supplier-scout/collector/profile"),
  ]);
  if (!capture) {
    throw new Error("Proteus 中没有与当前店铺匹配的待采集任务。");
  }
  const claimed = await api(
    `/supplier-scout/captures/${encodeURIComponent(capture.capture_id)}/claim`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "X-Proteus-Capture-Token": capture.capture_token,
      },
      body: JSON.stringify({
        page_url: tabUrl,
        extension_version: chrome.runtime.getManifest().version,
        parser_version: profile.parser_version,
      }),
    },
  );
  const state = {
    ...claimed,
    capture_token: capture.capture_token,
    profile,
  };
  await setState(state);
  return state;
}

async function ingestPage(page) {
  const state = await getState();
  if (!state) throw new Error("没有正在运行的 Proteus 采集任务。");
  const capture = await api(
    `/supplier-scout/captures/${encodeURIComponent(state.capture_id)}/pages`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "X-Proteus-Capture-Token": state.capture_token,
      },
      body: JSON.stringify(page),
    },
  );
  if (["COMPLETED", "PAUSED", "EXPIRED"].includes(capture.status)) {
    await setState(null);
  } else {
    await setState({ ...state, ...capture });
  }
  return capture;
}

async function pauseCapture(reason, pageUrl) {
  const state = await getState();
  if (!state) throw new Error("没有正在运行的 Proteus 采集任务。");
  const capture = await api(
    `/supplier-scout/captures/${encodeURIComponent(state.capture_id)}/pause`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "X-Proteus-Capture-Token": state.capture_token,
      },
      body: JSON.stringify({ reason, page_url: pageUrl }),
    },
  );
  await setState(null);
  return capture;
}

async function handleMessage(message) {
  switch (message?.type) {
    case "popup:claim":
      return claimCapture(message.tabUrl);
    case "popup:state":
    case "collector:state":
      return getState();
    case "popup:clear":
      await setState(null);
      return null;
    case "collector:ingest":
      return ingestPage(message.page);
    case "collector:pause":
      return pauseCapture(message.reason, message.pageUrl);
    default:
      throw new Error("未知的扩展消息。");
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  handleMessage(message)
    .then((value) => sendResponse({ ok: true, value }))
    .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
  return true;
});
