"""產生 PWA 需要的圖示。

沿用網站 favicon 的圖形 (一根紅 K 棒與兩個綠方塊)，用 Pillow 直接畫，
不依賴 SVG 轉檔工具。Android 安裝 PWA 時需要 192 與 512 兩種尺寸。

用法：
    python scripts/make_icons.py
"""
import _bootstrap  # noqa: F401
from PIL import Image, ImageDraw

from app import config

OUT_DIR = config.BASE_DIR / "frontend" / "public"

# 與 style.css 的色票一致
BG = "#fcfcfb"
BUY = "#e34948"
SELL = "#1baf7a"

# 圖形以 32x32 為基準座標，實際輸出時等比放大
BASE = 32
SHAPES = [
    # (x, y, 寬, 高, 顏色)
    (4, 4, 14, 24, BUY),
    (20, 4, 8, 13, SELL),
    (20, 19, 8, 9, SELL),
]
CORNER = 6


def draw_icon(size, padding_ratio=0.0):
    """畫出指定尺寸的圖示。

    padding_ratio 用於 maskable 圖示：Android 會把圖示裁成圓形或圓角方形，
    四周留白才不會被裁掉重要部分。
    """
    image = Image.new("RGBA", (size, size), BG)
    draw = ImageDraw.Draw(image)

    inner = size * (1 - padding_ratio * 2)
    offset = size * padding_ratio
    scale = inner / BASE

    def box(x, y, w, h):
        return [
            offset + x * scale,
            offset + y * scale,
            offset + (x + w) * scale,
            offset + (y + h) * scale,
        ]

    for x, y, w, h, color in SHAPES:
        radius = max(1, int(2 * scale))
        draw.rounded_rectangle(box(x, y, w, h), radius=radius, fill=color)
    return image


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = [
        ("pwa-192.png", 192, 0.0),
        ("pwa-512.png", 512, 0.0),
        # maskable 版本四周留 12%，被裁成圓形也不會切到圖形
        ("pwa-maskable-512.png", 512, 0.12),
        ("apple-touch-icon.png", 180, 0.0),
    ]
    for name, size, padding in targets:
        image = draw_icon(size, padding)
        path = OUT_DIR / name
        image.save(path, "PNG")
        print(f"{name}  {size}x{size}  {path.stat().st_size / 1024:.1f} KB")
    print(f"圖示已輸出至 {OUT_DIR}")


main()
