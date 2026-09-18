"""
i18n — lightweight English/Hebrew translation layer.
Usage: from i18n import t; t("welcome_title")
Language is read from config.json ("language": "en" | "he" | "auto").
"auto" detects from the Windows locale on first run, then is saved explicitly.
"""
import locale
import config as cfg

STRINGS = {
    "en": {
        # Common
        "app_name": "SnapCap",
        "back": "← Back",
        "next": "Next →",
        "finish": "Finish",
        "skip_setup": "Skip setup",
        "save": "Save",
        "cancel": "Cancel",
        "browse": "Browse",
        "show_key": "Show key",
        # Onboarding — language page
        "choose_language": "Choose your language",
        "choose_language_sub": "You can change this later in Settings.",
        "lang_english": "English",
        "lang_hebrew": "עברית (Hebrew)",
        # Onboarding — welcome
        "welcome_title": "Welcome to SnapCap",
        "welcome_sub": "The screenshot tool the market was missing.\nCapture, annotate, redact, share — supercharged by AI.\n\nThis quick setup takes less than a minute.",
        "feat_capture": "Smart Region / Window / Fullscreen / Scroll capture",
        "feat_annotate": "Full annotation suite — arrows, steps, callouts, blur",
        "feat_redact": "AI PII auto-redaction — emails, keys, IDs",
        "feat_ai": "Claude AI — summarize, bug report, translate, alt-text",
        "feat_library": "Searchable library with OCR full-text index",
        # Onboarding — hotkeys
        "hotkeys_title": "Global Hotkeys",
        "hotkeys_sub": "These shortcuts work system-wide, even when the app is minimized.",
        "hk_region": "Capture Region",
        "hk_fullscreen": "Capture Fullscreen",
        "hk_window": "Capture Window",
        "hk_scroll": "Scrolling Capture",
        "hk_library": "Open Library",
        "hk_text_ocr": "Quick Text Capture (OCR)",
        "hotkeys_note": "You can change hotkeys at any time in Settings → Hotkeys.",
        "hotkeys_tip": "Double-click the tray icon to launch Region Capture instantly.",
        # Onboarding — AI
        "ai_title": "AI Features (Optional)",
        "ai_sub": "SnapCap uses Claude AI for smart summarization, bug reports, text extraction, translation, and sensitivity detection.",
        "ai_key_label": "Anthropic API Key",
        "ai_key_placeholder": "sk-ant-…  (leave blank to skip)",
        "ai_auto_redact": "Enable auto-redact PII on every capture",
        "ai_key_where": "Where to get an API key:",
        "ai_key_skip_note": "You can skip this and add the key later in Settings → AI.",
        # Onboarding — save dir
        "save_title": "Save Location",
        "save_sub": "Screenshots will be saved here automatically.",
        "save_auto_copy": "Auto-copy to clipboard after each capture",
        "save_auto_save": "Auto-save each capture",
        "save_startup": "Launch SnapCap when Windows starts",
        # Onboarding — finish
        "finish_title": "You're all set!",
        "finish_sub": "SnapCap is now running in your system tray.\n\nUse {hotkey} to capture a region right now,\nor right-click the tray icon to explore all options.",
        "finish_tip": "Open Settings any time from the tray menu to change hotkeys, AI key, themes, and more.",
        # Tray menu
        "tray_capture_region": "Capture Region",
        "tray_capture_fullscreen": "Capture Fullscreen",
        "tray_capture_window": "Capture Window",
        "tray_capture_scroll": "Scrolling Capture",
        "tray_library": "Screenshot Library",
        "tray_capture_text_ocr": "Quick Text Capture (OCR → Clipboard)",
        "tray_settings": "Settings",
        "tray_about": "About / Updates",
        "tray_quit": "Quit",
        "tray_running": "Running in the system tray. Right-click for options.",
        "text_ocr_copied_msg": "Copied {count} characters of text to clipboard.",
        "text_ocr_empty_msg": "No text was detected in the selected region.",
        "pin_to_screen": "📌  Pin to Screen",
        "pin_tooltip": "Right-click to close · drag to move · scroll to resize",
        "tray_already_running_title": "SnapCap",
        "tray_already_running_msg": "SnapCap is already running.\n\nLook for the  S  icon in your system tray.",
        "update_available_title": "SnapCap — Update Available",
        "update_available_msg": "Version {version} is available. Open Settings → About to update.",
        "saved_msg": "Saved: {filename}",
        "redact_msg": "Redacted {count} sensitive item(s).",
        # Settings dialog
        "settings_title": "SnapCap — Settings",
        "tab_general": "General",
        "tab_ai": "AI",
        "tab_upload": "Upload",
        "tab_hotkeys": "Hotkeys",
        "tab_advanced": "Advanced",
        "lbl_save_dir": "Save directory:",
        "lbl_format": "Default format:",
        "lbl_language": "Language:",
        "lbl_theme": "Theme:",
        "cb_auto_copy": "Auto-copy to clipboard after capture",
        "cb_auto_save": "Auto-save every capture",
        "cb_auto_redact": "Auto-detect & redact PII after capture",
        "cb_check_updates": "Automatically check for updates",
        "cb_watermark": "Add watermark to screenshots",
        "lbl_watermark_text": "Watermark text:",
        "lbl_redact_style": "Redaction style:",
        "lbl_api_key": "Anthropic API Key (for Claude AI features):",
        "lbl_api_key_hint": "Get your key at console.anthropic.com",
        "lbl_imgur": "Imgur Client ID (for cloud upload):",
        "lbl_webhook": "Custom webhook URL:",
        "lbl_slack": "Slack webhook URL:",
        "lbl_teams": "Teams webhook URL:",
    },
    "he": {
        "app_name": "SnapCap",
        "back": "← הקודם",
        "next": "הבא →",
        "finish": "סיום",
        "skip_setup": "דלג על ההגדרה",
        "save": "שמור",
        "cancel": "ביטול",
        "browse": "עיון",
        "show_key": "הצג מפתח",
        "choose_language": "בחר שפה",
        "choose_language_sub": "תוכל לשנות זאת מאוחר יותר בהגדרות.",
        "lang_english": "English (אנגלית)",
        "lang_hebrew": "עברית",
        "welcome_title": "ברוכים הבאים ל-SnapCap",
        "welcome_sub": "כלי צילום המסך שהיה חסר בשוק.\nצלם, סמן, טשטש, שתף — עם בינה מלאכותית.\n\nההגדרה המהירה הזו לוקחת פחות מדקה.",
        "feat_capture": "צילום חכם — אזור / חלון / מסך מלא / גלילה",
        "feat_annotate": "סימון מלא — חצים, שלבים, הערות, טשטוש",
        "feat_redact": "טשטוש PII אוטומטי בעזרת AI — אימיילים, מפתחות, ת.ז.",
        "feat_ai": "בינה מלאכותית — סיכום, דוח באג, תרגום, טקסט נגיש",
        "feat_library": "ספרייה עם חיפוש טקסט מלא (OCR)",
        "hotkeys_title": "קיצורי מקלדת גלובליים",
        "hotkeys_sub": "הקיצורים הללו פועלים בכל המערכת, גם כשהאפליקציה ממוזערת.",
        "hk_region": "צילום אזור",
        "hk_fullscreen": "צילום מסך מלא",
        "hk_window": "צילום חלון",
        "hk_scroll": "צילום גלילה",
        "hk_library": "פתיחת ספרייה",
        "hk_text_ocr": "לכידת טקסט מהירה (OCR)",
        "hotkeys_note": "ניתן לשנות קיצורים בכל עת בהגדרות → קיצורים.",
        "hotkeys_tip": "לחיצה כפולה על סמל המגש תפתח מיד צילום אזור.",
        "ai_title": "תכונות AI (אופציונלי)",
        "ai_sub": "SnapCap משתמש ב-Claude AI לסיכום חכם, דוחות באגים, חילוץ טקסט, תרגום וזיהוי מידע רגיש.",
        "ai_key_label": "מפתח API של Anthropic",
        "ai_key_placeholder": "sk-ant-…  (השאר ריק כדי לדלג)",
        "ai_auto_redact": "הפעל טשטוש PII אוטומטי בכל צילום",
        "ai_key_where": "היכן להשיג מפתח API:",
        "ai_key_skip_note": "ניתן לדלג ולהוסיף את המפתח מאוחר יותר בהגדרות → AI.",
        "save_title": "מיקום שמירה",
        "save_sub": "צילומי המסך יישמרו כאן אוטומטית.",
        "save_auto_copy": "העתק אוטומטית ללוח לאחר כל צילום",
        "save_auto_save": "שמור אוטומטית כל צילום",
        "save_startup": "הפעל את SnapCap בהפעלת Windows",
        "finish_title": "הכול מוכן!",
        "finish_sub": "SnapCap פועל כעת במגש המערכת.\n\nהשתמש ב-{hotkey} כדי לצלם אזור עכשיו,\nאו לחץ ימני על סמל המגש לאפשרויות נוספות.",
        "finish_tip": "ניתן לפתוח הגדרות בכל עת מתפריט המגש כדי לשנות קיצורים, מפתח AI, ערכות נושא ועוד.",
        "tray_capture_region": "צילום אזור",
        "tray_capture_fullscreen": "צילום מסך מלא",
        "tray_capture_window": "צילום חלון",
        "tray_capture_scroll": "צילום גלילה",
        "tray_library": "ספריית צילומים",
        "tray_capture_text_ocr": "לכידת טקסט מהירה (OCR ← ללוח)",
        "tray_settings": "הגדרות",
        "tray_about": "אודות / עדכונים",
        "tray_quit": "יציאה",
        "tray_running": "פועל במגש המערכת. לחץ ימני לאפשרויות.",
        "text_ocr_copied_msg": "הועתקו {count} תווי טקסט ללוח.",
        "text_ocr_empty_msg": "לא זוהה טקסט באזור שנבחר.",
        "pin_to_screen": "📌  הצמד למסך",
        "pin_tooltip": "קליק ימני לסגירה · גרירה להזזה · גלגלת לשינוי גודל",
        "tray_already_running_title": "SnapCap",
        "tray_already_running_msg": "SnapCap כבר פועל.\n\nחפש את הסמל  S  במגש המערכת.",
        "update_available_title": "SnapCap — עדכון זמין",
        "update_available_msg": "גרסה {version} זמינה. פתח הגדרות → אודות כדי לעדכן.",
        "saved_msg": "נשמר: {filename}",
        "redact_msg": "טושטשו {count} פריטים רגישים.",
        "settings_title": "SnapCap — הגדרות",
        "tab_general": "כללי",
        "tab_ai": "בינה מלאכותית",
        "tab_upload": "העלאה",
        "tab_hotkeys": "קיצורים",
        "tab_advanced": "מתקדם",
        "lbl_save_dir": "תיקיית שמירה:",
        "lbl_format": "פורמט ברירת מחדל:",
        "lbl_language": "שפה:",
        "lbl_theme": "ערכת נושא:",
        "cb_auto_copy": "העתק אוטומטית ללוח לאחר צילום",
        "cb_auto_save": "שמור אוטומטית כל צילום",
        "cb_auto_redact": "זהה וטשטש PII אוטומטית לאחר צילום",
        "cb_check_updates": "בדוק עדכונים אוטומטית",
        "cb_watermark": "הוסף סימן מים לצילומים",
        "lbl_watermark_text": "טקסט סימן מים:",
        "lbl_redact_style": "סגנון טשטוש:",
        "lbl_api_key": "מפתח API של Anthropic (לתכונות AI):",
        "lbl_api_key_hint": "השג מפתח בכתובת console.anthropic.com",
        "lbl_imgur": "מזהה לקוח Imgur (להעלאה לענן):",
        "lbl_webhook": "כתובת webhook מותאמת אישית:",
        "lbl_slack": "כתובת webhook של Slack:",
        "lbl_teams": "כתובת webhook של Teams:",
    },
}

_RTL_LANGS = {"he", "ar"}


def detect_system_language() -> str:
    """Kept for callers that explicitly want the Windows locale (e.g. a
    'match my system language' button). NOT used automatically — see
    current_language(): the project standard is to always default to
    English and let the user switch explicitly, regardless of OS locale."""
    try:
        loc = locale.getdefaultlocale()[0] or ""
        if loc.lower().startswith("he"):
            return "he"
    except Exception:
        pass
    return "en"


def current_language() -> str:
    conf = cfg.load()
    lang = conf.get("language", "en")
    if lang == "auto":
        # Back-compat with configs saved before the default flipped to
        # English-always: "auto" no longer means "detect from Windows".
        lang = "en"
    return lang if lang in STRINGS else "en"


def is_rtl(lang: str = None) -> bool:
    return (lang or current_language()) in _RTL_LANGS


def t(key: str, lang: str = None, **kwargs) -> str:
    """Translate a key. Falls back to English, then to the key itself."""
    lang = lang or current_language()
    table = STRINGS.get(lang, STRINGS["en"])
    text = table.get(key) or STRINGS["en"].get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text
