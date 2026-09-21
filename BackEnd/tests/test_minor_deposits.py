"""소액 '기타 입금' 분리 테스트.

계좌를 참가비 전용으로 쓰지 않으면 1,500원짜리 잡음이 확인 필요 큐를 덮어버린다.
그렇다고 버리면 "5천원 보냈는데요" 하는 문의에 답할 수 없다.
그래서 버리지 않고 갈라 두기만 한다 — 그 동작을 검증한다.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("INGEST_TOKEN", "test-token")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.security import hash_password  # noqa: E402
from tests.test_kakao_real_format import build_real_format  # noqa: E402

PASSWORD = "mt-admin-1234"
# 최고 관리자 로그인 ID. 비밀번호는 모두 같고 ID 로 사람을 구분한다.
SUPER_ID = "wont0309"
INGEST_HEADERS = {"X-Ingest-Token": "test-token"}


@pytest.fixture()
def client():
    application = create_app()
    application.config.update(
        TESTING=True,
        ADMIN_PASSWORD_HASH=hash_password(PASSWORD),
        # 등급별 비밀번호는 test_admin_tiers.py 가 따로 지킨다. 여기서는 둘을 같게 두어
        # 이 파일이 보는 계약(누가 했는지 · 무엇이 보이는지)만 남긴다.
        STAFF_PASSWORD_HASH=hash_password(PASSWORD),
        LOGIN_RATE_LIMIT="1000 per minute",
        LOOKUP_RATE_LIMIT="1000 per minute",
    )
    with application.app_context():
        db.drop_all()
        db.create_all()
        yield application.test_client()
        db.session.remove()


def auth_headers(client) -> dict:
    return {
        "Authorization": f"Bearer {client.post('/api/admin/login', json={'username': SUPER_ID, 'password': PASSWORD}).get_json()['token']}"
    }


def submit_form(client, name: str, phone: str, member: bool = True, row: int = 2):
    return client.post(
        "/api/ingest/form",
        headers=INGEST_HEADERS,
        json={
            "row": row,
            "values": {
                "이름": name,
                "전화번호": phone,
                "총학생회비 납부": "납부" if member else "미납",
            },
        },
    )


def row(when: str, amount: int, balance: int, name: str) -> list:
    return [when, "입금", amount, balance, "일반입금", name, None]


def upload(client, headers, rows):
    return client.post(
        "/api/admin/deposits/import",
        headers=headers,
        data={"file": (io.BytesIO(build_real_format(rows)), "kakao.xlsx")},
        content_type="multipart/form-data",
    )


def statuses(client, headers, status: str = "") -> list[dict]:
    return client.get(f"/api/admin/deposits?status={status}", headers=headers).get_json()["items"]


def test_small_unknown_deposits_become_minor(client):
    headers = auth_headers(client)
    submit_form(client, "홍길동", "010-1234-5678")

    upload(
        client,
        headers,
        [
            row("2026.08.01 11:00:00", 5000, 1045000, "홍길동5678"),  # 정상 매칭
            row("2026.08.01 11:10:00", 1500, 1046500, "박정현"),       # 소액 잡음
            row("2026.08.01 11:20:00", 2000, 1048500, "강재호"),       # 소액 잡음
            row("2026.08.01 11:30:00", 90000, 1138500, "학부모님"),    # 큰 금액 → 확인 필요
        ],
    )

    by_status = {item["id"]: item["status"] for item in statuses(client, headers)}
    counts: dict[str, int] = {}
    for value in by_status.values():
        counts[value] = counts.get(value, 0) + 1

    assert counts["MATCHED"] == 1
    assert counts["MINOR"] == 2
    assert counts["UNMATCHED"] == 1

    # 확인 필요 큐에는 소액이 끼지 않아야 한다
    review = statuses(client, headers, "REVIEW")
    assert len(review) == 1
    assert review[0]["rawName"] == "학부모님"


def test_minor_deposits_are_still_visible_and_listed(client):
    """버린 것이 아니라 갈라 둔 것이므로 언제든 조회할 수 있어야 한다."""
    headers = auth_headers(client)
    upload(client, headers, [row("2026.08.01 11:10:00", 1500, 1001500, "박정현")])

    minor = statuses(client, headers, "MINOR")
    assert len(minor) == 1
    assert minor[0]["rawName"] == "박정현"
    assert minor[0]["amount"] == 1500
    assert "소액 입금" in minor[0]["matchReason"]

    # 전체 목록에도 그대로 들어 있다
    assert len(statuses(client, headers)) == 1


def test_small_deposit_with_matching_name_is_not_minor(client):
    """이름이 맞으면 금액이 작아도 사람이 봐야 한다 (부분 납입일 수 있다)."""
    headers = auth_headers(client)
    submit_form(client, "정약용", "010-7777-8888")

    upload(client, headers, [row("2026.08.01 11:00:00", 2000, 1002000, "정약용8888")])

    items = statuses(client, headers)
    assert items[0]["status"] == "MATCHED"     # 이름+뒷4자리가 확실하므로 연결된다

    participants = client.get("/api/admin/participants", headers=headers).get_json()["items"]
    assert participants[0]["status"] == "UNDERPAID"
    assert participants[0]["paidAmount"] == 2000


def test_small_deposit_with_name_only_match_stays_in_review(client):
    """이름만 맞고 금액이 안 맞는 소액은 확인 필요로 남아야 한다."""
    headers = auth_headers(client)
    submit_form(client, "유관순", "010-9999-0000", member=False)

    upload(client, headers, [row("2026.08.01 11:00:00", 5000, 1005000, "유관순")])

    items = statuses(client, headers)
    assert items[0]["status"] == "AMBIGUOUS"
    assert len(statuses(client, headers, "REVIEW")) == 1


def test_late_signup_rescues_minor_deposit(client):
    """소액을 먼저 보내고 나중에 신청서를 낸 경우, 기타 입금에서 다시 꺼내와야 한다."""
    headers = auth_headers(client)
    upload(client, headers, [row("2026.08.01 11:00:00", 2000, 1002000, "늦은신청1234")])
    assert statuses(client, headers)[0]["status"] == "MINOR"

    # 신청서 제출 → 자동 재매칭
    submit_form(client, "늦은신청", "010-0000-1234")

    item = statuses(client, headers)[0]
    assert item["status"] == "MATCHED"
    assert "이름+전화 뒷4자리 일치" in item["matchReason"]


def test_admin_can_pull_minor_back_into_queue(client):
    """관리자가 직접 확인 필요로 되돌릴 수 있어야 한다."""
    headers = auth_headers(client)
    upload(client, headers, [row("2026.08.01 11:10:00", 1500, 1001500, "박정현")])
    deposit_id = statuses(client, headers, "MINOR")[0]["id"]

    response = client.patch(
        f"/api/admin/deposits/{deposit_id}", headers=headers, json={"status": "UNMATCHED"}
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "UNMATCHED"
    assert len(statuses(client, headers, "REVIEW")) == 1


def test_summary_separates_minor_from_review(client):
    headers = auth_headers(client)
    upload(
        client,
        headers,
        [
            row("2026.08.01 11:10:00", 1500, 1001500, "박정현"),
            row("2026.08.01 11:20:00", 90000, 1091500, "학부모님"),
        ],
    )

    deposits = client.get("/api/admin/summary", headers=headers).get_json()["deposits"]
    assert deposits["needsReview"] == 1        # 소액은 빠져 있다
    assert deposits["minorCount"] == 1
    assert deposits["minorThreshold"] == 3_000


def test_threshold_zero_disables_the_split(client):
    """0 으로 두면 기능 자체가 꺼져 전부 확인 필요로 남는다."""
    client.application.config["MINOR_DEPOSIT_THRESHOLD"] = 0
    headers = auth_headers(client)
    upload(client, headers, [row("2026.08.01 11:10:00", 1500, 1001500, "박정현")])

    assert statuses(client, headers)[0]["status"] == "UNMATCHED"
