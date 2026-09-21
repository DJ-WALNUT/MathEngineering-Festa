"""거래내역 파일 파서 테스트.

카카오뱅크 내려받기 파일은 앞에 계좌 요약 줄이 붙고 컬럼명도 버전마다 다르다.
두 가지 대표 레이아웃(단일 거래금액+구분 / 입금액·출금액 분리)을 모두 검증한다.
"""

from __future__ import annotations

import io
import sys
from datetime import datetime
from pathlib import Path

import msoffcrypto
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.parsers import parse_statement  # noqa: E402

# 비밀번호 관련 테스트가 공유하는 최소 레이아웃
_SIMPLE_ROWS = [
    ["거래일시", "구분", "거래금액", "거래후잔액", "내용"],
    [datetime(2026, 8, 1, 12, 0), "입금", 45000, 1045000, "홍길동5678"],
]


def build_xlsx(rows: list[list]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def lock_xlsx(data: bytes, password: str) -> bytes:
    """카카오뱅크가 내려주는 것과 같은, 열기 비밀번호가 걸린 파일을 만든다."""
    buffer = io.BytesIO()
    msoffcrypto.OfficeFile(io.BytesIO(data)).encrypt(password, buffer)
    return buffer.getvalue()


def test_parse_kind_and_amount_layout():
    data = build_xlsx([
        ["카카오뱅크 거래내역"],
        ["계좌번호", "3333-01-1234567"],
        ["조회기간", "2026-08-01 ~ 2026-08-10"],
        [],
        ["거래일시", "구분", "거래금액", "거래 후 잔액", "내용"],
        [datetime(2026, 8, 1, 12, 0), "입금", 45000, 1045000, "홍길동5678"],
        [datetime(2026, 8, 1, 13, 0), "출금", 12000, 1033000, "편의점"],
        [datetime(2026, 8, 2, 9, 30), "입금", 59000, 1092000, "이순신1234"],
    ])

    result = parse_statement(data, "kakao.xlsx")

    assert result.header_row == 4
    assert len(result.rows) == 2
    assert [row.amount for row in result.rows] == [45000, 59000]
    assert result.rows[0].raw_name == "홍길동5678"
    assert result.rows[0].name_norm == "홍길동"
    assert result.rows[0].digit_suffix == "5678"
    assert result.rows[0].balance_after == 1045000
    assert any("출금" in item["reason"] for item in result.skipped)


def test_parse_split_in_out_layout():
    data = build_xlsx([
        ["거래일자", "입금액", "출금액", "잔액", "적요"],
        ["2026-08-01 12:00:00", "45,000", "", "1,045,000", "홍길동 5678"],
        ["2026-08-01 13:00:00", "", "12,000", "1,033,000", "카드결제"],
    ])

    result = parse_statement(data, "kakao.xlsx")

    assert len(result.rows) == 1
    assert result.rows[0].amount == 45000
    assert result.rows[0].name_norm == "홍길동"
    assert result.rows[0].occurred_at == datetime(2026, 8, 1, 12, 0)


def test_parse_csv_cp949():
    csv_text = (
        "카카오뱅크 거래내역\n"
        "거래일시,구분,거래금액,거래후잔액,내용\n"
        "2026-08-01 12:00:00,입금,45000,1045000,홍길동5678\n"
    )
    result = parse_statement(csv_text.encode("cp949"), "kakao.csv")
    assert len(result.rows) == 1
    assert result.rows[0].amount == 45000


def test_parse_password_protected_xlsx():
    """잠긴 파일을 그대로 올려도 등록된 비밀번호로 열려야 한다."""
    data = lock_xlsx(build_xlsx(_SIMPLE_ROWS), "test-lock-1234")

    # 껍데기가 zip 이 아니라 OLE 복합문서로 바뀐다
    assert data[:4] != b"PK\x03\x04"

    result = parse_statement(data, "kakao.xlsx", passwords=["test-lock-1234"])

    assert result.decrypted is True
    assert len(result.rows) == 1
    assert result.rows[0].amount == 45000
    assert result.rows[0].name_norm == "홍길동"


def test_password_candidates_are_tried_in_order():
    """비밀번호가 바뀌어도 옛 파일을 다시 올릴 수 있어야 한다."""
    data = lock_xlsx(build_xlsx(_SIMPLE_ROWS), "test-lock-1234")

    result = parse_statement(data, "kakao.xlsx", passwords=["999999", "test-lock-1234"])

    assert len(result.rows) == 1


def test_plain_xlsx_is_not_marked_decrypted():
    result = parse_statement(build_xlsx(_SIMPLE_ROWS), "kakao.xlsx", passwords=["test-lock-1234"])
    assert result.decrypted is False
    assert len(result.rows) == 1


def test_locked_file_without_password_raises():
    data = lock_xlsx(build_xlsx(_SIMPLE_ROWS), "test-lock-1234")
    try:
        parse_statement(data, "kakao.xlsx")
    except ValueError as exc:
        assert "비밀번호" in str(exc)
    else:
        raise AssertionError("비밀번호가 없으면 ValueError 를 내야 한다")


def test_locked_file_with_wrong_password_raises():
    data = lock_xlsx(build_xlsx(_SIMPLE_ROWS), "test-lock-1234")
    try:
        parse_statement(data, "kakao.xlsx", passwords=["000000"])
    except ValueError as exc:
        assert "열지 못했습니다" in str(exc)
    else:
        raise AssertionError("비밀번호가 틀리면 ValueError 를 내야 한다")


def test_broken_xlsx_raises_value_error():
    """500 이 아니라 400 으로 나가야 올린 사람이 이유를 안다."""
    try:
        parse_statement(b"PK\x03\x04 not really a workbook", "kakao.xlsx")
    except ValueError:
        pass
    else:
        raise AssertionError("깨진 파일은 ValueError 를 내야 한다")


def test_missing_header_raises():
    data = build_xlsx([["아무", "관계", "없는", "표"], [1, 2, 3, 4]])
    try:
        parse_statement(data, "junk.xlsx")
    except ValueError as exc:
        assert "헤더" in str(exc)
    else:
        raise AssertionError("헤더 없는 파일은 ValueError 를 내야 한다")
