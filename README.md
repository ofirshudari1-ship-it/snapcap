# SnapCap

A fast, local screenshot tool for Windows — capture, mark up, and grab text off your screen in seconds.

## What it does

SnapCap solves the "I just need this on my screen right now" problem that Windows' built-in Snipping Tool doesn't quite cover. Capture any region, a specific window, the full screen, or a long scrolling page with a global keyboard shortcut that works even while SnapCap is in the background. Need the text instead of the picture? One hotkey runs local OCR on a selected region and copies the text straight to your clipboard — no editor window required. Once you've captured something, a built-in editor lets you highlight, blur, draw arrows and shapes, add text, watermark, remove backgrounds, and automatically detect and redact sensitive information like emails, phone numbers, and API keys before you share it. A pin-to-screen mode keeps any capture floating always-on-top while you work in other windows, and a searchable local library (including search inside OCR'd text) keeps track of everything you've captured.

## Download & install

**[Download the latest version](https://github.com/ofirshudari1-ship-it/snapcap/releases/latest)**

1. Go to the [releases page](https://github.com/ofirshudari1-ship-it/snapcap/releases/latest) and download `SnapCap-Setup-<version>.exe`.
2. Run the installer.
3. Follow the setup wizard (choose your language, installation folder, and shortcuts).
4. Launch SnapCap — that's it.

**System requirements:** Windows 10 or 11. No GPU required. The installer requests administrator rights to install to `C:\Program Files\SnapCap`.

## Key features

- Region, full-screen, window, and long/scrolling screen capture
- Global keyboard shortcuts that work in the background (`Ctrl+Shift+S/F/W/L/T`)
- Quick Text Capture — select a region, get the text on your clipboard instantly via local OCR, no editor needed
- Pin to Screen — float any capture in an always-on-top window; drag to move, scroll to resize
- Full image editor: highlights, blur, arrows/shapes, text annotations, watermark, background removal
- Local OCR with table detection
- Automatic detection and redaction of sensitive info (emails, phone numbers, credit cards, API keys)
- Searchable local screenshot library, including full-text search over OCR'd content
- Share directly to clipboard, Imgur, S3, a custom URL, or a Slack/Teams webhook
- System tray icon with dark/light/system theme support

## Automatic updates

SnapCap checks GitHub for a new release a few seconds after it starts up. If a newer version is available, you'll get a quiet tray notification — click it to open the [releases page](https://github.com/ofirshudari1-ship-it/snapcap/releases) in your browser and grab the update yourself. If you're offline, the check simply fails silently and nothing changes.

## Privacy

SnapCap is local-first: screenshot capture, editing, and OCR all run entirely on your machine and never leave your computer by default.

SnapCap also offers a small set of **optional, opt-in cloud-AI features** (summarizing a capture, generating alt-text, translating text in an image, drafting a bug report, suggesting a smart filename, and scanning for sensitive content) that are turned off by default. Using them requires you to enter your own Anthropic API key in Settings — only then, and only when you explicitly trigger one of these tools, is the image sent to Anthropic's cloud API for processing. Your API key and any other credentials (Imgur, S3, webhook URLs) are encrypted at rest on your machine using Windows DPAPI, tied to your Windows user account.
