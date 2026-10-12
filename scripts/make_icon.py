"""生成应用图标 assets/printdeck.ico。

    python scripts/make_icon.py

用 PIL 直接画：蓝色圆角底板 + 打印纸 + 打印机出纸口，不依赖任何素材。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "printdeck.ico"

BG = (37, 99, 235, 255)      # 蓝
PAPER = (255, 255, 255, 255)  # 白
LINE = (37, 99, 235, 255)     # 纸上的线条用底色，形成镂空感

SIZE = 256


def draw() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 圆角底板
    d.rounded_rectangle([8, 8, SIZE - 8, SIZE - 8], radius=48, fill=BG)

    # 打印纸（带右上折角）
    d.polygon([(72, 36), (150, 36), (184, 70), (184, 140), (72, 140)], fill=PAPER)
    d.polygon([(150, 36), (184, 70), (150, 70)], fill=(191, 219, 254, 255))

    # 纸上的文字行
    for y in (84, 102, 120):
        d.rectangle([92, y, 164, y + 8], fill=LINE)

    # 打印机机身
    d.rounded_rectangle([52, 150, 204, 208], radius=14, fill=PAPER)
    # 出纸口
    d.rectangle([76, 168, 180, 180], fill=BG)
    # 第二张纸
    d.rounded_rectangle([84, 186, 172, 200], radius=6, fill=(219, 234, 254, 255))

    return img


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img = draw()
    img.save(
        OUT,
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
    )
    print(f"图标已生成：{OUT}  {OUT.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
