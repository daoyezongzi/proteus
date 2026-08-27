from __future__ import annotations

import json
from http.client import RemoteDisconnected
from urllib.parse import parse_qs, urlparse

import pytest

from proteus.providers.serpapi_ebay import SerpApiRequest, SerpApiResponse
from proteus.providers.serpapi_transport import perform_async_search


def _response(payload: dict) -> SerpApiResponse:
    return SerpApiResponse(200, json.dumps(payload).encode("utf-8"))


def test_async_search_submits_then_polls_serpapi_json_endpoint() -> None:
    responses = iter(
        [
            _response(
                {
                    "search_metadata": {
                        "id": "search-1",
                        "status": "Processing",
                        "json_endpoint": "https://serpapi.com/searches/search-1.json",
                    }
                }
            ),
            _response(
                {
                    "search_metadata": {"id": "search-1", "status": "Success"},
                    "organic_results": [],
                }
            ),
        ]
    )
    requests: list[SerpApiRequest] = []

    def transport(request: SerpApiRequest) -> SerpApiResponse:
        requests.append(request)
        return next(responses)

    result = perform_async_search(
        SerpApiRequest(
            "https://serpapi.com/search?engine=ebay&no_cache=true&api_key=secret",
            10,
        ),
        transport=transport,
        poll_interval_seconds=0,
    )

    submitted = parse_qs(urlparse(requests[0].url).query)
    assert submitted["async"] == ["true"]
    assert "no_cache" not in submitted
    assert requests[1].url == "https://serpapi.com/searches/search-1.json"
    assert json.loads(result.body)["search_metadata"]["status"] == "Success"


def test_async_search_rejects_untrusted_poll_endpoint() -> None:
    def transport(_request: SerpApiRequest) -> SerpApiResponse:
        return _response(
            {
                "search_metadata": {
                    "status": "Processing",
                    "json_endpoint": "https://attacker.invalid/capture?api_key=secret",
                }
            }
        )

    with pytest.raises(ValueError, match="trusted SerpApi HTTPS"):
        perform_async_search(
            SerpApiRequest("https://serpapi.com/search?api_key=secret", 10),
            transport=transport,
            poll_interval_seconds=0,
        )


def test_async_search_has_bounded_overall_wait() -> None:
    def transport(_request: SerpApiRequest) -> SerpApiResponse:
        return _response(
            {
                "search_metadata": {
                    "status": "Processing",
                    "json_endpoint": "https://serpapi.com/searches/search-1.json",
                }
            }
        )

    with pytest.raises(TimeoutError, match="did not finish"):
        perform_async_search(
            SerpApiRequest("https://serpapi.com/search?api_key=secret", 10),
            transport=transport,
            poll_interval_seconds=0,
            max_wait_seconds=0,
        )


def test_async_search_retries_transient_poll_disconnect() -> None:
    calls = 0

    def transport(_request: SerpApiRequest) -> SerpApiResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _response(
                {
                    "search_metadata": {
                        "status": "Processing",
                        "json_endpoint": "https://serpapi.com/searches/search-1.json",
                    }
                }
            )
        if calls == 2:
            raise RemoteDisconnected("poll disconnected")
        return _response({"search_metadata": {"status": "Success"}})

    result = perform_async_search(
        SerpApiRequest("https://serpapi.com/search?api_key=secret", 10),
        transport=transport,
        poll_interval_seconds=0,
    )

    assert calls == 3
    assert json.loads(result.body)["search_metadata"]["status"] == "Success"
