"""Low-frequency, first-page eBay US evidence acquisition for Proteus V0.1.

The module intentionally keeps Playwright behind a lazy import so that the
normalization and parsing helpers remain usable in offline workflows.  It does
not log in, solve challenges, use stealth techniques, or continue past the
first search-results page.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from html import unescape as html_unescape
from html.parser import HTMLParser
import re
import unicodedata
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse


SCHEMA_VERSION = "0.1"
PROVIDER = "EBAY_BROWSER_V0_1"
EXPECTED_MARKET_CONTEXT: dict[str, str] = {
    "marketplace_id": "EBAY_US",
    "site": "www.ebay.com",
    "locale": "en-US",
    "ship_to_country": "US",
    "ship_to_postal_code": "10001",
    "currency": "USD",
}

_SOLD_RE = re.compile(r"(?<!\w)(\d[\d,]*)\s*(\+)?\s+sold\b", re.IGNORECASE)
_AVAILABLE_RE = re.compile(r"(?<!\w)(\d[\d,]*)\s+available\b", re.IGNORECASE)
_ITEM_ID_PATTERNS = (
    re.compile(r"/itm/(?:[^/?#]+/)?(\d{9,15})(?:[/?#]|$)", re.IGNORECASE),
    re.compile(r"[?&](?:item|itemid)=(\d{9,15})(?:[&#]|$)", re.IGNORECASE),
)
_PART_WITH_SEPARATOR_RE = re.compile(
    r"(?<![A-Z0-9])(?=[A-Z0-9_-]*\d)[A-Z0-9]{1,12}"
    r"(?:[-_][A-Z0-9]{1,12})+(?![A-Z0-9])",
    re.IGNORECASE,
)
_PART_WITH_SPACES_RE = re.compile(
    r"(?<![A-Z0-9])(?:[A-Z]*\d[A-Z0-9]*)(?:\s+(?:[A-Z]*\d[A-Z0-9]*)){1,3}"
    r"(?![A-Z0-9])",
    re.IGNORECASE,
)
_COMPACT_PART_RE = re.compile(
    r"(?<![A-Z0-9])(?=[A-Z0-9]{6,}(?![A-Z0-9]))(?=[A-Z0-9]*\d)"
    r"[A-Z0-9]{6,}(?![A-Z0-9])",
    re.IGNORECASE,
)
_HTML_LANG_RE = re.compile(r"<html\b[^>]*\blang=[\"']?([^\"'\s>]+)", re.IGNORECASE)
_EN_US_STATE_RE = re.compile(
    r"(?:[\"'](?:locale|language)[\"']\s*:\s*[\"']en[-_]US[\"']|"
    r"(?:property|name)=[\"'](?:og:locale|locale)[\"'][^>]*content=[\"']en[-_]US[\"'])",
    re.IGNORECASE,
)
_LOCALE_STATE_VALUE_RE = re.compile(
    r"[\"'](?:locale|language)[\"']\s*:\s*[\"']([A-Za-z]{2}(?:[-_][A-Za-z]{2})?)[\"']",
    re.IGNORECASE,
)
_CURRENCY_STATE_VALUE_RE = re.compile(
    r"[\"']currency(?:Code)?[\"']\s*:\s*[\"']([A-Z]{3})[\"']",
    re.IGNORECASE,
)
_USD_MARKER_RE = re.compile(
    r"(?:\bUS\s*\$|\bUSD\b|[\"']currency(?:Code)?[\"']\s*:\s*[\"']USD[\"'])",
    re.IGNORECASE,
)
_NON_US_CURRENCY_RE = re.compile(r"\b(?:JPY|EUR|GBP|CAD|AUD|CNY|RMB)\b", re.IGNORECASE)
_POSTAL_RE = re.compile(r"(?<![\d-])(\d{5}(?:-\d{4})?|\d{3}-\d{4})(?![\d-])")
_NON_US_COUNTRY_RE = re.compile(
    r"\b(?:Japan|Canada|Mexico|United Kingdom|UK|Australia|Germany|France|China)\b|日本|加拿大|中国",
    re.IGNORECASE,
)
_CHALLENGE_MARKERS = (
    "pardon our interruption",
    "security measure",
    "verify yourself",
    "verify you are human",
    "captcha",
    "robot check",
    "to continue, please verify",
)
_AUTH_MARKERS = (
    "please sign in to continue",
    "you need to sign in to continue",
)
_ZERO_RESULT_MARKERS = (
    "0 results for",
    "no results found",
    "we couldn't find any results",
    "we couldn’t find any results",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clip(value: Any, limit: int = 300) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text:
        return None
    return text[:limit]


def _visible_text(html: str) -> str:
    without_nonvisible = re.sub(
        r"<(?:script|style|noscript)\b[^>]*>.*?</(?:script|style|noscript)\s*>",
        " ",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return re.sub(
        r"\s+",
        " ",
        html_unescape(re.sub(r"<[^>]+>", " ", without_nonvisible)),
    ).strip()


def normalize_part_number(raw_part_number: str) -> str:
    """Return the contract canonical form: uppercase ASCII letters and digits."""

    if not isinstance(raw_part_number, str) or not raw_part_number.strip():
        raise ValueError("raw_part_number must be a non-empty string")
    normalized = unicodedata.normalize("NFKC", raw_part_number).upper()
    canonical = re.sub(r"[^A-Z0-9]", "", normalized)
    if not canonical:
        raise ValueError("raw_part_number must contain at least one ASCII letter or digit")
    return canonical


def parse_sold_label(
    raw_label: str | None,
    *,
    locale: str = "en-US",
    marketplace_id: str = "EBAY_US",
) -> tuple[int | None, str]:
    """Parse an explicit eBay US sold label.

    Returns ``(sold_count, outcome)`` where outcome is ``PARSED``,
    ``NO_SOLD_SIGNAL``, or ``MARKET_CONTEXT_MISMATCH``.  A ``+`` label is
    deliberately represented by its visible lower bound (for example,
    ``10+ sold`` becomes ``10``), without attempting to estimate a total.
    """

    if locale.lower() != "en-us" or marketplace_id.upper() != "EBAY_US":
        return None, "MARKET_CONTEXT_MISMATCH"
    text = _clip(raw_label)
    if text is None:
        return None, "NO_SOLD_SIGNAL"
    match = _SOLD_RE.search(text)
    if match is None:
        return None, "NO_SOLD_SIGNAL"
    return int(match.group(1).replace(",", "")), "PARSED"


def parse_condition(raw_condition: str | None) -> str:
    """Map visible condition text onto the V0.1 condition enum conservatively."""

    text = (_clip(raw_condition) or "").casefold()
    if not text:
        return "UNKNOWN"
    if "remanufactured" in text or "reman" in text:
        return "REMANUFACTURED"
    if "used" in text or "pre-owned" in text or "preowned" in text:
        return "USED"
    if text in {"new", "brand new", "new with tags", "new in box", "new (other)"}:
        return "NEW"
    if text.startswith("new other") or "open box" in text or "for parts" in text:
        return "OTHER"
    return "UNKNOWN"


def parse_price(raw_price: str | None) -> dict[str, Any] | None:
    """Parse one unambiguous visible USD amount; ranges remain unknown."""

    text = _clip(raw_price)
    if text is None:
        return None
    if re.search(r"\b(?:to|through)\b", text, re.IGNORECASE):
        return None
    matches = re.findall(r"(?:US\s*)?\$\s*([0-9][0-9,]*(?:\.\d{1,2})?)", text, re.I)
    if len(matches) != 1:
        return None
    return {"amount": float(matches[0].replace(",", "")), "currency": "USD"}


def _extract_listing_id(url: str) -> str | None:
    for pattern in _ITEM_ID_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return None


def _extract_part_numbers(title: str) -> list[str]:
    candidates: list[tuple[int, str]] = []
    for pattern in (_PART_WITH_SEPARATOR_RE, _PART_WITH_SPACES_RE, _COMPACT_PART_RE):
        for match in pattern.finditer(title):
            raw = match.group(0).strip()
            year_range = re.fullmatch(r"((?:19|20)\d{2})[-_]((?:19|20)\d{2})", raw)
            if year_range and int(year_range.group(1)) <= int(year_range.group(2)):
                continue
            try:
                if len(normalize_part_number(raw)) >= 5:
                    candidates.append((match.start(), raw))
            except ValueError:
                continue

    unique: list[str] = []
    seen: set[str] = set()
    for _, raw in sorted(candidates, key=lambda item: item[0]):
        canonical = normalize_part_number(raw)
        if canonical not in seen:
            seen.add(canonical)
            unique.append(raw)
    return unique


def _contains_literal_part_number(title: str, raw_part_number: str) -> bool:
    escaped = re.escape(unicodedata.normalize("NFKC", raw_part_number).strip())
    return re.search(rf"(?<![A-Z0-9]){escaped}(?![A-Z0-9])", title, re.I) is not None


def _opposite_side_canonical(canonical: str) -> str | None:
    if "LH" in canonical:
        return canonical.replace("LH", "RH", 1)
    if "RH" in canonical:
        return canonical.replace("RH", "LH", 1)
    if "LEFT" in canonical:
        return canonical.replace("LEFT", "RIGHT", 1)
    if "RIGHT" in canonical:
        return canonical.replace("RIGHT", "LEFT", 1)
    return None


def classify_listing(
    raw_part_number: str,
    title: str,
    *,
    condition: str,
    sold_count: int | None,
    relation_hint: str | None = None,
) -> tuple[str, str]:
    """Classify part relation and evidence decision using transparent V0.1 rules."""

    canonical_query = normalize_part_number(raw_part_number)
    hint = (relation_hint or "").strip().casefold()
    lower_title = title.casefold()
    extracted = _extract_part_numbers(title)
    extracted_canonical = {normalize_part_number(value) for value in extracted}
    query_present = (
        canonical_query in extracted_canonical
        or _contains_literal_part_number(title, raw_part_number)
    )
    opposite_side = _opposite_side_canonical(canonical_query)

    if hint == "left_right_pair":
        match_type = "SIDE_MISMATCH"
    elif not query_present and opposite_side is not None and opposite_side in extracted_canonical:
        match_type = "SIDE_MISMATCH"
    elif not query_present:
        match_type = "IRRELEVANT"
    elif hint == "cross_reference" or "cross reference" in lower_title or "interchange" in lower_title:
        match_type = "CROSS_REFERENCE"
    elif hint == "replacement" or re.search(r"\b(?:replaces?|replacement for|supersedes?)\b", lower_title):
        match_type = "REPLACEMENT"
    elif hint in {"unknown_relation", "ambiguous"}:
        match_type = "AMBIGUOUS"
    elif opposite_side is not None and opposite_side in extracted_canonical:
        match_type = "LEFT_RIGHT_PAIR"
    elif any(value != canonical_query for value in extracted_canonical):
        match_type = "AMBIGUOUS"
    elif _contains_literal_part_number(title, raw_part_number):
        match_type = "EXACT"
    else:
        match_type = "NORMALIZED_EXACT"

    if match_type in {"CROSS_REFERENCE", "REPLACEMENT", "LEFT_RIGHT_PAIR", "AMBIGUOUS", "UNKNOWN"}:
        return match_type, "HUMAN_REVIEW"
    if match_type in {"SIDE_MISMATCH", "IRRELEVANT"}:
        return match_type, "REJECT"
    if condition == "NEW" and sold_count is not None and sold_count > 0:
        return match_type, "ACCEPT_DEMAND_EVIDENCE"
    return match_type, "REJECT"


def _as_absolute_ebay_url(raw_url: str, page_url: str) -> str:
    absolute = urljoin(page_url, raw_url)
    listing_id = _extract_listing_id(absolute)
    if listing_id:
        return f"https://www.ebay.com/itm/{listing_id}"
    return absolute


def _first_text(card: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _clip(card.get(key))
        if value:
            return value
    return None


def _parse_available_count(text: str | None) -> int | None:
    if not text:
        return None
    match = _AVAILABLE_RE.search(text)
    return int(match.group(1).replace(",", "")) if match else None


def parse_listing_card(
    card: Mapping[str, Any],
    raw_part_number: str | None = None,
    *,
    query: str | None = None,
    page_url: str = "https://www.ebay.com/",
    retrieved_at: str | None = None,
    locale: str = "en-US",
    marketplace_id: str = "EBAY_US",
) -> dict[str, Any]:
    """Convert a visible card mapping into schema-shaped listing evidence.

    The accepted card keys are intentionally simple and suitable for offline
    fixtures: ``url``, ``title``, ``condition``, ``price``, ``sold_label``,
    ``available``, ``seller``, ``location``, and optional ``relation_hint``.
    """

    part_number = raw_part_number if raw_part_number is not None else query
    if part_number is None:
        raise ValueError("raw_part_number or query is required")
    title = _first_text(card, "title")
    raw_url = _first_text(card, "url", "href")
    if not title or not raw_url:
        raise ValueError("listing card requires a visible title and item URL")
    url = _as_absolute_ebay_url(raw_url, page_url)
    listing_id = _extract_listing_id(url)
    if not listing_id:
        raise ValueError("listing card URL does not contain a valid eBay item ID")

    condition = parse_condition(_first_text(card, "condition"))
    details = _first_text(card, "details", "dynamic_text")
    sold_label = _first_text(card, "sold_label", "sold")
    if sold_label is None and details:
        sold_match = _SOLD_RE.search(details)
        sold_label = sold_match.group(0) if sold_match else None
    sold_count, _ = parse_sold_label(
        sold_label,
        locale=locale,
        marketplace_id=marketplace_id,
    )
    match_type, decision = classify_listing(
        part_number,
        title,
        condition=condition,
        sold_count=sold_count,
        relation_hint=_first_text(card, "relation_hint"),
    )
    available_text = _first_text(card, "available", "availability") or details
    timestamp = retrieved_at or _utc_now()
    raw_fields = [f"title={title}"]
    raw_condition = _first_text(card, "condition")
    if raw_condition:
        raw_fields.append(f"condition={raw_condition}")
    if sold_label:
        raw_fields.append(f"sold={sold_label}")
    raw_evidence = _clip(" | ".join(raw_fields), 500) or f"title={title}"

    return {
        "listing_id": listing_id,
        "url": url,
        "title": title,
        "condition": condition,
        "price": parse_price(_first_text(card, "price")),
        "sold_count": sold_count,
        "sold_label_raw": sold_label,
        "available_count": _parse_available_count(available_text),
        "seller": _first_text(card, "seller"),
        "location": _first_text(card, "location"),
        "part_numbers": _extract_part_numbers(title),
        "match_type": match_type,
        "decision": decision,
        "evidence": [
            {
                "metric": "listing_card_observation",
                "value": {
                    "listing_id": listing_id,
                    "condition": condition,
                    "sold_count": sold_count,
                },
                "source": "eBay visible search-result card",
                "url": url,
                "retrieved_at": timestamp,
                "extraction_method": "VISIBLE_TEXT",
                "raw_evidence": raw_evidence,
                "confidence": 1.0 if sold_count is not None else 0.8,
            }
        ],
    }


class _ListingCardHTMLParser(HTMLParser):
    """Small purpose-built parser for visible ``li.s-item`` card fields."""

    _VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict[str, str]] = []
        self._card: dict[str, str] | None = None
        self._depth = 0
        self._captures: list[tuple[int, str]] = []

    @staticmethod
    def _classes(attrs: dict[str, str]) -> set[str]:
        return {value for value in attrs.get("class", "").split() if value}

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {key: value or "" for key, value in attrs_list}
        classes = self._classes(attrs)
        is_void = tag in self._VOID_TAGS
        if self._card is None and "s-item" in classes:
            self._card = {}
            self._depth = 1
        elif self._card is not None and not is_void:
            self._depth += 1

        if self._card is None:
            return
        if tag == "a" and "s-item__link" in classes and attrs.get("href"):
            self._card.setdefault("url", attrs["href"])

        field: str | None = None
        if "s-item__title" in classes:
            field = "title"
        elif "s-item__condition" in classes:
            field = "condition"
        elif "s-item__price" in classes:
            field = "price"
        elif any("seller-info" in value for value in classes):
            field = "seller"
        elif "s-item__location" in classes:
            field = "location"
        elif any(
            marker in value.casefold()
            for value in classes
            for marker in ("quantitysold", "hotness", "dynamic", "availability")
        ):
            field = "details"
        if field is not None:
            self._captures.append((self._depth, field))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self._card is None or not self._captures:
            return
        text = _clip(data)
        if not text:
            return
        _, field = self._captures[-1]
        current = self._card.get(field)
        self._card[field] = f"{current} {text}".strip() if current else text

    def handle_endtag(self, tag: str) -> None:
        if self._card is None:
            return
        self._captures = [entry for entry in self._captures if entry[0] < self._depth]
        if self._depth == 1:
            self.cards.append(self._card)
            self._card = None
            self._captures = []
            self._depth = 0
        else:
            self._depth -= 1


def extract_listing_cards_from_html(html: str) -> list[dict[str, str]]:
    """Extract simple card mappings from a captured, already-rendered DOM."""

    parser = _ListingCardHTMLParser()
    parser.feed(html)
    parser.close()
    return parser.cards


def _diagnostic(code: str, message: str, raw_marker: Any = None) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "raw_marker": _clip(raw_marker, 200),
    }


def parse_listing_cards(
    cards: Sequence[Mapping[str, Any]],
    raw_part_number: str,
    *,
    page_url: str,
    retrieved_at: str | None = None,
    locale: str = "en-US",
    marketplace_id: str = "EBAY_US",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse and de-duplicate visible card mappings without making network calls."""

    listings: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, card in enumerate(cards):
        try:
            listing = parse_listing_card(
                card,
                raw_part_number,
                page_url=page_url,
                retrieved_at=retrieved_at,
                locale=locale,
                marketplace_id=marketplace_id,
            )
        except (TypeError, ValueError) as exc:
            title = _first_text(card, "title")
            if title and title.casefold() == "shop on ebay":
                continue
            diagnostics.append(
                _diagnostic("CARD_SKIPPED", f"Card {index} could not be parsed", str(exc))
            )
            continue
        listing_id = listing["listing_id"]
        if listing_id in seen:
            diagnostics.append(
                _diagnostic("DUPLICATE_LISTING", "Duplicate listing ID was ignored", listing_id)
            )
            continue
        seen.add(listing_id)
        listings.append(listing)
    return listings, diagnostics


def parse_search_html(
    html: str,
    raw_part_number: str,
    *,
    page_url: str,
    retrieved_at: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Offline HTML-to-listings helper used by the browser provider and tests."""

    cards = extract_listing_cards_from_html(html)
    return parse_listing_cards(
        cards,
        raw_part_number,
        page_url=page_url,
        retrieved_at=retrieved_at,
    )


def classify_page_status(
    *,
    url: str,
    html: str,
    http_status: int | None = None,
    timed_out: bool = False,
) -> tuple[str | None, str | None]:
    """Classify terminal transport/page states without conflating them with zero."""

    if timed_out:
        return "TIMEOUT", "navigation deadline exceeded"
    if http_status is not None and 400 <= http_status:
        return "HTTP_ERROR", f"HTTP {http_status}"
    lower_url = url.casefold()
    lower_visible_text = _visible_text(html).casefold()
    if "/splashui/challenge" in lower_url or "/challenge" in lower_url:
        return "CHALLENGE", _clip(url)
    if "signin.ebay." in lower_url or "/signin/" in lower_url:
        return "AUTH_REQUIRED", _clip(url)
    if re.search(r"<title\b[^>]*>\s*sign in\b", html, re.IGNORECASE):
        return "AUTH_REQUIRED", "sign-in page title"
    for marker in _AUTH_MARKERS:
        if marker in lower_visible_text:
            return "AUTH_REQUIRED", marker
    for marker in _CHALLENGE_MARKERS:
        if marker in lower_visible_text:
            return "CHALLENGE", marker
    for marker in _ZERO_RESULT_MARKERS:
        if marker in lower_visible_text:
            return "ZERO_RESULTS", marker
    return None, None


def _visible_ship_context(visible_text: str) -> tuple[bool, str | None]:
    """Return visible expected-context evidence and any higher-priority conflict."""

    expected_visible = False
    ship_prefix = re.compile(r"(?:ship(?:ping)?\s+to|deliver(?:y|ing)?\s+to)", re.I)
    for match in ship_prefix.finditer(visible_text):
        segment = visible_text[match.end() : match.end() + 120]
        postal_codes = _POSTAL_RE.findall(segment)
        for postal_code in postal_codes:
            if postal_code != "10001":
                return False, f"visible ship-to postal code conflicts with 10001: {postal_code}"
        if _NON_US_COUNTRY_RE.search(segment):
            country_marker = _NON_US_COUNTRY_RE.search(segment)
            return False, f"visible ship-to country conflicts with US: {country_marker.group(0)}"
        has_us = (
            re.search(r"\bUnited\s+States\b", segment, re.I) is not None
            or re.search(r"\bUS\b", segment) is not None
        )
        if has_us and "10001" in postal_codes:
            expected_visible = True
    return expected_visible, None


def market_context_is_exact(
    *,
    url: str,
    html: str,
    expected_query: str | None = None,
) -> tuple[bool, str | None]:
    """Fail closed unless the response proves the frozen eBay search context."""

    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    if host not in {"ebay.com", "www.ebay.com"}:
        return False, f"unexpected host: {host or 'missing'}"
    if parsed.path.rstrip("/").casefold() != "/sch/i.html":
        return False, f"unexpected eBay response path: {parsed.path or '/'}"
    if expected_query is not None:
        response_queries = parse_qs(parsed.query, keep_blank_values=True).get("_nkw", [])
        if len(response_queries) != 1:
            return False, "final search URL does not contain exactly one _nkw query"
        try:
            response_canonical = normalize_part_number(response_queries[0])
            expected_canonical = normalize_part_number(expected_query)
        except ValueError:
            return False, "final search URL contains an unusable _nkw query"
        if response_canonical != expected_canonical:
            return False, "final search URL _nkw does not match the requested candidate"

    language_match = _HTML_LANG_RE.search(html)
    language = (
        language_match.group(1).replace("_", "-").casefold()
        if language_match is not None
        else None
    )
    if language is not None and language != "en-us":
        return False, f"response does not explicitly prove en-US locale: {language}"
    state_locales = {
        value.replace("_", "-").casefold()
        for value in _LOCALE_STATE_VALUE_RE.findall(html)
    }
    conflicting_locales = sorted(value for value in state_locales if value != "en-us")
    if conflicting_locales:
        return False, f"response state contains conflicting locale: {conflicting_locales[0]}"
    if language is None and _EN_US_STATE_RE.search(html) is None:
        return False, "response has no explicit en-US locale evidence"

    # Request parameters only describe intent.  They are deliberately excluded
    # here because eBay can preserve _stpos=10001 while rendering another saved
    # country/postal context.  Require visible shipping text or an explicit
    # response-state country/postal pair instead.
    visible_text = _visible_text(html)
    visible_ship_context, visible_ship_conflict = _visible_ship_context(visible_text)
    if visible_ship_conflict is not None:
        return False, visible_ship_conflict

    state_ship_countries = re.findall(
        r"[\"']shipToCountry[\"']\s*:\s*[\"']([^\"']+)[\"']",
        html,
        re.IGNORECASE,
    )
    state_ship_postals = re.findall(
        r"[\"']shipToPostalCode[\"']\s*:\s*[\"']([^\"']+)[\"']",
        html,
        re.IGNORECASE,
    )
    if any(value.upper() != "US" for value in state_ship_countries):
        return False, "response state contains a non-US ship-to country"
    if any(value != "10001" for value in state_ship_postals):
        return False, "response state contains a ship-to postal code other than 10001"
    structured_ship_context = re.search(
        r"(?:[\"']shipToCountry[\"']\s*:\s*[\"']US[\"']"
        r".{0,300}[\"']shipToPostalCode[\"']\s*:\s*[\"']10001[\"']|"
        r"[\"']shipToPostalCode[\"']\s*:\s*[\"']10001[\"']"
        r".{0,300}[\"']shipToCountry[\"']\s*:\s*[\"']US[\"'])",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if not visible_ship_context and structured_ship_context is None:
        return False, "response does not explicitly prove ship-to US 10001"

    state_currencies = {value.upper() for value in _CURRENCY_STATE_VALUE_RE.findall(html)}
    conflicting_currencies = sorted(value for value in state_currencies if value != "USD")
    if conflicting_currencies:
        return False, f"response state contains conflicting currency: {conflicting_currencies[0]}"
    visible_currency_conflict = _NON_US_CURRENCY_RE.search(visible_text)
    if visible_currency_conflict is not None:
        return False, f"visible currency conflicts with USD: {visible_currency_conflict.group(0)}"
    if _USD_MARKER_RE.search(html) is None:
        return False, "response has no explicit USD currency evidence"
    return True, None


def _observed_demand(listings: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    eligible = [
        int(listing["sold_count"])
        for listing in listings
        if listing.get("decision") == "ACCEPT_DEMAND_EVIDENCE"
        and listing.get("match_type") in {"EXACT", "NORMALIZED_EXACT"}
        and listing.get("condition") == "NEW"
        and isinstance(listing.get("sold_count"), int)
        and int(listing["sold_count"]) > 0
    ]
    return {
        "eligible_listing_count": len(eligible),
        "max_single_listing_sold": max(eligible) if eligible else None,
        "aggregate_observed_sold": sum(eligible),
    }


def _base_outcome(raw_part_number: str, retrieved_at: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "platform": "EBAY",
        "provider": PROVIDER,
        "source_method": "BROWSER",
        "query": {
            "raw_part_number": raw_part_number,
            "canonical_part_number": normalize_part_number(raw_part_number),
            "query_type": "EXACT_PART_NUMBER",
        },
        "market_context": dict(EXPECTED_MARKET_CONTEXT),
        "status": "PARSER_FAILED",
        "retrieved_at": retrieved_at,
        "listings": [],
        "observed_demand": _observed_demand([]),
        "diagnostics": [],
    }


def _failure_outcome(
    raw_part_number: str,
    status: str,
    *,
    retrieved_at: str,
    marker: Any = None,
) -> dict[str, Any]:
    outcome = _base_outcome(raw_part_number, retrieved_at)
    outcome["status"] = status
    if status != "ZERO_RESULTS":
        outcome["diagnostics"] = [
            _diagnostic(status, f"eBay acquisition ended with {status}", marker)
        ]
    return outcome


def _search_url(raw_part_number: str) -> str:
    query = urlencode(
        {
            "_nkw": raw_part_number.strip(),
            "_sacat": "0",
            "_ipg": "60",
            "_stpos": EXPECTED_MARKET_CONTEXT["ship_to_postal_code"],
        }
    )
    return f"https://www.ebay.com/sch/i.html?{query}"


def _load_playwright() -> tuple[Any, type[Exception], type[Exception]]:
    """Import Playwright only when live browser acquisition is requested."""

    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    return sync_playwright, PlaywrightTimeoutError, PlaywrightError


def _browser_candidates(browser_channel: str) -> tuple[str, ...]:
    channel = browser_channel.strip().casefold()
    if channel == "auto":
        return "msedge", "chrome"
    if channel in {"edge", "msedge"}:
        return ("msedge",)
    if channel == "chrome":
        return "chrome", "msedge"
    raise ValueError("browser_channel must be one of: auto, chrome, edge, msedge")


def _is_missing_browser_error(exc: BaseException) -> bool:
    text = str(exc).casefold()
    return any(
        marker in text
        for marker in (
            "executable doesn't exist",
            "executable does not exist",
            "distribution 'chrome' is not found",
            'distribution "chrome" is not found',
            "distribution 'msedge' is not found",
            'distribution "msedge" is not found',
        )
    )


def _is_retryable_navigation_error(exc: BaseException) -> bool:
    text = str(exc).casefold()
    return any(
        marker in text
        for marker in (
            "err_connection_reset",
            "err_connection_closed",
            "err_connection_refused",
            "err_network_changed",
            "err_timed_out",
            "connection reset",
            "connection closed",
        )
    )


def _launch_browser(browser_type: Any, channels: Sequence[str], *, headless: bool) -> Any:
    last_missing_error: BaseException | None = None
    for channel in channels:
        try:
            return browser_type.launch(channel=channel, headless=headless)
        except Exception as exc:
            if not _is_missing_browser_error(exc):
                raise
            last_missing_error = exc
    if last_missing_error is not None:
        raise last_missing_error
    raise RuntimeError("no permitted system browser channel is configured")


def collect_ebay(
    raw_part_number: str,
    *,
    headless: bool = True,
    browser_channel: str = "chrome",
    timeout_ms: int = 30000,
) -> dict[str, Any]:
    """Collect one low-frequency, first-page eBay US acquisition outcome.

    There is no login, challenge handling, stealth, pagination, or concurrency.
    Navigation timeouts, connection failures, and HTTP 5xx responses receive at
    most one retry; 4xx, login, challenge, and market mismatches do not retry.
    """

    normalize_part_number(raw_part_number)
    if not isinstance(timeout_ms, int) or timeout_ms <= 0:
        raise ValueError("timeout_ms must be a positive integer")
    channels = _browser_candidates(browser_channel)
    retrieved_at = _utc_now()
    search_url = _search_url(raw_part_number)

    try:
        sync_playwright, timeout_error_type, playwright_error_type = _load_playwright()
    except Exception as exc:
        return _failure_outcome(
            raw_part_number,
            "PROVIDER_UNAVAILABLE",
            retrieved_at=retrieved_at,
            marker=exc,
        )

    browser = None
    context = None
    phase = "playwright_start"
    try:
        with sync_playwright() as playwright:
            phase = "browser_launch"
            try:
                browser = _launch_browser(playwright.chromium, channels, headless=headless)
            except Exception as exc:
                return _failure_outcome(
                    raw_part_number,
                    "PROVIDER_UNAVAILABLE",
                    retrieved_at=retrieved_at,
                    marker=exc,
                )

            phase = "context_create"
            context = browser.new_context(
                locale="en-US",
                timezone_id="America/New_York",
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            phase = "page_create"
            page = context.new_page()
            response = None
            navigation_error: BaseException | None = None
            for attempt in range(2):
                navigation_error = None
                phase = "navigation"
                try:
                    response = page.goto(
                        search_url,
                        wait_until="domcontentloaded",
                        timeout=timeout_ms,
                    )
                except timeout_error_type as exc:
                    navigation_error = exc
                    if attempt == 0:
                        continue
                    return _failure_outcome(
                        raw_part_number,
                        "TIMEOUT",
                        retrieved_at=retrieved_at,
                        marker=exc,
                    )
                except playwright_error_type as exc:
                    navigation_error = exc
                    if attempt == 0 and _is_retryable_navigation_error(exc):
                        continue
                    status = "TIMEOUT" if "timed out" in str(exc).casefold() else "HTTP_ERROR"
                    return _failure_outcome(
                        raw_part_number,
                        status,
                        retrieved_at=retrieved_at,
                        marker=exc,
                    )

                http_status = response.status if response is not None else None
                if http_status is not None and 500 <= http_status and attempt == 0:
                    continue
                break

            if navigation_error is not None:
                return _failure_outcome(
                    raw_part_number,
                    "HTTP_ERROR",
                    retrieved_at=retrieved_at,
                    marker=navigation_error,
                )

            phase = "dom_wait"
            try:
                page.wait_for_selector(
                    "li.s-item, .srp-controls__count-heading",
                    timeout=min(timeout_ms, 5000),
                )
            except timeout_error_type:
                pass

            phase = "content_capture"
            html = page.content()
            final_url = page.url
            http_status = response.status if response is not None else None
            phase = "response_parse"
            page_status, marker = classify_page_status(
                url=final_url,
                html=html,
                http_status=http_status,
            )
            if page_status in {"HTTP_ERROR", "AUTH_REQUIRED", "CHALLENGE"}:
                return _failure_outcome(
                    raw_part_number,
                    page_status,
                    retrieved_at=retrieved_at,
                    marker=marker,
                )

            market_exact, market_marker = market_context_is_exact(
                url=final_url,
                html=html,
                expected_query=raw_part_number,
            )
            if not market_exact:
                return _failure_outcome(
                    raw_part_number,
                    "MARKET_CONTEXT_MISMATCH",
                    retrieved_at=retrieved_at,
                    marker=market_marker,
                )

            if page_status == "ZERO_RESULTS":
                return _failure_outcome(
                    raw_part_number,
                    "ZERO_RESULTS",
                    retrieved_at=retrieved_at,
                    marker=marker,
                )

            listings, diagnostics = parse_search_html(
                html,
                raw_part_number,
                page_url=final_url,
                retrieved_at=retrieved_at,
            )
            if not listings:
                outcome = _failure_outcome(
                    raw_part_number,
                    "PARSER_FAILED",
                    retrieved_at=retrieved_at,
                    marker="no valid listing cards parsed from a non-zero results page",
                )
                outcome["diagnostics"] = diagnostics + outcome["diagnostics"]
                return outcome

            outcome = _base_outcome(raw_part_number, retrieved_at)
            outcome["status"] = "PARTIAL_SUCCESS" if diagnostics else "SUCCESS"
            outcome["listings"] = listings
            outcome["observed_demand"] = _observed_demand(listings)
            outcome["diagnostics"] = diagnostics
            return outcome
    except Exception as exc:
        if phase in {"playwright_start", "browser_launch", "context_create", "page_create"}:
            status = "PROVIDER_UNAVAILABLE"
        elif phase in {"navigation", "dom_wait"}:
            status = "TIMEOUT" if "timed out" in str(exc).casefold() else "HTTP_ERROR"
        else:
            status = "PARSER_FAILED"
        return _failure_outcome(
            raw_part_number,
            status,
            retrieved_at=retrieved_at,
            marker=f"{phase}: {exc}",
        )
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass


__all__ = [
    "EXPECTED_MARKET_CONTEXT",
    "classify_listing",
    "classify_page_status",
    "collect_ebay",
    "extract_listing_cards_from_html",
    "market_context_is_exact",
    "normalize_part_number",
    "parse_condition",
    "parse_listing_card",
    "parse_listing_cards",
    "parse_price",
    "parse_search_html",
    "parse_sold_label",
]
