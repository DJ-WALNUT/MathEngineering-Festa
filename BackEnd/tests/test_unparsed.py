"""읽지 못한 알림 보관 · 재파싱 테스트.

알림 포워딩 경로는 현재 운영에서 쓰지 않는다. 카카오뱅크가 유심 없는 기기의
로그인을 막고 있어 공기계로 알림을 받을 수 없기 때문이다.
다만 유심이 꽂힌 전용 기기를 마련하면 다시 켤 수 있으므로, 켰을 때
원문 보관과 재파싱이 제대로 도는지는 계속 검증한다.
"""

from __future__ import annotations

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
from app.models import UnparsedNotification  # noqa: E402
from app.security import hash_password  # noqa: E402

PASSWORD = "mt-admin-1234"
# 최고 관리자 로그인 ID. 비밀번호는 모두 같고 ID 로 사람을 구분한다.
SUPER_ID = "wont0309"
INGEST_HEADERS = {"X-Ingest-Token": "test-token"}
# 현재 규칙으로는 읽히지 않는 가상의 신규 문구.
# '도착했어요' 가 입금 키워드 목록에 없어서 초기에는 파싱에 실패한다.
UNKNOWN_TEXT = {"title": "카카오뱅크", "text": "머니가 도착했어요 홍길동5678 45,000원"}


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
        # 이 파일은 포워딩 경로 자체를 검증하므로 켜 둔다 (운영 기본값은 꺼짐)
        PUSH_INGEST_ENABLED=True,
    )
    with application.app_context():
        db.drop_all()
        db.create_all()
        yield application.test_client()
        db.session.remove()


def auth_headers(client) -> dict:
    response = client.post("/api/admin/login", json={"username": SUPER_ID, "password": PASSWORD})
    return {"Authorization": f"Bearer {response.get_json()['token']}"}


def test_unparsed_notification_is_kept(client):
    response = client.post("/api/ingest/deposit", headers=INGEST_HEADERS, json=UNKNOWN_TEXT)

    assert response.status_code == 202
    body = response.get_json()
    assert body["ok"] is False
    assert body["stored"] is True          # 버려지지 않아야 한다
    assert body["unparsedId"] is not None

    headers = auth_headers(client)
    items = client.get("/api/admin/notifications", headers=headers).get_json()["items"]
    assert len(items) == 1
    # 원문이 그대로 남아 실제 문구를 확인할 수 있어야 한다
    assert items[0]["payload"]["text"] == UNKNOWN_TEXT["text"]
    assert "머니가 도착했어요" in items[0]["preview"]


def test_repeated_identical_notification_increments_count(client):
    for _ in range(3):
        client.post("/api/ingest/deposit", headers=INGEST_HEADERS, json=UNKNOWN_TEXT)

    headers = auth_headers(client)
    items = client.get("/api/admin/notifications", headers=headers).get_json()["items"]
    assert len(items) == 1              # 행이 불어나지 않는다
    assert items[0]["receiveCount"] == 3


def test_reparse_recovers_after_rule_fix(client, monkeypatch):
    client.post("/api/ingest/deposit", headers=INGEST_HEADERS, json=UNKNOWN_TEXT)
    headers = auth_headers(client)

    # 규칙을 고쳐 새 문구를 읽을 수 있게 된 상황을 흉내낸다
    import re

    from app.parsers import push as push_parser

    monkeypatch.setattr(
        push_parser,
        "_DEPOSIT_HINTS",
        push_parser._DEPOSIT_HINTS + ("도착했어요",),
    )
    monkeypatch.setattr(
        push_parser,
        "_NAME_PATTERNS",
        (re.compile(r"도착했어요\s*(?P<name>[가-힣A-Za-z][가-힣A-Za-z0-9]{0,29})"),)
        + push_parser._NAME_PATTERNS,
    )

    result = client.post("/api/admin/notifications/reparse", headers=headers).get_json()
    assert result["attempted"] == 1
    assert result["recovered"] == 1

    # 목록에서 사라지고 입금으로 등록되어야 한다
    assert client.get("/api/admin/notifications", headers=headers).get_json()["items"] == []
    deposits = client.get("/api/admin/deposits?status=", headers=headers).get_json()["items"]
    assert len(deposits) == 1
    assert deposits[0]["amount"] == 45_000
    assert deposits[0]["rawName"] == "홍길동5678"


def test_dismiss_removes_from_queue(client):
    client.post("/api/ingest/deposit", headers=INGEST_HEADERS, json=UNKNOWN_TEXT)
    headers = auth_headers(client)
    entry_id = client.get("/api/admin/notifications", headers=headers).get_json()["items"][0]["id"]

    assert client.delete(f"/api/admin/notifications/{entry_id}", headers=headers).status_code == 200
    assert client.get("/api/admin/notifications", headers=headers).get_json()["items"] == []

    # 원문 자체는 남아 있어야 한다
    with client.application.app_context():
        assert db.session.query(UnparsedNotification).count() == 1


def test_summary_reports_unparsed_count(client):
    client.post("/api/ingest/deposit", headers=INGEST_HEADERS, json=UNKNOWN_TEXT)
    headers = auth_headers(client)
    summary = client.get("/api/admin/summary", headers=headers).get_json()
    assert summary["deposits"]["unparsedCount"] == 1


def test_ping_reports_parse_result_without_storing(client):
    headers = auth_headers(client)

    good = client.post(
        "/api/ingest/ping",
        headers=INGEST_HEADERS,
        json={"title": "카카오뱅크", "text": "입금 45,000원 홍길동5678 잔액 1,000원"},
    ).get_json()
    assert good["ok"] is True
    assert good["parse"]["ok"] is True
    assert good["parse"]["amount"] == 45_000
    assert good["parse"]["depositorName"] == "홍길동5678"

    bad = client.post("/api/ingest/ping", headers=INGEST_HEADERS, json=UNKNOWN_TEXT).get_json()
    assert bad["ok"] is True                  # 연결 자체는 정상
    assert bad["parse"]["ok"] is False        # 다만 해석은 실패

    # ping 은 아무것도 저장하지 않는다
    assert client.get("/api/admin/notifications", headers=headers).get_json()["items"] == []
    assert client.get("/api/admin/deposits", headers=headers).get_json()["items"] == []


def test_ping_requires_token(client):
    assert client.post("/api/ingest/ping", json={}).status_code == 401


def test_plain_text_body_is_accepted(client):
    """MacroDroid 가 알림 문구만 text/plain 으로 보내도 동작해야 한다."""
    response = client.post(
        "/api/ingest/deposit",
        headers={**INGEST_HEADERS, "Content-Type": "text/plain; charset=utf-8"},
        data="입금 45,000원 홍길동5678 잔액 1,234,567원".encode("utf-8"),
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["created"] is True


def test_broken_json_still_keeps_the_text(client):
    """알림 문구에 큰따옴표가 섞여 JSON 이 깨져도 원문을 잃지 않아야 한다."""
    broken = '{"title":"카카오뱅크","text":"입금 45,000원 "홍길동"5678 잔액 1,000원"}'
    response = client.post(
        "/api/ingest/deposit",
        headers={**INGEST_HEADERS, "Content-Type": "application/json"},
        data=broken.encode("utf-8"),
    )
    # 깨진 JSON 이어도 본문 전체가 raw 로 들어와 금액까지 읽힌다
    assert response.status_code == 200
    assert response.get_json()["ok"] is True

    headers = auth_headers(client)
    deposits = client.get("/api/admin/deposits?status=", headers=headers).get_json()["items"]
    assert len(deposits) == 1
    assert deposits[0]["amount"] == 45_000
    # 원문이 통째로 보관되어 나중에 사람이 확인할 수 있다
    assert "홍길동" in deposits[0]["rawPayload"]
