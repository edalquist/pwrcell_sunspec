"""End-to-end Playwright browser tests for Desktop, Tablet, and Mobile Web Explorer UI."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from werkzeug.serving import make_server

from pwrcell import mapping as mapping_module
from pwrcell.client import PwrcellClient
from pwrcell.state import FieldSource
from pwrcell.ui.server import create_app

try:
    from playwright.sync_api import sync_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    sync_playwright = None  # type: ignore[assignment]
    PLAYWRIGHT_AVAILABLE = False

REQUIRE_BROWSER_TESTS = os.environ.get("PWRCELL_REQUIRE_BROWSER_TESTS") == "1"

DESKTOP_WIDE = {"width": 1440, "height": 900}
DESKTOP_COMPACT = {"width": 1280, "height": 800}
TABLET_PORTRAIT = {"width": 768, "height": 1024}
MOBILE_IPHONE = {"width": 390, "height": 844}
MOBILE_COMPACT = {"width": 360, "height": 680}

INVERTER_SN = "000100070008"
BATTERY_SN = "000100080009"
PV_LINK_SN = "000100030003"
BEACON_SN = "000100120001"


@unittest.skipUnless(
    PLAYWRIGHT_AVAILABLE or REQUIRE_BROWSER_TESTS,
    "Playwright not installed (install requirements-dev.txt)",
)
class TestWebExplorerBrowserUI(unittest.TestCase):
    """Real Chromium UI tests verifying desktop, tablet, and mobile responsiveness."""

    @classmethod
    def setUpClass(cls):
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError(
                "PWRCELL_REQUIRE_BROWSER_TESTS=1 is set, but playwright is not installed."
            )

        cls._tmp_dir = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp_dir.name)
        real_mappings = mapping_module._resolve_mappings_path()
        tmp_mappings = tmp / "telemetry_mappings.yaml"
        if real_mappings.exists():
            shutil.copy(real_mappings, tmp_mappings)

        cls._patches = [
            mock.patch("pwrcell.ha.get_default_ha_config_path", return_value=tmp / "ha_config.yaml"),
            mock.patch("pwrcell.bridge.get_default_ha_config_path", return_value=tmp / "ha_config.yaml"),
            mock.patch("pwrcell.bridge.get_default_published_topics_path", return_value=tmp / ".ha_published_topics.json"),
            mock.patch("pwrcell.grouping.get_default_grouping_config_path", return_value=tmp / "custom_groupings.yaml"),
            mock.patch("pwrcell.mapping._resolve_mappings_path", return_value=tmp_mappings),
        ]
        for p in cls._patches:
            p.start()
        mapping_module.MappingRegistry._instance = None

        cls.client = PwrcellClient(is_mock=True)
        cls.client.start()
        cls.app = create_app(cls.client)

        cls.server = make_server("127.0.0.1", 0, cls.app, threaded=True)
        cls.server.daemon_threads = True
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls._server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls._server_thread.start()

        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        # Close browser and Playwright first so open SSE /api/stream connections terminate promptly.
        if getattr(cls, "browser", None) is not None:
            try:
                cls.browser.close()
            except Exception:
                pass
        if getattr(cls, "pw", None) is not None:
            try:
                cls.pw.stop()
            except Exception:
                pass
        if getattr(cls, "server", None) is not None:
            try:
                cls.server.shutdown()
                cls.server.server_close()
            except Exception:
                pass
        if getattr(cls, "client", None) is not None:
            try:
                cls.client.stop()
            except Exception:
                pass
        for p in reversed(getattr(cls, "_patches", [])):
            p.stop()
        mapping_module.MappingRegistry._instance = None
        if getattr(cls, "_tmp_dir", None) is not None:
            cls._tmp_dir.cleanup()

    def _new_page(self, viewport: dict, is_mobile: bool = False, has_touch: bool = False):
        """Create an isolated browser context/page with external URLs aborted and console/error tracking."""
        context = self.browser.new_context(
            viewport=viewport,
            is_mobile=is_mobile,
            has_touch=has_touch,
        )
        page = context.new_page()
        page_errors: list[str] = []
        console_errors: list[str] = []

        def _abort_external(route):
            route.abort()

        page.route(re.compile(r"^https?://(?!127\.0\.0\.1|localhost)"), _abort_external)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))

        def _on_console(msg):
            if msg.type == "error":
                text = msg.text or ""
                if "ERR_FAILED" in text and "fonts.googleapis.com" in text:
                    return
                if "net::ERR_FAILED" in text and "127.0.0.1" not in text:
                    return
                console_errors.append(text)

        page.on("console", _on_console)

        def _cleanup():
            try:
                page.close()
            finally:
                context.close()

        self.addCleanup(_cleanup)
        return page, page_errors, console_errors

    def _assert_clean_errors(self, page_errors: list[str], console_errors: list[str]):
        self.assertEqual(page_errors, [], f"Unexpected uncaught page errors: {page_errors}")
        self.assertEqual(console_errors, [], f"Unexpected console errors: {console_errors}")

    def _goto_and_wait_ready(self, page):
        page.goto(self.base_url, wait_until="domcontentloaded")
        page.wait_for_function(
            "() => document.querySelectorAll('#deviceList .device-card').length === 9"
        )
        page.wait_for_selector("#fieldTableBody tr .ha-checkbox", state="attached")
        page.wait_for_timeout(150)

    def _select_device_by_sn(self, page, sn: str, expect_drawer_auto_close: bool = False):
        card = page.locator(f'#deviceList .device-card[data-sn="{sn}"]')
        card.wait_for(state="visible")
        # Clear existing table rows watch via fetch completion + serial header + rendered checkbox rows
        with page.expect_response(
            lambda resp: f"/api/devices/{sn}" in resp.url and resp.request.method == "GET" and resp.status == 200
        ):
            card.click()
        page.wait_for_function(
            "(expectedSn) => document.getElementById('activeDeviceSerial')?.textContent?.trim() === expectedSn",
            arg=sn,
        )
        page.wait_for_selector("#fieldTableBody tr .ha-checkbox", state="attached")
        if expect_drawer_auto_close:
            page.wait_for_function(
                "() => !document.getElementById('deviceSidebar')?.classList.contains('open')"
            )
        page.wait_for_timeout(100)

    def _assert_no_horizontal_overflow(self, page, label: str = ""):
        metrics = page.evaluate(
            """() => ({
                innerWidth: window.innerWidth,
                docScrollWidth: document.documentElement.scrollWidth,
                bodyScrollWidth: document.body.scrollWidth,
            })"""
        )
        vw = metrics["innerWidth"]
        self.assertLessEqual(
            metrics["docScrollWidth"],
            vw + 1,
            f"[{label}] documentElement.scrollWidth ({metrics['docScrollWidth']}) > innerWidth ({vw})",
        )
        self.assertLessEqual(
            metrics["bodyScrollWidth"],
            vw + 1,
            f"[{label}] body.scrollWidth ({metrics['bodyScrollWidth']}) > innerWidth ({vw})",
        )

        for selector in [".app-header", ".device-banner", ".toolbar", ".app-footer"]:
            loc = page.locator(selector)
            if loc.count() > 0 and loc.first.is_visible():
                self._assert_within_viewport_horizontally(page, loc.first, f"{label}:{selector}")

        open_modals = page.locator(".modal-backdrop.open .modal")
        for idx in range(open_modals.count()):
            m = open_modals.nth(idx)
            if m.is_visible():
                self._assert_within_viewport_horizontally(page, m, f"{label}:open-modal-{idx}")

    def _assert_within_viewport_horizontally(self, page, locator, label: str = ""):
        vw = page.evaluate("() => window.innerWidth")
        box = locator.bounding_box()
        self.assertIsNotNone(box, f"[{label}] expected visible bounding box")
        assert box is not None
        self.assertGreaterEqual(
            box["x"],
            -1.0,
            f"[{label}] element starts left of viewport: x={box['x']}",
        )
        self.assertLessEqual(
            box["x"] + box["width"],
            vw + 1.0,
            f"[{label}] element overflows right edge: x+w={box['x'] + box['width']} > vw={vw}",
        )

    def _assert_modal_fits_and_close(self, page, modal_id: str, close_selector: str, label: str):
        modal = page.locator(f"#{modal_id}.modal-backdrop.open .modal")
        modal.wait_for(state="visible")
        page.wait_for_timeout(100)
        self._assert_no_horizontal_overflow(page, f"{label}:{modal_id}")
        self._assert_within_viewport_horizontally(page, modal, f"{label}:{modal_id}-dialog")
        vh = page.evaluate("() => window.innerHeight")
        box = modal.bounding_box()
        self.assertIsNotNone(box)
        assert box is not None
        self.assertLessEqual(box["height"], vh + 1.0, f"[{label}:{modal_id}] taller than viewport")

        close_btn = page.locator(f"#{modal_id} {close_selector}").first
        self.assertTrue(close_btn.is_visible(), f"[{label}:{modal_id}] close button not visible")
        self._assert_within_viewport_horizontally(page, close_btn, f"{label}:{modal_id}-close")
        close_btn.click()
        page.locator(f"#{modal_id}.modal-backdrop.open").wait_for(state="detached")

    # ------------------------------------------------------------------
    # Desktop Tests (1440x900 & 1280x800)
    # ------------------------------------------------------------------

    def test_desktop_initial_layout_and_no_overflow(self):
        for label, vp in [("desktop-1440", DESKTOP_WIDE), ("desktop-1280", DESKTOP_COMPACT)]:
            with self.subTest(viewport=label):
                page, page_errors, console_errors = self._new_page(vp)
                self._goto_and_wait_ready(page)

                self._assert_no_horizontal_overflow(page, label)
                self.assertTrue(page.locator("#deviceSidebar").is_visible())
                self.assertEqual(page.locator("#deviceList .device-card").count(), 9)
                self.assertTrue(page.locator("main.main-content .field-table thead").is_visible())

                for sel in [
                    "#topSolar",
                    "#topLoad",
                    "#topGrid",
                    "#topBattery",
                    "#modeSelect",
                    "#btnOpenCompare",
                    "#btnOpenBlockedSafety",
                    "#btnSyncModbus",
                    "#liveIndicator",
                    "#btnPreviewHA",
                    "#btnExportHADefaults",
                    "#btnCleanHA",
                    "#btnResetHA",
                    "#btnSaveHA",
                ]:
                    self.assertTrue(page.locator(sel).is_visible(), f"[{label}] missing {sel}")

                for mob_sel in [
                    "#btnMobileDevices",
                    "#btnMobileHeaderMenu",
                    "#btnMobileFooterMenu",
                    "#btnToggleMobileFilters",
                    "#mobileSortSelect",
                ]:
                    self.assertFalse(page.locator(mob_sel).is_visible(), f"[{label}] mobile control {mob_sel} visible")

                if label == "desktop-1440":
                    first_more = page.locator("#fieldTableBody .btn-icon-more").first
                    self._assert_within_viewport_horizontally(page, first_more, f"{label}:first-more-btn")

                self._assert_clean_errors(page_errors, console_errors)

    def test_desktop_device_switch_view_modes_and_expanders(self):
        page, page_errors, console_errors = self._new_page(DESKTOP_WIDE)
        self._goto_and_wait_ready(page)

        # Switch through Inverter -> Battery -> PV Link -> Beacon
        self._select_device_by_sn(page, INVERTER_SN)
        self.assertFalse(page.locator("#btnApplySameType").is_visible())

        # Expand a multi-source unified row on Inverter
        expand_btn = page.locator("#fieldTableBody .btn-group-expand").first
        expand_btn.click()
        page.locator("#fieldTableBody tr.group-children-row").first.wait_for(state="visible")
        self._assert_no_horizontal_overflow(page, "desktop-inverter-expanded")

        # Switch to Battery and expand a repeating sub-group rollup row
        self._select_device_by_sn(page, BATTERY_SN)
        rollup_expand = page.locator("#fieldTableBody .btn-rollup-expand").first
        rollup_expand.click()
        page.locator("#fieldTableBody tr.rollup-children-row").first.wait_for(state="visible")
        self._assert_no_horizontal_overflow(page, "desktop-battery-rollup-expanded")

        # Switch to PV Link: Apply to All becomes visible
        self._select_device_by_sn(page, PV_LINK_SN)
        self.assertTrue(page.locator("#btnApplySameType").is_visible())

        # Switch to Beacon & toggle Unified <-> All Registers
        self._select_device_by_sn(page, BEACON_SN)
        self.assertIn("sources", page.locator("#thModelContent").inner_text().lower())
        page.locator('.view-mode-btn[data-mode="raw"]').click()
        self.assertIn("model", page.locator("#thModelContent").inner_text().lower())
        page.locator('.view-mode-btn[data-mode="unified"]').click()
        self.assertIn("sources", page.locator("#thModelContent").inner_text().lower())

        self._assert_no_horizontal_overflow(page, "desktop-view-modes")
        self._assert_clean_errors(page_errors, console_errors)

    def test_desktop_search_filters_sorting_and_ha_save(self):
        page, page_errors, console_errors = self._new_page(DESKTOP_WIDE)
        self._goto_and_wait_ready(page)
        self._select_device_by_sn(page, INVERTER_SN)

        # Search and clear
        page.locator("#searchInput").fill("grid")
        self.assertTrue(page.locator("#searchClear").is_visible())
        filtered_count = page.locator("#fieldTableBody tr.unified-row").count()
        self.assertGreater(filtered_count, 0)
        page.locator("#searchClear").click()
        self.assertFalse(page.locator("#searchClear").is_visible())

        # Filter pills
        page.locator('.filter-pills .pill[data-filter="writable"]').click()
        self.assertGreater(page.locator("#fieldTableBody tr").count(), 0)
        page.locator('.filter-pills .pill[data-filter="selected"]').click()
        page.locator('.filter-pills .pill[data-filter="all"]').click()

        # Switch to raw mode and toggle Group by Model + Model filter
        page.locator('.view-mode-btn[data-mode="raw"]').click()
        page.locator("#groupByModel").check()
        self.assertGreater(page.locator("#fieldTableBody tr.model-group-row").count(), 0)
        model_val = page.evaluate(
            """() => {
                const opts = Array.from(document.querySelectorAll('#modelSelect option'));
                const m = opts.find(o => /^\\d+$/.test(o.value));
                return m ? m.value : 'all';
            }"""
        )
        page.locator("#modelSelect").select_option(model_val)
        page.locator("#modelSelect").select_option("all")
        page.locator("#groupByModel").uncheck()
        page.locator('.view-mode-btn[data-mode="unified"]').click()

        # Column header click sorting & clear
        page.locator('.field-table thead th.sortable[data-sort="name"]').click()
        self.assertTrue(page.locator("#sortBar").is_visible())
        page.locator("#btnClearSort").click()
        self.assertFalse(page.locator("#sortBar").is_visible())

        # Toggle HA checkbox and save
        before_count = int(page.locator("#haSelectedCount").inner_text().strip())
        first_chk = page.locator("#fieldTableBody .ha-checkbox").first
        first_chk.click()
        after_count = int(page.locator("#haSelectedCount").inner_text().strip())
        self.assertNotEqual(before_count, after_count)
        page.locator("#btnSaveHA").click()
        page.locator("#toast.show").wait_for(state="visible")

        self._assert_no_horizontal_overflow(page, "desktop-filters-save")
        self._assert_clean_errors(page_errors, console_errors)

    def test_desktop_all_modals_and_action_menu(self):
        page, page_errors, console_errors = self._new_page(DESKTOP_WIDE)
        self._goto_and_wait_ready(page)
        self._select_device_by_sn(page, INVERTER_SN)

        # 1. Modbus Details
        page.locator("#fieldTableBody .btn-details").first.click()
        page.wait_for_function(
            "() => !document.getElementById('detailsModalBody')?.textContent?.includes('Loading Modbus details')"
        )
        self._assert_modal_fits_and_close(page, "modbusDetailsModal", "#btnCloseDetailsModal", "desktop")

        # 2. Write Modal (filter writable to guarantee .btn-edit)
        page.locator('.filter-pills .pill[data-filter="writable"]').click()
        page.locator("#fieldTableBody .btn-edit").first.click()
        self._assert_modal_fits_and_close(page, "writeModal", "#btnCancelWrite", "desktop")

        # 3. Bounds Modal via row More menu on writable row
        writable_row = page.locator("#fieldTableBody tr.unified-row", has=page.locator(".btn-edit")).first
        writable_row.locator(".btn-icon-more").click()
        writable_row.locator(".action-dropdown-menu.show .item-bounds").click()
        self._assert_modal_fits_and_close(page, "boundsModal", "#btnCloseBoundsModal", "desktop")

        # 4. Grouping Modal via row More menu
        page.locator('.filter-pills .pill[data-filter="all"]').click()
        groupable_row = page.locator("#fieldTableBody tr.unified-row", has=page.locator(".item-group-with")).first
        groupable_row.locator(".btn-icon-more").click()
        groupable_row.locator(".action-dropdown-menu.show .item-group-with").click()
        self._assert_modal_fits_and_close(page, "groupingModal", "#btnCloseGroupingModal", "desktop")

        # 5. Compare Telemetry + tabs + Export Mappings modal
        page.locator("#btnOpenCompare").click()
        page.locator("#compareModal.modal-backdrop.open").wait_for(state="visible")
        page.locator("#tabCmpAll").click()
        page.wait_for_selector("#compareTableBody tr.compare-row", state="visible")
        self._assert_no_horizontal_overflow(page, "desktop-compare-all")
        page.locator("#btnOpenExportMappings").click()
        self._assert_modal_fits_and_close(page, "exportMappingsModal", "#btnCloseExportModal", "desktop")
        self._assert_modal_fits_and_close(page, "compareModal", "#btnCloseCompare", "desktop")

        # 6. Safety Policy
        page.locator("#btnOpenBlockedSafety").click()
        self._assert_modal_fits_and_close(page, "blockedSafetyModal", "#btnCloseSafetyModal", "desktop")

        # 7. Re-scan Devices
        page.locator("#btnOpenRescan").click()
        self._assert_modal_fits_and_close(page, "rescanModal", "#btnCloseRescanModal", "desktop")

        # 8. Preview HA
        page.locator("#btnPreviewHA").click()
        self._assert_modal_fits_and_close(page, "previewModal", "#btnCloseModal", "desktop")

        # 9. Export HA Defaults
        page.locator("#btnExportHADefaults").click()
        self._assert_modal_fits_and_close(page, "exportHADefaultsModal", "#btnCloseExportHAModal", "desktop")

        self._assert_clean_errors(page_errors, console_errors)

    def test_desktop_sse_live_update(self):
        page, page_errors, console_errors = self._new_page(DESKTOP_WIDE)
        self._goto_and_wait_ready(page)
        self._select_device_by_sn(page, INVERTER_SN)
        page.wait_for_function(
            "() => document.getElementById('connStatusText')?.textContent?.trim() === 'Live Feed'"
        )

        # Push a deterministic live field change through StateStore -> SSE -> UI
        self.client.state.set_field(
            device_sn=INVERTER_SN,
            name="solar_power_w",
            label="Solar Power",
            description="Live solar generation",
            value=4321,
            raw_value=4321,
            units="W",
            source=FieldSource.MQTT_PUSH,
            sub_group="live",
        )
        page.wait_for_function(
            "() => document.getElementById('topSolar')?.textContent?.includes('4321 W')"
        )
        self._assert_clean_errors(page_errors, console_errors)

    # ------------------------------------------------------------------
    # Mobile Tests (390x844 & 360x680)
    # ------------------------------------------------------------------

    def test_mobile_initial_layout_and_no_overflow(self):
        for label, vp in [("mobile-390", MOBILE_IPHONE), ("mobile-360", MOBILE_COMPACT)]:
            with self.subTest(viewport=label):
                page, page_errors, console_errors = self._new_page(vp, is_mobile=True, has_touch=True)
                self._goto_and_wait_ready(page)

                self._assert_no_horizontal_overflow(page, label)

                # Mobile drawer trigger & header menu visible; sidebar initially closed off-canvas
                self.assertTrue(page.locator("#btnMobileDevices").is_visible())
                self.assertTrue(page.locator("#btnMobileHeaderMenu").is_visible())
                self.assertFalse(page.locator("#deviceSidebar.open").count() > 0)
                sidebar_box = page.locator("#deviceSidebar").bounding_box()
                self.assertIsNotNone(sidebar_box)
                assert sidebar_box is not None
                self.assertLessEqual(sidebar_box["x"] + sidebar_box["width"], 2.0)

                # Quick telemetry chips all visible inside viewport
                for chip_sel in [
                    ".metric-chip.solar",
                    ".metric-chip.load",
                    ".metric-chip.grid",
                    ".metric-chip.battery",
                    ".metric-chip.mode",
                ]:
                    chip = page.locator(chip_sel)
                    self.assertTrue(chip.is_visible(), f"[{label}] {chip_sel} not visible")
                    self._assert_within_viewport_horizontally(page, chip, f"{label}:{chip_sel}")

                # Table header hidden, rows rendered as cards fitting horizontally
                self.assertFalse(page.locator("main.main-content .field-table thead").is_visible())
                first_row = page.locator("#fieldTableBody tr.unified-row").first
                self.assertTrue(first_row.is_visible())
                self._assert_within_viewport_horizontally(page, first_row, f"{label}:first-card")

                # Compact sticky footer visible inside viewport
                for foot_sel in ["#haSelectedCount", "#btnSaveHA", "#btnMobileFooterMenu"]:
                    loc = page.locator(foot_sel)
                    self.assertTrue(loc.is_visible(), f"[{label}] {foot_sel} not visible")
                    self._assert_within_viewport_horizontally(page, loc, f"{label}:{foot_sel}")

                # Vertical scrollability works smoothly and sticky footer remains pinned in viewport
                can_scroll = page.evaluate(
                    "() => document.documentElement.scrollHeight > window.innerHeight"
                )
                self.assertTrue(can_scroll)
                page.evaluate("() => window.scrollTo(0, 300)")
                scroll_y = page.evaluate("() => window.scrollY")
                self.assertGreater(scroll_y, 0)
                vh = page.evaluate("() => window.innerHeight")
                footer_box = page.locator("#appFooter").bounding_box()
                self.assertIsNotNone(footer_box)
                assert footer_box is not None
                self.assertGreaterEqual(footer_box["y"], 0)
                self.assertLessEqual(footer_box["y"] + footer_box["height"], vh + 2.0)

                self._assert_clean_errors(page_errors, console_errors)

    def test_mobile_device_drawer_open_select_and_close(self):
        page, page_errors, console_errors = self._new_page(MOBILE_IPHONE, is_mobile=True, has_touch=True)
        self._goto_and_wait_ready(page)

        # Open drawer via header button
        page.locator("#btnMobileDevices").click()
        page.locator("#deviceSidebar.open").wait_for(state="visible")
        page.locator("#sidebarBackdrop.open").wait_for(state="visible")
        page.wait_for_function(
            "() => { const r = document.getElementById('deviceSidebar')?.getBoundingClientRect(); return r && r.left >= -1; }"
        )
        self._assert_within_viewport_horizontally(page, page.locator("#deviceSidebar"), "mobile-drawer-open")

        # Selecting Battery updates active device and auto-closes drawer
        self._select_device_by_sn(page, BATTERY_SN, expect_drawer_auto_close=True)
        self.assertIn("Battery", page.locator("#activeDeviceName").inner_text())

        # Open via banner switch button, close via close button
        page.locator("#btnSwitchDeviceBanner").click()
        page.locator("#deviceSidebar.open").wait_for(state="visible")
        page.locator("#btnCloseSidebar").click()
        page.wait_for_function("() => !document.getElementById('deviceSidebar')?.classList.contains('open')")

        # Open again and close via Escape key
        page.locator("#btnMobileDevices").click()
        page.locator("#deviceSidebar.open").wait_for(state="visible")
        page.keyboard.press("Escape")
        page.wait_for_function("() => !document.getElementById('deviceSidebar')?.classList.contains('open')")

        # Open again and close via backdrop tap (right edge outside drawer)
        page.locator("#btnMobileDevices").click()
        page.locator("#deviceSidebar.open").wait_for(state="visible")
        page.locator("#sidebarBackdrop").click(position={"x": 360, "y": 200})
        page.wait_for_function("() => !document.getElementById('deviceSidebar')?.classList.contains('open')")

        self._assert_no_horizontal_overflow(page, "mobile-drawer-cycle")
        self._assert_clean_errors(page_errors, console_errors)

    def test_mobile_header_tools_and_footer_menus(self):
        page, page_errors, console_errors = self._new_page(MOBILE_IPHONE, is_mobile=True, has_touch=True)
        self._goto_and_wait_ready(page)

        # Header tools menu collapsed initially on mobile
        self.assertFalse(page.locator("#btnOpenCompare").is_visible())
        page.locator("#btnMobileHeaderMenu").click()
        page.locator("#headerStatusPanel.mobile-open").wait_for(state="visible")
        for sel in ["#btnOpenCompare", "#btnOpenBlockedSafety", "#btnSyncModbus"]:
            self.assertTrue(page.locator(sel).is_visible())
            self._assert_within_viewport_horizontally(page, page.locator(sel), f"mobile-tools:{sel}")

        # Opening Compare from Tools menu closes Tools menu
        page.locator("#btnOpenCompare").click()
        page.locator("#compareModal.modal-backdrop.open").wait_for(state="visible")
        self.assertFalse(page.locator("#headerStatusPanel.mobile-open").count() > 0)
        page.locator("#btnCloseCompare").click()
        page.locator("#compareModal.modal-backdrop.open").wait_for(state="detached")

        # Footer secondary menu collapsed initially, opens on tap
        self.assertFalse(page.locator("#btnPreviewHA").is_visible())
        page.locator("#btnMobileFooterMenu").click()
        page.locator("#appFooter.mobile-footer-open").wait_for(state="visible")
        for sel in ["#btnPreviewHA", "#btnExportHADefaults", "#btnCleanHA", "#btnResetHA"]:
            self.assertTrue(page.locator(sel).is_visible())
            self._assert_within_viewport_horizontally(page, page.locator(sel), f"mobile-footer:{sel}")

        page.locator("#btnPreviewHA").click()
        page.locator("#previewModal.modal-backdrop.open").wait_for(state="visible")
        self.assertFalse(page.locator("#appFooter.mobile-footer-open").count() > 0)
        page.locator("#btnCloseModal").click()

        self._assert_no_horizontal_overflow(page, "mobile-menus")
        self._assert_clean_errors(page_errors, console_errors)

    def test_mobile_search_filters_options_sort_and_cards(self):
        page, page_errors, console_errors = self._new_page(MOBILE_IPHONE, is_mobile=True, has_touch=True)
        self._goto_and_wait_ready(page)

        # Switch to Inverter for multi-source unified rows
        page.locator("#btnMobileDevices").click()
        self._select_device_by_sn(page, INVERTER_SN, expect_drawer_auto_close=True)

        # Search input & clear
        page.locator("#searchInput").fill("grid")
        self._assert_no_horizontal_overflow(page, "mobile-search")
        page.locator("#searchClear").click()

        # Filter pills horizontal strip doesn't overflow page
        page.locator('.filter-pills .pill[data-filter="writable"]').click()
        page.locator('.filter-pills .pill[data-filter="all"]').click()
        self._assert_no_horizontal_overflow(page, "mobile-filter-pills")

        # Options drawer toggle
        self.assertFalse(page.locator("#toolbarOptionsPanel.mobile-open").count() > 0)
        page.locator("#btnToggleMobileFilters").click()
        page.locator("#toolbarOptionsPanel.mobile-open").wait_for(state="visible")
        self._assert_no_horizontal_overflow(page, "mobile-options-open")
        page.locator("#btnToggleMobileFilters").click()

        # Mobile Sort dropdown syncs with sortBar & Clear Sort
        page.locator("#mobileSortSelect").select_option("name:asc")
        self.assertTrue(page.locator("#sortBar").is_visible())
        page.locator("#btnClearSort").click()
        self.assertFalse(page.locator("#sortBar").is_visible())
        self.assertEqual(page.locator("#mobileSortSelect").input_value(), "")

        # Expand multi-source unified card on Inverter
        page.locator("#fieldTableBody .btn-group-expand").first.click()
        page.locator("#fieldTableBody tr.group-children-row").first.wait_for(state="visible")
        self._assert_no_horizontal_overflow(page, "mobile-inverter-child-expanded")

        # Open More menu on a card and verify it stays inside viewport
        more_btn = page.locator("#fieldTableBody tr.unified-row .btn-icon-more").first
        more_btn.scroll_into_view_if_needed()
        more_btn.click()
        menu = page.locator("#fieldTableBody tr.unified-row .action-dropdown-menu.show").first
        menu.wait_for(state="visible")
        self._assert_within_viewport_horizontally(page, menu, "mobile-card-action-menu")
        page.keyboard.press("Escape")

        # Switch to Battery and expand rollup card
        page.locator("#btnMobileDevices").click()
        self._select_device_by_sn(page, BATTERY_SN, expect_drawer_auto_close=True)
        page.locator("#fieldTableBody .btn-rollup-expand").first.click()
        page.locator("#fieldTableBody tr.rollup-children-row").first.wait_for(state="visible")
        self._assert_no_horizontal_overflow(page, "mobile-battery-rollup-expanded")

        # Toggle HA checkbox & save
        before = int(page.locator("#haSelectedCount").inner_text().strip())
        page.locator("#fieldTableBody .ha-checkbox").first.click()
        after = int(page.locator("#haSelectedCount").inner_text().strip())
        self.assertNotEqual(before, after)
        page.locator("#btnSaveHA").click()
        page.locator("#toast.show").wait_for(state="visible")

        self._assert_clean_errors(page_errors, console_errors)

    def test_mobile_all_modals_fit_viewport(self):
        # Test full modal matrix at 390x844
        page, page_errors, console_errors = self._new_page(MOBILE_IPHONE, is_mobile=True, has_touch=True)
        self._goto_and_wait_ready(page)
        page.locator("#btnMobileDevices").click()
        self._select_device_by_sn(page, INVERTER_SN, expect_drawer_auto_close=True)

        # 1. Modbus Details
        page.locator("#fieldTableBody .btn-details").first.click()
        page.wait_for_function(
            "() => !document.getElementById('detailsModalBody')?.textContent?.includes('Loading Modbus details')"
        )
        self._assert_modal_fits_and_close(page, "modbusDetailsModal", "#btnCloseDetailsModal", "mobile-390")

        # 2. Write Modal
        page.locator('.filter-pills .pill[data-filter="writable"]').click()
        page.locator("#fieldTableBody .btn-edit").first.click()
        self._assert_modal_fits_and_close(page, "writeModal", "#btnCancelWrite", "mobile-390")

        # 3. Bounds Modal
        writable_row = page.locator("#fieldTableBody tr.unified-row", has=page.locator(".btn-edit")).first
        writable_row.locator(".btn-icon-more").click()
        writable_row.locator(".action-dropdown-menu.show .item-bounds").click()
        self._assert_modal_fits_and_close(page, "boundsModal", "#btnCloseBoundsModal", "mobile-390")

        # 4. Grouping Modal
        page.locator('.filter-pills .pill[data-filter="all"]').click()
        groupable_row = page.locator("#fieldTableBody tr.unified-row", has=page.locator(".item-group-with")).first
        groupable_row.locator(".btn-icon-more").click()
        groupable_row.locator(".action-dropdown-menu.show .item-group-with").click()
        self._assert_modal_fits_and_close(page, "groupingModal", "#btnCloseGroupingModal", "mobile-390")

        # 5. Compare Telemetry + All tab + expand row + Export Mappings
        page.locator("#btnMobileHeaderMenu").click()
        page.locator("#btnOpenCompare").click()
        page.locator("#compareModal.modal-backdrop.open").wait_for(state="visible")
        page.locator("#tabCmpAll").click()
        page.wait_for_selector("#compareTableBody tr.compare-row", state="visible")
        page.locator("#compareTableBody tr.compare-row .btn-expand-compare").first.click()
        self._assert_no_horizontal_overflow(page, "mobile-390-compare-expanded")
        page.locator("#btnOpenExportMappings").click()
        self._assert_modal_fits_and_close(page, "exportMappingsModal", "#btnCloseExportModal", "mobile-390")
        self._assert_modal_fits_and_close(page, "compareModal", "#btnCloseCompare", "mobile-390")

        # 6. Safety Policy
        page.locator("#btnMobileHeaderMenu").click()
        page.locator("#btnOpenBlockedSafety").click()
        self._assert_modal_fits_and_close(page, "blockedSafetyModal", "#btnCloseSafetyModal", "mobile-390")

        # 7. Re-scan Devices
        page.locator("#btnMobileDevices").click()
        page.locator("#btnOpenRescan").click()
        self._assert_modal_fits_and_close(page, "rescanModal", "#btnCloseRescanModal", "mobile-390")
        if page.locator("#deviceSidebar.open").count() > 0:
            page.locator("#btnCloseSidebar").click()

        # 8. Preview HA & Export HA Defaults
        page.locator("#btnMobileFooterMenu").click()
        page.locator("#btnPreviewHA").click()
        self._assert_modal_fits_and_close(page, "previewModal", "#btnCloseModal", "mobile-390")

        page.locator("#btnMobileFooterMenu").click()
        page.locator("#btnExportHADefaults").click()
        self._assert_modal_fits_and_close(page, "exportHADefaultsModal", "#btnCloseExportHAModal", "mobile-390")

        self._assert_clean_errors(page_errors, console_errors)

        # Also verify key complex modals on compact 360x680 viewport
        page360, errs360, cons360 = self._new_page(MOBILE_COMPACT, is_mobile=True, has_touch=True)
        self._goto_and_wait_ready(page360)
        page360.locator("#btnMobileDevices").click()
        self._select_device_by_sn(page360, INVERTER_SN, expect_drawer_auto_close=True)

        page360.locator("#fieldTableBody .btn-details").first.click()
        page360.wait_for_function(
            "() => !document.getElementById('detailsModalBody')?.textContent?.includes('Loading Modbus details')"
        )
        self._assert_modal_fits_and_close(page360, "modbusDetailsModal", "#btnCloseDetailsModal", "mobile-360")

        page360.locator("#btnMobileHeaderMenu").click()
        page360.locator("#btnOpenCompare").click()
        page360.locator("#compareModal.modal-backdrop.open").wait_for(state="visible")
        page360.locator("#tabCmpAll").click()
        page360.wait_for_selector("#compareTableBody tr.compare-row", state="visible")
        self._assert_modal_fits_and_close(page360, "compareModal", "#btnCloseCompare", "mobile-360")

        self._assert_clean_errors(errs360, cons360)

    # ------------------------------------------------------------------
    # Tablet (768x1024) & Dynamic Resize Round-Trip
    # ------------------------------------------------------------------

    def test_tablet_layout_and_drawer(self):
        page, page_errors, console_errors = self._new_page(TABLET_PORTRAIT, is_mobile=True, has_touch=True)
        self._goto_and_wait_ready(page)

        self._assert_no_horizontal_overflow(page, "tablet-768")
        self.assertTrue(page.locator("#btnMobileDevices").is_visible())
        page.locator("#btnMobileDevices").click()
        page.locator("#deviceSidebar.open").wait_for(state="visible")
        self._select_device_by_sn(page, INVERTER_SN, expect_drawer_auto_close=True)
        self._assert_no_horizontal_overflow(page, "tablet-768-after-select")
        self._assert_clean_errors(page_errors, console_errors)

    def test_dynamic_resize_desktop_mobile_roundtrip(self):
        page, page_errors, console_errors = self._new_page(DESKTOP_WIDE)
        self._goto_and_wait_ready(page)

        self.assertTrue(page.locator("main.main-content .field-table thead").is_visible())
        self.assertFalse(page.locator("#btnMobileDevices").is_visible())
        self._assert_no_horizontal_overflow(page, "resize-start-desktop")

        # Resize down to mobile
        page.set_viewport_size(MOBILE_IPHONE)
        page.wait_for_timeout(150)
        self.assertFalse(page.locator("main.main-content .field-table thead").is_visible())
        self.assertTrue(page.locator("#btnMobileDevices").is_visible())
        self._assert_no_horizontal_overflow(page, "resize-mobile")

        # Open drawer on mobile, then resize back up to desktop -> drawer/backdrop cleaned up
        page.locator("#btnMobileDevices").click()
        page.locator("#deviceSidebar.open").wait_for(state="visible")
        page.set_viewport_size(DESKTOP_WIDE)
        page.wait_for_function(
            "() => !document.getElementById('deviceSidebar')?.classList.contains('open') && !document.body.classList.contains('drawer-open')"
        )
        self.assertTrue(page.locator("main.main-content .field-table thead").is_visible())
        self.assertFalse(page.locator("#btnMobileDevices").is_visible())
        self._assert_no_horizontal_overflow(page, "resize-back-desktop")

        self._assert_clean_errors(page_errors, console_errors)


if __name__ == "__main__":
    unittest.main()
