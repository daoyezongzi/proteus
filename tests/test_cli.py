from __future__ import annotations

import json
from pathlib import Path

from proteus import cli


RETRIEVED_AT = "2026-08-25T00:00:00Z"


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _canonical(raw_part_number: str) -> str:
    return "".join(character for character in raw_part_number.upper() if character.isalnum())


def _evidence(
    *, metric: str, value: object, source: str, url: str, raw: str
) -> dict[str, object]:
    return {
        "metric": metric,
        "value": value,
        "source": source,
        "url": url,
        "retrieved_at": RETRIEVED_AT,
        "extraction_method": "MANUAL_REVIEW",
        "raw_evidence": raw,
        "confidence": 0.9,
    }


def _manual_record(raw_part_number: str) -> dict[str, object]:
    canonical = _canonical(raw_part_number)
    offer_url = f"https://detail.1688.com/offer/{canonical}.html"
    return {
        "raw_part_number": raw_part_number,
        "amazon": {
            "acquisition_status": "SUCCESS",
            "source_method": "MANUAL",
            "query": raw_part_number,
            "market_context": {
                "marketplace_id": "AMAZON_US",
                "site": "www.amazon.com",
                "locale": "en-US",
                "ship_to_country": "US",
                "ship_to_postal_code": "10001",
                "currency": "USD",
            },
            "relevance_reviewed": True,
            "relevant_result_count": 2,
            "evidence": [
                _evidence(
                    metric="relevant_result_count",
                    value=2,
                    source="Amazon manual search review",
                    url=f"https://www.amazon.com/s?k={canonical}",
                    raw="Two relevant exact-part results were manually reviewed.",
                )
            ],
        },
        "alibaba_1688": {
            "acquisition_status": "SUCCESS",
            "source_method": "MANUAL",
            "matched_part_numbers": [canonical],
            "match_type": "EXACT",
            "supplier": "Fixture Supplier",
            "offer_url": offer_url,
            "purchasable": True,
            "price_cny": 40,
            "moq": 2,
            "evidence": [
                _evidence(
                    metric="purchasable",
                    value=True,
                    source="1688 manual offer review",
                    url=offer_url,
                    raw="Exact part offer is available to order.",
                ),
                _evidence(
                    metric="price_cny",
                    value=40,
                    source="1688 manual offer review",
                    url=offer_url,
                    raw="Offer price is CNY 40.",
                ),
                _evidence(
                    metric="moq",
                    value=2,
                    source="1688 manual offer review",
                    url=offer_url,
                    raw="Minimum order quantity is 2.",
                ),
            ],
        },
    }


def _ebay_acquisition(raw_part_number: str) -> dict[str, object]:
    canonical = _canonical(raw_part_number)
    listing_url = f"https://www.ebay.com/itm/{canonical}"
    return {
        "schema_version": "0.1",
        "platform": "EBAY",
        "provider": "offline-test-fixture",
        "source_method": "BROWSER",
        "query": {
            "raw_part_number": raw_part_number,
            "canonical_part_number": canonical,
            "query_type": "EXACT_PART_NUMBER",
        },
        "market_context": {
            "marketplace_id": "EBAY_US",
            "site": "www.ebay.com",
            "locale": "en-US",
            "ship_to_country": "US",
            "ship_to_postal_code": "10001",
            "currency": "USD",
        },
        "status": "SUCCESS",
        "retrieved_at": RETRIEVED_AT,
        "listings": [
            {
                "listing_id": canonical,
                "url": listing_url,
                "title": f"New OEM {raw_part_number}",
                "condition": "NEW",
                "price": {"amount": 25, "currency": "USD"},
                "sold_count": 2,
                "sold_label_raw": "2 sold",
                "available_count": None,
                "seller": "fixture-seller",
                "location": "United States",
                "part_numbers": [canonical],
                "match_type": "EXACT",
                "decision": "ACCEPT_DEMAND_EVIDENCE",
                "evidence": [
                    {
                        "metric": "sold_count",
                        "value": 2,
                        "source": "eBay search result card",
                        "url": listing_url,
                        "retrieved_at": RETRIEVED_AT,
                        "extraction_method": "VISIBLE_TEXT",
                        "raw_evidence": "2 sold",
                        "confidence": 0.95,
                    }
                ],
            }
        ],
        "observed_demand": {
            "eligible_listing_count": 1,
            "max_single_listing_sold": 2,
            "aggregate_observed_sold": 2,
        },
        "diagnostics": [],
    }


def _ebay_challenge(raw_part_number: str) -> dict[str, object]:
    acquisition = _ebay_acquisition(raw_part_number)
    acquisition["status"] = "CHALLENGE"
    acquisition["listings"] = []
    acquisition["observed_demand"] = {
        "eligible_listing_count": 0,
        "max_single_listing_sold": None,
        "aggregate_observed_sold": 0,
    }
    acquisition["diagnostics"] = [
        {
            "code": "CHALLENGE",
            "message": "eBay presented a verification challenge.",
            "raw_marker": "Pardon our interruption",
        }
    ]
    return acquisition


def test_offline_cli_preserves_order_and_manual_provenance(tmp_path: Path) -> None:
    candidates = ["53630-53010", "A18-67004-004"]
    candidate_path = _write_json(
        tmp_path / "candidates.json",
        {
            "schema_version": "0.1",
            "candidates": [
                {"raw_part_number": part_number} for part_number in candidates
            ],
        },
    )
    manual_path = _write_json(
        tmp_path / "manual.json",
        {
            "schema_version": "0.1",
            "evidence": [_manual_record(part_number) for part_number in candidates],
        },
    )
    ebay_path = _write_json(
        tmp_path / "ebay.json",
        {
            "schema_version": "0.1",
            "acquisitions": [
                _ebay_acquisition(part_number) for part_number in candidates
            ],
        },
    )
    output_path = tmp_path / "reports.json"

    exit_code = cli.main(
        [
            "--candidate-pool",
            str(candidate_path),
            "--manual-evidence",
            str(manual_path),
            "--ebay-evidence",
            str(ebay_path),
            "--max-moq",
            "5",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    reports = json.loads(output_path.read_text(encoding="utf-8"))
    assert [report["candidate"]["raw_part_number"] for report in reports] == candidates
    assert [report["decision"] for report in reports] == [
        "OPPORTUNITY_CANDIDATE",
        "OPPORTUNITY_CANDIDATE",
    ]
    for report in reports:
        amazon = report["stages"]["amazon_competition"]
        supply = report["stages"]["alibaba_1688_supply"]
        assert amazon["source_method"] == "MANUAL"
        assert supply["source_method"] == "MANUAL"
        assert amazon["evidence"][0]["extraction_method"] == "MANUAL_REVIEW"
        assert supply["evidence"][0]["extraction_method"] == "MANUAL_REVIEW"


def test_live_ebay_is_sequential_defaults_to_auto_and_missing_manual_reviews(
    tmp_path: Path, monkeypatch
) -> None:
    candidates = ["53630-53010", "A18-67004-004"]
    candidate_path = _write_json(tmp_path / "candidates.json", candidates)
    output_path = tmp_path / "reports.json"
    calls: list[tuple[str, bool, str]] = []

    def fake_collect(
        raw_part_number: str, *, headless: bool, browser_channel: str
    ) -> dict[str, object]:
        calls.append((raw_part_number, headless, browser_channel))
        return _ebay_acquisition(raw_part_number)

    monkeypatch.setattr(cli, "collect_ebay", fake_collect)

    exit_code = cli.main(
        [
            "--candidate-pool",
            str(candidate_path),
            "--live-ebay",
            "--max-moq",
            "5",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert calls == [
        ("53630-53010", True, "auto"),
        ("A18-67004-004", True, "auto"),
    ]
    reports = json.loads(output_path.read_text(encoding="utf-8"))
    assert all(report["decision"] == "REVIEW_REQUIRED" for report in reports)
    assert all(
        report["stages"]["amazon_competition"]["status"] == "REVIEW_REQUIRED"
        for report in reports
    )


def test_live_challenge_is_preserved_and_never_promoted(
    tmp_path: Path, monkeypatch
) -> None:
    raw_part_number = "53630-53010"
    candidate_path = _write_json(tmp_path / "candidates.json", [raw_part_number])
    manual_path = _write_json(
        tmp_path / "manual.json", [_manual_record(raw_part_number)]
    )
    output_path = tmp_path / "reports.json"

    monkeypatch.setattr(
        cli,
        "collect_ebay",
        lambda *_args, **_kwargs: _ebay_challenge(raw_part_number),
    )

    exit_code = cli.main(
        [
            "--candidate-pool",
            str(candidate_path),
            "--manual-evidence",
            str(manual_path),
            "--live-ebay",
            "--max-moq",
            "5",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))[0]
    assert report["decision"] == "REVIEW_REQUIRED"
    assert report["stages"]["ebay_demand"]["status"] == "REVIEW_REQUIRED"
    assert report["stages"]["ebay_demand"]["acquisition"]["status"] == "CHALLENGE"
    assert report["stages"]["amazon_competition"]["status"] == "NOT_CHECKED"
    assert report["stages"]["alibaba_1688_supply"]["status"] == "NOT_CHECKED"


def test_manual_import_rejects_non_manual_provenance(
    tmp_path: Path, capsys
) -> None:
    raw_part_number = "53630-53010"
    candidate_path = _write_json(tmp_path / "candidates.json", [raw_part_number])
    ebay_path = _write_json(
        tmp_path / "ebay.json", [_ebay_acquisition(raw_part_number)]
    )
    record = _manual_record(raw_part_number)
    record["amazon"]["source_method"] = "HTTP"
    manual_path = _write_json(tmp_path / "manual.json", [record])
    output_path = tmp_path / "reports.json"

    exit_code = cli.main(
        [
            "--candidate-pool",
            str(candidate_path),
            "--manual-evidence",
            str(manual_path),
            "--ebay-evidence",
            str(ebay_path),
            "--max-moq",
            "5",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 2
    assert "source_method must be 'MANUAL'" in capsys.readouterr().err
    assert not output_path.exists()


def test_invalid_offline_acquisition_does_not_write_partial_output(
    tmp_path: Path, capsys
) -> None:
    raw_part_number = "53630-53010"
    candidate_path = _write_json(tmp_path / "candidates.json", [raw_part_number])
    invalid_acquisition = _ebay_acquisition(raw_part_number)
    invalid_acquisition["market_context"]["currency"] = "US dollars"
    ebay_path = _write_json(tmp_path / "ebay.json", [invalid_acquisition])
    output_path = tmp_path / "reports.json"

    exit_code = cli.main(
        [
            "--candidate-pool",
            str(candidate_path),
            "--ebay-evidence",
            str(ebay_path),
            "--max-moq",
            "5",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 2
    assert "violates v0_1_acquisition.schema.json" in capsys.readouterr().err
    assert not output_path.exists()


def test_missing_offline_acquisition_fails_closed_without_partial_output(
    tmp_path: Path, capsys
) -> None:
    candidates = ["53630-53010", "A18-67004-004"]
    candidate_path = _write_json(tmp_path / "candidates.json", candidates)
    ebay_path = _write_json(
        tmp_path / "ebay.json", [_ebay_acquisition(candidates[0])]
    )
    output_path = tmp_path / "reports.json"

    exit_code = cli.main(
        [
            "--candidate-pool",
            str(candidate_path),
            "--ebay-evidence",
            str(ebay_path),
            "--max-moq",
            "5",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 2
    assert (
        "has no acquisition for candidate 'A18-67004-004'"
        in capsys.readouterr().err
    )
    assert not output_path.exists()
