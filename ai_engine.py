"""
AI Engine — OCR, PII redaction, Claude AI features.
All functions degrade gracefully when dependencies are missing.
"""
import re
import io
import base64
from typing import Optional, List, Tuple, Dict

from PIL import Image, ImageFilter, ImageDraw

from logger import get_logger
log = get_logger("ai_engine")

# ── Tesseract auto-detection ──────────────────────────────────────────────────
def _setup_tesseract() -> bool:
    """Find and configure Tesseract. Returns True if available."""
    try:
        import pytesseract, subprocess, glob, os
        # Already configured
        try:
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            pass
        # Search common Windows paths
        candidates = (
            glob.glob(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
            + glob.glob(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe")
            + glob.glob(r"C:\Users\*\AppData\Local\Tesseract-OCR\tesseract.exe")
        )
        for path in candidates:
            pytesseract.pytesseract.tesseract_cmd = path
            try:
                pytesseract.get_tesseract_version()
                return True
            except Exception:
                continue
        return False
    except ImportError:
        return False

_TESSERACT_OK: Optional[bool] = None

def _tesseract_available() -> bool:
    global _TESSERACT_OK
    if _TESSERACT_OK is None:
        _TESSERACT_OK = _setup_tesseract()
    return _TESSERACT_OK

def _ocr_langs() -> str:
    """Return available OCR languages (prefer heb+eng, fall back to eng)."""
    try:
        import pytesseract
        available = pytesseract.get_languages()
        if "heb" in available:
            return "heb+eng"
        return "eng"
    except Exception:
        return "eng"

# ── OCR ───────────────────────────────────────────────────────────────────────
def ocr_extract_text(img: Image.Image) -> str:
    """Extract text from image. Returns plain string."""
    if not _tesseract_available():
        return (
            "[Tesseract OCR not installed]\n\n"
            "Install from: https://github.com/UB-Mannheim/tesseract/wiki\n"
            "Then restart SnapCap."
        )
    try:
        import pytesseract
        # Pre-process: convert to RGB, upscale small images for better accuracy
        rgb = img.convert("RGB")
        if rgb.width < 800:
            scale = 800 / rgb.width
            rgb = rgb.resize(
                (int(rgb.width * scale), int(rgb.height * scale)),
                Image.LANCZOS,
            )
        text = pytesseract.image_to_string(rgb, lang=_ocr_langs(),
                                            config="--psm 3 --oem 3")
        return text.strip() or "[No text detected]"
    except Exception as e:
        return f"[OCR error: {e}]"


def ocr_extract_table(img: Image.Image) -> Optional[List[List[str]]]:
    """Extract table structure. Returns list-of-rows or None."""
    if not _tesseract_available():
        return None
    try:
        import pytesseract
        data = pytesseract.image_to_data(
            img.convert("RGB"), output_type=pytesseract.Output.DICT,
            lang=_ocr_langs(), config="--psm 6"
        )
        rows: Dict[Tuple, List] = {}
        for i, word in enumerate(data["text"]):
            word = word.strip()
            if not word or int(data.get("conf", [-1])[i]) < 30:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            rows.setdefault(key, []).append((data["left"][i], word))
        if not rows:
            return None
        sorted_rows = [
            [w for _, w in sorted(rows[k], key=lambda x: x[0])]
            for k in sorted(rows)
        ]
        return sorted_rows if len(sorted_rows) > 1 else None
    except Exception as e:
        log.warning("OCR table extraction failed: %s", e)
        return None


def table_to_csv(table: List[List[str]]) -> str:
    return "\n".join(",".join(f'"{c.replace(chr(34), chr(39))}"' for c in row) for row in table)


def table_to_markdown(table: List[List[str]]) -> str:
    if not table:
        return ""
    header = "| " + " | ".join(table[0]) + " |"
    sep    = "| " + " | ".join("---" for _ in table[0]) + " |"
    rows   = ["| " + " | ".join(r) + " |" for r in table[1:]]
    return "\n".join([header, sep] + rows)


# ── PII Detection & Smart Redaction ───────────────────────────────────────────
PII_PATTERNS: Dict[str, re.Pattern] = {
    "email":       re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
    "phone":       re.compile(r"(\+?\d[\d\s\-\(\)\.]{6,}\d)"),
    "credit_card": re.compile(r"\b(?:\d[ \-]?){13,16}\b"),
    "api_key":     re.compile(r"(?i)(?:sk-|api[_\-]?key|bearer\s+)[A-Za-z0-9_\-]{16,}"),
    "ip_address":  re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "israeli_id":  re.compile(r"\b\d{9}\b"),
    "password":    re.compile(r"(?i)(?:password|passwd|pwd)\s*[:=]\s*\S+"),
    "url_with_token": re.compile(r"https?://[^\s]*(?:token|key|secret|auth)[^\s]*=[^\s&]+"),
}

REDACT_LABELS = {
    "email": "EMAIL", "phone": "PHONE", "credit_card": "CARD",
    "api_key": "KEY", "ip_address": "IP", "israeli_id": "ID",
    "password": "PWD", "url_with_token": "TOKEN",
}


def detect_pii_regions(img: Image.Image, types: List[str] = None) -> List[Dict]:
    """Detect PII in image via OCR. Returns list of {type, text, bbox}."""
    if not _tesseract_available():
        return []
    try:
        import pytesseract
        active = set(types or list(PII_PATTERNS.keys()))
        data = pytesseract.image_to_data(
            img.convert("RGB"), output_type=pytesseract.Output.DICT,
            lang=_ocr_langs()
        )
        findings = []
        for i, word in enumerate(data["text"]):
            word_str = word.strip()
            if not word_str:
                continue
            for t in active:
                pat = PII_PATTERNS.get(t)
                if pat and pat.search(word_str):
                    findings.append({
                        "type": t,
                        "text": word_str,
                        "bbox": (
                            int(data["left"][i]),
                            int(data["top"][i]),
                            int(data["width"][i]),
                            int(data["height"][i]),
                        ),
                    })
                    break  # one match per word is enough
        return findings
    except Exception as e:
        log.warning("PII detection failed: %s", e)
        return []


def redact_regions(img: Image.Image, regions: List[Dict], style: str = "blur") -> Image.Image:
    """Apply visual redaction to detected regions."""
    if not regions:
        return img.copy()
    result = img.copy()
    draw = ImageDraw.Draw(result)
    for r in regions:
        x, y, w, h = r["bbox"]
        pad = 6
        x1, y1 = max(0, x - pad), max(0, y - pad)
        x2, y2 = min(img.width, x + w + pad), min(img.height, y + h + pad)
        if x2 <= x1 or y2 <= y1:
            continue
        crop = result.crop((x1, y1, x2, y2))
        if style == "blur":
            result.paste(crop.filter(ImageFilter.GaussianBlur(radius=14)), (x1, y1))
        elif style == "pixelate":
            tiny = crop.resize((max(1, (x2-x1)//8), max(1, (y2-y1)//8)), Image.NEAREST)
            result.paste(tiny.resize((x2-x1, y2-y1), Image.NEAREST), (x1, y1))
        elif style == "black":
            draw.rectangle([x1, y1, x2, y2], fill=(0, 0, 0))
        elif style == "label":
            draw.rectangle([x1, y1, x2, y2], fill=(30, 30, 30))
            label = REDACT_LABELS.get(r.get("type", ""), "REDACTED")
            draw.text((x1 + 2, y1 + 1), f"[{label}]", fill=(200, 60, 80))
    return result


def auto_redact(
    img: Image.Image,
    types: List[str] = None,
    style: str = "blur",
) -> Tuple[Image.Image, List[Dict]]:
    """Detect PII and redact. Returns (redacted_image, findings_list)."""
    findings = detect_pii_regions(img, types)
    return redact_regions(img, findings, style), findings


# ── Image enhancement helpers ─────────────────────────────────────────────────
def enhance_for_ocr(img: Image.Image) -> Image.Image:
    """Sharpen and increase contrast for better OCR accuracy."""
    from PIL import ImageEnhance
    img = img.convert("RGB")
    img = ImageEnhance.Contrast(img).enhance(1.5)
    img = ImageEnhance.Sharpness(img).enhance(2.0)
    return img


def remove_background(img: Image.Image) -> Image.Image:
    """Simple background removal using numpy thresholding."""
    try:
        import numpy as np
        arr = np.array(img.convert("RGBA"))
        gray = np.mean(arr[:, :, :3], axis=2)
        mask = (gray < 245).astype(np.uint8) * 255
        arr[:, :, 3] = mask
        return Image.fromarray(arr, "RGBA")
    except Exception:
        return img


def add_watermark(img: Image.Image, text: str, opacity: int = 80) -> Image.Image:
    """Add semi-transparent watermark text to bottom-right corner."""
    result = img.copy().convert("RGBA")
    overlay = Image.new("RGBA", result.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    try:
        from PIL import ImageFont
        font = ImageFont.truetype("arial.ttf", max(14, img.width // 40))
    except Exception:
        font = ImageDraw.ImageDraw.font if hasattr(ImageDraw.ImageDraw, "font") else None
    bbox = draw.textbbox((0, 0), text, font=font) if font else (0, 0, len(text)*8, 16)
    tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
    x = img.width - tw - 12
    y = img.height - th - 10
    draw.rectangle([x-4, y-3, x+tw+4, y+th+3], fill=(0, 0, 0, 120))
    draw.text((x, y), text, fill=(255, 255, 255, opacity), font=font)
    return Image.alpha_composite(result, overlay).convert("RGB")


# ── Claude AI Features ────────────────────────────────────────────────────────
def _img_to_base64(img: Image.Image, max_px: int = 1600) -> str:
    """Convert PIL image to base64 PNG, resizing if too large."""
    rgb = img.convert("RGB")
    if max(rgb.size) > max_px:
        rgb.thumbnail((max_px, max_px), Image.LANCZOS)
    buf = io.BytesIO()
    rgb.save(buf, "PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def _claude_vision(img: Image.Image, prompt: str, api_key: str, max_tokens: int = 1024) -> str:
    """Send image + prompt to Claude and return text. Never raises — every
    failure path (missing package, bad key, rate limit, network, etc.)
    degrades to a friendly '[AI Error: ...]' string the caller can display."""
    # `anthropic` is imported on its own, ahead of the API-call try block:
    # the previous version imported it *inside* the same try that the
    # `except anthropic.AuthenticationError` / `except anthropic.RateLimitError`
    # clauses belong to. If the import itself failed (package not installed —
    # a real possibility since it's an optional/cloud-only dependency),
    # Python evaluates `anthropic.AuthenticationError` while matching the
    # ImportError against that clause, which raises a NameError (the name
    # `anthropic` was never bound) — masking the original error and crashing
    # the caller instead of showing a friendly message.
    try:
        import anthropic
    except ImportError:
        log.warning("Claude API call skipped: 'anthropic' package not installed")
        return "[AI Error: The 'anthropic' package is not installed. Run: pip install anthropic]"

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=max_tokens,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": _img_to_base64(img),
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        return response.content[0].text
    except anthropic.AuthenticationError:
        log.warning("Claude API call rejected: invalid API key")
        return "[AI Error: Invalid API key. Check Settings > AI tab.]"
    except anthropic.RateLimitError:
        log.warning("Claude API call rate-limited")
        return "[AI Error: Rate limit reached. Wait a moment and try again.]"
    except Exception as e:
        log.error("Claude API call failed: %s", e, exc_info=True)
        return f"[AI Error: {e}]"


def ai_summarize(img: Image.Image, api_key: str) -> str:
    return _claude_vision(
        img,
        "Describe what you see in this screenshot in 2-3 sentences. "
        "Be concise, factual, and note the app or context if recognisable.",
        api_key,
    )


def ai_alt_text(img: Image.Image, api_key: str) -> str:
    return _claude_vision(
        img,
        "Write a concise accessibility alt-text for this screenshot "
        "(1-2 sentences, suitable for screen readers). Start directly with the description.",
        api_key,
    )


def ai_extract_text_structured(img: Image.Image, api_key: str) -> str:
    return _claude_vision(
        img,
        "Extract ALL visible text from this screenshot. "
        "Use markdown: tables for tabular data, bullet lists for lists, "
        "headers for section titles. Output only the content, no commentary.",
        api_key,
        max_tokens=2048,
    )


def ai_generate_steps(img: Image.Image, api_key: str) -> str:
    return _claude_vision(
        img,
        "If this screenshot shows a process, UI flow, or tutorial, "
        "extract the steps as a numbered list with clear action verbs. "
        "If it's not step-based, describe the key UI elements briefly.",
        api_key,
    )


def ai_smart_title(img: Image.Image, api_key: str) -> str:
    result = _claude_vision(
        img,
        "Generate a short descriptive filename (3-6 words, kebab-case) for this screenshot. "
        "Examples: 'login-error-modal', 'checkout-step3-payment', 'dark-mode-settings'. "
        "Output ONLY the filename, no extension, no quotes.",
        api_key,
    )
    cleaned = re.sub(r"[^a-z0-9\-]", "-", result.strip().lower())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned[:60] or "screenshot"


def ai_bug_report(img: Image.Image, api_key: str) -> str:
    return _claude_vision(
        img,
        "Analyze this screenshot for bugs or UI issues. Generate a concise bug report:\n"
        "**Title:** one-line summary\n"
        "**What's visible:** describe the current state\n"
        "**Issue:** what appears wrong or unexpected\n"
        "**Steps to reproduce:** likely sequence\n"
        "**Severity:** Low / Medium / High\n"
        "If no bug is visible, describe the UI state and mention 'No obvious issue detected.'",
        api_key,
        max_tokens=600,
    )


def ai_translate(img: Image.Image, api_key: str, target_lang: str = "English") -> str:
    return _claude_vision(
        img,
        f"Extract all text from this screenshot and translate it to {target_lang}. "
        "Format: original text → translation. Keep the structure.",
        api_key,
        max_tokens=1500,
    )


def ai_sensitive_check(img: Image.Image, api_key: str) -> str:
    return _claude_vision(
        img,
        "Scan this screenshot for potentially sensitive or confidential information "
        "(passwords, private keys, personal data, confidential docs, internal URLs, etc.). "
        "List each finding with its location and risk level. "
        "If nothing sensitive is found, say 'No sensitive content detected.'",
        api_key,
    )
