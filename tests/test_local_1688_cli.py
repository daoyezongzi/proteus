from __future__ import annotations

import json

from proteus.providers.local_1688_cli import (
    collect_1688_supplier,
    is_1688_cli_authenticated,
)


def test_local_cli_authentication_check_is_read_only() -> None:
    calls: list[list[str]] = []

    def run(argv, _timeout):
        calls.append(list(argv))
        return 0, '{"loggedIn": true, "memberId": "member-1"}', ""

    assert is_1688_cli_authenticated(command_runner=run) is True
    assert calls == [["1688", "whoami", "--profile", "default", "--json"]]


def test_local_cli_supplier_prefilter_stops_on_search_supplier_evidence() -> None:
    calls: list[list[str]] = []

    def run(argv, _timeout):
        calls.append(list(argv))
        return (
            0,
            json.dumps(
                {
                    "keyword": argv[2],
                    "offers": [
                        {
                            "offerId": "628196518518",
                            "title": "Chevrolet Silverado 雾灯框 25778388",
                            "detailUrl": "https://detail.1688.com/offer/628196518518.html",
                            "supplier": {"memberId": "seller-1", "companyName": "测试汽配有限公司"},
                        }
                    ],
                }
            ),
            "",
        )

    outcome = collect_1688_supplier(
        "25778388",
        family={
            "part_type": "fog light bezel",
            "fitments": [{"make": "Chevrolet", "model": "Silverado"}],
        },
        command_runner=run,
    )

    assert outcome["acquisition_status"] == "SUCCESS"
    assert outcome["supplier_found"] is True
    assert outcome["supplier"]["name"] == "测试汽配有限公司"
    assert outcome["offer_id"] == "628196518518"
    assert len(calls) == 1
    assert "--deeppro" not in calls[0]
    assert calls[0][1:3] == ["search", "25778388"]


def test_local_cli_reads_one_offer_when_search_card_lacks_supplier() -> None:
    calls: list[list[str]] = []

    def run(argv, _timeout):
        calls.append(list(argv))
        if argv[1] == "search":
            return (
                0,
                json.dumps(
                    {
                        "offers": [
                            {
                                "offerId": "628196518518",
                                "title": "25778388 雾灯框",
                                "detailUrl": "https://detail.1688.com/offer/628196518518.html",
                            }
                        ]
                    }
                ),
                "",
            )
        return (
            0,
            json.dumps(
                {
                    "offerId": "628196518518",
                    "title": "25778388 雾灯框",
                    "detailUrl": "https://detail.1688.com/offer/628196518518.html",
                    "supplier": {"name": "详情汽配供应商"},
                }
            ),
            "",
        )

    outcome = collect_1688_supplier(
        "25778388",
        family={"part_type": "fog light bezel"},
        command_runner=run,
    )

    assert outcome["supplier_found"] is True
    assert outcome["supplier"]["name"] == "详情汽配供应商"
    assert [call[1] for call in calls] == ["search", "offer"]


def test_local_cli_failure_is_reviewable_and_never_fabricates_no_supplier() -> None:
    def run(_argv, _timeout):
        return 1, "", "RISK_CONTROL verification required"

    outcome = collect_1688_supplier("25778388", command_runner=run)

    assert outcome["acquisition_status"] == "RISK_CONTROL"
    assert outcome["supplier_found"] is False
    assert outcome["diagnostics"][0]["code"] == "1688_CLI_RISK_CONTROL"
