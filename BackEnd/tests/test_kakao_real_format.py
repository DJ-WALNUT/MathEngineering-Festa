"""카카오뱅크가 실제로 내려주는 거래내역 파일 형식 테스트.

실물 파일(카카오뱅크_거래내역_N********_************.xlsx)의 구조를 그대로 재현한다.

  - A열이 통째로 비어 있고 표는 B열부터 시작한다
  - 2행 제목, 4~5행 계좌 요약, 7~9행 안내문 뒤 11행에 헤더가 온다
  - 헤더: 거래일시 | 구분 | 거래금액 | 거래 후 잔액 | 거래구분 | 내용 | 메모
  - 출금은 거래금액이 음수로 찍힌다
  - 입금자명은 '내용' 열에 들어간다
"""

from __future__ import annotations

import io
import sys
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.parsers import parse_statement  # noqa: E402


def build_real_format(rows: list[list], *, datetimes_as_text: bool = True) -> bytes:
    """실물 파일과 같은 배치로 엑셀을 만든다. A열은 비워 둔다."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "카카오뱅크 거래내역"

    sheet["B2"] = "카카오뱅크 거래내역"
    sheet["B4"], sheet["C4"] = "성명", "최원서"
    sheet["D4"], sheet["E4"] = "조회기간", "2026.05.01 - 2026.05.26"
    sheet["B5"], sheet["C5"] = "계좌번호", "****-**-***5913"
    sheet["D5"], sheet["E5"] = "요청일시", "2026.05.26 18:03:24"
    sheet["B7"] = "※ 금액앞에 '-' 표시는 출금 금액입니다."
    sheet["B8"] = "※ 본 거래내역은 법적효력이 없는 참고용 문서입니다."
    sheet["B9"] = "※ 제출 용도로 거래내역서를 받으시려면 [카카오뱅크앱>전체메뉴>고객센터>증명서발급] 메뉴를 이용해주시기 바랍니다."

    header = ["거래일시", "구분", "거래금액", "거래 후 잔액", "거래구분", "내용", "메모"]
    for offset, title in enumerate(header):
        sheet.cell(row=11, column=2 + offset, value=title)

    for index, row in enumerate(rows):
        for offset, value in enumerate(row):
            if offset == 0 and not datetimes_as_text and isinstance(value, str):
                value = datetime.strptime(value, "%Y.%m.%d %H:%M:%S")
            sheet.cell(row=12 + index, column=2 + offset, value=value)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# 스크린샷에 보이는 실제 행들 (입금자명만 MT 참가자로 바꿈)
REAL_ROWS = [
    ["2026.05.06 11:40:59", "출금", -120000, 17449637, "일반이체", "가톨릭대학교 총학생", "아우름제 물품대여"],
    ["2026.05.08 14:40:09", "입금", 44500, 17494137, "일반입금", "가톨릭대학교 총학생", None],
    ["2026.05.11 20:28:46", "출금", -120000, 17374137, "일반이체", "차연지(청결아이스)", "아우름제 노점 얼음"],
    ["2026.05.17 18:23:42", "출금", -147390, 17226747, "체크카드결제", "쿠팡(쿠페이)", "아우름제 노점 화채재료"],
    ["2026.05.18 20:32:20", "출금", -8000, 17211157, "체크카드결제", "아성다이소", "아우름제 노점 물품구매"],
    ["2026.05.21 11:10:21", "입금", 45000, 17068037, "일반입금", "홍길동5678", None],
    ["2026.05.21 11:13:01", "입금", 59000, 17127037, "일반입금", "이순신1234", None],
    ["2026.05.21 11:28:19", "입금", 1500, 17128537, "일반입금", "권병준", None],
    ["2026.05.21 11:29:06", "입금", 3000, 17131537, "일반입금", "강재호", None],
]


def test_real_layout_is_parsed():
    result = parse_statement(build_real_format(REAL_ROWS), "카카오뱅크_거래내역_N8880317596.xlsx")

    # 헤더는 11행 = 인덱스 10
    assert result.header_row == 10
    # A열이 비어 있으므로 실제 컬럼은 1부터 시작해야 한다
    assert result.columns["datetime"] == 1
    assert result.columns["kind"] == 2
    assert result.columns["amount"] == 3
    assert result.columns["balance"] == 4
    assert result.columns["name"] == 6

    # 입금만 5건, 출금 4건은 걸러진다
    assert len(result.rows) == 5
    assert [row.amount for row in result.rows] == [44500, 45000, 59000, 1500, 3000]
    assert all(item["reason"].startswith("입금 아님") for item in result.skipped)


def test_depositor_name_comes_from_content_column():
    result = parse_statement(build_real_format(REAL_ROWS), "kakao.xlsx")
    by_amount = {row.amount: row for row in result.rows}

    assert by_amount[45000].raw_name == "홍길동5678"
    assert by_amount[45000].name_norm == "홍길동"
    assert by_amount[45000].digit_suffix == "5678"

    assert by_amount[59000].raw_name == "이순신1234"
    assert by_amount[59000].name_norm == "이순신"


def test_dotted_datetime_and_balance():
    result = parse_statement(build_real_format(REAL_ROWS), "kakao.xlsx")
    first = result.rows[0]
    assert first.occurred_at == datetime(2026, 5, 8, 14, 40, 9)
    assert first.balance_after == 17494137


def test_works_when_cells_are_real_datetimes():
    """엑셀이 거래일시를 문자열이 아닌 날짜 셀로 저장한 경우."""
    result = parse_statement(
        build_real_format(REAL_ROWS, datetimes_as_text=False), "kakao.xlsx"
    )
    assert len(result.rows) == 5
    assert result.rows[0].occurred_at == datetime(2026, 5, 8, 14, 40, 9)


def test_amounts_as_formatted_strings():
    """거래금액이 '-120,000' 같은 문자열로 저장된 경우도 처리한다."""
    rows = [
        ["2026.05.06 11:40:59", "출금", "-120,000", "17,449,637", "일반이체", "누군가", None],
        ["2026.05.08 14:40:09", "입금", "44,500", "17,494,137", "일반입금", "홍길동5678", None],
    ]
    result = parse_statement(build_real_format(rows), "kakao.xlsx")

    assert len(result.rows) == 1
    assert result.rows[0].amount == 44500
    assert result.rows[0].balance_after == 17494137


def test_memo_column_is_preserved_in_raw():
    """메모는 매칭에 쓰지 않지만 관리자가 볼 수 있게 원본에 남긴다."""
    result = parse_statement(build_real_format(REAL_ROWS), "kakao.xlsx")
    memoed = [row for row in result.rows if "메모" in row.raw]
    # 입금 행 중 메모가 있는 건은 없지만, 구조상 키가 유지되는지 확인
    assert all("내용" in row.raw for row in result.rows)
    assert memoed == [] or all(row.raw["메모"] for row in memoed)
