"""로컬 테스트용 데모 데이터 생성기.

두 가지를 한다.

  1. 신청자 8명을 폼 수집 경로(`/api/ingest/form`)로 밀어넣는다.
  2. 그 신청자들에 대응하는 **카카오뱅크 거래내역 형식 엑셀 파일**을 만들어 둔다.
     관리자 페이지 → '거래내역 업로드' 에서 이 파일을 올리면 실제 운영과
     똑같은 경로로 매칭이 돌아간다.

매칭 4단계가 한 번씩 나오도록 까다로운 경우를 일부러 섞어 두었다.

    python scripts/demo_seed.py
    python scripts/demo_seed.py --base-url http://127.0.0.1:8000

주의: 개발용이다. 기본값은 localhost 이며, 그 외 주소로 쏘려면 --i-know 를 붙여야 한다.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Config  # noqa: E402  (.env 를 로드하는 부수효과가 있다)

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
OUTPUT = Path(__file__).resolve().parent.parent / "samples" / "demo-거래내역.xlsx"

# --- 신청자 ---------------------------------------------------------------
# (이름, 전화번호, 총학생회비 납부, 학과, 뒤풀이 참가)
#
# 참가비는 두 겹이다 — 본 행사 5,000원(미납부자 7,000원) 위에 뒤풀이 10,000원.
# 뒤풀이비는 별도 안내로 나중에 걷으므로, 본 행사비만 먼저 낸 사람과 한 번에
# 합쳐 보낸 사람이 섞여 있다. 화면에서 이 둘이 갈려 보이는지 확인하는 데 쓴다.
PARTICIPANTS = [
    ("홍길동", "010-1234-5678", True, "기계공학과", False),
    ("이순신", "010-1111-2222", False, "전기공학과", False),
    ("김철수", "010-3333-4444", True, "컴퓨터공학과", False),   # 동명이인 ①
    ("김철수", "010-5555-6666", True, "화학공학과", False),     # 동명이인 ②
    ("정약용", "010-7777-8888", True, "건축학과", False),
    ("유관순", "010-9999-0000", False, "산업공학과", True),
    ("장영실", "010-2468-1357", True, "신소재공학과", True),
    ("세종대왕", "010-1357-2468", True, "전자공학과", True),
]

# --- 거래내역 행 ----------------------------------------------------------
# (거래일시, 구분, 금액, 내용=입금자명, 메모, 기대 결과 설명)
TRANSACTIONS = [
    ("2026.08.01 09:12:03", "출금", -120000, "○○대관료", "대관 예약금", "출금 → 무시"),
    ("2026.08.01 11:10:21", "입금", 5000, "홍길동5678", None, "1단계 자동 연결"),
    ("2026.08.01 13:40:55", "입금", 7000, "이순신", None, "2단계 자동 연결"),
    ("2026.08.02 10:02:11", "입금", 5000, "김철수", None, "동명이인 특정 불가 → 확인 필요"),
    ("2026.08.02 10:30:47", "입금", 5000, "김철수4444", None, "동명이인 → 뒷4자리로 특정"),
    ("2026.08.02 14:22:09", "입금", 3000, "정약용8888", None, "부분 납입 → 부족 납입"),
    ("2026.08.03 09:05:31", "입금", 4000, "유관순", None, "금액 불일치 → 확인 필요"),
    ("2026.08.03 11:44:02", "입금", 90000, "학부모님", None, "이름 불일치 → 미매칭"),
    ("2026.08.03 15:20:18", "입금", 1500, "당근마켓", None, "소액 잡음 → 기타 입금"),
    ("2026.08.04 08:31:50", "입금", 15000, "장영실2021", None, "뒤풀이비까지 합산 납부"),
    ("2026.08.04 09:10:00", "입금", 5000, "세종대왕2468", None, "본 행사비만 → 뒤풀이비 미납"),
    ("2026.08.04 16:00:00", "출금", -8000, "아성다이소", "물품 구매", "출금 → 무시"),
]


def post(url: str, payload: dict, token: str) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8", "X-Ingest-Token": token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise SystemExit(f"요청 실패 {error.code}: {error.read().decode('utf-8', 'replace')}") from error
    except urllib.error.URLError as error:
        raise SystemExit(
            f"서버에 연결하지 못했습니다 ({url}).\n"
            f"  백엔드가 떠 있는지 확인해 주세요:  python wsgi.py\n"
            f"  원인: {error.reason}"
        ) from error


def build_statement() -> Path:
    """카카오뱅크가 내려주는 것과 같은 배치의 엑셀을 만든다.

    A열은 비우고, 머리말 뒤 11행에 헤더가 오는 실제 구조를 그대로 흉내낸다.
    """
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "카카오뱅크 거래내역"

    sheet["B2"] = "카카오뱅크 거래내역"
    sheet["B4"], sheet["C4"] = "성명", "공과대학 학생회"
    sheet["D4"], sheet["E4"] = "조회기간", "2026.08.01 - 2026.08.05"
    sheet["B5"], sheet["C5"] = "계좌번호", "****-**-***0000"
    sheet["D5"], sheet["E5"] = "요청일시", "2026.08.05 18:03:24"
    sheet["B7"] = "※ 금액앞에 '-' 표시는 출금 금액입니다."
    sheet["B8"] = "※ 본 거래내역은 법적효력이 없는 참고용 문서입니다."

    for offset, title in enumerate(
        ["거래일시", "구분", "거래금액", "거래 후 잔액", "거래구분", "내용", "메모"]
    ):
        sheet.cell(row=11, column=2 + offset, value=title)

    balance = 1_000_000
    for index, (when, kind, amount, name, memo, _note) in enumerate(TRANSACTIONS):
        balance += amount
        values = [
            when,
            kind,
            amount,
            balance,
            "일반입금" if kind == "입금" else "일반이체",
            name,
            memo,
        ]
        for offset, value in enumerate(values):
            sheet.cell(row=12 + index, column=2 + offset, value=value)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(OUTPUT)
    return OUTPUT


def main() -> int:
    # Windows 콘솔이 cp949 로 잡히면 한글이 깨지므로 강제로 UTF-8 로 출력한다.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="로컬 테스트용 데모 데이터 생성")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--i-know", action="store_true", help="localhost 가 아닌 곳에도 주입")
    parser.add_argument("--file-only", action="store_true", help="엑셀만 만들고 서버에 붙지 않음")
    args = parser.parse_args()

    if not args.file_only:
        base = args.base_url.rstrip("/")
        if not any(host in base for host in LOCAL_HOSTS) and not args.i_know:
            print(f"{base} 은 로컬이 아닙니다. 정말이라면 --i-know 를 붙이세요.", file=sys.stderr)
            return 1

        token = Config.INGEST_TOKEN
        if not token:
            print("INGEST_TOKEN 이 비어 있습니다. BackEnd/.env 를 확인해 주세요.", file=sys.stderr)
            return 1

        rows = [
            {
                "row": index + 2,
                "values": {
                    "타임스탬프": f"2026-07-25T10:{index:02d}:00",
                    "이름": name,
                    "전화번호": phone,
                    "학과": department,
                    "학번": f"2026{1000 + index}",
                    "총학생회비를 납부하셨나요?": "납부" if member else "미납",
                    "뒤풀이에 참가하시나요?": "예" if afterparty else "아니오",
                },
            }
            for index, (name, phone, member, department, afterparty) in enumerate(PARTICIPANTS)
        ]
        counts = post(f"{base}/api/ingest/form", {"rows": rows}, token)["result"]
        print(
            f"신청자 {counts['created']}명 등록 / {counts['updated']}명 갱신 "
            f"/ {counts['skipped']}건 제외\n"
        )

    path = build_statement()
    print(f"거래내역 엑셀 생성: {path}")
    print("\n이 파일을 관리자 페이지 → '거래내역 업로드' 에서 올리면 아래처럼 판정됩니다.\n")
    for when, kind, amount, name, _memo, note in TRANSACTIONS:
        mark = "-" if kind == "출금" else "+"
        print(f"  {mark} {when[:16]}  {amount:>8,}원  {name:<12} {note}")

    print(
        "\n확인해 보세요:\n"
        "  관리자 화면  http://localhost:5173/admin\n"
        "  본인 조회    http://localhost:5173/payment  (예: 홍길동 / 010-1234-5678)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
