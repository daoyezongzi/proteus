#!/usr/bin/env python3
"""Low-frequency, unauthenticated HTTP probe for Proteus Phase 0.

This script deliberately does not log in, reuse cookies, retry requests, solve
CAPTCHAs, or imitate a browser fingerprint. A successful HTTP response only
means that a response was returned; it does not prove that product data is
complete, stable, or permitted for production use.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Final


DEFAULT_QUERIES: Final[tuple[str, ...]] = (
    "53630-53010",
    "A18-67004-004",
)

SEARCH_URLS: Final[dict[str, str]] = {
    "amazon": "https://www.amazon.com/s?k={query}",
    "ebay": "https://www.ebay.com/sch/i.html?_nkw={query}",
    "1688": "https://s.1688.com/selloffer/offer_search.htm?keywords={query}",
}

MARKERS: Final[dict[str, tuple[str, ...]]] = {
    "challenge": (
        "captcha",
        "robot check",
        "enter the characters",
        "verify you are human",
        "pardon our interruption",
        "security measure",
        "验证码",
        "滑块",
        "验证后继续",
        "安全验证",
        "请完成验证",
    ),
    "login": (
        "登录页面",
        "密码登录",
        "短信登录",
        "使用 1688 / 淘宝app 扫码登录",
    ),
    "error_page": (
        "sorry! something went wrong!",
        "service unavailable",
        "access denied",
        "访问受限",
        "请求异常",
        "系统繁忙",
    ),
}


@dataclass(frozen=True)
class ProbeResult:
    platform: str
    query: str
    request_url: str
    status: int | None
    final_origin_path: str | None
    body_bytes: int
    body_sha256: str | None
    title: str
    contains_query: bool
    markers: dict[str, list[str]]
    outcome: str
    error: str | None = None


def _origin_path(url: str) -> str:
    """Keep redirect evidence without persisting transient login tokens."""
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _decode_body(body: bytes, content_type: str) -> str:
    charset_match = re.search(r"charset=([\w-]+)", content_type, re.IGNORECASE)
    charset = charset_match.group(1) if charset_match else "utf-8"
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _extract_title(text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return re.sub(r"\s+", " ", html.unescape(match.group(1))).strip()


def _find_markers(text: str) -> dict[str, list[str]]:
    folded = text.casefold()
    return {
        category: [marker for marker in markers if marker.casefold() in folded]
        for category, markers in MARKERS.items()
    }


def _classify(
    *, status: int | None, final_url: str | None, markers: dict[str, list[str]]
) -> str:
    if status is None:
        return "NETWORK_ERROR"
    if status >= 400:
        return "HTTP_ERROR"
    if markers["challenge"]:
        return "CHALLENGE"
    if final_url and urllib.parse.urlsplit(final_url).hostname == "login.taobao.com":
        return "AUTH_REQUIRED"
    if markers["login"]:
        return "AUTH_REQUIRED"
    if markers["error_page"]:
        return "ERROR_PAGE"
    return "RESPONSE_RETURNED"


def probe(platform: str, query: str, timeout: float) -> ProbeResult:
    request_url = SEARCH_URLS[platform].format(query=urllib.parse.quote_plus(query))
    request = urllib.request.Request(
        request_url,
        headers={
            "User-Agent": "Proteus-Recon/0.1 (public feasibility probe; no authentication)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )

    status: int | None = None
    final_url: str | None = None
    content_type = ""
    body = b""
    error: str | None = None

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            final_url = response.geturl()
            content_type = response.headers.get("Content-Type", "")
            body = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        final_url = exc.geturl()
        content_type = exc.headers.get("Content-Type", "") if exc.headers else ""
        body = exc.read()
        error = f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        error = f"{type(exc).__name__}: {exc}"

    text = _decode_body(body, content_type)
    markers = _find_markers(text)
    return ProbeResult(
        platform=platform,
        query=query,
        request_url=request_url,
        status=status,
        final_origin_path=_origin_path(final_url) if final_url else None,
        body_bytes=len(body),
        body_sha256=hashlib.sha256(body).hexdigest() if body else None,
        title=_extract_title(text),
        contains_query=query.casefold() in text.casefold(),
        markers=markers,
        outcome=_classify(status=status, final_url=final_url, markers=markers),
        error=error,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--platform",
        choices=("all", *SEARCH_URLS),
        default="all",
        help="Platform to probe (default: all).",
    )
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        help="Part number to probe; repeat for multiple values.",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between requests in seconds (default: 1).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.timeout <= 0 or args.delay < 0:
        raise SystemExit("--timeout must be positive and --delay must be non-negative")

    platforms = tuple(SEARCH_URLS) if args.platform == "all" else (args.platform,)
    queries = tuple(args.queries) if args.queries else DEFAULT_QUERIES
    request_count = len(platforms) * len(queries)
    completed = 0

    for platform in platforms:
        for query in queries:
            print(json.dumps(asdict(probe(platform, query, args.timeout)), ensure_ascii=False))
            completed += 1
            if completed < request_count and args.delay:
                time.sleep(args.delay)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
