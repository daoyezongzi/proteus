"""Northway-shaped, product-family-first automotive parts screening MVP."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from proteus.normalization import normalize_part_number
from proteus.providers.hiobuy import collect_1688_supply
from proteus.providers.local_1688_cli import (
    collect_1688_supplier,
    is_1688_cli_available,
    is_real_1688_url,
    is_valid_1688_offer_id,
)
from proteus.providers.serpapi_amazon import collect_amazon_search
from proteus.providers.serpapi_ebay_discovery import collect_ebay_sold_candidates


DISCOVERY_COLLECTOR = "discovery"
AMAZON_SEARCH_COLLECTOR = "amazon_search"
SUPPLY_COLLECTOR = "china_supply"
SUPPLIER_PREFILTER_COLLECTOR = "1688_supplier_prefilter"


ARCHETYPES: dict[str, dict[str, Any]] = {
    "fog_light_bezel": {
        "profile": "vehicle_specific_small_trim",
        "part_type": "fog light bezel",
        "aliases": ("fog light bezel", "fog lamp bezel", "fog light cover", "fog lamp cover"),
        "discovery_keyword": "fog light bezel OEM",
    },
    "tow_hook_cover": {
        "profile": "vehicle_specific_small_trim",
        "part_type": "tow hook cover",
        "aliases": ("tow hook cover", "tow eye cover", "towing eye cover"),
        "discovery_keyword": "tow hook cover OEM",
    },
    "bumper_reflector": {
        "profile": "vehicle_specific_small_trim",
        "part_type": "bumper reflector",
        "aliases": ("bumper reflector", "rear reflector", "bumper side reflector"),
        "discovery_keyword": "bumper reflector OEM",
    },
    "headlight_washer_cover": {
        "profile": "vehicle_specific_small_trim",
        "part_type": "headlight washer cover",
        "aliases": (
            "headlight washer cover",
            "headlamp washer cover",
            "headlight washer cap",
            "headlamp washer cap",
            "headlight washer covers",
        ),
        "discovery_keyword": "headlight washer cover OEM",
    },
    "lower_air_deflector": {
        "profile": "vehicle_specific_small_trim",
        "part_type": "lower air deflector",
        "aliases": ("lower air deflector", "lower splash shield", "lower air shield"),
        "discovery_keyword": "lower air deflector OEM",
    },
    "hood_latch_release_cable": {
        "profile": "vehicle_specific_cable",
        "part_type": "hood latch release cable",
        "aliases": (
            "hood latch release cable",
            "hood release cable",
            "bonnet release cable",
            "hood lock cable",
        ),
        "discovery_keyword": "hood release cable OEM",
    },
    "accelerator_cable": {
        "profile": "vehicle_specific_cable",
        "part_type": "accelerator cable",
        "aliases": ("accelerator cable", "throttle cable", "gas pedal cable"),
        "discovery_keyword": "accelerator cable OEM",
    },
    "door_handle_bowden_cable": {
        "profile": "vehicle_specific_cable",
        "part_type": "door handle Bowden cable",
        "aliases": ("door handle bowden cable", "door handle cable", "door latch cable"),
        "discovery_keyword": "door handle cable OEM",
    },
    "transmission_shift_control_cable": {
        "profile": "vehicle_specific_cable",
        "part_type": "transmission shift control cable",
        "aliases": (
            "transmission shift control cable",
            "shift control cable",
            "gear selector cable",
            "shifter cable",
        ),
        "discovery_keyword": "shift control cable OEM",
    },
}

_OUT_OF_SCOPE_TERMS = (
    "universal",
    "cleaner",
    "cleaning kit",
    "chemical",
    "polish",
    "brake",
    "steering",
    "airbag",
    "headlight assembly",
    "tail light assembly",
    "led assembly",
    "complete assembly",
)
_NEGATIVE_IDENTIFIERS = ("00289-acrkt", "00289acrkt")
_YEAR_RANGE = re.compile(
    r"(?<!\d)((?:19|20)\d{2})\s*[-–/]\s*((?:19|20)?\d{2})(?!\d)"
)
_SHORT_YEAR_RANGE = re.compile(r"(?<!\d)(\d{2})\s*[-–/]\s*(\d{2})(?!\d)")
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_LEFT = re.compile(r"\b(?:left|driver(?:'s)?(?:\s+side)?)\b", re.IGNORECASE)
_RIGHT = re.compile(r"\b(?:right|passenger(?:'s)?(?:\s+side)?)\b", re.IGNORECASE)
_PAIR = re.compile(r"\b(?:pair|set\s+of\s+2|2\s*(?:pc|pcs|piece|pieces))\b", re.IGNORECASE)
_KIT = re.compile(r"\bkit\b", re.IGNORECASE)
_POSITION_TERMS = ("front", "rear", "upper", "lower", "inner", "outer")
_TRANSMISSION_TERMS = {"automatic": "automatic", "manual": "manual"}

_MAKE_ALIASES: dict[str, tuple[str, ...]] = {
    "Acura": ("acura",),
    "Audi": ("audi",),
    "BMW": ("bmw",),
    "Buick": ("buick",),
    "Cadillac": ("cadillac",),
    "Chevrolet": ("chevrolet", "chevy"),
    "Chrysler": ("chrysler",),
    "Dodge": ("dodge",),
    "Ford": ("ford",),
    "GMC": ("gmc",),
    "Honda": ("honda",),
    "Hyundai": ("hyundai",),
    "Infiniti": ("infiniti",),
    "Jeep": ("jeep",),
    "Kia": ("kia",),
    "Lexus": ("lexus",),
    "Lincoln": ("lincoln",),
    "Mazda": ("mazda",),
    "Mercedes-Benz": ("mercedes-benz", "mercedes benz", "mercedes"),
    "Mercury": ("mercury",),
    "Mini": ("mini",),
    "Mitsubishi": ("mitsubishi",),
    "Nissan": ("nissan",),
    "Pontiac": ("pontiac",),
    "Porsche": ("porsche",),
    "Ram": ("ram",),
    "Saab": ("saab",),
    "Saturn": ("saturn",),
    "Scion": ("scion",),
    "Subaru": ("subaru",),
    "Suzuki": ("suzuki",),
    "Toyota": ("toyota",),
    "Volkswagen": ("volkswagen", "vw"),
    "Volvo": ("volvo",),
}

_MODEL_NOISE = {
    "new",
    "genuine",
    "oem",
    "oe",
    "replacement",
    "replaces",
    "replace",
    "fits",
    "fit",
    "for",
    "with",
    "without",
    "black",
    "chrome",
    "painted",
    "unpainted",
    "front",
    "rear",
    "left",
    "right",
    "driver",
    "drivers",
    "passenger",
    "passengers",
    "side",
    "upper",
    "lower",
    "inner",
    "outer",
    "pair",
    "set",
    "kit",
    "piece",
    "pieces",
    "pc",
    "pcs",
    "automatic",
    "manual",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", value).strip() if isinstance(value, str) else ""


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    return normalized or "unknown"


def _archetype(key: str) -> dict[str, Any]:
    if key not in ARCHETYPES:
        raise ValueError(f"unknown Northway archetype: {key}")
    return ARCHETYPES[key]


def _selected_archetypes(
    archetype: str | None,
    archetypes: Sequence[str] | None,
) -> list[str]:
    if archetype is not None and archetypes is not None:
        raise ValueError("use archetype or archetypes, not both")
    if archetype is not None:
        selected = [archetype]
    elif archetypes is not None:
        if isinstance(archetypes, (str, bytes)):
            raise ValueError("archetypes must be a sequence of archetype keys")
        selected = list(dict.fromkeys(archetypes))
    else:
        selected = list(ARCHETYPES)
    if not selected:
        raise ValueError("at least one Northway archetype is required")
    for key in selected:
        if not isinstance(key, str):
            raise ValueError("archetype keys must be strings")
        _archetype(key)
    return selected


def _matching_archetype(
    candidates: Sequence[Mapping[str, Any]],
    selected: Sequence[str],
) -> str:
    title = _clean_text(candidates[0].get("source_listing_title")) if candidates else ""
    for key in selected:
        if classify_scope(title, key)["status"] == "IN_SCOPE":
            return key
    for candidate in candidates:
        discovered_as = candidate.get("_discovery_archetype")
        if isinstance(discovered_as, str) and discovered_as in selected:
            return discovered_as
    return selected[0]


def _public_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in candidate.items()
        if not str(key).startswith("_discovery_")
    }


def northway_mvp_policy() -> dict[str, Any]:
    return {
        "schema_version": "0.2.4",
        "profile": "northway-product-family-mvp",
        "decision_labels": [
            "OPPORTUNITY_CANDIDATE",
            "MARKET_SHORTLIST_CANDIDATE",
            "REVIEW_REQUIRED",
            "REJECTED",
        ],
        "category_profiles": {
            "vehicle_specific_small_trim": {
                "label": "Vehicle-specific small trim",
                "archetypes": [
                    key
                    for key, value in ARCHETYPES.items()
                    if value["profile"] == "vehicle_specific_small_trim"
                ],
            },
            "vehicle_specific_cable": {
                "label": "Vehicle-specific cable",
                "archetypes": [
                    key
                    for key, value in ARCHETYPES.items()
                    if value["profile"] == "vehicle_specific_cable"
                ],
            },
        },
        "archetypes": {
            key: {
                "category_profile": value["profile"],
                "part_type": value["part_type"],
                "discovery_keyword": value["discovery_keyword"],
            }
            for key, value in ARCHETYPES.items()
        },
        "default_thresholds": {
            "min_family_price_usd": 20.0,
            "min_observed_ebay_demand": 1,
            "max_amazon_queries_per_family": 3,
        },
        "competition_rule": {
            "automatic_upper_bound": None,
            "count_usage": "ranking_and_manual_review",
        },
        "run_bounds": {
            "candidate_cap": None,
            "discovery_pages": {"minimum": 1, "maximum": 10, "default": 1},
            "request_budget": {"minimum": 1, "maximum": 500, "default": 20},
            "max_1688_checks": {"minimum": 0, "maximum": 500, "default": 20},
        },
        "archetype_selection": {
            "required": True,
            "selection_mode": "one_leaf_category",
            "description": "Each run selects exactly one Northway leaf archetype.",
        },
        "qualification_boundary": (
            "Each run scans one selected Northway archetype. After local scope, family and "
            "demand filters, a shallow read-only 1688 supplier prefilter runs before Amazon. "
            "Only a family with a valid 1688 offer ID, real 1688 URL, supplier identity and "
            "matching title proceeds to Amazon. Observed competition is a ranking and manual-"
            "review signal, not an automatic upper bound. It is not a purchase instruction."
        ),
    }


def classify_scope(title: str, archetype_key: str) -> dict[str, Any]:
    profile = _archetype(archetype_key)
    text = _clean_text(title).casefold()
    reasons: list[str] = []
    if not text:
        return {"status": "REVIEW_REQUIRED", "reasons": ["Listing title is missing."]}
    if any(term in text for term in _NEGATIVE_IDENTIFIERS):
        reasons.append("Known chemical/cleaning negative control identifier was detected.")
    if any(term in text for term in _OUT_OF_SCOPE_TERMS):
        reasons.append("Listing contains an explicitly excluded product-shape term.")
    if reasons:
        return {"status": "OUT_OF_SCOPE", "reasons": reasons}
    if not any(alias in text for alias in profile["aliases"]):
        return {
            "status": "OUT_OF_SCOPE",
            "reasons": [f"Title does not describe the selected {profile['part_type']} archetype."],
        }
    return {
        "status": "IN_SCOPE",
        "reasons": [f"Title matches the {profile['part_type']} Northway archetype."],
    }


def _title_years(title: str) -> tuple[int | None, int | None]:
    years: list[int] = []
    for match in _YEAR_RANGE.finditer(title):
        start = int(match.group(1))
        raw_end = match.group(2)
        end = int(raw_end)
        if len(raw_end) == 2:
            end = (start // 100) * 100 + end
            if end < start:
                end += 100
        if 1886 <= start <= end <= 2100:
            years.extend((start, end))
    if not years:
        for match in _SHORT_YEAR_RANGE.finditer(title):
            short_start = int(match.group(1))
            short_end = int(match.group(2))
            start = (1900 if short_start >= 70 else 2000) + short_start
            end = (start // 100) * 100 + short_end
            if end < start:
                end += 100
            if 1886 <= start <= end <= 2100 and end - start <= 30:
                years.extend((start, end))
    if not years:
        years = [int(value) for value in _YEAR.findall(title)]
    return (min(years), max(years)) if years else (None, None)


def _find_make(title: str) -> str | None:
    folded = title.casefold()
    matches: list[tuple[int, str]] = []
    for make, aliases in _MAKE_ALIASES.items():
        for alias in aliases:
            match = re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", folded)
            if match:
                matches.append((match.start(), make))
                break
    return min(matches)[1] if matches else None


def _fallback_fitments(title: str, profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    make = _find_make(title)
    if make is None:
        return []
    year_from, year_to = _title_years(title)
    folded_make_aliases = {
        token
        for aliases in _MAKE_ALIASES.values()
        for alias in aliases
        for token in alias.split()
    }
    part_words = {
        token
        for alias in profile["aliases"]
        for token in re.findall(r"[a-z0-9]+", alias.casefold())
    }
    tokens = re.findall(r"[A-Za-z0-9]+", title)
    model_tokens: list[str] = []
    for token in tokens:
        folded = token.casefold()
        if folded in _MODEL_NOISE or folded in folded_make_aliases or folded in part_words:
            continue
        if re.fullmatch(r"(?:19|20)\d{2}", token):
            continue
        if re.fullmatch(r"\d{2}", token) and year_from is not None:
            continue
        try:
            canonical = normalize_part_number(token)
        except (TypeError, ValueError):
            canonical = ""
        if len(canonical) >= 6 and any(char.isalpha() for char in canonical) and any(
            char.isdigit() for char in canonical
        ):
            continue
        if token.isdigit() and len(token) >= 5:
            continue
        model_tokens.append(token)
    if not model_tokens:
        return []
    transmissions = [
        normalized
        for term, normalized in _TRANSMISSION_TERMS.items()
        if re.search(rf"\b{term}\b", title, re.IGNORECASE)
    ]
    return [
        {
            "make": make,
            "model": " ".join(model_tokens[:3]),
            "year_from": year_from,
            "year_to": year_to,
            "engines": [],
            "transmissions": transmissions,
        }
    ]


def _compatibility_fitments(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        make = _clean_text(row.get("make"))
        model = _clean_text(row.get("model"))
        year = row.get("year")
        if not make or not model or isinstance(year, bool) or not isinstance(year, int):
            continue
        key = (make.casefold(), model.casefold())
        group = grouped.setdefault(
            key,
            {
                "make": make,
                "model": model,
                "years": [],
                "engines": set(),
                "transmissions": set(),
            },
        )
        group["years"].append(year)
        engine = _clean_text(row.get("engine"))
        if engine:
            group["engines"].add(engine)
        notes = f"{_clean_text(row.get('notes'))} {_clean_text(row.get('trim'))}".casefold()
        for term, normalized in _TRANSMISSION_TERMS.items():
            if re.search(rf"\b{term}\b", notes):
                group["transmissions"].add(normalized)
    return [
        {
            "make": value["make"],
            "model": value["model"],
            "year_from": min(value["years"]),
            "year_to": max(value["years"]),
            "engines": sorted(value["engines"]),
            "transmissions": sorted(value["transmissions"]),
        }
        for value in grouped.values()
    ]


def resolve_product_family(
    candidates: Sequence[Mapping[str, Any]],
    archetype_key: str,
    *,
    fitment_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    profile = _archetype(archetype_key)
    if not candidates:
        raise ValueError("at least one discovery candidate is required")
    title = _clean_text(candidates[0].get("source_listing_title"))
    scope = classify_scope(title, archetype_key)
    if scope["status"] == "OUT_OF_SCOPE":
        return {
            "scope_status": "OUT_OF_SCOPE",
            "identity_status": "NOT_RESOLVED",
            "category_profile": None,
            "family": None,
            "reasons": list(scope["reasons"]),
        }

    identifiers: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in candidates:
        raw = _clean_text(item.get("raw_part_number"))
        if not raw:
            continue
        try:
            canonical = normalize_part_number(raw)
        except (TypeError, ValueError):
            continue
        if canonical in seen_ids:
            continue
        seen_ids.add(canonical)
        identifiers.append(
            {
                "raw": raw,
                "canonical": canonical,
                "identifier_type": "OEM",
                "role": "PRIMARY" if not identifiers else "ALIAS",
            }
        )
    if not identifiers:
        return {
            "scope_status": "IN_SCOPE",
            "identity_status": "REVIEW_REQUIRED",
            "category_profile": profile["profile"],
            "family": None,
            "reasons": ["No verified identifier survived normalization."],
        }

    fitments = _compatibility_fitments(fitment_rows or [])
    fitment_method = "compatibility" if fitments else "title"
    if not fitments:
        fitments = _fallback_fitments(title, profile)
    if not fitments:
        return {
            "scope_status": "IN_SCOPE",
            "identity_status": "REVIEW_REQUIRED",
            "category_profile": profile["profile"],
            "family": None,
            "identifiers": identifiers,
            "reasons": ["Vehicle make/model fitment could not be resolved."],
        }

    sides: list[str] = []
    if _LEFT.search(title):
        sides.append("LEFT")
    if _RIGHT.search(title):
        sides.append("RIGHT")
    positions = [term.upper() for term in _POSITION_TERMS if re.search(rf"\b{term}\b", title, re.I)]
    package_type = "PAIR" if _PAIR.search(title) else "KIT" if _KIT.search(title) else "SINGLE"
    package_quantity = 2 if package_type == "PAIR" else 1
    relations: list[dict[str, Any]] = []
    source_reference = _clean_text(candidates[0].get("source_listing_url")) or "https://www.ebay.com/"
    relation_type = (
        "replacement"
        if re.search(r"\b(?:replace|replaces|replacement|supersedes)\b", title, re.I)
        else "unknown_relation"
    )
    for identifier in identifiers[1:]:
        relations.append(
            {
                "relation_type": relation_type,
                "target_identifier": identifier["raw"],
                "evidence_reference": source_reference,
            }
        )
    identity_payload = {
        "part_type": profile["part_type"],
        "fitments": fitments,
        "positions": positions,
        "sides": sides,
        "package_quantity": package_quantity,
        "package_type": package_type,
        "identifiers": [item["canonical"] for item in identifiers],
    }
    digest = hashlib.sha256(
        json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    family = {
        "family_key": f"family_{digest}",
        "part_type": profile["part_type"],
        "fitments": fitments,
        "positions": positions,
        "sides": sides,
        "critical_specs": [],
        "package_quantity": package_quantity,
        "package_type": package_type,
        "identifiers": identifiers,
        "relations": relations,
        "confidence": 0.9 if fitment_method == "compatibility" else 0.7,
        "evidence": [
            {
                "source_reference": source_reference,
                "field": "title",
                "raw_value": title,
            },
            {
                "source_reference": source_reference,
                "field": "fitment",
                "raw_value": f"Resolved from {fitment_method}: {fitments}",
            },
        ],
    }
    return {
        "scope_status": "IN_SCOPE",
        "identity_status": "RESOLVED",
        "category_profile": profile["profile"],
        "family": family,
        "reasons": list(scope["reasons"]),
    }


def build_amazon_query_pack(
    family: Mapping[str, Any], *, max_queries: int = 3
) -> list[dict[str, str]]:
    if isinstance(max_queries, bool) or not isinstance(max_queries, int) or max_queries < 1:
        raise ValueError("max_queries must be a positive integer")
    candidates: list[dict[str, str]] = []
    for identifier in family.get("identifiers", []):
        if isinstance(identifier, Mapping) and _clean_text(identifier.get("raw")):
            candidates.append(
                {"query_type": "exact_identifier", "query": _clean_text(identifier["raw"])}
            )
    fitments = family.get("fitments")
    if isinstance(fitments, list) and fitments:
        fitment = fitments[0]
        if isinstance(fitment, Mapping):
            make = _clean_text(fitment.get("make"))
            model = _clean_text(fitment.get("model"))
            year_from = fitment.get("year_from")
            year_to = fitment.get("year_to")
            years = ""
            if isinstance(year_from, int) and isinstance(year_to, int):
                years = str(year_from) if year_from == year_to else f"{year_from}-{year_to}"
            base = " ".join(
                value
                for value in (_clean_text(family.get("part_type")), make, model, years)
                if value
            )
            candidates.append({"query_type": "fitment_name", "query": base})
            qualifiers = " ".join(
                [*(str(value).lower() for value in family.get("sides", [])), *(str(value).lower() for value in family.get("positions", []))]
            )
            if qualifiers:
                candidates.append(
                    {"query_type": "fitment_position", "query": f"{base} {qualifiers}"}
                )
            specs = " ".join(
                _clean_text(item.get("value"))
                for item in family.get("critical_specs", [])
                if isinstance(item, Mapping)
            )
            if specs:
                candidates.append({"query_type": "fitment_specification", "query": f"{base} {specs}"})
    seen: set[str] = set()
    pack: list[dict[str, str]] = []
    for item in candidates:
        query = re.sub(r"\s+", " ", item["query"]).strip()
        folded = query.casefold()
        if not query or folded in seen:
            continue
        seen.add(folded)
        pack.append({"query_type": item["query_type"], "query": query})
        if len(pack) >= max_queries:
            break
    return pack


def _product_sides(title: str) -> set[str]:
    sides: set[str] = set()
    if _LEFT.search(title):
        sides.add("LEFT")
    if _RIGHT.search(title):
        sides.add("RIGHT")
    return sides


def _product_relation(family: Mapping[str, Any], product: Mapping[str, Any]) -> dict[str, Any]:
    title = _clean_text(product.get("title"))
    folded = title.casefold()
    profile = next(
        (value for value in ARCHETYPES.values() if value["part_type"] == family.get("part_type")),
        None,
    )
    if not title or profile is None:
        return {"relation": "REVIEW_REQUIRED", "reason": "Product title is incomplete."}
    if any(term in folded for term in _OUT_OF_SCOPE_TERMS):
        return {"relation": "IRRELEVANT", "reason": "Product is explicitly outside scope."}
    if not any(alias in folded for alias in profile["aliases"]):
        return {"relation": "IRRELEVANT", "reason": "Part type does not match."}

    target_sides = set(str(value) for value in family.get("sides", []))
    product_sides = _product_sides(title)
    if target_sides == {"LEFT"} and product_sides == {"RIGHT"}:
        return {"relation": "LEFT_RIGHT_COUNTERPART", "reason": "Right-side counterpart."}
    if target_sides == {"RIGHT"} and product_sides == {"LEFT"}:
        return {"relation": "LEFT_RIGHT_COUNTERPART", "reason": "Left-side counterpart."}
    target_pair = family.get("package_type") == "PAIR"
    product_pair = bool(_PAIR.search(title) or product_sides == {"LEFT", "RIGHT"})
    if target_pair != product_pair and (target_pair or product_pair):
        return {"relation": "PACKAGE_MISMATCH", "reason": "Single/pair package identity differs."}

    normalized_title = re.sub(r"[^A-Z0-9]", "", title.upper())
    exact_identifier = any(
        isinstance(item, Mapping)
        and _clean_text(item.get("canonical"))
        and _clean_text(item.get("canonical")) in normalized_title
        for item in family.get("identifiers", [])
    )
    fitment_match = False
    for fitment in family.get("fitments", []):
        if not isinstance(fitment, Mapping):
            continue
        make = _clean_text(fitment.get("make")).casefold()
        model_tokens = re.findall(r"[a-z0-9]+", _clean_text(fitment.get("model")).casefold())
        if make and make in folded and model_tokens and all(token in folded for token in model_tokens):
            fitment_match = True
            break
        if make == "chevrolet" and "chevy" in folded and model_tokens and all(
            token in folded for token in model_tokens
        ):
            fitment_match = True
            break
        if make == "volkswagen" and re.search(r"\bvw\b", folded) and model_tokens and all(
            token in folded for token in model_tokens
        ):
            fitment_match = True
            break
    if not exact_identifier and not fitment_match:
        return {
            "relation": "REVIEW_REQUIRED",
            "reason": "Part type matches but interchangeability is not proven.",
        }
    is_oem = bool(re.search(r"\b(?:genuine|oem|original equipment)\b", title, re.I))
    return {
        "relation": "INTERCHANGEABLE",
        "reason": "Part type and identifier or fitment match the family.",
        "is_original_equipment": is_oem,
    }


def _cluster_key(product: Mapping[str, Any]) -> str:
    title = _clean_text(product.get("title")).casefold()
    normalized = re.sub(r"\b(?:new|replacement|fits?|for|oem)\b", " ", title)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _stage(status: str, value: Any, operator: str | None, threshold: Any, reason: str) -> dict[str, Any]:
    return {
        "status": status,
        "value": value,
        "operator": operator,
        "threshold": threshold,
        "reason": reason,
    }


def aggregate_amazon_family_results(
    family: Mapping[str, Any],
    query_results: Sequence[Mapping[str, Any]],
    *,
    min_family_price_usd: float,
    max_competitive_products: int | None = None,
) -> dict[str, Any]:
    products_by_asin: dict[str, dict[str, Any]] = {}
    matched_queries: dict[str, set[str]] = defaultdict(set)
    query_evidence: list[dict[str, Any]] = []
    complete = bool(query_results)
    for outcome in query_results:
        query = _clean_text(outcome.get("query"))
        query_evidence.append(dict(outcome))
        if outcome.get("acquisition_status") not in {"SUCCESS", "ZERO_RESULTS"}:
            complete = False
        if outcome.get("result_page_complete") is not True:
            complete = False
        products = outcome.get("products")
        if not isinstance(products, list):
            complete = False
            continue
        for raw_product in products:
            if not isinstance(raw_product, Mapping):
                complete = False
                continue
            asin = _clean_text(raw_product.get("asin")).upper()
            if not asin:
                complete = False
                continue
            products_by_asin.setdefault(asin, dict(raw_product))
            if query:
                matched_queries[asin].add(query)

    observations: list[dict[str, Any]] = []
    relevant: list[dict[str, Any]] = []
    for asin, product in products_by_asin.items():
        relation = _product_relation(family, product)
        observation = {
            **product,
            "asin": asin,
            **relation,
            "matched_queries": sorted(matched_queries[asin]),
        }
        observations.append(observation)
        if relation["relation"] == "INTERCHANGEABLE":
            observation["product_cluster_key"] = _cluster_key(product)
            relevant.append(observation)

    clusters = {item["product_cluster_key"] for item in relevant}
    offers = {
        item["asin"]: item.get("active_offer_count_lower_bound")
        for item in relevant
        if isinstance(item.get("active_offer_count_lower_bound"), int)
        and not isinstance(item.get("active_offer_count_lower_bound"), bool)
    }
    prices = [
        float(item["price_usd"])
        for item in relevant
        if isinstance(item.get("price_usd"), (int, float))
        and not isinstance(item.get("price_usd"), bool)
    ]
    aftermarket_prices = [
        float(item["price_usd"])
        for item in relevant
        if item.get("is_original_equipment") is not True
        and isinstance(item.get("price_usd"), (int, float))
        and not isinstance(item.get("price_usd"), bool)
    ]
    cluster_count = len(clusters)
    if not complete:
        competition_stage = _stage(
            "REVIEW_REQUIRED",
            cluster_count,
            None,
            None,
            "Observed competition is only a lower bound because one or more family searches are incomplete; the count has no automatic upper limit.",
        )
    else:
        competition_stage = _stage(
            "PASSED",
            cluster_count,
            None,
            None,
            "Complete family search evidence is available; the observed substitute-product cluster count is retained for ranking and manual review without an automatic upper limit.",
        )
    price_floor = min(prices) if prices else None
    aftermarket_floor = min(aftermarket_prices) if aftermarket_prices else None
    decision_floor = aftermarket_floor if aftermarket_floor is not None else price_floor
    if decision_floor is None:
        price_stage = _stage(
            "REVIEW_REQUIRED",
            None,
            "GT",
            float(min_family_price_usd),
            "No complete visible family price floor is available.",
        )
    elif decision_floor <= float(min_family_price_usd):
        price_stage = _stage(
            "REJECTED",
            decision_floor,
            "GT",
            float(min_family_price_usd),
            "The substitute-family price floor is at or below the configured limit.",
        )
    else:
        price_stage = _stage(
            "PASSED",
            decision_floor,
            "GT",
            float(min_family_price_usd),
            "The substitute-family price floor remains above the configured limit.",
        )
    return {
        "competition_complete": complete,
        "competitive_product_cluster_count": cluster_count,
        "competitive_asin_count": len(relevant),
        "original_equipment_asin_count": sum(
            item.get("is_original_equipment") is True for item in relevant
        ),
        "aftermarket_asin_count": sum(
            item.get("is_original_equipment") is not True for item in relevant
        ),
        "offer_count_by_asin": offers,
        "family_offer_count_lower_bound": sum(offers.values()),
        "family_price_floor_usd": price_floor,
        "aftermarket_family_price_floor_usd": aftermarket_floor,
        "competition_stage": competition_stage,
        "price_stage": price_stage,
        "observations": observations,
        "query_evidence": query_evidence,
    }


def _compact_fields(value: Any, keys: Sequence[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {key: value[key] for key in keys if key in value and value[key] is not None}


def _compact_diagnostics(value: Any) -> dict[str, Any]:
    diagnostics = value if isinstance(value, list) else []
    codes = Counter(
        _clean_text(item.get("code")) or "UNKNOWN"
        for item in diagnostics
        if isinstance(item, Mapping)
    )
    return {
        "count": len(diagnostics),
        "codes": dict(sorted(codes.items())),
    }


def _compact_stage(value: Any) -> dict[str, Any]:
    return _compact_fields(value, ("status", "value", "operator", "threshold", "reason"))


def _compact_source_listing(value: Any) -> dict[str, Any]:
    return _compact_fields(
        value,
        (
            "raw_part_number",
            "canonical_part_number",
            "identifier_type",
            "source_listing_id",
            "source_listing_url",
            "source_listing_title",
            "source_listing_position",
            "source_sold_count",
        ),
    )


def _compact_family(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return _compact_fields(
        value,
        (
            "family_key",
            "part_type",
            "fitments",
            "positions",
            "sides",
            "critical_specs",
            "package_quantity",
            "package_type",
            "identifiers",
            "relations",
            "confidence",
        ),
    )


def _compact_observation(value: Any) -> dict[str, Any]:
    compact = _compact_fields(
        value,
        (
            "asin",
            "title",
            "url",
            "price_usd",
            "active_offer_count_lower_bound",
            "active_offer_count_complete",
            "is_original_equipment",
            "relation",
            "reason",
            "matched_queries",
        ),
    )
    asin = _clean_text(value.get("asin")) if isinstance(value, Mapping) else ""
    if asin:
        compact["url"] = f"https://www.amazon.com/dp/{asin}"
    return compact


def _compact_query_evidence(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    products = value.get("products")
    compact = _compact_fields(
        value,
        (
            "provider",
            "source_method",
            "marketplace_id",
            "query",
            "retrieved_at",
            "acquisition_status",
            "result_page_complete",
            "has_next_page",
            "reported_total_results",
            "results_seen",
        ),
    )
    compact["products_seen"] = len(products) if isinstance(products, list) else None
    compact["diagnostics"] = _compact_diagnostics(value.get("diagnostics"))
    return compact


def _compact_competition(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    observations = [item for item in value.get("observations", []) if isinstance(item, Mapping)]
    relation_counts = Counter(_clean_text(item.get("relation")) or "UNKNOWN" for item in observations)
    relation_samples: dict[str, list[dict[str, Any]]] = {}
    for relation in sorted(relation_counts):
        if relation == "INTERCHANGEABLE":
            continue
        relation_samples[relation] = [
            _compact_observation(item)
            for item in observations
            if (_clean_text(item.get("relation")) or "UNKNOWN") == relation
        ][:3]
    compact = _compact_fields(
        value,
        (
            "competition_complete",
            "competitive_product_cluster_count",
            "competitive_asin_count",
            "original_equipment_asin_count",
            "aftermarket_asin_count",
            "offer_count_by_asin",
            "family_offer_count_lower_bound",
            "family_price_floor_usd",
            "aftermarket_family_price_floor_usd",
        ),
    )
    compact.update(
        {
            "observation_count": len(observations),
            "relation_counts": dict(sorted(relation_counts.items())),
            "relevant_products": [
                _compact_observation(item)
                for item in observations
                if item.get("relation") == "INTERCHANGEABLE"
            ],
            "relation_samples": relation_samples,
            "competition_stage": _compact_stage(value.get("competition_stage")),
            "price_stage": _compact_stage(value.get("price_stage")),
            "query_evidence": [
                _compact_query_evidence(item)
                for item in value.get("query_evidence", [])
                if isinstance(item, Mapping)
            ],
        }
    )
    return compact


def _compact_supply(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    compact = _compact_fields(
        value,
        (
            "provider",
            "acquisition_status",
            "source_method",
            "query",
            "title",
            "offer_id",
            "matched_part_numbers",
            "match_type",
            "offer_url",
            "supplier_found",
            "purchasable",
            "price_cny",
            "moq",
            "retrieved_at",
        ),
    )
    supplier = value.get("supplier")
    if isinstance(supplier, Mapping):
        compact["supplier"] = _compact_fields(supplier, ("id", "name", "shop_name", "url"))
    elif supplier is not None:
        compact["supplier"] = supplier
    preview = value.get("order_preview")
    if isinstance(preview, Mapping):
        compact["order_preview"] = _compact_fields(
            preview,
            ("offer_id", "sku_id", "quantity", "currency", "payment_cny", "shipping_cny", "retrieved_at"),
        )
    compact["diagnostics"] = _compact_diagnostics(value.get("diagnostics"))
    return compact


def _compact_report(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    resolution = value.get("resolution")
    family = value.get("family")
    if not isinstance(family, Mapping) and isinstance(resolution, Mapping):
        family = resolution.get("family")
    stages = value.get("stages")
    compact_stages = (
        {
            key: _compact_stage(stage)
            for key, stage in stages.items()
            if isinstance(stage, Mapping)
        }
        if isinstance(stages, Mapping)
        else {}
    )
    return {
        **_compact_fields(
            value,
            (
                "schema_version",
                "profile",
                "candidate_id",
                "discovery_order",
                "decision",
                "rank",
                "category_profile",
                "archetype",
            ),
        ),
        "source_listings": [
            _compact_source_listing(item)
            for item in value.get("source_listings", [])
            if isinstance(item, Mapping)
        ],
        "resolution": _compact_fields(
            resolution,
            ("scope_status", "identity_status", "category_profile", "reasons"),
        ),
        "family": _compact_family(family),
        "query_pack": [
            _compact_fields(item, ("query_type", "query"))
            for item in value.get("query_pack", [])
            if isinstance(item, Mapping)
        ],
        "competition": _compact_competition(value.get("competition")),
        "demand": _compact_fields(
            value.get("demand"),
            ("observed_sold_count_lower_bound", "source_listing_count", "complete_365_day_metric"),
        ),
        "supply": _compact_supply(value.get("supply")),
        "stages": compact_stages,
        "evidence_gaps": list(value.get("evidence_gaps", []))
        if isinstance(value.get("evidence_gaps"), list)
        else [],
        "failure_reasons": list(value.get("failure_reasons", []))
        if isinstance(value.get("failure_reasons"), list)
        else [],
        "provider_attempts": [
            _compact_fields(item, ("provider", "query", "status"))
            for item in value.get("provider_attempts", [])
            if isinstance(item, Mapping)
        ],
    }


def compact_northway_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Build the default operator export without duplicating raw provider evidence.

    The complete result remains available from the full export endpoint. This view keeps
    the identifiers, decisions, stage readings, pagination/budget state, relevant Amazon
    products, and bounded samples of rejected relations while omitting raw diagnostics,
    duplicate resolution evidence, and full per-query product arrays.
    """

    if not isinstance(result, Mapping):
        raise ValueError("Northway result must be a mapping")
    policy = _compact_fields(
        result.get("policy"),
        (
            "archetypes",
            "category_profiles",
            "min_family_price_usd",
            "min_observed_ebay_demand",
            "max_1688_checks",
            "max_amazon_queries_per_family",
            "competition_upper_bound",
        ),
    )
    policy["competition_upper_bound"] = None
    manifest = _compact_fields(
        result.get("scan_manifest"),
        (
            "marketplace",
            "category_id",
            "archetypes",
            "discovery_queries",
            "pages_requested",
            "pages_attempted",
            "pages_completed",
            "selected_archetype",
        ),
    )
    discovery = result.get("discovery")
    compact_discovery = _compact_fields(
        discovery,
        (
            "status",
            "listing_groups",
            "resolved_family_count",
            "deduplicated_candidate_count",
            "stats",
        ),
    )
    diagnostics = discovery.get("diagnostics") if isinstance(discovery, Mapping) else None
    compact_discovery["diagnostics"] = _compact_diagnostics(diagnostics)
    compact_discovery["per_archetype"] = [
        _compact_fields(
            item,
            (
                "archetype",
                "category_profile",
                "keyword",
                "status",
                "pages_attempted",
                "pages_completed",
                "candidates_emitted",
                "stats",
            ),
        )
        for item in (discovery.get("per_archetype", []) if isinstance(discovery, Mapping) else [])
        if isinstance(item, Mapping)
    ]
    provider_budgets = result.get("provider_budgets")
    compact_provider_budgets = {
        provider: _compact_fields(value, ("limit", "used", "remaining"))
        for provider, value in provider_budgets.items()
        if isinstance(value, Mapping)
    } if isinstance(provider_budgets, Mapping) else {}
    return {
        "schema_version": result.get("schema_version", "0.2.4"),
        "export_format": "compact_v1",
        "profile": result.get("profile", "northway-product-family-mvp"),
        "result_id": result.get("result_id"),
        "generated_at": result.get("generated_at"),
        "policy": policy,
        "scan_manifest": manifest,
        "request_budget": _compact_fields(result.get("request_budget"), ("limit", "used", "remaining")),
        "provider_budgets": compact_provider_budgets,
        "supply_filter": _compact_fields(
            result.get("supply_filter"),
            ("provider", "checked", "supplier_found", "no_supplier", "review_required", "not_run"),
        ),
        "discovery": compact_discovery,
        "summary": _compact_fields(
            result.get("summary"),
            (
                "candidate_count",
                "opportunity_candidates",
                "market_shortlist_candidates",
                "review_required",
                "rejected",
            ),
        ),
        "ranking": list(result.get("ranking", [])) if isinstance(result.get("ranking"), list) else [],
        "reports": [
            _compact_report(report)
            for report in result.get("reports", [])
            if isinstance(report, Mapping)
        ],
        "export_notes": {
            "full_evidence_endpoint": "export",
            "omitted": [
                "raw provider diagnostics",
                "duplicate family-resolution evidence",
                "full product arrays from each Amazon query",
            ],
        },
    }


def _demand_stage(source_listings: Sequence[Mapping[str, Any]], minimum: int) -> dict[str, Any]:
    seen: set[str] = set()
    observed = 0
    for listing in source_listings:
        listing_id = _clean_text(listing.get("source_listing_id"))
        sold = listing.get("source_sold_count")
        if not listing_id or listing_id in seen or isinstance(sold, bool) or not isinstance(sold, int):
            continue
        seen.add(listing_id)
        observed += max(0, sold)
    status = "PASSED" if observed >= minimum else "REVIEW_REQUIRED"
    reason = (
        "Observed source listings provide a family-bound sold-count lower bound."
        if status == "PASSED"
        else "Visible source listings do not prove the configured demand floor."
    )
    return _stage(status, observed, "GTE", minimum, reason)


def _supply_stage(outcome: Mapping[str, Any] | None, configured: bool) -> dict[str, Any]:
    if not configured:
        return _stage(
            "REVIEW_REQUIRED",
            None,
            None,
            None,
            "China non-OEM supply verification is not configured.",
        )
    if outcome is None:
        return _stage(
            "REVIEW_REQUIRED", None, None, None, "China supply verification was not completed."
        )

    supplier = outcome.get("supplier")
    supplier_present = bool(
        (isinstance(supplier, Mapping) and any(value for value in supplier.values()))
        or (isinstance(supplier, str) and supplier.strip())
    )
    preview = outcome.get("order_preview")
    offer_id = outcome.get("offer_id") or outcome.get("product_id")
    if not offer_id and isinstance(preview, Mapping):
        offer_id = preview.get("offer_id")
    offer_url = outcome.get("offer_url") or outcome.get("url")
    valid_evidence = bool(
        supplier_present
        and is_valid_1688_offer_id(offer_id)
        and is_real_1688_url(offer_url)
    )
    if outcome.get("acquisition_status") == "SUCCESS" and (
        outcome.get("supplier_found") is True or valid_evidence
    ) and valid_evidence:
        return _stage(
            "PASSED",
            True,
            "EQ",
            True,
            "A valid family-matching 1688 offer, real offer URL and supplier identity are available.",
        )
    if outcome.get("acquisition_status") in {"SUCCESS", "ZERO_RESULTS"}:
        return _stage(
            "REJECTED",
            False,
            "EQ",
            True,
            "No valid family-matching 1688 offer with a supplier identity was found.",
        )
    return _stage(
        "REVIEW_REQUIRED",
        outcome.get("supplier_found"),
        "EQ",
        True,
        "1688 supplier evidence needs review because the provider or parser did not complete.",
    )


def _report_decision(stages: Mapping[str, Mapping[str, Any]]) -> str:
    if any(stage.get("status") == "REJECTED" for stage in stages.values()):
        return "REJECTED"
    market_keys = ("scope", "identity", "demand", "amazon_family_competition")
    market_passed = all(stages[key].get("status") == "PASSED" for key in market_keys)
    price_not_failed = stages["family_price_floor"].get("status") != "REJECTED"
    supply_passed = stages["china_non_oem_supply"].get("status") == "PASSED"
    if market_passed and price_not_failed and supply_passed:
        return "OPPORTUNITY_CANDIDATE"
    if market_passed and price_not_failed:
        return "REVIEW_REQUIRED"
    return "REVIEW_REQUIRED"


def _rank_key(report: Mapping[str, Any]) -> tuple[Any, ...]:
    decision_order = {
        "OPPORTUNITY_CANDIDATE": 0,
        "MARKET_SHORTLIST_CANDIDATE": 1,
        "REVIEW_REQUIRED": 2,
        "REJECTED": 3,
    }
    stages = report.get("stages", {})
    passed = sum(
        isinstance(stage, Mapping) and stage.get("status") == "PASSED"
        for stage in stages.values()
    )
    competition = report.get("competition", {}).get("competitive_product_cluster_count")
    price = report.get("competition", {}).get("aftermarket_family_price_floor_usd")
    demand = report.get("demand", {}).get("observed_sold_count_lower_bound")
    return (
        decision_order.get(report.get("decision"), 9),
        -passed,
        len(report.get("evidence_gaps", [])),
        competition if isinstance(competition, int) else 10**9,
        -(float(price) if isinstance(price, (int, float)) else -1.0),
        -(int(demand) if isinstance(demand, int) else -1),
        report.get("discovery_order", 0),
    )


def run_northway_mvp(
    *,
    serpapi_key: str | None,
    archetype: str | None = None,
    archetypes: Sequence[str] | None = None,
    discovery_pages: int = 1,
    ebay_category_id: str = "6028",
    request_budget: int = 20,
    max_1688_checks: int = 20,
    max_amazon_queries_per_family: int = 3,
    max_competitive_products: int | None = None,
    min_family_price_usd: float = 20.0,
    min_observed_ebay_demand: int = 1,
    hiobuy_key: str | None = None,
    receiver: Mapping[str, Any] | None = None,
    max_supply_moq: int = 10,
    collectors: Mapping[str, Callable[..., Mapping[str, Any]]] | None = None,
    progress_callback: Callable[[Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    selected_archetypes = _selected_archetypes(archetype, archetypes)
    if not isinstance(discovery_pages, int) or isinstance(discovery_pages, bool) or not 1 <= discovery_pages <= 10:
        raise ValueError("discovery_pages must be between 1 and 10")
    if not isinstance(request_budget, int) or isinstance(request_budget, bool) or not 1 <= request_budget <= 500:
        raise ValueError("request_budget must be between 1 and 500")
    discovery_request_count = len(selected_archetypes) * discovery_pages
    if request_budget < discovery_request_count:
        raise ValueError(
            "request_budget must cover every selected archetype discovery page "
            f"({discovery_request_count} requests required)"
        )
    if not isinstance(max_1688_checks, int) or isinstance(max_1688_checks, bool) or not 0 <= max_1688_checks <= 500:
        raise ValueError("max_1688_checks must be between 0 and 500")
    if not 1 <= max_amazon_queries_per_family <= 5:
        raise ValueError("max_amazon_queries_per_family must be between 1 and 5")
    if min_family_price_usd < 0 or min_observed_ebay_demand < 0:
        raise ValueError("screening thresholds must be non-negative")
    if not isinstance(ebay_category_id, str) or not ebay_category_id.isdigit():
        raise ValueError("ebay_category_id must contain digits only")

    active: dict[str, Callable[..., Mapping[str, Any]]] = {
        DISCOVERY_COLLECTOR: collect_ebay_sold_candidates,
        AMAZON_SEARCH_COLLECTOR: collect_amazon_search,
        SUPPLY_COLLECTOR: collect_1688_supply,
        SUPPLIER_PREFILTER_COLLECTOR: collect_1688_supplier,
    }
    if collectors:
        active.update(collectors)
    if not callable(active[DISCOVERY_COLLECTOR]) or not callable(active[AMAZON_SEARCH_COLLECTOR]):
        raise ValueError("discovery and amazon_search collectors must be callable")
    secret = serpapi_key if isinstance(serpapi_key, str) else ""
    budget_used = 0
    supply_checks_used = 0

    def emit_progress(
        *,
        phase: str,
        current: int,
        total: int,
        last_query: str | None = None,
        provider: str | None = None,
    ) -> None:
        if progress_callback is None:
            return
        payload = {
            "phase": phase,
            "current": max(0, current),
            "total": max(0, total),
            "last_query": last_query,
            "provider": provider,
            "budget_used": budget_used,
            "updated_at": _utc_now(),
        }
        try:
            progress_callback(payload)
        except Exception:
            # Progress is an operator aid and must never make a provider run fail.
            return

    emit_progress(
        phase="discovery",
        current=0,
        total=discovery_request_count,
        provider="serpapi-ebay-discovery",
    )
    discovery_diagnostics: list[dict[str, Any]] = []
    discovery_stats = Counter()
    raw_candidates: list[Mapping[str, Any]] = []
    pages_completed = 0
    pages_attempted = 0
    discovery_by_archetype: list[dict[str, Any]] = []
    discovery_statuses: list[str] = []
    for archetype_key in selected_archetypes:
        profile = _archetype(archetype_key)
        type_stats = Counter()
        type_pages_attempted = 0
        type_pages_completed = 0
        type_candidate_count = 0
        type_status = "SUCCESS"
        for page in range(1, discovery_pages + 1):
            type_pages_attempted += 1
            pages_attempted += 1
            budget_used += 1
            emit_progress(
                phase="discovery",
                current=pages_attempted,
                total=discovery_request_count,
                last_query=profile["discovery_keyword"],
                provider="serpapi-ebay-discovery",
            )
            outcome = active[DISCOVERY_COLLECTOR](
                api_key=secret,
                category_id=ebay_category_id,
                keyword=profile["discovery_keyword"],
                max_candidates=1000,
                page=page,
            )
            status = str(outcome.get("status") or "PARSER_FAILED")
            emit_progress(
                phase="discovery",
                current=pages_attempted,
                total=discovery_request_count,
                last_query=profile["discovery_keyword"],
                provider="serpapi-ebay-discovery",
            )
            for item in outcome.get("diagnostics", []):
                if isinstance(item, Mapping):
                    discovery_diagnostics.append(
                        {
                            "archetype": archetype_key,
                            "keyword": profile["discovery_keyword"],
                            "page": page,
                            **dict(item),
                        }
                    )
            stats = outcome.get("stats")
            if isinstance(stats, Mapping):
                for key, value in stats.items():
                    if isinstance(value, int) and not isinstance(value, bool):
                        discovery_stats[key] += value
                        type_stats[key] += value
            if status == "ZERO_RESULTS":
                type_pages_completed += 1
                pages_completed += 1
                type_status = "ZERO_RESULTS"
                break
            if status not in {"SUCCESS", "PARTIAL_SUCCESS"}:
                type_status = status
                break
            type_pages_completed += 1
            pages_completed += 1
            if status == "PARTIAL_SUCCESS":
                type_status = "PARTIAL_SUCCESS"
            candidates = outcome.get("candidates")
            if isinstance(candidates, list):
                for item in candidates:
                    if not isinstance(item, Mapping):
                        continue
                    tagged = dict(item)
                    tagged["_discovery_archetype"] = archetype_key
                    tagged["_discovery_keyword"] = profile["discovery_keyword"]
                    raw_candidates.append(tagged)
                    type_candidate_count += 1
        discovery_statuses.append(type_status)
        discovery_by_archetype.append(
            {
                "archetype": archetype_key,
                "category_profile": profile["profile"],
                "keyword": profile["discovery_keyword"],
                "status": type_status,
                "pages_attempted": type_pages_attempted,
                "pages_completed": type_pages_completed,
                "candidates_emitted": type_candidate_count,
                "stats": dict(type_stats),
            }
        )

    failed_discovery = [
        status
        for status in discovery_statuses
        if status not in {"SUCCESS", "PARTIAL_SUCCESS", "ZERO_RESULTS"}
    ]
    if failed_discovery:
        discovery_status = (
            "PARTIAL_SUCCESS"
            if len(failed_discovery) < len(discovery_statuses)
            else failed_discovery[0]
        )
    elif "PARTIAL_SUCCESS" in discovery_statuses:
        discovery_status = "PARTIAL_SUCCESS"
    elif raw_candidates:
        discovery_status = "SUCCESS"
    else:
        discovery_status = "ZERO_RESULTS"

    listing_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for index, item in enumerate(raw_candidates):
        listing_id = _clean_text(item.get("source_listing_id")) or f"missing-{index}"
        listing_groups[listing_id].append(item)

    resolved_groups: list[dict[str, Any]] = []
    for order, group in enumerate(listing_groups.values()):
        group_archetype = _matching_archetype(group, selected_archetypes)
        resolution = resolve_product_family(group, group_archetype)
        resolved_groups.append(
            {
                "order": order,
                "archetype": group_archetype,
                "resolution": resolution,
                "source_listings": [_public_candidate(group[0])],
                "candidates": [_public_candidate(item) for item in group],
            }
        )

    deduped: list[dict[str, Any]] = []
    by_identity: dict[str, dict[str, Any]] = {}
    for group in resolved_groups:
        family = group["resolution"].get("family")
        identity = (
            str(family["family_key"])
            if isinstance(family, Mapping)
            else f"listing:{group['source_listings'][0].get('source_listing_id')}"
        )
        existing = by_identity.get(identity)
        if existing is None:
            by_identity[identity] = group
            deduped.append(group)
        else:
            existing["source_listings"].extend(group["source_listings"])
            existing["candidates"].extend(group["candidates"])

    reports: list[dict[str, Any]] = []
    emit_progress(
        phase="family_resolution",
        current=len(deduped),
        total=len(deduped),
        provider=None,
    )

    explicit_prefilter = bool(collectors and SUPPLIER_PREFILTER_COLLECTOR in collectors)
    explicit_legacy_supply = bool(collectors and SUPPLY_COLLECTOR in collectors)
    local_cli_available = is_1688_cli_available()
    if explicit_prefilter:
        supplier_mode = "injected_prefilter"
    elif explicit_legacy_supply:
        supplier_mode = "injected_legacy_supply"
    elif local_cli_available:
        supplier_mode = "local_1688_cli"
    elif hiobuy_key and receiver:
        supplier_mode = "hiobuy_compatibility"
    else:
        supplier_mode = "local_1688_cli"

    def call_supplier(
        primary: str,
        family: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if supplier_mode == "injected_prefilter":
            return active[SUPPLIER_PREFILTER_COLLECTOR](
                primary,
                family=family,
                max_offers=5,
            )
        if supplier_mode in {"injected_legacy_supply", "hiobuy_compatibility"}:
            return active[SUPPLY_COLLECTOR](
                primary,
                api_key=hiobuy_key or "",
                receiver=receiver,
                max_acceptable_moq=max_supply_moq,
            )
        return active[SUPPLIER_PREFILTER_COLLECTOR](
            primary,
            family=family,
            max_offers=5,
        )

    supplier_provider_label = {
        "injected_prefilter": "1688_supplier_prefilter",
        "injected_legacy_supply": "china_supply",
        "hiobuy_compatibility": "HIOBUY_PUBLIC_REST",
        "local_1688_cli": "LOCAL_1688_CLI",
    }[supplier_mode]
    for group in deduped:
        resolution = group["resolution"]
        family = resolution.get("family")
        report_id = (
            str(family["family_key"])
            if isinstance(family, Mapping)
            else f"unresolved_{group['order'] + 1}"
        )
        scope_status = resolution.get("scope_status")
        identity_status = resolution.get("identity_status")
        stages = {
            "scope": _stage(
                "PASSED" if scope_status == "IN_SCOPE" else "REJECTED" if scope_status == "OUT_OF_SCOPE" else "REVIEW_REQUIRED",
                scope_status,
                None,
                "IN_SCOPE",
                "; ".join(resolution.get("reasons", [])),
            ),
            "identity": _stage(
                "PASSED" if identity_status == "RESOLVED" else "REVIEW_REQUIRED",
                identity_status,
                None,
                "RESOLVED",
                "Sellable product family resolved." if identity_status == "RESOLVED" else "Sellable product family needs review.",
            ),
        }
        demand_stage = _demand_stage(group["source_listings"], min_observed_ebay_demand)
        stages["demand"] = demand_stage
        evidence_gaps: list[str] = []
        failure_reasons: list[str] = []
        provider_attempts: list[dict[str, Any]] = []
        query_pack: list[dict[str, str]] = []
        competition: dict[str, Any] = {
            "competition_complete": False,
            "competitive_product_cluster_count": None,
            "competitive_asin_count": None,
            "offer_count_by_asin": {},
            "family_price_floor_usd": None,
            "aftermarket_family_price_floor_usd": None,
            "observations": [],
            "query_evidence": [],
        }
        supply_outcome: Mapping[str, Any] | None = None
        if stages["scope"]["status"] == "REJECTED":
            stages["amazon_family_competition"] = _stage(
                "NOT_RUN", None, None, None, "Out-of-scope product was not searched on Amazon."
            )
            stages["family_price_floor"] = _stage("NOT_RUN", None, None, None, "Not evaluated.")
            stages["china_non_oem_supply"] = _stage(
                "NOT_RUN", None, None, None, "Out-of-scope product was not checked on 1688."
            )
            failure_reasons.append("OUT_OF_SCOPE")
        elif not isinstance(family, Mapping):
            stages["amazon_family_competition"] = _stage(
                "REVIEW_REQUIRED", None, None, None, "Family identity is unresolved; competition was not measured."
            )
            stages["family_price_floor"] = _stage(
                "REVIEW_REQUIRED", None, "GT", float(min_family_price_usd), "Family identity is unresolved."
            )
            stages["china_non_oem_supply"] = _stage(
                "NOT_RUN", None, None, None, "Family identity is unresolved; 1688 was not checked."
            )
            evidence_gaps.append("PRODUCT_FAMILY_UNRESOLVED")
        elif stages["identity"]["status"] != "PASSED" or stages["demand"]["status"] != "PASSED":
            stages["amazon_family_competition"] = _stage(
                "NOT_RUN", None, None, None, "Local family or demand filter did not pass; Amazon was not searched."
            )
            stages["family_price_floor"] = _stage("NOT_RUN", None, None, None, "Not evaluated.")
            stages["china_non_oem_supply"] = _stage(
                "NOT_RUN", None, None, None, "Local family or demand filter did not pass; 1688 was not checked."
            )
            if stages["demand"]["status"] != "PASSED":
                evidence_gaps.append("EBAY_DEMAND_FILTER_NOT_PASSED")
        else:
            primary = _clean_text(family.get("identifiers", [{}])[0].get("raw"))
            if not primary:
                stages["china_non_oem_supply"] = _stage(
                    "REVIEW_REQUIRED", None, None, None, "No primary family identifier is available for 1688."
                )
                evidence_gaps.append("PRODUCT_FAMILY_IDENTIFIER_MISSING")
            elif supply_checks_used >= max_1688_checks:
                stages["china_non_oem_supply"] = _stage(
                    "REVIEW_REQUIRED",
                    None,
                    None,
                    None,
                    "The separate 1688 supplier-check budget was exhausted before this family.",
                )
                evidence_gaps.append("1688_CHECK_BUDGET_EXHAUSTED")
            else:
                supply_checks_used += 1
                emit_progress(
                    phase="1688_supplier",
                    current=supply_checks_used,
                    total=min(len(deduped), max_1688_checks),
                    last_query=primary,
                    provider=supplier_provider_label,
                )
                supply_outcome = call_supplier(primary, family)
                provider_attempts.append(
                    {
                        "provider": supply_outcome.get("provider", supplier_provider_label),
                        "query": supply_outcome.get("query", primary),
                        "status": supply_outcome.get("acquisition_status"),
                    }
                )
                stages["china_non_oem_supply"] = _supply_stage(supply_outcome, True)
                emit_progress(
                    phase="1688_supplier",
                    current=supply_checks_used,
                    total=min(len(deduped), max_1688_checks),
                    last_query=supply_outcome.get("query", primary),
                    provider=supply_outcome.get("provider", supplier_provider_label),
                )

            if stages["china_non_oem_supply"]["status"] == "PASSED":
                query_pack = build_amazon_query_pack(
                    family, max_queries=max_amazon_queries_per_family
                )
                query_results: list[Mapping[str, Any]] = []
                for query_index, query in enumerate(query_pack, start=1):
                    emit_progress(
                        phase="amazon",
                        current=query_index,
                        total=len(query_pack),
                        last_query=query["query"],
                        provider="serpapi-amazon",
                    )
                    if budget_used >= request_budget:
                        query_results.append(
                            {
                                "query": query["query"],
                                "acquisition_status": "REQUEST_BUDGET_EXHAUSTED",
                                "result_page_complete": False,
                                "products": [],
                                "diagnostics": [
                                    {
                                        "code": "REQUEST_BUDGET_EXHAUSTED",
                                        "message": "Run request budget was exhausted before this query.",
                                    }
                                ],
                            }
                        )
                        evidence_gaps.append("REQUEST_BUDGET_EXHAUSTED")
                        continue
                    budget_used += 1
                    outcome = active[AMAZON_SEARCH_COLLECTOR](
                        query["query"], api_key=secret
                    )
                    query_results.append(outcome)
                    provider_attempts.append(
                        {
                            "provider": outcome.get("provider", "amazon_search"),
                            "query": query["query"],
                            "status": outcome.get("acquisition_status"),
                        }
                    )
                competition = aggregate_amazon_family_results(
                    family,
                    query_results,
                    max_competitive_products=max_competitive_products,
                    min_family_price_usd=float(min_family_price_usd),
                )
                stages["amazon_family_competition"] = competition["competition_stage"]
                stages["family_price_floor"] = competition["price_stage"]
                if not competition["competition_complete"]:
                    evidence_gaps.append("AMAZON_FAMILY_SEARCH_INCOMPLETE")
            else:
                stages["amazon_family_competition"] = _stage(
                    "NOT_RUN", None, None, None, "1688 supplier prefilter did not pass; Amazon was not searched."
                )
                stages["family_price_floor"] = _stage("NOT_RUN", None, None, None, "Not evaluated.")
        supply_stage = stages["china_non_oem_supply"]
        if supply_stage["status"] != "PASSED":
            evidence_gaps.append("CHINA_NON_OEM_SUPPLY_UNVERIFIED")
        for name, stage in stages.items():
            if stage.get("status") == "REJECTED":
                failure_reasons.append(name.upper())
        decision = _report_decision(stages)
        reports.append(
            {
                "schema_version": "0.2.4",
                "profile": "northway-product-family-mvp",
                "candidate_id": report_id,
                "discovery_order": group["order"],
                "decision": decision,
                "rank": None,
                "category_profile": resolution.get("category_profile"),
                "archetype": group["archetype"],
                "source_listings": group["source_listings"],
                "resolution": resolution,
                "family": family,
                "query_pack": query_pack,
                "competition": competition,
                "demand": {
                    "observed_sold_count_lower_bound": demand_stage["value"],
                    "source_listing_count": len(group["source_listings"]),
                    "complete_365_day_metric": False,
                },
                "supply": dict(supply_outcome) if supply_outcome is not None else None,
                "stages": stages,
                "evidence_gaps": sorted(set(evidence_gaps)),
                "failure_reasons": sorted(set(failure_reasons)),
                "provider_attempts": provider_attempts,
            }
        )
        emit_progress(
            phase="family_screening",
            current=len(reports),
            total=len(deduped),
            provider=supplier_provider_label,
        )

    reports.sort(key=_rank_key)
    for rank, report in enumerate(reports, start=1):
        report["rank"] = rank
    counts = Counter(report["decision"] for report in reports)
    supply_statuses = Counter(
        report.get("stages", {}).get("china_non_oem_supply", {}).get("status")
        for report in reports
    )
    supply_filter = {
        "provider": supplier_provider_label,
        "checked": supply_checks_used,
        "supplier_found": supply_statuses["PASSED"],
        "no_supplier": supply_statuses["REJECTED"],
        "review_required": supply_statuses["REVIEW_REQUIRED"],
        "not_run": supply_statuses["NOT_RUN"],
    }
    generated_at = _utc_now()
    run_id = hashlib.sha256(
        f"{','.join(selected_archetypes)}:{generated_at}:{len(reports)}".encode("utf-8")
    ).hexdigest()[:16]
    emit_progress(
        phase="completed",
        current=len(reports),
        total=len(deduped),
        provider=None,
    )
    return {
        "schema_version": "0.2.4",
        "profile": "northway-product-family-mvp",
        "result_id": f"result_{run_id}",
        "generated_at": generated_at,
        "policy": {
            "archetypes": selected_archetypes,
            "category_profiles": sorted(
                {_archetype(key)["profile"] for key in selected_archetypes}
            ),
            "max_competitive_products": max_competitive_products,
            "min_family_price_usd": float(min_family_price_usd),
            "min_observed_ebay_demand": min_observed_ebay_demand,
            "max_1688_checks": max_1688_checks,
            "max_amazon_queries_per_family": max_amazon_queries_per_family,
            "competition_upper_bound": None,
        },
        "scan_manifest": {
            "marketplace": "EBAY_US",
            "category_id": ebay_category_id,
            "archetypes": selected_archetypes,
            "discovery_queries": [
                {
                    "archetype": key,
                    "category_profile": _archetype(key)["profile"],
                    "keyword": _archetype(key)["discovery_keyword"],
                }
                for key in selected_archetypes
            ],
            "pages_requested": discovery_pages,
            "pages_attempted": pages_attempted,
            "pages_completed": pages_completed,
            "candidate_cap": None,
            "selected_archetype": selected_archetypes[0]
            if len(selected_archetypes) == 1
            else None,
        },
        "request_budget": {
            "limit": request_budget,
            "used": budget_used,
            "remaining": max(0, request_budget - budget_used),
        },
        "provider_budgets": {
            "serpapi": {
                "limit": request_budget,
                "used": budget_used,
                "remaining": max(0, request_budget - budget_used),
            },
            "1688": {
                "limit": max_1688_checks,
                "used": supply_checks_used,
                "remaining": max(0, max_1688_checks - supply_checks_used),
            },
        },
        "discovery": {
            "status": discovery_status,
            "listing_groups": len(listing_groups),
            "resolved_family_count": sum(
                isinstance(group["resolution"].get("family"), Mapping)
                for group in deduped
            ),
            "deduplicated_candidate_count": len(deduped),
            "stats": dict(discovery_stats),
            "diagnostics": discovery_diagnostics,
            "per_archetype": discovery_by_archetype,
        },
        "summary": {
            "candidate_count": len(reports),
            "opportunity_candidates": counts["OPPORTUNITY_CANDIDATE"],
            "market_shortlist_candidates": counts["MARKET_SHORTLIST_CANDIDATE"],
            "review_required": counts["REVIEW_REQUIRED"],
            "rejected": counts["REJECTED"],
        },
        "supply_filter": supply_filter,
        "ranking": [report["candidate_id"] for report in reports],
        "reports": reports,
    }


__all__ = [
    "AMAZON_SEARCH_COLLECTOR",
    "ARCHETYPES",
    "DISCOVERY_COLLECTOR",
    "SUPPLY_COLLECTOR",
    "SUPPLIER_PREFILTER_COLLECTOR",
    "aggregate_amazon_family_results",
    "build_amazon_query_pack",
    "classify_scope",
    "compact_northway_result",
    "northway_mvp_policy",
    "resolve_product_family",
    "run_northway_mvp",
]
