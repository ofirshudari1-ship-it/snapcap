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
        # Was "Open Settings → About" — the Update button actually lives in
        # Settings → Advanced, not About (fixed 2026-09-23).
        "update_available_msg": "Version {version} is available. Open Settings → Advanced to update.",
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
        "btn_check_updates_now": "Check for Updates Now",
        "update_check_latest_msg": "You're on the latest version (v{version}).",
        "cb_watermark": "Add watermark to screenshots",
        "lbl_watermark_text": "Watermark text:",
        "lbl_redact_style": "Redaction style:",
        "lbl_api_key": "Anthropic API Key (for Claude AI features):",
        "lbl_api_key_hint": "Get your key at console.anthropic.com",
        "lbl_imgur": "Imgur Client ID (for cloud upload):",
        "lbl_webhook": "Custom webhook URL:",
        "lbl_slack": "Slack webhook URL:",
        "lbl_teams": "Teams webhook URL:",
        # Settings — 2026-09-20 upgrade pass
        "grp_capture": "Capture",
        "grp_appearance": "Appearance",
        "grp_annotation": "Annotation defaults",
        "lbl_capture_delay": "Capture delay:",
        "capture_delay_none": "None",
        "capture_delay_fmt": "{sec} seconds",
        "cb_capture_sound": "Play a shutter sound on capture",
        "cb_skip_editor": "Skip the editor after capture (just copy/save silently)",
        "lbl_default_font_size": "Default text size:",
        "cb_fill_shapes": "Fill shape",
        "captured_quiet_msg": "Captured",
        # Settings — 2026-09-20 Windows-integration pass
        "grp_startup": "Startup",
        "cb_skip_splash_autostart": "Skip splash screen when launched at Windows startup",
        "cb_show_startup_notification": "Show a tray notification each time SnapCap starts",
        # Settings — 2026-09-21 self-update pass
        "cb_auto_update": "Automatically download and install updates",
        "btn_update_now": "Update Now",
        "update_launched_msg": "Downloading and installing v{version}… SnapCap will restart automatically.",
        "update_auto_failed_msg": "Version {version} is available, but the automatic update couldn't complete. Opening the release page instead.",
        "update_check_failed_msg": "Couldn't check for updates. Please check your internet connection and try again.",
        # Settings — 2026-09-22 desktop widget pass
        "grp_widget": "Desktop Widget",
        "cb_show_desktop_widget": "Show desktop widget",
        "widget_capture_now": "📷  Capture now",
        "widget_open_library": "📚  Open Library",
        "widget_stat_zero": "📸 No captures yet this month",
        "widget_tooltip": "Drag to move · click × to hide",
        # Library window — 2026-09-21 i18n/RTL/accessibility pass
        "lib_window_title": "SnapCap — Screenshot Library",
        "lib_search_placeholder": "🔍  Search screenshots… (searches file names and OCR text)",
        "lib_sort_newest": "Newest first",
        "lib_sort_oldest": "Oldest first",
        "lib_sort_largest": "Largest first",
        "lib_sort_az": "A–Z",
        "lib_refresh": "↺ Refresh",
        "lib_open_folder": "📂 Open Folder",
        "lib_preview": "Preview",
        "lib_select_screenshot": "Select a screenshot",
        "lib_open_editor": "✏  Open in Editor",
        "lib_copy_clipboard": "📋  Copy to Clipboard",
        "lib_upload_imgur": "📤  Upload to Imgur",
        "lib_ocr_extract": "🔍  OCR Extract Text",
        "lib_delete": "🗑  Delete",
        "lib_building_index": "⏳ Building search index…",
        "lib_indexing_fmt": "🔍 Indexing {indexed}/{total}…",
        "lib_index_complete_fmt": "✅ Index complete: {count} images searchable",
        "lib_index_ready_fmt": "✅ Search index: {count} images",
        "lib_empty_none": "📭  No screenshots yet — capture one with Ctrl+Shift+S to see it here",
        "lib_empty_search": "🔍  No screenshots match your search",
        "lib_count_fmt": "  {n} screenshot(s)",
        "lib_count_filtered_fmt": "  {n} screenshot(s) (filtered from {total})",
        "lib_stat_month_fmt": "📸 {count} captured this month",
        "lib_select_first_msg": "Select a screenshot first.",
        "lib_imgur_set_key_msg": "Set Imgur Client ID in Settings.",
        "lib_uploaded_fmt": "Uploaded!\n{url}",
        "lib_upload_failed_msg": "Upload failed.",
        "lib_ocr_result_title": "OCR Result",
        "close": "Close",
        "lib_delete_title": "Delete",
        "lib_delete_confirm_fmt": "Delete {filename}?",
        "error": "Error",
        # About dialog — main.py:_show_about (2026-09-23 localization pass)
        "about_title": "About SnapCap",
        "about_tagline": "The screenshot tool the market was missing.",
        "about_feat_capture": "Smart region / window / fullscreen / scrolling capture",
        "about_feat_annotate": "Full annotation — arrows, shapes, steps, callouts",
        "about_feat_redact": "AI PII auto-redaction (emails, keys, IDs, phones)",
        "about_feat_ocr": "OCR with table extraction (CSV / Markdown export)",
        "about_feat_ai": "Claude AI — summarize, alt-text, bug reports, translate",
        "about_feat_library": "Searchable screenshot library with OCR index",
        "about_feat_share": "Imgur, custom webhook, Slack, Teams, email sharing",
        # Export Diagnostics — main.py:_export_diagnostics (2026-09-25)
        "btn_export_diagnostics": "Export Diagnostics",
        "diag_export_dialog_title": "Export Diagnostics",
        "diag_export_success_title": "Diagnostics Exported",
        "diag_export_success_fmt": "Diagnostics saved to:\n{path}",
        "diag_export_failed_title": "Export Failed",
        "diag_export_failed_fmt": "Couldn't export diagnostics: {error}",
        # Scrolling-capture progress dialog — main.py:_capture_scroll
        "scroll_capture_progress": "Scrolling and stitching…",
        "scroll_capture_dialog_title": "SnapCap — Scrolling Capture",
        # Splash screen — splash_screen.py
        "splash_starting": "Starting…",
        # Region selector overlay — region_selector.py
        "region_selector_hint": "Drag to select region  •  ESC to cancel",
        # Editor panel collapsible section headers — editor_window.py
        "editor_section_share_export": "Share & Export",
        "editor_section_ocr": "Extract Text (OCR)",
        # Settings validation — editor_window.py:SettingsDialog._validate
        "invalid_settings_title": "Invalid Settings",
        "validate_save_dir_empty": "Save directory cannot be empty.",
        "validate_save_dir_not_writable": "Save directory isn't writable:\n{dir}\n\n{err}",
        "validate_url_invalid": "{label} doesn't look like a valid URL (must start with http:// or https://):\n{val}",
        "lbl_slack_webhook_short": "Slack webhook",
        "lbl_teams_webhook_short": "Teams webhook",
        "lbl_custom_webhook_short": "Custom webhook",
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
        "update_available_msg": "גרסה {version} זמינה. פתח הגדרות → מתקדם כדי לעדכן.",
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
        "btn_check_updates_now": "בדוק עדכונים עכשיו",
        "update_check_latest_msg": "אתה משתמש בגרסה העדכנית ביותר (v{version}).",
        "cb_watermark": "הוסף סימן מים לצילומים",
        "lbl_watermark_text": "טקסט סימן מים:",
        "lbl_redact_style": "סגנון טשטוש:",
        "lbl_api_key": "מפתח API של Anthropic (לתכונות AI):",
        "lbl_api_key_hint": "השג מפתח בכתובת console.anthropic.com",
        "lbl_imgur": "מזהה לקוח Imgur (להעלאה לענן):",
        "lbl_webhook": "כתובת webhook מותאמת אישית:",
        "lbl_slack": "כתובת webhook של Slack:",
        "lbl_teams": "כתובת webhook של Teams:",
        "grp_capture": "צילום",
        "grp_appearance": "מראה",
        "grp_annotation": "ברירות מחדל לסימון",
        "lbl_capture_delay": "השהיית צילום:",
        "capture_delay_none": "ללא",
        "capture_delay_fmt": "{sec} שניות",
        "cb_capture_sound": "השמע צליל תריס בעת צילום",
        "cb_skip_editor": "דלג על העורך לאחר צילום (העתק/שמור בשקט בלבד)",
        "lbl_default_font_size": "גודל טקסט ברירת מחדל:",
        "cb_fill_shapes": "מלא צורה",
        "captured_quiet_msg": "צולם",
        "grp_startup": "הפעלה",
        "cb_skip_splash_autostart": "דלג על מסך הפתיחה בעת הפעלה עם Windows",
        "cb_show_startup_notification": "הצג התראת מגש בכל הפעלה של SnapCap",
        "cb_auto_update": "הורד והתקן עדכונים אוטומטית",
        "btn_update_now": "עדכן עכשיו",
        "update_launched_msg": "מוריד ומתקין גרסה {version}… SnapCap יופעל מחדש אוטומטית.",
        "update_auto_failed_msg": "גרסה {version} זמינה, אך העדכון האוטומטי לא הושלם. פותח את דף ההורדה במקום.",
        "update_check_failed_msg": "לא ניתן היה לבדוק עדכונים. בדוק את חיבור האינטרנט ונסה שוב.",
        # Settings — 2026-09-22 desktop widget pass
        "grp_widget": "ווידג'ט שולחן עבודה",
        "cb_show_desktop_widget": "הצג ווידג'ט שולחן עבודה",
        "widget_capture_now": "📷  צלם עכשיו",
        "widget_open_library": "📚  פתח ספרייה",
        "widget_stat_zero": "📸 עוד לא צולם החודש",
        "widget_tooltip": "גרור להזזה · לחץ על × להסתרה",
        # Library window — 2026-09-21 i18n/RTL/accessibility pass
        "lib_window_title": "SnapCap — ספריית צילומים",
        "lib_search_placeholder": "🔍  חיפוש צילומים… (מחפש בשמות קבצים ובטקסט OCR)",
        "lib_sort_newest": "החדש ביותר",
        "lib_sort_oldest": "הישן ביותר",
        "lib_sort_largest": "הגדול ביותר",
        "lib_sort_az": "א–ת",
        "lib_refresh": "↺ רענן",
        "lib_open_folder": "📂 פתח תיקייה",
        "lib_preview": "תצוגה מקדימה",
        "lib_select_screenshot": "בחר צילום מסך",
        "lib_open_editor": "✏  פתח בעורך",
        "lib_copy_clipboard": "📋  העתק ללוח",
        "lib_upload_imgur": "📤  העלה ל-Imgur",
        "lib_ocr_extract": "🔍  חלץ טקסט (OCR)",
        "lib_delete": "🗑  מחק",
        "lib_building_index": "⏳ בונה אינדקס חיפוש…",
        "lib_indexing_fmt": "🔍 מאנדקס {indexed}/{total}…",
        "lib_index_complete_fmt": "✅ האינדקס הושלם: {count} תמונות ניתנות לחיפוש",
        "lib_index_ready_fmt": "✅ אינדקס חיפוש: {count} תמונות",
        "lib_empty_none": "📭  אין עדיין צילומי מסך — צלם אחד עם Ctrl+Shift+S כדי לראות אותו כאן",
        "lib_empty_search": "🔍  אין צילומים התואמים לחיפוש",
        "lib_count_fmt": "  {n} צילומים",
        "lib_count_filtered_fmt": "  {n} צילומים (מסונן מתוך {total})",
        "lib_stat_month_fmt": "📸 {count} צולמו החודש",
        "lib_select_first_msg": "בחר צילום מסך תחילה.",
        "lib_imgur_set_key_msg": "הגדר מזהה לקוח Imgur בהגדרות.",
        "lib_uploaded_fmt": "הועלה בהצלחה!\n{url}",
        "lib_upload_failed_msg": "ההעלאה נכשלה.",
        "lib_ocr_result_title": "תוצאת OCR",
        "close": "סגור",
        "lib_delete_title": "מחיקה",
        "lib_delete_confirm_fmt": "למחוק את {filename}?",
        "error": "שגיאה",
        # About dialog — main.py:_show_about (2026-09-23 localization pass)
        "about_title": "אודות SnapCap",
        "about_tagline": "כלי צילום המסך שהיה חסר בשוק.",
        "about_feat_capture": "צילום חכם — אזור / חלון / מסך מלא / גלילה",
        "about_feat_annotate": "סימון מלא — חצים, צורות, שלבים, הערות",
        "about_feat_redact": "טשטוש PII אוטומטי בעזרת AI (אימיילים, מפתחות, ת.ז., טלפונים)",
        "about_feat_ocr": "OCR עם חילוץ טבלאות (ייצוא ל-CSV / Markdown)",
        "about_feat_ai": "Claude AI — סיכום, טקסט נגיש, דוחות באגים, תרגום",
        "about_feat_library": "ספריית צילומי מסך עם אינדקס חיפוש OCR",
        "about_feat_share": "שיתוף ל-Imgur, webhook מותאם אישית, Slack, Teams ומייל",
        # Export Diagnostics — main.py:_export_diagnostics (2026-09-25)
        "btn_export_diagnostics": "ייצוא אבחון",
        "diag_export_dialog_title": "ייצוא אבחון",
        "diag_export_success_title": "האבחון יוצא בהצלחה",
        "diag_export_success_fmt": "קובץ האבחון נשמר בנתיב:\n{path}",
        "diag_export_failed_title": "הייצוא נכשל",
        "diag_export_failed_fmt": "לא ניתן לייצא את קובץ האבחון: {error}",
        # Scrolling-capture progress dialog — main.py:_capture_scroll
        "scroll_capture_progress": "גולל ותופר…",
        "scroll_capture_dialog_title": "SnapCap — צילום גלילה",
        # Splash screen — splash_screen.py
        "splash_starting": "מתחיל…",
        # Region selector overlay — region_selector.py
        "region_selector_hint": "גרור לבחירת אזור  •  ESC לביטול",
        # Editor panel collapsible section headers — editor_window.py
        "editor_section_share_export": "שיתוף וייצוא",
        "editor_section_ocr": "חילוץ טקסט (OCR)",
        # Settings validation — editor_window.py:SettingsDialog._validate
        "invalid_settings_title": "הגדרות לא תקינות",
        "validate_save_dir_empty": "תיקיית השמירה לא יכולה להיות ריקה.",
        "validate_save_dir_not_writable": "לא ניתן לכתוב לתיקיית השמירה:\n{dir}\n\n{err}",
        "validate_url_invalid": "{label} לא נראית ככתובת URL תקינה (חייבת להתחיל ב-http:// או https://):\n{val}",
        "lbl_slack_webhook_short": "Webhook של Slack",
        "lbl_teams_webhook_short": "Webhook של Teams",
        "lbl_custom_webhook_short": "Webhook מותאם אישית",
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
