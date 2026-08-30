import assert from "node:assert/strict";
import test from "node:test";

await import("../../browser-extension/supplier-collector/collector-core.js");

const core = globalThis.Proteus1688CollectorCore;
const profile = {
  auth_text: ["快捷登录"],
  risk_text: ["拖动滑块"],
  next_page_selectors: ["a.next"],
};

test("canonicalizes only real 1688 offer links", () => {
  assert.equal(
    core.canonicalOfferUrl(
      "//detail.1688.com/offer/123456.html?spm=test",
      "https://shop.example.1688.com/page/offerlist.htm",
    ),
    "https://detail.1688.com/offer/123456.html",
  );
  assert.equal(core.offerIdFromUrl("https://example.com/offer/123456.html"), "");
  assert.equal(core.offerIdFromUrl("javascript:alert(1)"), "");
});

test("distinguishes authentication and risk-control text", () => {
  assert.equal(
    core.detectBlockFromText("请使用快捷登录", "https://shop.example.1688.com/", profile),
    "AUTH_REQUIRED",
  );
  assert.equal(
    core.detectBlockFromText("请拖动滑块", "https://shop.example.1688.com/", profile),
    "RISK_CONTROL",
  );
  assert.equal(
    core.detectBlockFromText("普通商品列表", "https://shop.example.1688.com/", profile),
    null,
  );
});

test("requires explicit active or disabled pagination evidence", () => {
  const active = {
    className: "next",
    disabled: false,
    textContent: "下一页",
    matches: () => true,
    getAttribute: (name) => (name === "rel" ? "next" : null),
  };
  const disabled = {
    ...active,
    className: "next disabled",
    getAttribute: (name) => (name === "aria-disabled" ? "true" : null),
  };
  const documentWith = (value) => ({ querySelectorAll: () => value ? [value] : [] });

  assert.equal(core.paginationState(documentWith(active), profile).has_next_page, true);
  assert.equal(core.paginationState(documentWith(disabled), profile).has_next_page, false);
  assert.equal(core.paginationState(documentWith(null), profile).has_next_page, null);
});

test("never lets a reported total override an explicit next page", () => {
  assert.equal(core.resolveHasNext({
    paginationHasNext: true,
    emptyState: false,
    availableOfferCount: 1,
    priorObservedCount: 0,
    currentOfferCount: 1,
  }), true);
  assert.equal(core.resolveHasNext({
    paginationHasNext: null,
    emptyState: false,
    availableOfferCount: 2,
    priorObservedCount: 1,
    currentOfferCount: 1,
  }), null);
  assert.equal(core.resolveHasNext({
    paginationHasNext: null,
    emptyState: false,
    availableOfferCount: 1,
    priorObservedCount: 0,
    currentOfferCount: 1,
  }), false);
});
