"""명찰 디자인 원본(PSD) → `public/badge/` 배경 세 장.

명찰은 배경 위에 이름 · 학과 · 조 · QR 만 얹으면 되는 구조다. 그래서 **사람마다
달라지는 것만 지운 배경**을 미리 구워 둔다. 로고 · STAFF/GUEST 띠 · 일정표처럼
효과(그레이디언트 · 엠보싱 · 그림자)가 잔뜩 걸린 것들은 브라우저로 흉내 내면 반드시
어긋나므로, 포토샵이 만든 병합본을 그대로 잘라 쓴다.

지우는 것
  · 앞면 — 이름 · 학과 · 조 (자리는 `src/data/badge.ts` 가 안다)
  · 뒷면 — QR 세 개와 그 받침. 받침은 조금 키워 다시 그린다. 시안의 60px 로는
           모듈 하나가 0.2mm 라 폰이 잘 못 읽는데, 흰 칸(84px) 안에서 조용한 구역
           4모듈을 지키며 키울 수 있는 최대가 64px 이고 받침은 76px 이다.

뒷면은 스태프 · 참가자가 1px 어긋난 것 말고는 같아 한 장만 쓴다. 참가자 아트보드는
스태프보다 2px 아래에서 시작해(1854 가 아니라 1856) 두 앞면의 좌표가 정확히 겹친다.

    pip install psd-tools pillow
    python scripts/build-badge-background.py ~/Downloads/'명찰 최종본.psd'
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw
from psd_tools import PSDImage

OUT = Path(__file__).resolve().parent.parent / "public" / "badge"

W, H = 1240, 1754  # 아트보드 한 장 = A6 @300dpi

# 아트보드 왼쪽 위 (PSD 캔버스 기준)
BOARDS = {
    "front-staff": (0, 0),
    "front-guest": (0, 1856),
    "back": (1340, 0),
}

BAND = (0xF7, 0xF8, 0xF6)   # 이름칸 · 하단 띠
CELL = (0xF9, 0xFC, 0xFE)   # 뒷면 흰 칸
PLATE = (0xC3, 0xDF, 0xE1)  # QR 받침

# 앞면에서 지울 가변 글자 (학과 · 이름 · 조). 안티에일리어싱 자락까지 넉넉히 판다.
VAR_TEXT = [(386, 630, 853, 676), (283, 762, 955, 990), (579, 1062, 655, 1106)]

# 뒷면 — 시안의 QR 받침(지울 것)과 흰 칸 오른쪽 끝(새 받침을 맞출 기준)
OLD_PLATE = [(372, 1578, 444, 1643), (686, 1578, 758, 1643), (1002, 1578, 1074, 1643)]
CELL_RIGHT = [461, 769, 1077]
CELL_MID_Y = (1567 + 1651) // 2
PLATE_SIZE = 76
RIGHT_PAD = 8


def main(source: Path) -> None:
    psd = PSDImage.open(source)
    if (psd.width, psd.height) != (2580, 3609):
        print(f"경고: 예상과 다른 캔버스 {psd.width}×{psd.height}. 좌표를 다시 확인할 것.")

    # 레이어를 따로 합성하지 않고 포토샵이 만든 병합본을 쓴다 — 효과까지 그대로다.
    full = psd.topil().convert("RGB")
    OUT.mkdir(parents=True, exist_ok=True)

    for name, (ox, oy) in BOARDS.items():
        board = Image.new("RGB", (W, H), BAND)
        board.paste(full.crop((ox, oy, ox + W, min(oy + H, psd.height))), (0, 0))
        draw = ImageDraw.Draw(board)

        if name.startswith("front"):
            for x0, y0, x1, y1 in VAR_TEXT:
                draw.rectangle([x0 - 8, y0 - 8, x1 + 8, y1 + 8], fill=BAND)
        else:
            for x0, y0, x1, y1 in OLD_PLATE:
                draw.rectangle([x0 - 6, y0 - 6, x1 + 6, y1 + 6], fill=CELL)
            for cell_right in CELL_RIGHT:  # 셋의 오른쪽 여백을 똑같이 맞춘다
                left = cell_right - RIGHT_PAD - PLATE_SIZE
                top = CELL_MID_Y - PLATE_SIZE // 2
                draw.rectangle([left, top, left + PLATE_SIZE, top + PLATE_SIZE], fill=PLATE)

        path = OUT / f"{name}.png"
        board.save(path, optimize=True)
        print(f"{path.name}  {board.size[0]}×{board.size[1]}  {path.stat().st_size // 1024} KB")

    print("\nbadge.ts 의 뒷면 QR 받침 좌표:")
    for cell_right in CELL_RIGHT:
        print(f"  x: {cell_right - RIGHT_PAD - PLATE_SIZE}, y: {CELL_MID_Y - PLATE_SIZE // 2},"
              f" size: {PLATE_SIZE}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"사용법: python {Path(__file__).name} <명찰.psd>")
    main(Path(sys.argv[1]).expanduser())
