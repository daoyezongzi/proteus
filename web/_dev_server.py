"""Local UI harness: real API surface, stubbed provider results.

Not part of the product. It exists so the operator UI can be driven in a
browser without live provider calls, covering all five gate statuses.
Run: python web/_dev_server.py
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from proteus.api import create_app  # noqa: E402
from proteus.automatic_mvp import automatic_mvp_policy  # noqa: E402
from proteus.category_catalog import builtin_public_catalog, builtin_runtime_categories  # noqa: E402
from proteus.northway_mvp import run_northway_mvp  # noqa: E402
from proteus.providers.local_1688_store import normalize_1688_supplier_target  # noqa: E402
from proteus.supplier_inventory_import import (  # noqa: E402
    IMPORT_FORMAT,
    IMPORT_SCHEMA_NAME,
    IMPORT_VERSION,
    MAX_IMPORT_DOCUMENT_BYTES,
    MAX_IMPORT_OFFERS,
    normalize_supplier_inventory_import,
)
from proteus.supplier_scout import run_supplier_scout, supplier_scout_policy  # noqa: E402


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
            "PASSED", value=34, operator="GT", threshold=0,
            reason="Observed distinct exact sold listings exceed the configured MVP threshold.",
        ),
        "amazon_us_competition": _stage(
            "PASSED", value=3, operator="LTE", threshold=5,
            reason="Complete Amazon US exact competitor count is within the threshold.",
        ),
        "amazon_us_minimum_price": _stage(
            "PASSED", value=36.5, operator="GT", threshold=20.0,
            reason="Amazon minimum exact-result price is above the threshold.",
        ),
        "amazon_us_active_offers": _stage(
            "PASSED", value=4, operator="LTE", threshold=10,
            reason="Complete Amazon active-offer count is within the seller saturation limit.",
        ),
        "ebay_compatibility": _stage(
            "PASSED", value=12, operator="GT", threshold=0,
            reason="At least one exact sold listing exposed normalized YMMT fitment.",
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
            "PASSED", value=27, operator="GT", threshold=0,
            reason="Observed distinct exact sold listings exceed the configured MVP threshold.",
        ),
        "amazon_us_competition": _stage(
            "PASSED", value=5, operator="LTE", threshold=5,
            reason="Complete Amazon US exact competitor count is within the threshold.",
        ),
        "amazon_us_minimum_price": _stage(
            "PASSED", value=28.99, operator="GT", threshold=20.0,
            reason="Amazon minimum exact-result price is above the threshold.",
        ),
        "amazon_us_active_offers": _stage(
            "REVIEW_REQUIRED", value=8, operator="LTE", threshold=10,
            reason="Amazon active-offer count is only a lower bound and cannot prove the seller limit.",
        ),
        "ebay_compatibility": _not_run(),
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
            "PASSED", value=61, operator="GT", threshold=0,
            reason="Observed distinct exact sold listings exceed the configured MVP threshold.",
        ),
        "amazon_us_competition": _stage(
            "REJECTED", value=147, operator="LTE", threshold=5,
            reason="Complete Amazon US exact competitor count exceeds the threshold.",
        ),
        "amazon_us_minimum_price": _not_run(),
        "amazon_us_active_offers": _not_run(),
        "ebay_compatibility": _not_run(),
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
            "REVIEW_REQUIRED", value=0, operator="GT", threshold=0,
            reason=(
                "The provider-visible recent subset does not prove the trailing-year "
                "threshold; it is not treated as a rejection."
            ),
        ),
        "amazon_us_competition": _not_run(),
        "amazon_us_minimum_price": _not_run(),
        "amazon_us_active_offers": _not_run(),
        "ebay_compatibility": _not_run(),
    },
}


class StubService:
    def __init__(self) -> None:
        self._runs: dict[str, dict] = {}
        self._snapshots: dict[str, dict] = {}
        self._n = 0
        self._suppliers = [
            {
                "supplier_id": "sup_dev_fixture",
                "label": "示例汽配供应商",
                "submitted_target": "https://shop3w093345o1043.1688.com/page/offerlist.htm",
                "canonical_url": "https://shop3w093345o1043.1688.com/page/offerlist.htm",
                "shop_host": "shop3w093345o1043.1688.com",
                "member_id": "dev-supplier",
                "status": "ACTIVE",
                "created_at": "2026-08-30T00:00:00Z",
                "updated_at": "2026-08-30T00:00:00Z",
            }
        ]

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
        return {
            "profile": "provider-readiness",
            "providers": [
                {
                    "provider_id": "local-1688-cli",
                    "capability": "ALIBABA_1688_SUPPLY",
                    "status": "READY",
                    "checks": [
                        {
                            "name": "REPLAY_FIXTURE",
                            "status": "PASS",
                            "message": "The UI harness uses a deterministic read-only 1688 fixture.",
                        }
                    ],
                }
            ],
        }

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
                    "provider_count": 1,
                },
                "discovery": {
                    "category_id": request.get("ebay_category_id"),
                    "keyword": request.get("discovery_keyword"),
                    "pages_requested": request.get("discovery_pages"),
                    "pages_completed": request.get("discovery_pages"),
                    "results_seen": len(reports),
                    "eligible_sold_listings": len(reports),
                    "listings_with_part_number": len(reports),
                    "candidates_emitted": len(reports),
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

    def submit_northway_run(self, request: dict) -> dict:
        self._n += 1
        run_id = f"northway-dev-{self._n}"

        candidates = [
            {
                "raw_part_number": "25778388",
                "canonical_part_number": "25778388",
                "source_listing_id": "northway-right",
                "source_listing_url": "https://www.ebay.com/itm/100000000001",
                "source_listing_title": (
                    "Right Fog Light Bezel for 2007-2013 Chevrolet Silverado 25778388"
                ),
                "source_listing_position": 1,
                "source_sold_count": 12,
            },
            {
                "raw_part_number": "25778389",
                "canonical_part_number": "25778389",
                "source_listing_id": "northway-left",
                "source_listing_url": "https://www.ebay.com/itm/100000000002",
                "source_listing_title": (
                    "Left Fog Light Bezel for 2007-2013 Chevrolet Silverado 25778389"
                ),
                "source_listing_position": 2,
                "source_sold_count": 7,
            },
        ]

        def discover(**kwargs):
            selected = candidates if kwargs.get("keyword") == "fog light bezel OEM" else []
            return {
                "status": "SUCCESS" if selected else "ZERO_RESULTS",
                "retrieved_at": "2026-08-28T09:00:00Z",
                "stats": {
                    "results_seen": len(selected),
                    "eligible_sold_listings": len(selected),
                    "listings_with_part_number": len(selected),
                    "candidates_emitted": len(selected),
                },
                "candidates": selected,
                "diagnostics": [],
            }

        def amazon_search(query: str, **_kwargs):
            left = "25778389" in query
            products = []
            count = 7 if left else 1
            part_number = "25778389" if left else "25778388"
            side = "Left" if left else "Right"
            for index in range(count):
                products.append(
                    {
                        "asin": f"B000000{index + (10 if left else 1):03d}",
                        "title": (
                            f"Brand {index + 1} {side} Fog Light Bezel for 2007-2013 "
                            f"Chevrolet Silverado {part_number}"
                        ),
                        "url": f"https://www.amazon.com/dp/B000000{index + (10 if left else 1):03d}",
                        "price_usd": 32.99 if left else 31.99,
                        "active_offer_count_lower_bound": index + 1,
                        "active_offer_count_complete": True,
                    }
                )
            return {
                "schema_version": "0.2.4",
                "provider": "DEV_AMAZON_REPLAY",
                "marketplace_id": "AMAZON_US",
                "query": query,
                "search_url": "https://www.amazon.com/s",
                "retrieved_at": "2026-08-28T09:01:00Z",
                "acquisition_status": "SUCCESS",
                "result_page_complete": True,
                "has_next_page": False,
                "reported_total_results": len(products),
                "results_seen": len(products),
                "products": products,
                "diagnostics": [],
            }

        def supplier_prefilter(raw_part_number: str, *, family: dict, **_kwargs):
            return {
                "provider": "DEV_1688_CLI_REPLAY",
                "source_method": "LOCAL_CLI_REPLAY",
                "acquisition_status": "SUCCESS",
                "query": raw_part_number,
                "offer_id": f"1688-{raw_part_number}",
                "offer_url": f"https://detail.1688.com/offer/{raw_part_number}.html",
                "title": f"{family.get('part_type', '汽车配件')} Chevrolet Silverado {raw_part_number}",
                "supplier": {"id": "dev-supplier", "name": "Northway 1688 Replay Supplier"},
                "supplier_found": True,
                "matched_part_numbers": [raw_part_number],
                "match_type": "IDENTIFIER_OR_FAMILY_MATCH",
                "retrieved_at": "2026-08-28T09:00:30Z",
                "diagnostics": [],
            }

        result = run_northway_mvp(
            serpapi_key="dev-only",
            collectors={
                "discovery": discover,
                "amazon_search": amazon_search,
                "1688_supplier_prefilter": supplier_prefilter,
            },
            **request,
        )
        self._runs[run_id] = {
            "run_id": run_id,
            "status": "COMPLETED",
            "created_at": "2026-08-28T09:00:00Z",
            "started_at": "2026-08-28T09:00:00Z",
            "completed_at": "2026-08-28T09:01:00Z",
            "error": None,
            "result": result,
        }
        return {"run_id": run_id, "status": "QUEUED"}

    def get_northway_run(self, run_id: str) -> dict | None:
        return self._runs.get(run_id)

    def supplier_scout_policy(self) -> dict:
        policy = supplier_scout_policy(
            builtin_runtime_categories(),
            category_catalog=builtin_public_catalog(),
        )
        policy["inventory_import"] = {
            "format": IMPORT_FORMAT,
            "version": IMPORT_VERSION,
            "schema": IMPORT_SCHEMA_NAME,
            "max_document_bytes": MAX_IMPORT_DOCUMENT_BYTES,
            "max_offers": MAX_IMPORT_OFFERS,
            "primary": True,
        }
        return policy

    def list_supplier_scout_suppliers(self) -> dict:
        return {"suppliers": list(self._suppliers)}

    def inspect_supplier_scout_supplier(self, request: dict) -> dict:
        normalized = normalize_1688_supplier_target(request["target"])
        return {
            "schema_version": "0.2.6",
            "provider": "DEV_1688_STORE_REPLAY",
            "source_method": "TEST_FIXTURE",
            "acquisition_status": "PARTIAL",
            "submitted_target": request["target"],
            "canonical_url": normalized["canonical_url"],
            "supplier": {
                "member_id": "dev-supplier",
                "name": "示例汽配供应商",
                "shop_host": normalized["shop_host"],
            },
            "pages_attempted": 1,
            "pages_completed": 1,
            "observed_offer_count": 2,
            "available_offer_count": 86,
            "has_next_page": True,
            "inventory_complete": False,
            "offers": [],
            "warnings": ["DEV_REPLAY", "PAGE_BOUND_REACHED"],
            "retrieved_at": "2026-08-30T00:00:00Z",
        }

    def add_supplier_scout_supplier(self, request: dict) -> dict:
        normalized = normalize_1688_supplier_target(request["target"])
        supplier = {
            "supplier_id": f"sup_dev_{len(self._suppliers) + 1}",
            "label": request["label"],
            "submitted_target": request["target"],
            "canonical_url": normalized["canonical_url"],
            "shop_host": normalized["shop_host"],
            "member_id": None,
            "status": "ACTIVE",
            "created_at": "2026-08-30T00:00:00Z",
            "updated_at": "2026-08-30T00:00:00Z",
        }
        self._suppliers.append(supplier)
        return supplier

    def import_supplier_inventory(
        self, supplier_id: str, document: dict, filename: str | None = None
    ) -> dict:
        selected = next(
            item for item in self._suppliers if item["supplier_id"] == supplier_id
        )
        if selected["status"] != "ACTIVE":
            raise ValueError("supplier source is archived")
        snapshot, report = normalize_supplier_inventory_import(
            document, selected, filename=filename
        )
        self._n += 1
        snapshot_id = f"snap_dev_import_{self._n}"
        snapshot.update(
            {
                "snapshot_id": snapshot_id,
                "supplier_id": supplier_id,
                "snapshot_sha256": "dev-" + snapshot_id,
            }
        )
        self._snapshots[snapshot_id] = snapshot
        return {
            "snapshot": {
                key: snapshot.get(key)
                for key in (
                    "snapshot_id",
                    "supplier_id",
                    "snapshot_sha256",
                    "retrieved_at",
                    "acquisition_status",
                    "inventory_complete",
                    "pages_attempted",
                    "pages_completed",
                    "observed_offer_count",
                    "available_offer_count",
                    "has_next_page",
                    "source_method",
                    "provider",
                    "warnings",
                )
            },
            "import": report,
            "can_run": report["can_run"],
        }

    def latest_supplier_snapshot(self, supplier_id: str) -> dict | None:
        snapshots = [
            snapshot
            for snapshot in self._snapshots.values()
            if snapshot.get("supplier_id") == supplier_id
        ]
        if not snapshots:
            return None
        snapshot = snapshots[-1]
        return {
            key: snapshot.get(key)
            for key in (
                "snapshot_id",
                "supplier_id",
                "snapshot_sha256",
                "retrieved_at",
                "acquisition_status",
                "inventory_complete",
                "pages_attempted",
                "pages_completed",
                "observed_offer_count",
                "available_offer_count",
                "has_next_page",
                "source_method",
                "provider",
                "import",
                "warnings",
                "diagnostics",
            )
        }

    def submit_supplier_scout_run(self, request: dict) -> dict:
        self._n += 1
        run_id = f"supplier-dev-{self._n}"
        selected_supplier = next(
            item for item in self._suppliers if item["supplier_id"] == request["supplier_id"]
        )
        snapshot_id = request.get("inventory_snapshot_id")
        if not snapshot_id or snapshot_id not in self._snapshots:
            raise ValueError("inventory_snapshot_id is required; import JSON first")
        inventory = dict(self._snapshots[snapshot_id])
        if inventory.get("supplier_id") != selected_supplier["supplier_id"]:
            raise ValueError("inventory snapshot belongs to a different supplier")

        def ebay_demand(raw_part_number: str, **_kwargs):
            return {
                "provider": "DEV_EBAY_REPLAY",
                "status": "SUCCESS",
                "observed_demand": {
                    "eligible_listing_count": 1,
                    "max_single_listing_sold": 8,
                    "aggregate_observed_sold": 8,
                },
                "listings": [],
                "diagnostics": [],
            }

        def amazon_search(query: str, **_kwargs):
            is_left = "25778389" in query or "Cadillac" in query
            count = 7 if is_left else 3
            raw_part = "25778389" if is_left else "25778388"
            make_model = "Cadillac CTS" if is_left else "Chevrolet Silverado"
            products = [
                {
                    "asin": f"B0000{index + (100 if is_left else 1):05d}",
                    "title": f"Brand {index + 1} Fog Light Bezel for 2008-2013 {make_model} {raw_part}",
                    "url": f"https://www.amazon.com/dp/B0000{index + (100 if is_left else 1):05d}",
                    "price_usd": 28.0 + index,
                    "active_offer_count_lower_bound": 1,
                    "active_offer_count_complete": True,
                }
                for index in range(count)
            ]
            return {
                "provider": "DEV_AMAZON_REPLAY",
                "query": query,
                "acquisition_status": "SUCCESS",
                "result_page_complete": True,
                "has_next_page": False,
                "products": products,
                "diagnostics": [],
            }

        result = run_supplier_scout(
            inventory,
            category_definitions=builtin_runtime_categories(),
            selected_category_ids=request["selected_category_ids"],
            serpapi_key="dev-only",
            market_request_budget=request["market_request_budget"],
            max_amazon_queries_per_family=request["max_amazon_queries_per_family"],
            grade_a_max_competitors=request["grade_a_max_competitors"],
            grade_a_minus_max_competitors=request["grade_a_minus_max_competitors"],
            min_family_price_usd=request["min_family_price_usd"],
            min_observed_ebay_demand=request["min_observed_ebay_demand"],
            collectors={"ebay_demand": ebay_demand, "amazon_search": amazon_search},
        )
        self._runs[run_id] = {
            "run_id": run_id,
            "status": "COMPLETED",
            "created_at": "2026-08-30T00:00:00Z",
            "started_at": "2026-08-30T00:00:01Z",
            "completed_at": "2026-08-30T00:00:04Z",
            "error": None,
            "result": result,
        }
        return {"run_id": run_id, "status": "QUEUED"}

    def get_supplier_scout_run(self, run_id: str) -> dict | None:
        return self._runs.get(run_id)

    def submit_run(self, request: dict) -> dict:
        return self.submit_mvp_run(request)

    def get_run(self, run_id: str) -> dict | None:
        return self._runs.get(run_id)


if __name__ == "__main__":
    import uvicorn

    assert automatic_mvp_policy()["profile"] == "automatic-mvp"
    uvicorn.run(create_app(service=StubService()), host="127.0.0.1", port=8766)
