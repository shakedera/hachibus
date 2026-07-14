# -*- coding: utf-8 -*-
"""PWAアイコン生成（Pillow使用・バスを模した簡単な図案）
使い方: python scripts/make_icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

BLUE = (22, 86, 160)     # 市バス青 #1656A0
NAVY = (14, 58, 110)     # 濃紺 #0E3A6E
AMBER = (255, 177, 0)    # アンバー #FFB100
WHITE = (255, 255, 255)
DARK = (30, 40, 52)

S = 512
img = Image.new("RGB", (S, S), BLUE)
d = ImageDraw.Draw(img)

# 背景に軽いグラデーション感（下半分を濃紺寄りに）
for y in range(S):
    t = y / S
    r = int(BLUE[0] + (NAVY[0] - BLUE[0]) * t)
    g = int(BLUE[1] + (NAVY[1] - BLUE[1]) * t)
    b = int(BLUE[2] + (NAVY[2] - BLUE[2]) * t)
    d.line([(0, y), (S, y)], fill=(r, g, b))

# バス車体（白・角丸）
body = (72, 152, 440, 372)
d.rounded_rectangle(body, radius=42, fill=WHITE)

# フロントガラス＋側面窓（青）
d.rounded_rectangle((100, 184, 218, 268), radius=18, fill=BLUE)
d.rounded_rectangle((238, 184, 316, 268), radius=18, fill=BLUE)
d.rounded_rectangle((336, 184, 414, 268), radius=18, fill=BLUE)

# 行先表示（アンバーの帯）
d.rounded_rectangle((100, 300, 414, 336), radius=14, fill=AMBER)

# タイヤ
for cx in (156, 356):
    d.ellipse((cx - 44, 330, cx + 44, 418), fill=DARK)
    d.ellipse((cx - 20, 354, cx + 20, 394), fill=WHITE)

img.save(DOCS / "icon-512.png")
img.resize((192, 192), Image.LANCZOS).save(DOCS / "icon-192.png")
print("生成: docs/icon-512.png, docs/icon-192.png")
