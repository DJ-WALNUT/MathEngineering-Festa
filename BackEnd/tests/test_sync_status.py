"""업로드 이력 · 반영 시점 노출 테스트.

입금 확인은 실시간이 아니다. 참가자가 '왜 미납으로 뜨지?' 하고 오해하지 않도록
언제까지 반영됐는지가 공개 응답에 정확히 담겨야 한다.
"""

from __future__ import annotations

import io
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
from app.security import hash_password  # noqa: E402
from tests.test_kakao_real_format import build_real_format  # noqa: E402

PASSWORD = "mt-admin-1234"
# 최고 관리자 로그인 ID. 비밀번호는 모두 같고 ID 로 사람을 구분한다.
SUPER_ID = "wont0309"
INGEST_HEADERS = {"X-Ingest-Token": "test-token"}

ROWS = [
    ["2026.08.01 11:00:00", "입금", 5000, 1045000, "일반입금", "홍길동5678", None],
    ["2026.08.03 14:20:00", "입금", 7000, 1104000, "일반입금", "이순신1234", None],
    ["2026.08.03 15:00:00", "출금", -3000, 1101000, "체크카드결제", "편의점", None],
]


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
    response = client.post("/api/admin/login", json={"username": SUPER_ID, "password": PASSWORD})
    return {"Authorization": f"Bearer {response.get_json()['token']}"}


def submit_form(client, name: str, phone: str, member: bool = True, row: int = 2):
    return client.post(
        "/api/ingest/form",
        headers=INGEST_HEADERS,
        json={
            "row": row,
            "values": {
                "이름": name,
                "전화번호": phone,
                "총학생회비 납부 여부": "납부" if member else "미납",
            },
        },
    )


def upload(client, headers):
    return client.post(
        "/api/admin/deposits/import",
        headers=headers,
        data={"file": (io.BytesIO(build_real_format(ROWS)), "카카오뱅크_거래내역.xlsx")},
        content_type="multipart/form-data",
    )


def test_sync_status_is_empty_before_any_upload(client):
    body = client.get("/api/sync-status").get_json()
    assert body["hasData"] is False
    assert body["lastImportedAt"] is None
    assert body["coverageUntil"] is None


def test_upload_records_period_and_coverage(client):
    headers = auth_headers(client)
    submit_form(client, "홍길동", "010-1234-5678", row=2)
    submit_form(client, "이순신", "010-1111-1234", member=False, row=3)

    result = upload(client, headers).get_json()
    assert result["created"] == 2
    # 파일 머리말의 조회기간이 읽혀야 한다
    assert result["periodFrom"].startswith("2026-05-01")
    assert result["periodTo"].startswith("2026-05-26")
    # 반영 범위는 파일에 담긴 마지막 '거래' 시각이 기준이다
    assert result["latestTransactionAt"] == "2026-08-03T14:20:00"

    body = client.get("/api/sync-status").get_json()
    assert body["hasData"] is True
    assert body["lastImportedAt"] is not None
    assert body["coverageUntil"] == "2026-08-03T14:20:00"


def test_status_lookup_carries_sync_info(client):
    headers = auth_headers(client)
    submit_form(client, "홍길동", "010-1234-5678")
    upload(client, headers)

    found = client.post(
        "/api/status", json={"name": "홍길동", "phone": "010-1234-5678"}
    ).get_json()
    assert found["found"] is True
    assert found["participant"]["status"] == "PAID"
    assert found["sync"]["coverageUntil"] == "2026-08-03T14:20:00"

    # 신청 내역이 없을 때도 반영 시점은 알려줘야 한다
    # (미납이 아니라 '아직 반영 전'일 수 있으므로)
    missing = client.post(
        "/api/status", json={"name": "없는사람", "phone": "010-0000-0000"}
    ).get_json()
    assert missing["found"] is False
    assert missing["sync"]["hasData"] is True


def test_import_history_is_listed(client):
    headers = auth_headers(client)
    submit_form(client, "홍길동", "010-1234-5678")
    upload(client, headers)
    upload(client, headers)  # 같은 파일 재업로드 → 전부 중복

    items = client.get("/api/admin/imports", headers=headers).get_json()["items"]
    assert len(items) == 2
    assert items[0]["duplicatedCount"] == 2   # 최신순, 두 번째 업로드는 전부 중복
    assert items[0]["createdCount"] == 0
    assert items[0]["filename"] == "카카오뱅크_거래내역.xlsx"


def test_admin_summary_reports_sync(client):
    headers = auth_headers(client)
    submit_form(client, "홍길동", "010-1234-5678")
    upload(client, headers)

    summary = client.get("/api/admin/summary", headers=headers).get_json()
    assert summary["sync"]["hasData"] is True
    assert summary["sync"]["coverageUntil"] == "2026-08-03T14:20:00"
    assert summary["sync"]["pushIngestEnabled"] is False


def test_push_ingest_is_disabled_by_default(client):
    """유심 없는 공기계로는 카카오뱅크 알림을 받을 수 없어 기본적으로 꺼져 있다."""
    response = client.post(
        "/api/ingest/deposit",
        headers=INGEST_HEADERS,
        json={"title": "카카오뱅크", "text": "입금 45,000원 홍길동5678 잔액 1,000원"},
    )
    assert response.status_code == 503
    assert response.get_json()["error"] == "push_ingest_disabled"


def test_push_ingest_still_works_when_enabled(client):
    """유심이 꽂힌 전용 기기를 마련하면 다시 켤 수 있어야 한다."""
    client.application.config["PUSH_INGEST_ENABLED"] = True
    submit_form(client, "홍길동", "010-1234-5678")

    response = client.post(
        "/api/ingest/deposit",
        headers=INGEST_HEADERS,
        json={"title": "카카오뱅크", "text": "입금 45,000원 홍길동5678 잔액 1,000원"},
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "MATCHED"
