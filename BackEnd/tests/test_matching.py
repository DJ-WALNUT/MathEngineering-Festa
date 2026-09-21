"""매칭 엔진 / 파서 스모크 테스트.

    cd BackEnd && python -m pytest tests -q
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("INGEST_TOKEN", "test-token")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.matching import match_deposit  # noqa: E402
from app.models import (  # noqa: E402
    DEP_AMBIGUOUS,
    DEP_MATCHED,
    DEP_UNMATCHED,
    PAY_PAID,
    PAY_UNDERPAID,
    PAY_UNPAID,
    Participant,
)
from app.parsers import parse_push_payload  # noqa: E402
from app.services import register_deposit, upsert_participant  # noqa: E402
from app.utils import normalize_name, normalize_phone, split_depositor  # noqa: E402


@pytest.fixture()
def app():
    application = create_app()
    application.config.update(TESTING=True)
    with application.app_context():
        db.drop_all()
        db.create_all()
        yield application
        db.session.remove()


def add_participant(name: str, phone: str, member: bool = True) -> Participant:
    participant, _ = upsert_participant({
        "이름": name,
        "전화번호": phone,
        "총학생회비 납부 여부": "납부" if member else "미납",
    })
    db.session.commit()
    return participant


def deposit(name: str, amount: int, balance: int, when: str = "2026-08-01 12:00:00"):
    result, _ = register_deposit(
        occurred_at=datetime.fromisoformat(when),
        amount=amount,
        balance_after=balance,
        raw_name=name,
    )
    db.session.commit()
    return result


# --- 정규화 ---

def test_normalize():
    assert normalize_name(" 홍 길동 ") == "홍길동"
    assert normalize_phone("+82 10-1234-5678") == "01012345678"
    assert split_depositor("홍길동5678") == ("홍길동", "5678")
    assert split_depositor("홍길동 5678") == ("홍길동", "5678")
    assert split_depositor("5678홍길동") == ("홍길동", "5678")
    assert split_depositor("홍길동") == ("홍길동", "")


def test_fee_by_membership(app):
    member = add_participant("김납부", "010-1111-2222", member=True)
    non_member = add_participant("박미납", "010-3333-4444", member=False)
    assert member.expected_amount == 5_000
    assert non_member.expected_amount == 7_000
    assert member.payment_status == PAY_UNPAID


# --- 매칭 4단계 ---

def test_tier1_name_and_phone_suffix(app):
    add_participant("홍길동", "010-1234-5678")
    add_participant("홍길동", "010-9999-0000")  # 동명이인
    result = deposit("홍길동5678", 5_000, 1_000_000)
    assert result.status == DEP_MATCHED
    assert result.allocations[0].participant.phone == "01012345678"


def test_tier2_name_only_with_amount(app):
    add_participant("이순신", "010-2222-3333", member=False)
    result = deposit("이순신", 7_000, 1_000_000)
    assert result.status == DEP_MATCHED
    assert result.allocations[0].participant.payment_status == PAY_PAID


def test_ambiguous_when_amount_mismatch(app):
    add_participant("강감찬", "010-5555-6666")
    result = deposit("강감찬", 30_000, 1_000_000)
    assert result.status == DEP_AMBIGUOUS
    assert "금액 불일치" in result.match_reason


def test_ambiguous_on_homonyms_without_suffix(app):
    add_participant("김철수", "010-1111-1111")
    add_participant("김철수", "010-2222-2222")
    result = deposit("김철수", 5_000, 1_000_000)
    assert result.status == DEP_AMBIGUOUS


def test_unknown_name_is_unmatched(app):
    """입금 1건은 참가자 1명의 것이므로, 금액 조합으로 합산 입금을 추측하지 않는다."""
    add_participant("대표자", "010-7777-8888")
    result = deposit("모르는사람", 90_000, 1_000_000)
    assert result.status == DEP_UNMATCHED
    assert result.match_reason == "일치하는 신청자 없음"


def test_underpaid_when_partial(app):
    """이름+뒷4자리가 확실하면 금액이 모자라도 붙이고 '부족 납입'으로 표시한다."""
    participant = add_participant("정약용", "010-4444-5555")
    result = deposit("정약용5555", 3_000, 1_000_000)
    assert result.status == DEP_MATCHED
    assert participant.payment_status == PAY_UNDERPAID
    assert participant.paid_amount == 3_000


def test_wrong_suffix_falls_back_to_name_and_amount(app):
    """뒷4자리가 학번 등 다른 숫자여도 이름+금액이 맞으면 매칭된다."""
    participant = add_participant("세종대왕", "010-6666-7777")
    result = deposit("세종대왕2021", 5_000, 1_000_000)
    assert result.status == DEP_MATCHED
    assert participant.payment_status == PAY_PAID


def test_second_deposit_completes_payment(app):
    participant = add_participant("유관순", "010-1212-3434")
    deposit("유관순3434", 3_000, 1_000_000, "2026-08-01 12:00:00")
    deposit("유관순3434", 2_000, 1_003_000, "2026-08-02 12:00:00")
    assert participant.paid_amount == 5_000
    assert participant.payment_status == PAY_PAID


# --- 중복 제거 ---

def test_duplicate_fingerprint_is_ignored(app):
    add_participant("중복이", "010-8888-9999")
    first, created_first = register_deposit(
        occurred_at=datetime(2026, 8, 1, 12, 0, 0),
        amount=5_000,
        balance_after=5_000_000,
        raw_name="중복이9999",
    )
    db.session.commit()
    # 같은 입금이 엑셀로 다시 들어옴 (시각이 몇 분 어긋남)
    second, created_second = register_deposit(
        occurred_at=datetime(2026, 8, 1, 12, 3, 0),
        amount=5_000,
        balance_after=5_000_000,
        raw_name="중복이9999",
        source="import",
    )
    db.session.commit()
    assert created_first is True
    assert created_second is False
    assert first.id == second.id


# --- 푸시 파서 ---

@pytest.mark.parametrize(
    "payload,expected_name,expected_amount",
    [
        ({"title": "카카오뱅크", "text": "입금 5,000원 홍길동5678 잔액 1,234,567원"}, "홍길동5678", 5_000),
        ({"title": "입금 7,000원", "text": "이순신1234 | 잔액 2,000,000원"}, "이순신1234", 7_000),
        ({"text": "홍길동5678님이 5,000원을 입금했어요"}, "홍길동5678", 5_000),
        ({"name": "박보검0001", "amount": "5000", "balance": "999,999"}, "박보검0001", 5_000),
    ],
)
def test_push_parser(payload, expected_name, expected_amount):
    parsed = parse_push_payload(payload)
    assert parsed.ok, parsed.reason
    assert parsed.amount == expected_amount
    assert parsed.raw_name == expected_name


def test_push_parser_rejects_withdrawal():
    parsed = parse_push_payload({"title": "카카오뱅크", "text": "출금 12,000원 편의점 잔액 100,000원"})
    assert parsed.ok is False


# --- 본인 조회 API ---

def test_status_endpoint(app):
    add_participant("조회자", "010-1000-2000")
    client = app.test_client()

    hit = client.post("/api/status", json={"name": "조회자", "phone": "010-1000-2000"})
    assert hit.status_code == 200
    assert hit.get_json()["found"] is True
    assert hit.get_json()["participant"]["name"] == "조*자"

    miss = client.post("/api/status", json={"name": "다른사람", "phone": "010-1000-2000"})
    assert miss.get_json()["found"] is False


def test_ingest_requires_token(app):
    client = app.test_client()
    assert client.post("/api/ingest/deposit", json={}).status_code == 401


# --- 뒤풀이가 얹힌 참가비 ---
#
# 뒤풀이비는 별도 안내로 나중에 걷는다. 그래서 뒤풀이 신청자가 지금 보낼 법한
# 금액이 하나가 아니다 — 본 행사비만, 뒤풀이비만, 또는 둘을 합쳐서.


def add_afterparty_participant(name: str, phone: str) -> Participant:
    participant = add_participant(name, phone)
    participant.joins_afterparty = True
    participant.expected_amount = 15_000  # 5,000 + 10,000
    db.session.commit()
    return participant


def test_base_fee_only_is_matched_and_afterparty_stays_unpaid(app):
    participant = add_afterparty_participant("봄이", "010-3030-4040")
    result = deposit("봄이4040", 5_000, 1_000_000)

    assert result.status == DEP_MATCHED
    # 본 행사비는 다 냈다. 뒤풀이비가 비었다고 본 행사까지 미납으로 물들면 안 된다.
    assert participant.payment_status == PAY_PAID
    assert participant.afterparty_status == "UNPAID"
    assert participant.afterparty_prepaid is False


def test_afterparty_fee_sent_later_is_matched_by_amount(app):
    participant = add_afterparty_participant("여름이", "010-5050-6060")
    deposit("여름이6060", 5_000, 1_000_000, "2026-08-01 12:00:00")
    # 별도 안내를 받고 뒤풀이비만 따로 보냈다.
    result = deposit("여름이6060", 10_000, 1_005_000, "2026-08-10 12:00:00")

    assert result.status == DEP_MATCHED
    assert participant.payment_status == PAY_PAID
    assert participant.afterparty_status == "PAID"
    # 두 번에 나눠 낸 사람은 '합산 납부'가 아니다. 안내를 받고 낸 것이다.
    assert participant.afterparty_prepaid is False


def test_lump_sum_is_flagged_as_prepaid(app):
    participant = add_afterparty_participant("가을이", "010-7070-8080")
    result = deposit("가을이8080", 15_000, 1_000_000)

    assert result.status == DEP_MATCHED
    assert participant.payment_status == PAY_PAID
    assert participant.afterparty_status == "PAID"
    # 안내가 나가기 전에 한 번에 보낸 사람. 다시 걷으러 가지 않도록 배지가 붙는다.
    assert participant.afterparty_prepaid is True
