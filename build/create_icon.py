"""
Generate the app icon programmatically (no external assets needed).

Must stay visually identical to the gradient "S" badge drawn at runtime in
main.py (_make_tray_icon) and splash_screen.py (_make_logo) — the project
standard requires the SAME logo everywhere: installer icon, installed exe,
taskbar, shortcuts, tray icon, and splash screen, not a different mark in
each place.
"""
from PIL import Image, ImageDraw, ImageFont
import os

sizes = [16, 32, 48, 64, 128, 256]
imgs = []

# Matches the QLinearGradient(0, 0, size, size) stops used in main.py/splash_screen.py
GRAD_START = (0, 217, 163)    # #00d9a3
GRAD_END = (59, 130, 246)     # #3b82f6


def _gradient_disc(size: int) -> Image.Image:
    """A diagonal-gradient circle (top-left to bottom-right), same look as
    the QPainter-drawn version used at runtime."""
    base = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    grad = Image.new("RGB", (size, size))
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * max(size - 1, 1))
            r = int(GRAD_START[0] + (GRAD_END[0] - GRAD_START[0]) * t)
            g = int(GRAD_START[1] + (GRAD_END[1] - GRAD_START[1]) * t)
            b = int(GRAD_START[2] + (GRAD_END[2] - GRAD_START[2]) * t)
            grad.putpixel((x, y), (r, g, b))

    mask = Image.new("L", (size, size), 0)
    mdraw = ImageDraw.Draw(mask)
    margin = max(1, size // 24)
    mdraw.ellipse([margin, margin, size - margin, size - margin], fill=255)

    base.paste(grad, (0, 0), mask)
    return base


for size in sizes:
    img = _gradient_disc(size)
    draw = ImageDraw.Draw(img)
    font_size = int(size * 0.5)
    try:
        font = ImageFont.truetype("arialbd.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()
    text = "S"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - tw) // 2 - bbox[0]
    y = (size - th) // 2 - bbox[1]
    draw.text((x, y), text, fill="white", font=font)
    imgs.append(img)

# icon.ico must sit under assets/ at the project root (build/ is one level
# down from there), matching where main.py, installer, etc. all look for it.
out_dir = os.path.join(os.path.dirname(__file__), "..", "assets")
os.makedirs(out_dir, exist_ok=True)
out_path = os.path.join(out_dir, "icon.ico")
imgs[0].save(
    out_path,
    format="ICO",
    sizes=[(s, s) for s in sizes],
    append_images=imgs[1:],
)
print(f"Icon created: {out_path}")
