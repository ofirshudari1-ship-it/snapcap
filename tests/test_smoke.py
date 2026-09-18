"""
Smoke tests for SnapCap's critical paths — per the project stability
standard ("at least smoke tests for critical paths"). Uses stdlib unittest
only (no new dependency). Run with:

    python -m unittest discover -s tests -v

These are NOT a full test suite (no GUI/PyQt event-loop testing here) —
they cover the parts that are cheap to verify without a live display and
that have broken silently before: config round-tripping, i18n defaults,
DPI-scaling math in the region selector, and PII regex correctness.
"""
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestConfig(unittest.TestCase):
    def test_load_returns_all_defaults(self):
        import config as cfg
        conf = cfg.load()
        for key in cfg.DEFAULT_CONFIG:
            self.assertIn(key, conf)

    def test_version_matches_version_json(self):
        import config as cfg
        import json
        with open(Path(__file__).resolve().parent.parent / "version.json", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(cfg.APP_VERSION, data["version"])

    def test_secret_roundtrip_survives_save_load(self):
        import config as cfg
        conf = dict(cfg.DEFAULT_CONFIG)
        conf["anthropic_api_key"] = "sk-ant-test-roundtrip-value"
        cfg.save(conf)
        reloaded = cfg.load()
        self.assertEqual(reloaded["anthropic_api_key"], "sk-ant-test-roundtrip-value")
        # cleanup: restore an empty key so this test doesn't leave a fake secret behind
        conf["anthropic_api_key"] = ""
        cfg.save(conf)

    def test_corrupt_config_file_falls_back_to_defaults(self):
        import config as cfg
        cfg._make_dirs()
        original = cfg.CONFIG_FILE.read_text(encoding="utf-8") if cfg.CONFIG_FILE.exists() else None
        try:
            cfg.CONFIG_FILE.write_text("{ not valid json", encoding="utf-8")
            conf = cfg.load()
            self.assertEqual(conf, cfg.DEFAULT_CONFIG)
        finally:
            if original is not None:
                cfg.CONFIG_FILE.write_text(original, encoding="utf-8")
            else:
                cfg.CONFIG_FILE.unlink(missing_ok=True)


class TestI18n(unittest.TestCase):
    def test_default_language_is_english(self):
        import config as cfg
        self.assertEqual(cfg.DEFAULT_CONFIG["language"], "en")

    def test_translate_known_key_both_languages(self):
        from i18n import t
        self.assertTrue(t("app_name", "en"))
        self.assertTrue(t("app_name", "he"))

    def test_translate_missing_key_falls_back_to_key_itself(self):
        from i18n import t
        self.assertEqual(t("__no_such_key__", "en"), "__no_such_key__")

    def test_rtl_only_for_hebrew(self):
        from i18n import is_rtl
        self.assertTrue(is_rtl("he"))
        self.assertFalse(is_rtl("en"))


class TestRegionSelectorDpiMath(unittest.TestCase):
    """The DPI-scaling bug (region-capture preview looking 'zoomed in') was
    found and fixed in region_selector.py — these pin the coordinate math so
    a regression there fails a test instead of shipping silently."""

    def test_logical_to_physical_conversion(self):
        import sys
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QPixmap, QColor
        from PyQt6.QtCore import QPoint
        app = QApplication.instance() or QApplication(sys.argv)
        import region_selector as rs

        bg = QPixmap(300, 300)
        bg.fill(QColor("black"))
        bg.setDevicePixelRatio(1.5)

        sel = rs.RegionSelector(bg)
        self.assertEqual(sel._scale, 1.5)

        sel._start = QPoint(10, 10)
        sel._end = QPoint(60, 60)
        sel._selecting = True

        results = []
        sel.region_selected.connect(lambda x, y, w, h: results.append((x, y, w, h)))

        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtCore import QPointF, Qt as QtC
        ev = QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease, QPointF(60, 60),
            QtC.MouseButton.LeftButton, QtC.MouseButton.LeftButton,
            QtC.KeyboardModifier.NoModifier,
        )
        sel.mouseReleaseEvent(ev)

        self.assertEqual(results, [(15, 15, 75, 75)])


class TestAiEnginePii(unittest.TestCase):
    def test_email_pattern_matches(self):
        from ai_engine import PII_PATTERNS
        self.assertTrue(PII_PATTERNS["email"].search("contact me at test@example.com"))

    def test_email_pattern_does_not_match_plain_word(self):
        from ai_engine import PII_PATTERNS
        self.assertFalse(PII_PATTERNS["email"].search("just a normal sentence"))

    def test_ocr_gracefully_reports_when_tesseract_missing_or_present(self):
        # Doesn't assert Tesseract IS installed (environment-dependent) —
        # just that the function never raises and always returns a string.
        from PIL import Image
        import ai_engine as ai
        img = Image.new("RGB", (50, 20), "white")
        result = ai.ocr_extract_text(img)
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)


class TestEditorWindowTheme(unittest.TestCase):
    def test_apply_theme_system_resolves_to_dark_or_light(self):
        import editor_window as ew
        ew.apply_theme("system")
        self.assertIn(ew.DARK_BG, (ew._THEMES["dark"]["DARK_BG"], ew._THEMES["light"]["DARK_BG"]))
        ew.apply_theme("dark")  # restore a known state for any test run after this one


class TestClaudeVisionImportFailure(unittest.TestCase):
    """Pins the fix for a real bug: _claude_vision() used to `import anthropic`
    inside the same try block as `except anthropic.AuthenticationError` /
    `except anthropic.RateLimitError`. If the import itself failed (package
    not installed — it's an optional, cloud-only dependency), Python had to
    evaluate `anthropic.AuthenticationError` to match the except clause,
    which raised an unrelated NameError instead of the intended friendly
    "[AI Error: ...]" string — silently crashing whatever called an AI
    feature (Summarize, Alt-Text, Bug Report, etc.) if anthropic wasn't
    installed. This test forces that exact ImportError path and asserts the
    function returns a string instead of raising."""

    def test_returns_friendly_string_when_anthropic_not_installed(self):
        import builtins
        import ai_engine as ai
        from PIL import Image

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "anthropic":
                raise ImportError("simulated: anthropic not installed")
            return real_import(name, *args, **kwargs)

        img = Image.new("RGB", (10, 10), "white")
        with unittest.mock.patch("builtins.__import__", side_effect=fake_import):
            result = ai.ai_summarize(img, "fake-api-key")

        self.assertIsInstance(result, str)
        self.assertIn("AI Error", result)


class TestHotkeyDefaults(unittest.TestCase):
    """The one-step "capture region -> OCR -> copy text" quick action
    (main.py:_capture_text_ocr) needs a default hotkey and must appear in
    the user-configurable hotkeys dict, like every other capture mode."""

    def test_capture_text_ocr_hotkey_is_registered(self):
        import config as cfg
        self.assertIn("capture_text_ocr", cfg.DEFAULT_CONFIG["hotkeys"])
        self.assertTrue(cfg.DEFAULT_CONFIG["hotkeys"]["capture_text_ocr"])


class TestPinWindow(unittest.TestCase):
    """Pin to Screen (editor_window.PinWindow) — the always-on-top floating
    screenshot feature. Only tests the pure scale-clamping logic, not
    drag/resize mouse interaction (that needs a live display)."""

    def test_scale_is_clamped_to_min_and_max(self):
        import sys
        from PyQt6.QtWidgets import QApplication
        from PIL import Image
        app = QApplication.instance() or QApplication(sys.argv)
        import editor_window as ew

        img = Image.new("RGB", (100, 80), "white")
        pin = ew.PinWindow(img)
        try:
            pin._scale = ew.PinWindow.MIN_SCALE
            pin._apply_size()
            self.assertGreaterEqual(pin.width(), 1)
            self.assertGreaterEqual(pin.height(), 1)

            pin._scale = ew.PinWindow.MAX_SCALE
            pin._apply_size()
            self.assertEqual(pin.width(), int(100 * ew.PinWindow.MAX_SCALE))
            self.assertEqual(pin.height(), int(80 * ew.PinWindow.MAX_SCALE))
        finally:
            pin.close()
            ew._PINNED_WINDOWS.clear()


if __name__ == "__main__":
    unittest.main()
