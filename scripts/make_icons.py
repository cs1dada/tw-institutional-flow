"""產生 PWA 需要的圖示。

圖形與網站 favicon (index.html) 相同：紅底圓角方塊上，一枚金幣拖著三條速度線往前跑，
呼應網站名稱「跟著錢錢跑」。用 Pillow 直接畫，不依賴 SVG 轉檔工具。
Android 安裝 PWA 時需要 192 與 512 兩種尺寸。

用法：
    python scripts/make_icons.py
"""
import _bootstrap  # noqa: F401
from PIL import Image, ImageDraw, ImageFont

from app import config

OUT_DIR = config.BASE_DIR / "frontend" / "public"

# 與 style.css 的色票、index.html 的 favicon 一致
BG = "#e34948"
COIN = "#ffd34d"
COIN_TEXT = "#b5651d"
WHITE = "#ffffff"

# 圖形以 64x64 為基準座標 (與 favicon 的 SVG viewBox 相同)，實際輸出時等比放大
BASE = 64
CORNER = 14
# 速度線：(x1, y1, x2, y2)
SPEED_LINES = [(8, 30, 20, 30), (12, 39, 22, 39), (8, 48, 18, 48)]
COIN_CENTER = (38, 36)
COIN_RADIUS = 17
# 先放大這個倍數畫，再縮回目標尺寸，邊緣比較平滑
SUPERSAMPLE = 4


def draw_icon(size, art_scale=1.0, rounded=True):
    """畫出指定尺寸的圖示。

    art_scale 用於 maskable 圖示：Android 會把圖示裁成圓形或圓角方形，
    圖案縮小到中間的安全區才不會被裁掉；背景則鋪滿整張。
    rounded 為 False 時背景是直角方形，給 iOS 與 maskable 用 (系統會自己裁形狀)。
    """
    canvas = size * SUPERSAMPLE
    unit = canvas / BASE
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    if rounded:
        draw.rounded_rectangle([0, 0, canvas - 1, canvas - 1], radius=CORNER * unit, fill=BG)
    else:
        draw.rectangle([0, 0, canvas - 1, canvas - 1], fill=BG)

    def pos(x, y):
        """基準座標轉成畫布座標，以中心為準套用 art_scale"""
        center = BASE / 2
        return (
            (center + (x - center) * art_scale) * unit,
            (center + (y - center) * art_scale) * unit,
        )

    scale = unit * art_scale

    # 速度線：白色、圓頭，略帶透明，畫在獨立圖層再疊上去
    lines = Image.new("RGBA", image.size, (0, 0, 0, 0))
    line_draw = ImageDraw.Draw(lines)
    width = round(4 * scale)
    for x1, y1, x2, y2 in SPEED_LINES:
        p1, p2 = pos(x1, y1), pos(x2, y2)
        line_draw.line([p1, p2], fill=(255, 255, 255, 217), width=width)
        for px, py in (p1, p2):
            line_draw.ellipse([px - width / 2, py - width / 2, px + width / 2, py + width / 2],
                              fill=(255, 255, 255, 217))
    image = Image.alpha_composite(image, lines)
    draw = ImageDraw.Draw(image)

    # 金幣：白色外框加黃色本體
    cx, cy = pos(*COIN_CENTER)
    outer = (COIN_RADIUS + 1.5) * scale
    inner = (COIN_RADIUS - 1.5) * scale
    draw.ellipse([cx - outer, cy - outer, cx + outer, cy + outer], fill=WHITE)
    draw.ellipse([cx - inner, cy - inner, cx + inner, cy + inner], fill=COIN)

    # 錢幣上的 $
    font = ImageFont.truetype("arialbd.ttf", round(22 * scale))
    draw.text((cx, cy), "$", font=font, fill=COIN_TEXT, anchor="mm")

    return image.resize((size, size), Image.LANCZOS)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = [
        ("pwa-192.png", 192, 1.0, True),
        ("pwa-512.png", 512, 1.0, True),
        # maskable 版本圖案縮到 78%，被裁成圓形也不會切到金幣
        ("pwa-maskable-512.png", 512, 0.78, False),
        # iOS 會自己裁圓角，給直角方形
        ("apple-touch-icon.png", 180, 1.0, False),
    ]
    for name, size, art_scale, rounded in targets:
        image = draw_icon(size, art_scale, rounded)
        path = OUT_DIR / name
        image.save(path, "PNG")
        print(f"{name}  {size}x{size}  {path.stat().st_size / 1024:.1f} KB")
    print(f"圖示已輸出至 {OUT_DIR}")


main()
