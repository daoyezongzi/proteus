"""Local UI harness: real API surface, stubbed provider results.

Not part of the product. It exists so the operator UI can be driven in a
browser without live SerpApi/NHTSA calls, covering all four gate statuses.
Run: python web/_dev_server.py
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from proteus.api import create_app  # noqa: E402
from proteus.automatic_mvp import automatic_mvp_policy  # noqa: E402


def _stage(status, *, value, operator, threshold, reason, at="2026-08-27T09:14:00Z"):
    return {
        "status": status,
        "value": value,
        "operator": operator,
        "threshold": threshold,
        "reason": reason,
        "provider_status": "SUCCESS" if status != "NOT_RUN" else None,
        "retrieved_at": at if status != "NOT_RUN" else None,
    }


def _not_run():
    return _stage("NOT_RUN", value=None, operator=None, threshold=None, reason="Not evaluated")


PASS = {
    "schema_version": "0.2.3",
    "profile": "automatic-mvp",
    "part_number": {"raw": "A18-67004-004", "canonical": "A1867004004"},
    "source": {
        "source_listing_id": "296412887301",
        "source_listing_url": "https://www.ebay.com/itm/296412887301",
        "source_listing_title": "A18-67004-004 Freightliner Cascadia Left Driver Exterior Door Handle",
        "source_sold_count": 41,
    },
    "decision": "MVP_OPPORTUNITY_CANDIDATE",
    "human_review_required": True,
    "evidence": {},
    "stages": {
        "ebay_recent_sold_lower_bound": _stage(
            "PASSED", value=34, operator="GT", threshold=20,
            reason="Observed distinct exact sold listings exceed the configured MVP threshold.",
        ),
        "amazon_us_competition": _stage(
            "PASSED", value=3, operator="LTE", threshold=5,
            reason="Complete Amazon US exact competitor count is within the threshold.",
        ),
        "ebay_compatibility": _stage(
            "PASSED", value=12, operator="GT", threshold=0,
            reason="At least one exact sold listing exposed normalized YMMT fitment.",
        ),
        "us_active_vehicle_proxy": _stage(
            "PASSED", value=18422, operator="GTE", threshold=5000,
            reason="Complete New York registration model estimate meets the MVP threshold.",
        ),
    },
}

REVIEW = {
    **PASS,
    "part_number": {"raw": "53630-53010", "canonical": "5363053010"},
    "source": {
        "source_listing_id": "156882440118",
        "source_listing_url": "https://www.ebay.com/itm/156882440118",
        "source_listing_title": "53630-53010 Lexus IS250 IS350 Hood Support Strut Damper OEM",
        "source_sold_count": 32,
    },
    "decision": "REVIEW_REQUIRED",
    "stages": {
        "ebay_recent_sold_lower_bound": _stage(
            "PASSED", value=27, operator="GT", threshold=20,
            reason="Observed distinct exact sold listings exceed the configured MVP threshold.",
        ),
        "amazon_us_competition": _stage(
            "PASSED", value=5, operator="LTE", threshold=5,
            reason="Complete Amazon US exact competitor count is within the threshold.",
        ),
        "ebay_compatibility": _stage(
            "PASSED", value=6, operator="GT", threshold=0,
            reason="At least one exact sold listing exposed normalized YMMT fitment.",
        ),
        "us_active_vehicle_proxy": _stage(
            "REVIEW_REQUIRED", value=2140, operator="GTE", threshold=5000,
            reason=(
                "New York registration estimate is below threshold, but one-state sampled "
                "coverage cannot decisively reject nationwide vehicle population."
            ),
        ),
    },
}

REJECTED = {
    **PASS,
    "part_number": {"raw": "04465-42160", "canonical": "0446542160"},
    "source": {
        "source_listing_id": "134998210447",
        "source_listing_url": "https://www.ebay.com/itm/134998210447",
        "source_listing_title": "04465-42160 Front Brake Pad Set Fits Toyota RAV4 2013-2018",
        "source_sold_count": 88,
    },
    "decision": "REJECTED",
    "stages": {
        "ebay_recent_sold_lower_bound": _stage(
            "PASSED", value=61, operator="GT", threshold=20,
            reason="Observed distinct exact sold listings exceed the configured MVP threshold.",
        ),
        "amazon_us_competition": _stage(
            "REJECTED", value=147, operator="LTE", threshold=5,
            reason="Complete Amazon US exact competitor count exceeds the threshold.",
        ),
        "ebay_compatibility": _not_run(),
        "us_active_vehicle_proxy": _not_run(),
    },
}

EARLY_REVIEW = {
    **PASS,
    "part_number": {"raw": "BP4W-33-23Z", "canonical": "BP4W3323Z"},
    "source": {
        "source_listing_id": "285991447203",
        "source_listing_url": "https://www.ebay.com/itm/285991447203",
        "source_listing_title": "BP4W-33-23Z Mazda 3 Front Wheel Hub Bearing Assembly",
        "source_sold_count": 21,
    },
    "decision": "REVIEW_REQUIRED",
    "stages": {
        "ebay_recent_sold_lower_bound": _stage(
            "REVIEW_REQUIRED", value=9, operator="GT", threshold=20,
            reason=(
                "The provider-visible recent subset does not prove the trailing-year "
                "threshold; it is not treated as a rejection."
            ),
        ),
        "amazon_us_competition": _not_run(),
        "ebay_compatibility": _not_run(),
        "us_active_vehicle_proxy": _not_run(),
    },
}


class StubService:
    def __init__(self) -> None:
        self._runs: dict[str, dict] = {}
        self._n = 0

    def configuration_status(self) -> dict:
        return {
            "profile": "automatic-mvp",
            "ready": True,
            "account_count": 1,
            "required_credentials": ["SERPAPI_API_KEY"],
            "optional_credentials": ["MARKETCHECK_API_KEY", "HIOBUY_API_KEY"],
            "credentials": {
                "SERPAPI_API_KEY": {"configured": True, "source": "os_keyring"},
                "MARKETCHECK_API_KEY": {"configured": False, "source": None},
                "HIOBUY_API_KEY": {"configured": False, "source": None},
            },
            "receiver": {"configured": False, "source": None},
        }

    def provider_status(self) -> dict:
        return {"profile": "provider-readiness", "providers": []}

    def submit_mvp_run(self, request: dict) -> dict:
        self._n += 1
        run_id = f"dev-{self._n}"
        reports = [PASS, REVIEW, EARLY_REVIEW, REJECTED]
        self._runs[run_id] = {
            "run_id": run_id,
            "status": "COMPLETED",
            "created_at": "2026-08-27T09:14:00Z",
            "started_at": "2026-08-27T09:14:01Z",
            "completed_at": "2026-08-27T09:14:52Z",
            "error": None,
            "result": {
                "schema_version": "0.2.3",
                "profile": "automatic-mvp",
                "policy": request,
                "execution": {
                    "mode": "AUTOMATIC_HEURISTIC_MVP",
                    "human_review_required": True,
                    "provider_count": 2,
                },
                "discovery": {
                    "category_id": request.get("ebay_category_id"),
                    "keyword": request.get("discovery_keyword"),
                    "pages_requested": request.get("discovery_pages"),
                    "pages_completed": request.get("discovery_pages"),
                    "candidate_count": len(reports),
                    "diagnostics": [],
                },
                "reports": reports,
                "summary": {
                    "mvp_opportunity_candidates": 1,
                    "rejected": 1,
                    "review_required": 2,
                },
                "completed_at": "2026-08-27T09:14:52Z",
            },
        }
        return {"run_id": run_id, "status": "QUEUED"}

    def get_mvp_run(self, run_id: str) -> dict | None:
        return self._runs.get(run_id)

    def submit_run(self, request: dict) -> dict:
        return self.submit_mvp_run(request)

    def get_run(self, run_id: str) -> dict | None:
        return self._runs.get(run_id)


if __name__ == "__main__":
    import uvicorn

    assert automatic_mvp_policy()["profile"] == "automatic-mvp"
    uvicorn.run(create_app(service=StubService()), host="127.0.0.1", port=8766)
