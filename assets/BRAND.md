# SnapCap — Brand Guide

## Logo

The mark is a gradient circle badge with a white "S", used identically
everywhere the app shows a logo — installer icon, installed `.exe` icon,
taskbar, Desktop/Start Menu shortcuts, system tray icon, splash screen, and
the onboarding wizard. Nothing renders a different mark in a different
place.

| File | Use |
|---|---|
| `logo-mark.svg` | Icon only, full gradient — square contexts (favicon-style, app tiles) |
| `logo-full.svg` | Icon + "SnapCap" wordmark + tagline — horizontal lockup for headers/banners |
| `logo-mono-dark.svg` | Single dark-navy (`#1a1a2e`) fill, white "S" — light backgrounds, print, 1-color contexts |
| `logo-mono-light.svg` | Single white fill, navy "S" — dark backgrounds, dark banners |
| `icon.ico` | Multi-resolution (16/32/48/64/128/256) Windows icon, generated from the same gradient design by `build/create_icon.py` |

`icon.ico` is generated programmatically (Pillow) rather than exported from
the SVGs above — its gradient math and letterform are kept in sync with
`logo-mark.svg` by hand; if the mark design changes, update
`build/create_icon.py`'s `GRAD_START`/`GRAD_END`/font settings to match and
regenerate (`python build/create_icon.py`).

## Color Palette

Two full palettes — dark (default-adjacent) and light — plus a shared accent
that never changes between themes.

| Role | Dark theme | Light theme | Notes |
|---|---|---|---|
| **Primary / Accent** | `#00d9a3` | `#00d9a3` | Brand teal/mint — buttons, active states, primary CTAs. Constant across themes. |
| **Secondary** | `#3b82f6` | `#3b82f6` | Brand blue — gradient partner, hover states. |
| **Surface (background)** | `#1a1a2e` | `#f4f5f9` | Window background. |
| **Surface (panel)** | `#16213e` | `#ffffff` | Side panels, dialogs, cards. |
| **Surface (control)** | `#1f3a6b` | `#e3e7f1` | Buttons, inputs at rest. |
| **Surface (control hover)** | `#3b82f6` | `#c7d2ea` | Buttons, inputs on hover/checked. |
| **Text** | `#eaeaea` | `#1c1c2b` | Primary text color. |
| **Success** | `#1dd1a1` | `#1dd1a1` | AI status "connected", positive confirmations. |
| **Warning** | `#feca57` | `#feca57` | Non-blocking caution states. |
| **Error** | `#ff6b6b` | `#ff6b6b` | Redaction/destructive category, error text. |
| **Info accent** | `#48dbfb` | `#48dbfb` | Share & Export category label. |

Source of truth for the two full theme dictionaries: `editor_window.py`
(`_THEMES["dark"]` / `_THEMES["light"]`), read at runtime via `apply_theme()`.
The gradient used in the logo/tray/splash (`#00d9a3` → `#3b82f6`) is the same
Primary→Secondary pair listed above, just rendered as a diagonal gradient
instead of flat fills.

## Typography

**Segoe UI** everywhere (`QFont("Segoe UI", …)` throughout the codebase) —
Windows' own system font, which already ships with solid Hebrew glyph
coverage, needs no bundling/licensing, and renders identically to what the
user sees in every other native Windows app. (An alternative like
Rubik/Heebo/Assistant/Noto Sans Hebrew was considered per the shared
cross-project font guidance, but switching away from the OS-native font for
a small utility app would add a font-bundling dependency for no visible gain
on Windows 10/11, where Segoe UI's Hebrew support is already good.)

## Usage rules

- Never stretch, recolor, or rotate the mark outside the variants above.
- Minimum clear space around the mark: half the mark's own diameter on all
  sides.
- On a dark background, use `logo-mono-light.svg` or the full-gradient mark
  (both read fine); never use `logo-mono-dark.svg` on dark backgrounds — its
  navy fill disappears.
- The gradient direction is always top-left → bottom-right (135°). Don't
  flip or reverse it.
