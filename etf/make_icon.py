# -*- coding: utf-8 -*-
"""
etf/make_icon.py — 바탕화면 바로가기 아이콘 생성
================================================
바탕화면에 바로가기가 15개쯤 있어서 기본 HTML 아이콘으로는 눈에 안 띈다.
「JGHBM 일일리포트」 전용 아이콘을 만들어 한눈에 찾게 한다.

리포트 본문(make_daily_report.py)과 같은 남색→파랑 계열을 쓴다.
한 번 만들면 끝이라 run_all.py에는 넣지 않는다(수동 실행).

    .venv/Scripts/python.exe etf/make_icon.py
산출: etf/output/jghbm.ico  (그리고 바로가기에 적용하는 PowerShell 안내 출력)
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent.parent
ICO = BASE / "etf" / "output" / "jghbm.ico"

S = 512                      # 큰 캔버스에서 그리고 줄여야 계단이 안 진다
NAVY = (20, 38, 74)
BLUE = (47, 109, 246)
WHITE = (255, 255, 255)


def _font(size: int) -> ImageFont.FreeTypeFont:
    """굵은 한/영 폰트 — 없으면 기본 폰트로 떨어진다(아이콘이라 치명적이지 않다)."""
    for name in ("malgunbd.ttf", "segoeuib.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_icon() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 둥근 사각 바탕 — 위(남색)에서 아래(파랑)로 그라데이션
    grad = Image.new("RGB", (1, S))
    for y in range(S):
        t = y / (S - 1)
        grad.putpixel((0, y), tuple(int(a + (b - a) * t)
                                    for a, b in zip(NAVY, BLUE)))
    grad = grad.resize((S, S))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1],
                                           radius=int(S * 0.22), fill=255)
    img.paste(grad, (0, 0), mask)

    # 상승 꺾은선 — 리포트의 스파크라인과 같은 인상
    pts = [(0.14, 0.70), (0.30, 0.58), (0.44, 0.64), (0.60, 0.40),
           (0.74, 0.46), (0.87, 0.26)]
    xy = [(x * S, y * S) for x, y in pts]
    d.line(xy, fill=WHITE + (235,), width=int(S * 0.045), joint="curve")
    r = S * 0.035
    d.ellipse([xy[-1][0] - r, xy[-1][1] - r, xy[-1][0] + r, xy[-1][1] + r],
              fill=WHITE)

    # HBM 글자 — 아래쪽에 작게
    f = _font(int(S * 0.155))
    t = "HBM"
    box = d.textbbox((0, 0), t, font=f)
    d.text(((S - (box[2] - box[0])) / 2 - box[0], S * 0.735), t,
           font=f, fill=WHITE + (245,))
    return img


def main() -> int:
    ICO.parent.mkdir(parents=True, exist_ok=True)
    img = draw_icon()
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    img.save(ICO, format="ICO", sizes=sizes)
    print(f"아이콘 생성 → {ICO}  (크기 {len(sizes)}종)")
    print("\n바로가기에 적용하려면 (PowerShell):")
    print('  $w = New-Object -ComObject WScript.Shell')
    print(r'  $s = $w.CreateShortcut("$([Environment]::GetFolderPath('
          r"'Desktop'))\JGHBM 일일리포트.lnk\")")
    print(f'  $s.IconLocation = "{ICO}"; $s.Save()')
    return 0


if __name__ == "__main__":
    sys.exit(main())
