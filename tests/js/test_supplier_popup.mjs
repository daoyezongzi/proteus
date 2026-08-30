import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const popupSource = await readFile(
  new URL("../../browser-extension/supplier-collector/popup.js", import.meta.url),
  "utf8",
);

function element() {
  return {
    dataset: {},
    disabled: false,
    hidden: false,
    listeners: {},
    textContent: "",
    addEventListener(type, listener) {
      this.listeners[type] = listener;
    },
  };
}

async function flushPromises() {
  await new Promise((resolve) => setImmediate(resolve));
}

async function exercisePopup(sendError) {
  const elements = {
    status: element(),
    start: element(),
    clear: element(),
    openProteus: element(),
  };
  const reloaded = [];
  let closed = false;
  const context = {
    URL,
    document: {
      getElementById(id) {
        return elements[id];
      },
    },
    window: {
      close() {
        closed = true;
      },
    },
    chrome: {
      runtime: {
        lastError: null,
        sendMessage(message, callback) {
          if (message.type === "popup:state") callback({ ok: true, value: null });
          else if (message.type === "popup:claim") {
            callback({
              ok: true,
              value: {
                supplier_label: "测试供应商",
                shop_host: "shop.example.1688.com",
                next_page_number: 1,
              },
            });
          }
        },
      },
      tabs: {
        async query() {
          return [{ id: 42, url: "https://shop.example.1688.com/page/offerlist.htm" }];
        },
        async sendMessage() {
          throw sendError;
        },
        async reload(tabId) {
          reloaded.push(tabId);
        },
        create() {},
      },
    },
    setTimeout,
    clearTimeout,
  };

  vm.runInNewContext(popupSource, context, { filename: "popup.js" });
  await flushPromises();
  await elements.start.listeners.click();

  return { closed, elements, reloaded };
}

test("reloads a pre-existing store tab when its content script has no receiver", async () => {
  const { closed, elements, reloaded } = await exercisePopup(
    new Error("Could not establish connection. Receiving end does not exist."),
  );

  assert.deepEqual(reloaded, [42]);
  assert.match(elements.status.textContent, /自动刷新/);
  assert.equal(elements.status.dataset.tone, "ready");
  assert.equal(closed, true);
});

test("does not reload the store tab for an unrelated extension error", async () => {
  const { closed, elements, reloaded } = await exercisePopup(
    new Error("Extension API unavailable."),
  );

  assert.deepEqual(reloaded, []);
  assert.equal(elements.status.textContent, "Extension API unavailable.");
  assert.equal(elements.status.dataset.tone, "error");
  assert.equal(elements.start.disabled, false);
  assert.equal(closed, false);
});
