"use strict";

const statusElement = document.getElementById("status");
const startButton = document.getElementById("start");
const clearButton = document.getElementById("clear");

function send(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else if (!response?.ok) reject(new Error(response?.error || "扩展通信失败"));
      else resolve(response.value);
    });
  });
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

function show(message, tone = "") {
  statusElement.textContent = message;
  if (tone) statusElement.dataset.tone = tone;
  else delete statusElement.dataset.tone;
}

function isMissingContentScript(error) {
  const message = error?.message || String(error || "");
  return (
    message.includes("Receiving end does not exist")
    || message.includes("Could not establish connection")
  );
}

async function startCollector(tab) {
  try {
    await chrome.tabs.sendMessage(tab.id, { type: "collector:start" });
  } catch (error) {
    if (!isMissingContentScript(error)) throw error;
    show("当前店铺页打开早于扩展，正在自动刷新并继续采集…", "ready");
    await chrome.tabs.reload(tab.id);
  }
}

async function boot() {
  try {
    const [tab, state] = await Promise.all([activeTab(), send({ type: "popup:state" })]);
    const host = tab?.url ? new URL(tab.url).hostname : "";
    if (!host.endsWith(".1688.com") || host === "detail.1688.com") {
      show("当前不是 1688 供应商店铺页。请先打开 Proteus 保存的店铺商品列表。", "error");
      return;
    }
    if (state) {
      show(`已有采集任务：${state.pages_completed || 0} 页、${state.observed_offer_count || 0} 件。`, "ready");
      clearButton.hidden = false;
    } else {
      show("页面可用。点击下方按钮连接 Proteus 中与当前店铺匹配的待采集任务。", "ready");
    }
    startButton.disabled = false;
  } catch (error) {
    show(`无法检查状态：${error.message}`, "error");
  }
}

startButton.addEventListener("click", async () => {
  startButton.disabled = true;
  try {
    const tab = await activeTab();
    const state = await send({ type: "popup:claim", tabUrl: tab.url });
    show(`已连接「${state.supplier_label || state.shop_host}」，正在读取第 ${state.next_page_number} 页。`, "ready");
    await startCollector(tab);
    window.close();
  } catch (error) {
    show(error.message, "error");
    startButton.disabled = false;
  }
});

document.getElementById("openProteus").addEventListener("click", () => {
  chrome.tabs.create({ url: "http://127.0.0.1:8765/supplier-scout.html" });
});

clearButton.addEventListener("click", async () => {
  await send({ type: "popup:clear" });
  clearButton.hidden = true;
  show("已清除扩展中的失效状态；Proteus 已封存的快照不受影响。", "ready");
});

boot();
