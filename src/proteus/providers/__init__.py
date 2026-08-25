"""Managed REST acquisition providers for Proteus."""

from proteus.providers.hiobuy import (
    HIOBUY_PROVIDER,
    ORDER_PREVIEW_ENDPOINT,
    PRODUCT_DETAIL_ENDPOINT,
    PRODUCT_SEARCH_ENDPOINT,
    HioBuyRequest,
    HioBuyResponse,
    collect_1688_supply,
)

from proteus.providers.nexscope import (
    AMAZON_SEARCH_ENDPOINT,
    EBAY_SEARCH_ENDPOINT,
    NEXSCOPE_PROVIDER,
    SOURCE_METHOD,
    SUPPLY_1688_SEARCH_ENDPOINT,
    RestRequest,
    RestResponse,
    Transport,
    collect_1688_search,
    collect_amazon_search,
    collect_ebay_search,
)

__all__ = [
    "AMAZON_SEARCH_ENDPOINT",
    "EBAY_SEARCH_ENDPOINT",
    "NEXSCOPE_PROVIDER",
    "SOURCE_METHOD",
    "SUPPLY_1688_SEARCH_ENDPOINT",
    "RestRequest",
    "RestResponse",
    "Transport",
    "collect_1688_search",
    "collect_amazon_search",
    "collect_ebay_search",
    "HIOBUY_PROVIDER",
    "ORDER_PREVIEW_ENDPOINT",
    "PRODUCT_DETAIL_ENDPOINT",
    "PRODUCT_SEARCH_ENDPOINT",
    "HioBuyRequest",
    "HioBuyResponse",
    "collect_1688_supply",
]
