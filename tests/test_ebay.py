from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from proteus import ebay


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = json.loads((ROOT / "fixtures" / "ebay_v0_1_cases.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((ROOT / "contracts" / "v0_1_acquisition.schema.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", FIXTURES["normalization_cases"], ids=lambda case: case["id"])
def test_normalize_part_number_fixture(case: dict[str, object]) -> None:
    assert ebay.normalize_part_number(case["raw"]) == case["expected_canonical"]


@pytest.mark.parametrize("invalid", ["", "   ", "---", None])
def test_normalize_part_number_rejects_unusable_input(invalid: object) -> None:
    with pytest.raises(ValueError):
        ebay.normalize_part_number(invalid)  # type: ignore[arg-type]


@pytest.mark.parametrize("case", FIXTURES["sold_label_cases"], ids=lambda case: case["id"])
def test_parse_sold_label_fixture(case: dict[str, object]) -> None:
    count, outcome = ebay.parse_sold_label(
        case["raw_label"],
        locale=case["locale"],
        marketplace_id=case["marketplace_id"],
    )
    assert count == case["expected_sold_count"]
    assert outcome == case["expected_label_outcome"]


@pytest.mark.parametrize("case", FIXTURES["matching_cases"], ids=lambda case: case["id"])
def test_classify_listing_fixture(case: dict[str, object]) -> None:
    match_type, decision = ebay.classify_listing(
        case["query"],
        case["candidate_title"],
        condition=case["condition"],
        sold_count=case["sold_count"],
        relation_hint=case["relation_hint"],
    )
    assert match_type == case["expected_match_type"]
    assert decision == case["expected_decision"]


def test_parse_listing_card_retains_only_minimum_visible_evidence() -> None:
    listing = ebay.parse_listing_card(
        {
            "url": "https://www.ebay.com/itm/123456789012?hash=tracking",
            "title": "New OEM 53630-53010 Automotive Part",
            "condition": "New",
            "price": "US $1,234.50",
            "sold_label": "32 sold",
            "available": "7 available",
            "seller": "parts-seller",
            "location": "Located in United States",
        },
        "53630-53010",
        retrieved_at="2026-08-25T00:00:00Z",
    )

    assert listing["listing_id"] == "123456789012"
    assert listing["url"] == "https://www.ebay.com/itm/123456789012"
    assert listing["condition"] == "NEW"
    assert listing["price"] == {"amount": 1234.5, "currency": "USD"}
    assert listing["sold_count"] == 32
    assert listing["available_count"] == 7
    assert listing["match_type"] == "EXACT"
    assert listing["decision"] == "ACCEPT_DEMAND_EVIDENCE"
    assert listing["evidence"][0]["raw_evidence"] == (
        "title=New OEM 53630-53010 Automotive Part | condition=New | sold=32 sold"
    )
    assert "hash=tracking" not in listing["evidence"][0]["raw_evidence"]


def test_vehicle_year_range_does_not_make_exact_part_number_ambiguous() -> None:
    match_type, decision = ebay.classify_listing(
        "A18-67004-004",
        "2017-2024 Freightliner New Door Handle A18-67004-004",
        condition="NEW",
        sold_count=5,
    )

    assert match_type == "EXACT"
    assert decision == "ACCEPT_DEMAND_EVIDENCE"


def test_html_parser_reads_visible_cards_and_deduplicates_listing_id() -> None:
    html = """
    <html lang="en-US"><body>
      <ul>
        <li class="s-item">
          <a class="s-item__link" href="https://www.ebay.com/itm/123456789012"><span class="s-item__title">New OEM 53630-53010 Automotive Part</span></a>
          <span class="s-item__condition">New</span>
          <span class="s-item__price">$88.00</span>
          <span class="s-item__quantitySold">32 sold</span>
        </li>
        <li class="s-item">
          <a class="s-item__link" href="https://www.ebay.com/itm/123456789012"><span class="s-item__title">Duplicate 53630-53010</span></a>
          <span class="s-item__condition">New</span>
          <span class="s-item__quantitySold">99 sold</span>
        </li>
      </ul>
    </body></html>
    """

    listings, diagnostics = ebay.parse_search_html(
        html,
        "53630-53010",
        page_url="https://www.ebay.com/sch/i.html?_stpos=10001",
        retrieved_at="2026-08-25T00:00:00Z",
    )

    assert len(listings) == 1
    assert listings[0]["sold_count"] == 32
    assert diagnostics == [
        {
            "code": "DUPLICATE_LISTING",
            "message": "Duplicate listing ID was ignored",
            "raw_marker": "123456789012",
        }
    ]


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            {"url": "https://www.ebay.com/sch/i.html", "html": "<html>0 results for x</html>"},
            "ZERO_RESULTS",
        ),
        (
            {
                "url": "https://www.ebay.com/sch/i.html",
                "html": "<html>Pardon Our Interruption</html>",
            },
            "CHALLENGE",
        ),
        (
            {
                "url": "https://www.ebay.com/splashui/challenge?flow=abc",
                "html": '<html lang="ja-JP"><header>Japan 100-0001</header></html>',
            },
            "CHALLENGE",
        ),
        (
            {"url": "https://signin.ebay.com/signin/", "html": "<html></html>"},
            "AUTH_REQUIRED",
        ),
        (
            {
                "url": "https://www.ebay.com/sch/i.html",
                "html": "<html>Pardon Our Interruption</html>",
                "http_status": 403,
            },
            "HTTP_ERROR",
        ),
        (
            {"url": "https://www.ebay.com/sch/i.html", "html": "", "timed_out": True},
            "TIMEOUT",
        ),
    ],
)
def test_page_failure_classification_is_explicit(kwargs: dict[str, object], expected: str) -> None:
    status, _ = ebay.classify_page_status(**kwargs)
    assert status == expected


def test_market_context_requires_us_site_language_and_ship_to() -> None:
    exact, marker = ebay.market_context_is_exact(
        url="https://www.ebay.com/sch/i.html?_stpos=10001",
        html=(
            '<html lang="en-US"><div>Ship to United States 10001</div>'
            '<span class="s-item__price">US $10.00</span></html>'
        ),
    )
    assert exact is True
    assert marker is None

    wrong_locale, marker = ebay.market_context_is_exact(
        url="https://www.ebay.com/sch/i.html?_stpos=10001",
        html='<html lang="ja-JP"><div>Ship to United States 10001</div><span>US $10.00</span></html>',
    )
    assert wrong_locale is False
    assert "en-US" in marker

    unverifiable_ship_to, marker = ebay.market_context_is_exact(
        url="https://www.ebay.com/sch/i.html?_stpos=10001",
        html='<html lang="en-US"><span>US $10.00</span></html>',
    )
    assert unverifiable_ship_to is False
    assert "10001" in marker


def test_market_context_request_parameter_cannot_override_rendered_japan_context() -> None:
    exact, marker = ebay.market_context_is_exact(
        url="https://www.ebay.com/sch/i.html?_stpos=10001",
        html=(
            '<html lang="ja-JP"><header>Ship to Japan 100-0001</header>'
            '<span>JPY 12,000</span></html>'
        ),
    )

    assert exact is False
    assert "en-US" in marker


def test_market_context_accepts_explicit_response_state_not_request_intent() -> None:
    exact, marker = ebay.market_context_is_exact(
        url="https://www.ebay.com/sch/i.html?_stpos=99999",
        html=(
            '<html lang="en-US"><script type="application/json">'
            '{"shipToCountry":"US","shipToPostalCode":"10001","currency":"USD"}'
            "</script></html>"
        ),
    )

    assert exact is True
    assert marker is None


@pytest.mark.parametrize(
    ("html", "marker_fragment"),
    [
        (
            '<html lang="ja-JP"><header>Ship to Japan 100-0001</header>'
            '<script>{"locale":"en-US","shipToCountry":"US",'
            '"shipToPostalCode":"10001","currency":"USD"}</script></html>',
            "en-US",
        ),
        (
            '<html lang="en-US"><header>Ship to Japan 100-0001</header>'
            '<script>{"shipToCountry":"US","shipToPostalCode":"10001",'
            '"currency":"USD"}</script></html>',
            "postal code",
        ),
        (
            '<html lang="en-US"><header>Ship to United States 90210</header>'
            '<script>{"shipToCountry":"US","shipToPostalCode":"10001",'
            '"currency":"USD"}</script></html>',
            "90210",
        ),
        (
            '<html lang="en-US"><header>Ship to United States 10001; Currency JPY</header>'
            '<script>{"shipToCountry":"US","shipToPostalCode":"10001",'
            '"currency":"USD"}</script></html>',
            "JPY",
        ),
    ],
)
def test_market_context_visible_conflict_beats_stale_expected_script_state(
    html: str,
    marker_fragment: str,
) -> None:
    exact, marker = ebay.market_context_is_exact(
        url="https://www.ebay.com/sch/i.html?_nkw=53630-53010",
        html=html,
        expected_query="53630-53010",
    )

    assert exact is False
    assert marker_fragment in marker


def test_market_context_requires_search_path_and_matching_final_query() -> None:
    html = (
        '<html lang="en-US"><header>Ship to United States 10001; Currency USD</header></html>'
    )

    homepage, marker = ebay.market_context_is_exact(
        url="https://www.ebay.com/?_nkw=53630-53010",
        html=html,
        expected_query="53630-53010",
    )
    assert homepage is False
    assert "path" in marker

    wrong_query, marker = ebay.market_context_is_exact(
        url="https://www.ebay.com/sch/i.html?_nkw=A18-67004-004",
        html=html,
        expected_query="53630-53010",
    )
    assert wrong_query is False
    assert "_nkw" in marker

    normalized_match, marker = ebay.market_context_is_exact(
        url="https://www.ebay.com/sch/i.html?_nkw=5363053010",
        html=html,
        expected_query="53630-53010",
    )
    assert normalized_match is True
    assert marker is None


def test_challenge_vocabulary_inside_script_is_not_a_visible_challenge() -> None:
    status, marker = ebay.classify_page_status(
        url="https://www.ebay.com/sch/i.html",
        html=(
            '<html lang="en-US"><script>const feature = "captcha";</script>'
            "<body>ordinary search results</body></html>"
        ),
    )

    assert status is None
    assert marker is None


class _FakeTimeoutError(Exception):
    pass


class _FakePlaywrightError(Exception):
    pass


class _FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status


class _FakePage:
    def __init__(
        self,
        html: str,
        statuses: list[int],
        url_override: str | None = None,
        fail_at: str | None = None,
    ) -> None:
        self._html = html
        self._statuses = statuses
        self._url_override = url_override
        self._fail_at = fail_at
        self.url = "about:blank"
        self.goto_calls = 0

    def goto(self, url: str, **_: object) -> _FakeResponse:
        if self._fail_at == "goto":
            raise RuntimeError("injected goto failure")
        self.goto_calls += 1
        self.url = self._url_override or url
        status = self._statuses[min(self.goto_calls - 1, len(self._statuses) - 1)]
        return _FakeResponse(status)

    def wait_for_selector(self, *_: object, **__: object) -> None:
        if self._fail_at == "wait_for_selector":
            raise RuntimeError("injected DOM wait failure")
        return None

    def content(self) -> str:
        if self._fail_at == "content":
            raise RuntimeError("injected content failure")
        return self._html


class _FakeContext:
    def __init__(self, page: _FakePage, fail_at: str | None = None) -> None:
        self.page = page
        self._fail_at = fail_at
        self.closed = False

    def new_page(self) -> _FakePage:
        if self._fail_at == "new_page":
            raise RuntimeError("injected new-page failure")
        return self.page

    def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self, page: _FakePage, fail_at: str | None = None) -> None:
        self._fail_at = fail_at
        self.context = _FakeContext(page, fail_at)
        self.context_options: dict[str, object] | None = None
        self.closed = False

    def new_context(self, **kwargs: object) -> _FakeContext:
        if self._fail_at == "new_context":
            raise RuntimeError("injected new-context failure")
        self.context_options = kwargs
        return self.context

    def close(self) -> None:
        self.closed = True


class _FakeChromium:
    def __init__(self, browser: _FakeBrowser, *, chrome_missing: bool = False) -> None:
        self.browser = browser
        self.chrome_missing = chrome_missing
        self.channels: list[str] = []

    def launch(self, *, channel: str, headless: bool) -> _FakeBrowser:
        self.channels.append(channel)
        assert headless is True
        if self.chrome_missing and channel == "chrome":
            raise _FakePlaywrightError("Executable doesn't exist for chrome")
        return self.browser


class _FakePlaywright:
    def __init__(self, chromium: _FakeChromium) -> None:
        self.chromium = chromium


class _FakeManager:
    def __init__(self, playwright: _FakePlaywright, fail_at: str | None = None) -> None:
        self.playwright = playwright
        self._fail_at = fail_at

    def __enter__(self) -> _FakePlaywright:
        if self._fail_at == "enter":
            raise RuntimeError("injected Playwright enter failure")
        return self.playwright

    def __exit__(self, *_: object) -> None:
        return None


def _install_fake_playwright(
    monkeypatch: pytest.MonkeyPatch,
    html: str,
    *,
    statuses: list[int] | None = None,
    url_override: str | None = None,
    chrome_missing: bool = False,
    fail_at: str | None = None,
) -> tuple[_FakePage, _FakeChromium]:
    page = _FakePage(html, statuses or [200], url_override, fail_at)
    browser = _FakeBrowser(page, fail_at)
    chromium = _FakeChromium(browser, chrome_missing=chrome_missing)
    playwright = _FakePlaywright(chromium)
    monkeypatch.setattr(
        ebay,
        "_load_playwright",
        lambda: (
            lambda: _FakeManager(playwright, fail_at),
            _FakeTimeoutError,
            _FakePlaywrightError,
        ),
    )
    return page, chromium


VALID_HTML = """
<html lang="en-US"><body>
  <header>Ship to United States 10001</header>
  <li class="s-item">
    <a class="s-item__link" href="https://www.ebay.com/itm/123456789012">
      <span class="s-item__title">New OEM 53630-53010 Automotive Part</span>
    </a>
    <span class="s-item__condition">New</span>
    <span class="s-item__price">US $88.00</span>
    <span class="s-item__quantitySold">32 sold</span>
  </li>
</body></html>
"""


def test_collect_ebay_offline_fake_browser_returns_schema_valid_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page, chromium = _install_fake_playwright(monkeypatch, VALID_HTML, chrome_missing=True)

    outcome = ebay.collect_ebay("53630-53010")

    jsonschema.validate(outcome, SCHEMA, format_checker=jsonschema.FormatChecker())
    assert outcome["status"] == "SUCCESS"
    assert outcome["market_context"] == FIXTURES["market_context"]
    assert outcome["observed_demand"] == {
        "eligible_listing_count": 1,
        "max_single_listing_sold": 32,
        "aggregate_observed_sold": 32,
    }
    assert chromium.channels == ["chrome", "msedge"]
    assert page.goto_calls == 1


def test_collect_ebay_rejects_homepage_cards_even_with_expected_market_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_playwright(
        monkeypatch,
        VALID_HTML,
        url_override="https://www.ebay.com/?_nkw=53630-53010",
    )

    outcome = ebay.collect_ebay("53630-53010", browser_channel="msedge")

    jsonschema.validate(outcome, SCHEMA, format_checker=jsonschema.FormatChecker())
    assert outcome["status"] == "MARKET_CONTEXT_MISMATCH"
    assert outcome["listings"] == []
    assert "path" in outcome["diagnostics"][0]["raw_marker"]


def test_collect_ebay_rejects_search_results_for_a_different_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_playwright(
        monkeypatch,
        VALID_HTML,
        url_override="https://www.ebay.com/sch/i.html?_nkw=A18-67004-004",
    )

    outcome = ebay.collect_ebay("53630-53010", browser_channel="msedge")

    jsonschema.validate(outcome, SCHEMA, format_checker=jsonschema.FormatChecker())
    assert outcome["status"] == "MARKET_CONTEXT_MISMATCH"
    assert outcome["listings"] == []
    assert "_nkw" in outcome["diagnostics"][0]["raw_marker"]


@pytest.mark.parametrize(
    ("html", "url_override", "http_status", "expected"),
    [
        (
            '<html lang="en-US"><header>Ship to United States 10001</header>'
            '<span>Currency USD</span>0 results for x</html>',
            None,
            200,
            "ZERO_RESULTS",
        ),
        ('<html lang="en-US">Pardon Our Interruption</html>', None, 200, "CHALLENGE"),
        ('<html lang="en-US"></html>', "https://signin.ebay.com/signin/", 200, "AUTH_REQUIRED"),
        ('<html lang="en-US"></html>', None, 403, "HTTP_ERROR"),
        (
            '<html lang="ja-JP"><header>Ship to Japan 100-0001</header>'
            '<span>JPY 100</span>0 results for x</html>',
            None,
            200,
            "MARKET_CONTEXT_MISMATCH",
        ),
        (
            '<html lang="en-US"><header>Ship to United States 10001</header>'
            '<span>Currency USD</span>ordinary page</html>',
            None,
            200,
            "PARSER_FAILED",
        ),
    ],
)
def test_collect_ebay_failure_outcomes_are_not_zero_results(
    monkeypatch: pytest.MonkeyPatch,
    html: str,
    url_override: str | None,
    http_status: int,
    expected: str,
) -> None:
    _install_fake_playwright(
        monkeypatch,
        html,
        statuses=[http_status],
        url_override=url_override,
    )

    outcome = ebay.collect_ebay("53630-53010", browser_channel="auto")

    jsonschema.validate(outcome, SCHEMA, format_checker=jsonschema.FormatChecker())
    assert outcome["status"] == expected
    assert outcome["listings"] == []
    assert outcome["observed_demand"]["aggregate_observed_sold"] == 0


def test_collect_ebay_retries_one_http_5xx_then_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    page, _ = _install_fake_playwright(monkeypatch, VALID_HTML, statuses=[503, 200])

    outcome = ebay.collect_ebay("53630-53010", browser_channel="msedge")

    assert outcome["status"] == "SUCCESS"
    assert page.goto_calls == 2


def test_collect_ebay_retries_http_5xx_only_once(monkeypatch: pytest.MonkeyPatch) -> None:
    page, _ = _install_fake_playwright(monkeypatch, VALID_HTML, statuses=[503, 503, 200])

    outcome = ebay.collect_ebay("53630-53010", browser_channel="msedge")

    assert outcome["status"] == "HTTP_ERROR"
    assert page.goto_calls == 2


@pytest.mark.parametrize(
    ("fail_at", "expected_status"),
    [
        ("enter", "PROVIDER_UNAVAILABLE"),
        ("new_context", "PROVIDER_UNAVAILABLE"),
        ("new_page", "PROVIDER_UNAVAILABLE"),
        ("goto", "HTTP_ERROR"),
        ("wait_for_selector", "HTTP_ERROR"),
        ("content", "PARSER_FAILED"),
    ],
)
def test_collect_ebay_maps_lifecycle_exceptions_to_explicit_outcomes(
    monkeypatch: pytest.MonkeyPatch,
    fail_at: str,
    expected_status: str,
) -> None:
    _install_fake_playwright(monkeypatch, VALID_HTML, fail_at=fail_at)

    outcome = ebay.collect_ebay("53630-53010", browser_channel="msedge")

    jsonschema.validate(outcome, SCHEMA, format_checker=jsonschema.FormatChecker())
    assert outcome["status"] == expected_status
    assert outcome["listings"] == []
    assert outcome["diagnostics"]


def test_helpers_do_not_import_playwright_at_module_import_time() -> None:
    assert "playwright" not in ebay.__dict__
    assert ebay.normalize_part_number("a18-67004-004") == "A1867004004"
