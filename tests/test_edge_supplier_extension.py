from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from proteus.api import DefaultFrontendService
from proteus.category_catalog import CategoryCatalog
from proteus.supplier_capture import supplier_collector_profile
from proteus.supplier_scout import SupplierScoutStore


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "browser-extension" / "supplier-collector"


def test_edge_extension_manifest_has_only_narrow_read_capture_permissions() -> None:
    manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["manifest_version"] == 3
    assert set(manifest["permissions"]) == {"activeTab", "storage"}
    assert set(manifest["host_permissions"]) == {
        "https://*.1688.com/*",
        "http://127.0.0.1:8765/*",
    }
    assert not ({"cookies", "debugger", "proxy", "webRequest"} & set(manifest["permissions"]))
    assert "content_security_policy" not in manifest
    for script in manifest["content_scripts"][0]["js"]:
        assert (EXTENSION / script).is_file()
    assert (EXTENSION / manifest["background"]["service_worker"]).is_file()
    assert (EXTENSION / manifest["action"]["default_popup"]).is_file()


def test_packaged_selector_profile_is_non_executable_and_bounded() -> None:
    profile = supplier_collector_profile()

    assert profile["schema_version"] == "1"
    assert profile["offer_link_selectors"]
    assert profile["next_page_selectors"]
    assert profile["scroll"]["max_rounds"] <= 20
    assert all(isinstance(value, str) for value in profile["risk_text"])
    assert not any("javascript:" in value.lower() for value in profile["offer_link_selectors"])


def test_policy_exposes_json_import_as_the_primary_supplier_source(tmp_path: Path) -> None:
    service = DefaultFrontendService(
        category_catalog=CategoryCatalog(tmp_path / "categories.sqlite3"),
        supplier_store=SupplierScoutStore(tmp_path / "supplier-scout.sqlite3"),
    )

    policy = service.supplier_scout_policy()

    import_policy = policy["inventory_import"]
    assert import_policy["format"] == "proteus.supplier_inventory"
    assert import_policy["version"] == 1
    assert import_policy["max_document_bytes"] == 10 * 1024 * 1024
    assert import_policy["max_offers"] == 1000
    assert "edge_collector" not in policy


def test_supplier_scout_frontend_uses_json_snapshot_instead_of_edge_capture() -> None:
    html = (ROOT / "web" / "supplier-scout.html").read_text(encoding="utf-8")
    javascript = (ROOT / "web" / "supplier-scout.js").read_text(encoding="utf-8")

    assert 'id="importInventoryButton"' in html
    assert "examples/supplier_inventory_import.example.json" in html
    assert "browser-extension/supplier-collector" not in html
    assert 'id="headed"' not in html
    assert "inventory_snapshot_id: activeSnapshotId" in javascript
    assert "#headed" not in javascript
    assert "createCapture" not in javascript
    assert "snapshots/import" in javascript
    assert "已导入" in javascript


def test_supplier_collector_core_node_contract() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed")

    completed = subprocess.run(
        [node, "--test", str(ROOT / "tests" / "js" / "test_supplier_collector_core.mjs")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_supplier_collector_popup_node_contract() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed")

    completed = subprocess.run(
        [node, "--test", str(ROOT / "tests" / "js" / "test_supplier_popup.mjs")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_supplier_collector_core_in_a_real_browser_dom() -> None:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    profile = supplier_collector_profile()
    html = """
    <!doctype html><html><body>
      <p>共 2 件商品</p>
      <div class="offer-card" data-offer-id="10001">
        <a title="丰田雾灯框 81482-0R010"
           href="https://detail.1688.com/offer/10001.html?spm=test">
          <img alt="雾灯框" src="https://cbu01.alicdn.com/10001.jpg">
        </a>
        <span class="price">¥ 12.50</span><span>5 件起批</span>
      </div>
      <nav class="pagination"><a rel="next" href="?pageNum=2">下一页</a></nav>
    </body></html>
    """

    with sync_playwright() as playwright:
        browser = None
        for channel in ("msedge", None):
            try:
                browser = playwright.chromium.launch(channel=channel, headless=True)
                break
            except PlaywrightError:
                continue
        if browser is None:
            pytest.skip("No Playwright Chromium or Microsoft Edge executable is installed")
        try:
            page = browser.new_page()
            page.set_content(html)
            page.add_script_tag(path=EXTENSION / "collector-core.js")
            result = page.evaluate(
                """profile => ({
                  offers: globalThis.Proteus1688CollectorCore.extractOffers(document, profile, location.href),
                  available: globalThis.Proteus1688CollectorCore.availableOfferCount(document),
                  hasNext: globalThis.Proteus1688CollectorCore.paginationState(document, profile).has_next_page
                })""",
                profile,
            )
            page.set_content("<p>请拖动滑块完成安全验证</p>")
            page.add_script_tag(path=EXTENSION / "collector-core.js")
            blocked = page.evaluate(
                "profile => globalThis.Proteus1688CollectorCore.detectBlock(document, location.href, profile)",
                profile,
            )
            page.set_content(
                '<div class="captcha" style="display:none">拖动滑块</div><p>普通商品列表</p>'
            )
            page.add_script_tag(path=EXTENSION / "collector-core.js")
            hidden_block = page.evaluate(
                "profile => globalThis.Proteus1688CollectorCore.detectBlock(document, location.href, profile)",
                profile,
            )
            page.set_content(
                """
                <div class="modern-item" data-offer-id="90001"
                     data-href="/offer/90001.html" data-title="现代店铺商品 90001">
                  <img alt="现代店铺商品 90001" src="https://cbu01.alicdn.com/90001.jpg">
                </div>
                    <div class="query-item" data-href="/item/view.htm?offerId=90002"
                         data-title="查询参数商品 90002"></div>
                    <a href="https://example.com/private?token=must-not-leak">外站</a>
                    <a href="https://shop.example.1688.com/page/category.htm">分类</a>
                    <div class="wp-paging-unit"><button class="next-page">下一页</button></div>
                <iframe src="https://show.1688.com/page/offers.html?token=must-not-leak"></iframe>
                """
            )
            page.add_script_tag(path=EXTENSION / "collector-core.js")
            fallback = page.evaluate(
                """profile => ({
                  offers: globalThis.Proteus1688CollectorCore.extractOffers(document, profile, "https://shop.example.1688.com/page/offerlist.htm"),
                  pagination: globalThis.Proteus1688CollectorCore.paginationState(document, profile).has_next_page,
                  probe: globalThis.Proteus1688CollectorCore.parserProbe(document, profile, "https://shop.example.1688.com/page/offerlist.htm")
                })""",
                profile,
            )
            page.set_content(
                """
                <div id="shadow-host" class="product-shell"></div>
                <script>
                  const host = document.querySelector("#shadow-host");
                  const root = host.attachShadow({ mode: "open" });
                  root.innerHTML = '<a href="https://detail.1688.com/offer/91001.html">Shadow 商品 91001</a>';
                </script>
                """
            )
            page.add_script_tag(path=EXTENSION / "collector-core.js")
            shadow_probe = page.evaluate(
                """profile => globalThis.Proteus1688CollectorCore.parserProbe(
                  document, profile, "https://shop.example.1688.com/page/offerlist.htm"
                )""",
                profile,
            )
        finally:
            browser.close()

    assert result["offers"] == [
        {
            "offer_id": "10001",
            "title": "丰田雾灯框 81482-0R010",
            "offer_url": "https://detail.1688.com/offer/10001.html",
            "image_url": "https://cbu01.alicdn.com/10001.jpg",
            "price_cny": 12.5,
            "moq": 5,
        }
    ]
    assert result["available"] == 2
    assert result["hasNext"] is True
    assert blocked == "RISK_CONTROL"
    assert hidden_block is None
    assert fallback["offers"] == [
        {
            "offer_id": "90001",
            "title": "现代店铺商品 90001",
            "offer_url": "https://detail.1688.com/offer/90001.html",
            "image_url": "https://cbu01.alicdn.com/90001.jpg",
        },
        {
            "offer_id": "90002",
            "title": "查询参数商品 90002",
            "offer_url": "https://detail.1688.com/offer/90002.html",
        },
    ]
    assert fallback["pagination"] is True
    assert fallback["probe"]["configured_offer_match_count"] == 1
    assert fallback["probe"]["offer_candidates"][0]["data_offer_id"] == "90001"
    assert fallback["probe"]["link_candidates"] == [
        {
            "tag": "a",
            "url": "https://shop.example.1688.com/page/category.htm",
            "text": "分类",
        }
    ]
    assert fallback["probe"]["iframe_hints"][0]["host_class"] == "1688"
    assert fallback["probe"]["iframe_hints"][0]["same_origin_accessible"] is False
    assert fallback["probe"]["iframe_hints"][0]["url"] == "https://show.1688.com/page/offers.html"
    assert fallback["probe"]["document_ready_state"] == "complete"
    assert fallback["probe"]["body_text_length"] > 0
    assert fallback["probe"]["resource_count"] >= fallback["probe"]["offerish_resource_count"] >= 0
    assert fallback["probe"]["apiish_resource_count"] >= 0
    assert "data-href" in fallback["probe"]["light_dom_data_attribute_names"]
    assert "token=" not in json.dumps(fallback["probe"], ensure_ascii=False)
    assert "example.com" not in json.dumps(fallback["probe"], ensure_ascii=False)
    assert shadow_probe["shadow_host_count"] == 1
    assert shadow_probe["shadow_root_hints"] == [
        {
            "tag": "div",
            "class_name": "product-shell",
            "child_count": 1,
            "anchor_count": 1,
            "configured_offer_match_count": 1,
            "offer_candidate_count": 1,
            "nested_shadow_host_count": 0,
            "text_length": 15,
        }
    ]
    assert shadow_probe["link_candidates"] == []
    assert shadow_probe["light_dom_identity_markers"] == []
    assert shadow_probe["light_dom_structure_hints"] == [
        {
            "tag": "div",
            "id_name": "shadow-host",
            "class_name": "product-shell",
            "child_count": 0,
            "anchor_count": 0,
            "image_count": 0,
            "visible": True,
            "identity_attribute_names": [],
            "text_length": 0,
        }
    ]
