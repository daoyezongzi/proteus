#!/usr/bin/env node

// Read-only bridge for one bounded 1688 supplier storefront. It deliberately
// does not import or call inquiry, messaging, favorites, cart, order, or
// checkout commands, and never reads/prints profile cookies or tokens.

import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const EXPECTED_VERSION = "0.1.47";

function args(argv) {
  const result = { headed: false };
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    if (key === "--headed") {
      result.headed = true;
      continue;
    }
    if (!key.startsWith("--") || index + 1 >= argv.length) {
      throw new Error("invalid bridge arguments");
    }
    result[key.slice(2).replaceAll("-", "_")] = argv[index + 1];
    index += 1;
  }
  return result;
}

function integer(value, minimum, maximum, label) {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new Error(`${label} is outside the supported bound`);
  }
  return parsed;
}

function timestamp() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

function compactText(value, limit = 500) {
  return String(value ?? "").replace(/\s+/g, " ").trim().slice(0, limit);
}

function isChallenge(title, body) {
  const text = `${title} ${body}`.toLowerCase();
  return /captcha|slider|verification|拖动|滑块|请完成验证|安全验证|访问验证/.test(text);
}

function isLogin(url, title, body) {
  const text = `${url} ${title} ${body}`.toLowerCase();
  return /login\.taobao|login\.1688|passport|账号登录|密码登录|扫码登录/.test(text);
}

function base(url) {
  return {
    provider: "LOCAL_1688_STORE_BRIDGE",
    source_method: "AUTHENTICATED_BROWSER_DOM",
    acquisition_status: "PARSER_FAILED",
    canonical_url: url,
    supplier: { shop_host: new URL(url).hostname.toLowerCase() },
    pages_attempted: 0,
    pages_completed: 0,
    observed_offer_count: 0,
    available_offer_count: null,
    has_next_page: null,
    inventory_complete: false,
    offers: [],
    warnings: [],
    retrieved_at: timestamp(),
  };
}

async function visibleState(page) {
  const title = compactText(await page.title().catch(() => ""), 300);
  const body = compactText(
    await page.locator("body").innerText({ timeout: 5000 }).catch(() => ""),
    10000,
  );
  return { title, body, url: page.url() };
}

async function waitForManualClearance(page, seconds) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    const state = await visibleState(page);
    if (!isChallenge(state.title, state.body)) return true;
    await page.waitForTimeout(1000);
  }
  return false;
}

async function storeIdentity(page, fallbackHost) {
  const extracted = await page.evaluate(() => {
    const text = (value) => String(value ?? "").replace(/\s+/g, " ").trim();
    const candidates = [
      document.querySelector("h1")?.textContent,
      document.querySelector("[class*='company-name']")?.textContent,
      document.querySelector("[class*='shop-name']")?.textContent,
      document.querySelector("meta[property='og:site_name']")?.getAttribute("content"),
    ].map(text).filter(Boolean);
    return { name: candidates[0] || "" };
  });
  const html = await page.content().catch(() => "");
  const memberMatch = html.match(/(?:memberId|member_id|memberid)["'\s:=]+([a-zA-Z0-9_-]{3,120})/i);
  const identity = { shop_host: fallbackHost };
  if (extracted.name) identity.name = compactText(extracted.name, 300);
  if (memberMatch?.[1]) identity.member_id = memberMatch[1];
  return identity;
}

async function offersOnPage(page) {
  return page.evaluate(() => {
    const clean = (value, limit = 500) => String(value ?? "").replace(/\s+/g, " ").trim().slice(0, limit);
    const records = [];
    const seen = new Set();
    for (const anchor of document.querySelectorAll("a[href*='/offer/']")) {
      const rawHref = anchor.getAttribute("href") || "";
      let url;
      try {
        url = new URL(rawHref, location.href);
      } catch {
        continue;
      }
      const match = url.pathname.match(/\/offer\/(\d+)(?:\.html)?/i);
      if (!match || seen.has(match[1])) continue;
      const card = anchor.closest("li, article, [class*='offer'], [class*='item'], [class*='product']") || anchor;
      const title = clean(
        anchor.getAttribute("title") ||
        anchor.querySelector("[title]")?.getAttribute("title") ||
        anchor.textContent ||
        card.querySelector("[title]")?.getAttribute("title") ||
        card.textContent,
      );
      if (!title) continue;
      seen.add(match[1]);
      const image = card.querySelector("img")?.getAttribute("src") || card.querySelector("img")?.getAttribute("data-src") || "";
      const cardText = clean(card.textContent, 1200);
      const priceMatch = cardText.match(/(?:¥|￥)\s*(\d+(?:\.\d+)?)/);
      const moqMatch = cardText.match(/(\d+)\s*(?:件|个|套|起批)/);
      records.push({
        offer_id: match[1],
        title,
        offer_url: `https://detail.1688.com/offer/${match[1]}.html`,
        ...(image ? { image_url: new URL(image, location.href).href } : {}),
        ...(priceMatch ? { price_cny: Number(priceMatch[1]) } : {}),
        ...(moqMatch ? { moq: Number(moqMatch[1]) } : {}),
      });
    }
    return records;
  });
}

async function availableCount(page) {
  const body = await page.locator("body").innerText({ timeout: 5000 }).catch(() => "");
  const patterns = [
    /共\s*(\d[\d,]*)\s*(?:件|个)?\s*(?:商品|产品)/,
    /全部商品\s*[（(]?\s*(\d[\d,]*)/,
    /(\d[\d,]*)\s*(?:件|个)商品/,
  ];
  for (const pattern of patterns) {
    const match = body.match(pattern);
    if (match) return Number(match[1].replaceAll(",", ""));
  }
  return null;
}

async function nextControl(page) {
  return page.evaluate(() => {
    const controls = [...document.querySelectorAll("a, button")];
    let disabledControl = null;
    for (const control of controls) {
      const label = `${control.textContent || ""} ${control.getAttribute("aria-label") || ""}`.replace(/\s+/g, " ").trim();
      if (!/^(下一页|下页|next)|下一页|next page/i.test(label)) continue;
      const disabled = control.matches(":disabled, [disabled], [aria-disabled='true'], .disabled, [class*='disabled']");
      const href = control instanceof HTMLAnchorElement ? control.href : "";
      if (disabled) {
        disabledControl = { href: "", label, disabled: true };
        continue;
      }
      return { href, label, disabled: false };
    }
    return disabledControl;
  });
}

async function clickNext(page, control, expectedHost) {
  if (control.href) {
    const next = new URL(control.href);
    if (next.hostname.toLowerCase() !== expectedHost) return false;
    await page.goto(next.href, { waitUntil: "domcontentloaded", timeout: 45000 });
    return true;
  }
  const selector = page.getByRole("button", { name: /下一页|下页|next/i }).or(
    page.getByRole("link", { name: /下一页|下页|next/i }),
  ).first();
  if (await selector.count() === 0) return false;
  await selector.click({ timeout: 10000 });
  await page.waitForTimeout(1500);
  return true;
}

async function collectWithContext(context, options, result) {
  const page = context.pages()[0] || await context.newPage();
  result.pages_attempted = 1;
  try {
    await page.goto(options.url, { waitUntil: "domcontentloaded", timeout: 45000 });
  } catch (error) {
    if (/timeout/i.test(String(error?.message))) {
      result.acquisition_status = "TIMEOUT";
      result.warnings.push("STORE_NAVIGATION_TIMEOUT");
      return result;
    }
    throw error;
  }
  await page.waitForTimeout(1200);
  let state = await visibleState(page);
  if (isLogin(state.url, state.title, state.body)) {
    result.acquisition_status = "AUTH_REQUIRED";
    result.warnings.push("AUTH_REQUIRED");
    return result;
  }
  if (isChallenge(state.title, state.body)) {
    if (!options.headed || !(await waitForManualClearance(page, options.challengeTimeout))) {
      result.acquisition_status = "RISK_CONTROL";
      result.warnings.push(options.headed ? "MANUAL_CHALLENGE_NOT_CLEARED" : "MANUAL_CHALLENGE_REQUIRED");
      return result;
    }
    await page.waitForTimeout(1000);
    state = await visibleState(page);
    if (isLogin(state.url, state.title, state.body)) {
      result.acquisition_status = "AUTH_REQUIRED";
      result.warnings.push("AUTH_REQUIRED_AFTER_MANUAL_CHALLENGE");
      return result;
    }
    if (isChallenge(state.title, state.body)) {
      result.acquisition_status = "RISK_CONTROL";
      result.warnings.push("MANUAL_CHALLENGE_NOT_CLEARED");
      return result;
    }
  }

  const expectedHost = new URL(options.url).hostname.toLowerCase();
  if (new URL(state.url).hostname.toLowerCase() !== expectedHost) {
    result.acquisition_status = "PARSER_FAILED";
    result.warnings.push("STORE_HOST_REDIRECTED");
    return result;
  }
  result.supplier = await storeIdentity(page, expectedHost);
  const seen = new Map();
  let reachedEnd = false;
  for (let pageNumber = 1; pageNumber <= options.maxPages; pageNumber += 1) {
    if (pageNumber > 1) result.pages_attempted += 1;
    await page.waitForTimeout(750);
    state = await visibleState(page);
    if (isLogin(state.url, state.title, state.body)) {
      result.acquisition_status = "AUTH_REQUIRED";
      result.warnings.push("AUTH_REQUIRED_DURING_PAGINATION");
      break;
    }
    if (isChallenge(state.title, state.body)) {
      if (!options.headed || !(await waitForManualClearance(page, options.challengeTimeout))) {
        result.acquisition_status = "RISK_CONTROL";
        result.warnings.push("RISK_CONTROL_DURING_PAGINATION");
        break;
      }
      await page.waitForTimeout(1000);
      state = await visibleState(page);
    }
    if (isLogin(state.url, state.title, state.body)) {
      result.acquisition_status = "AUTH_REQUIRED";
      result.warnings.push("AUTH_REQUIRED_DURING_PAGINATION");
      break;
    }
    if (isChallenge(state.title, state.body)) {
      result.acquisition_status = "RISK_CONTROL";
      result.warnings.push("RISK_CONTROL_DURING_PAGINATION");
      break;
    }
    if (new URL(state.url).hostname.toLowerCase() !== expectedHost) {
      result.acquisition_status = "PARSER_FAILED";
      result.warnings.push("STORE_HOST_REDIRECTED_DURING_PAGINATION");
      break;
    }
    const pageOffers = await offersOnPage(page);
    result.pages_completed += 1;
    for (const item of pageOffers) {
      if (!seen.has(item.offer_id)) seen.set(item.offer_id, item);
      if (seen.size >= options.maxOffers) break;
    }
    const available = await availableCount(page);
    if (available !== null) result.available_offer_count = available;
    const next = await nextControl(page);
    if (next && !next.disabled) {
      result.has_next_page = true;
    } else if (
      next?.disabled ||
      (result.available_offer_count !== null && seen.size >= result.available_offer_count)
    ) {
      result.has_next_page = false;
    } else {
      result.has_next_page = null;
    }
    if (seen.size >= options.maxOffers) {
      result.warnings.push("OFFER_BOUND_REACHED");
      break;
    }
    if (result.has_next_page === false) {
      reachedEnd = true;
      break;
    }
    if (result.has_next_page !== true || !next) {
      result.warnings.push("PAGINATION_END_NOT_PROVEN");
      break;
    }
    if (pageNumber >= options.maxPages) {
      result.warnings.push("PAGE_BOUND_REACHED");
      break;
    }
    if (!(await clickNext(page, next, expectedHost))) {
      result.warnings.push("NEXT_PAGE_UNSAFE_OR_UNAVAILABLE");
      break;
    }
  }
  result.offers = [...seen.values()];
  result.observed_offer_count = result.offers.length;
  if (["AUTH_REQUIRED", "RISK_CONTROL", "TIMEOUT"].includes(result.acquisition_status)) {
    return result;
  }
  result.inventory_complete = reachedEnd && result.has_next_page === false;
  if (result.offers.length > 0) {
    result.acquisition_status = result.inventory_complete ? "SUCCESS" : "PARTIAL";
  } else if (result.inventory_complete && result.available_offer_count === 0) {
    result.acquisition_status = "EMPTY";
  } else {
    result.acquisition_status = "PARSER_FAILED";
    result.inventory_complete = false;
    result.warnings.push("EMPTY_NOT_PROVEN");
  }
  return result;
}

async function main() {
  const options = args(process.argv.slice(2));
  if (!options.cli_root || !options.url || !options.profile) {
    throw new Error("cli-root, url and profile are required");
  }
  const parsedUrl = new URL(options.url);
  if (parsedUrl.protocol !== "https:" || !(parsedUrl.hostname === "1688.com" || parsedUrl.hostname.endsWith(".1688.com"))) {
    throw new Error("url must be a trusted HTTPS 1688 URL");
  }
  const maxPages = integer(options.max_pages, 1, 20, "max-pages");
  const maxOffers = integer(options.max_offers, 1, 1000, "max-offers");
  const challengeTimeout = integer(options.challenge_timeout_seconds, 10, 600, "challenge-timeout-seconds");
  const packagePath = path.join(options.cli_root, "package.json");
  const packageDocument = JSON.parse(await fs.readFile(packagePath, "utf8"));
  if (packageDocument.name !== "1688-cli" || packageDocument.version !== EXPECTED_VERSION) {
    const result = base(options.url);
    result.acquisition_status = "NOT_CONFIGURED";
    result.warnings.push("UNSUPPORTED_1688_CLI_VERSION");
    process.stdout.write(JSON.stringify(result));
    return;
  }
  const sessionModule = path.join(options.cli_root, "dist", "session", "context.js");
  const daemonModule = path.join(options.cli_root, "dist", "daemon", "manager.js");
  const { withSession } = await import(pathToFileURL(sessionModule).href);
  const daemon = await import(pathToFileURL(daemonModule).href);
  if (typeof withSession !== "function" || typeof daemon.status !== "function" || typeof daemon.stop !== "function") {
    throw new Error("unsupported 1688-cli dependency layout");
  }
  const result = base(options.url);
  const daemonState = await daemon.status(options.profile).catch(() => ({ running: false }));
  if (daemonState.running) await daemon.stop(options.profile);
  try {
    await withSession(
      { profile: options.profile, headless: !options.headed },
      async (context) => collectWithContext(context, {
        url: options.url,
        headed: options.headed,
        maxPages,
        maxOffers,
        challengeTimeout,
      }, result),
    );
  } finally {
    if (daemonState.running && typeof daemon.start === "function") {
      await daemon.start(options.profile).catch(() => {
        result.warnings.push("DAEMON_RESTART_FAILED");
      });
    }
  }
  process.stdout.write(JSON.stringify(result));
}

main().catch((error) => {
  const message = compactText(error?.message || error, 300);
  process.stdout.write(JSON.stringify({
    provider: "LOCAL_1688_STORE_BRIDGE",
    source_method: "AUTHENTICATED_BROWSER_DOM",
    acquisition_status: /timeout/i.test(message) ? "TIMEOUT" : "CLI_ERROR",
    supplier: {},
    pages_attempted: 0,
    pages_completed: 0,
    observed_offer_count: 0,
    available_offer_count: null,
    has_next_page: null,
    inventory_complete: false,
    offers: [],
    warnings: ["STORE_BRIDGE_FAILED"],
    retrieved_at: timestamp(),
  }));
  process.exitCode = 1;
});
