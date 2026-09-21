"""관리자 계정 · 역할군 · 탭 권한.

이 기능이 노리는 것은 침입 차단이 아니라 **책임 추적**이다. 비밀번호는 모두가
같은 것을 쓰고, 로그인 ID 로 누구인지만 밝힌다. 그래서 이 파일이 지키는 계약도
'막혔는가'가 아니라 **'누가 했는지 남는가'와 '누구에게 무엇이 보이는가'** 다.
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
from app.admins import ensure_default_roles, ensure_super_admin  # noqa: E402
from app.extensions import db  # noqa: E402
from app.security import hash_password  # noqa: E402

PASSWORD = "mt-admin-1234"
# 최고 관리자 로그인 ID. 비밀번호는 모두 같고 ID 로 사람을 구분한다.
SUPER_ID = "wont0309"


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
        ensure_super_admin()
        ensure_default_roles()
        yield application.test_client()
        db.session.remove()


def login(client, username: str, password: str = PASSWORD):
    return client.post("/api/admin/login", json={"username": username, "password": password})


def headers_of(client, username: str) -> dict:
    response = login(client, username)
    assert response.status_code == 200, response.get_json()
    return {"Authorization": f"Bearer {response.get_json()['token']}"}


def add_admin(client, headers, username: str, **payload):
    return client.post(
        "/api/admin/admins", headers=headers, json={"username": username, **payload}
    )


def test_super_admin_exists_and_sees_every_tab(client):
    body = login(client, SUPER_ID).get_json()
    assert body["isSuper"] is True
    assert "admins" in body["tabs"]
    assert body["actor"] == "최고 관리자"


def test_super_admin_is_restored_if_the_row_disappears(client):
    """DB 를 직접 손대다 이 행이 사라지면 아무도 권한을 줄 수 없게 된다."""
    from app.models import AdminAccount

    db.session.query(AdminAccount).delete()
    db.session.commit()

    assert login(client, SUPER_ID).status_code == 200


def test_unknown_id_is_rejected_even_with_the_right_password(client):
    response = login(client, "정체불명")
    assert response.status_code == 401
    assert response.get_json()["error"] == "unknown_admin"


def test_audit_records_the_person_not_admin(client):
    """이 기능의 목적. 지금까지 모든 조작이 'admin' 한 이름으로 뭉쳐 있었다."""
    super_headers = headers_of(client, SUPER_ID)
    assert add_admin(client, super_headers, "홍길동", displayName="홍길동").status_code == 201

    headers = headers_of(client, "홍길동")
    client.post(
        "/api/admin/participants",
        headers=headers,
        json={"name": "참가자", "phone": "010-1234-5678"},
    )

    audit = client.get("/api/admin/audit", headers=super_headers).get_json()["items"]
    entry = next(item for item in audit if item["action"] == "participant.create")
    assert entry["actor"] == "홍길동"


def test_id_is_matched_loosely(client):
    """이름을 ID 로 쓰므로 '홍 길동' 처럼 띄어 쓰는 사람이 나온다."""
    super_headers = headers_of(client, SUPER_ID)
    add_admin(client, super_headers, "홍길동", displayName="홍길동")

    assert login(client, " 홍 길동 ").status_code == 200
    assert login(client, "WONT0309").status_code == 200


def test_role_decides_which_tabs_are_open(client):
    super_headers = headers_of(client, SUPER_ID)
    roles = client.get("/api/admin/admins", headers=super_headers).get_json()["roles"]
    member = next(role for role in roles if role["name"] == "국원")

    add_admin(client, super_headers, "김국원", displayName="김국원", roleId=member["id"])
    body = login(client, "김국원").get_json()
    assert body["tabs"] == member["tabs"]
    assert body["isSuper"] is False
    assert "admins" not in body["tabs"]

    # 역할의 탭을 고치면 그 역할을 쓰는 사람 전원이 함께 바뀐다 — 역할군을 두는 이유다.
    client.patch(
        f"/api/admin/roles/{member['id']}",
        headers=super_headers,
        json={"tabs": ["summary", "participants"]},
    )
    assert login(client, "김국원").get_json()["tabs"] == ["summary", "participants"]


def test_personal_tabs_win_over_the_role(client):
    super_headers = headers_of(client, SUPER_ID)
    roles = client.get("/api/admin/admins", headers=super_headers).get_json()["roles"]
    member = next(role for role in roles if role["name"] == "국원")

    add_admin(
        client, super_headers, "이차장", displayName="이차장",
        roleId=member["id"], tabs=["deposits", "audit"],
    )
    assert login(client, "이차장").get_json()["tabs"] == ["deposits", "audit"]


def test_only_the_super_admin_can_hand_out_permissions(client):
    """탭 권한은 화면을 가릴 뿐이지만, 권한을 스스로 올리는 길만은 막는다."""
    super_headers = headers_of(client, SUPER_ID)
    add_admin(client, super_headers, "홍길동", displayName="홍길동")
    headers = headers_of(client, "홍길동")

    assert client.get("/api/admin/admins", headers=headers).status_code == 403
    assert add_admin(client, headers, "새관리자").status_code == 403
    assert client.post(
        "/api/admin/roles", headers=headers, json={"name": "내맘대로"}
    ).status_code == 403

    # 명단 같은 일반 API 는 그대로 쓸 수 있다 (탭 권한은 화면 기준이다)
    assert client.get("/api/admin/participants", headers=headers).status_code == 200


def test_super_admin_cannot_be_removed_or_disabled(client):
    headers = headers_of(client, SUPER_ID)
    accounts = client.get("/api/admin/admins", headers=headers).get_json()["accounts"]
    super_account = next(item for item in accounts if item["isSuper"])

    assert client.delete(
        f"/api/admin/admins/{super_account['id']}", headers=headers
    ).status_code == 400
    assert client.patch(
        f"/api/admin/admins/{super_account['id']}", headers=headers, json={"isActive": False}
    ).status_code == 400


def test_disabled_account_cannot_get_in_or_keep_working(client):
    """권한을 내린 것이 상대가 로그아웃할 때까지 기다리지 않고 곧바로 들어야 한다."""
    super_headers = headers_of(client, SUPER_ID)
    created = add_admin(client, super_headers, "홍길동", displayName="홍길동").get_json()
    headers = headers_of(client, "홍길동")
    assert client.get("/api/admin/participants", headers=headers).status_code == 200

    client.patch(
        f"/api/admin/admins/{created['id']}", headers=super_headers, json={"isActive": False}
    )

    # 이미 손에 쥔 토큰도 그 순간부터 막힌다
    assert client.get("/api/admin/participants", headers=headers).status_code == 401
    assert login(client, "홍길동").status_code == 401


def test_duplicate_id_is_rejected(client):
    headers = headers_of(client, SUPER_ID)
    assert add_admin(client, headers, "홍길동", displayName="홍길동").status_code == 201
    assert add_admin(client, headers, "홍길동", displayName="다른 홍길동").status_code == 409


def test_role_in_use_cannot_be_deleted(client):
    """지우면 그 사람들의 권한이 조용히 사라진다. 먼저 옮기게 한다."""
    headers = headers_of(client, SUPER_ID)
    roles = client.get("/api/admin/admins", headers=headers).get_json()["roles"]
    member = next(role for role in roles if role["name"] == "국원")
    add_admin(client, headers, "김국원", displayName="김국원", roleId=member["id"])

    response = client.delete(f"/api/admin/roles/{member['id']}", headers=headers)
    assert response.status_code == 400
    assert response.get_json()["error"] == "role_in_use"
    assert "김국원" in response.get_json()["message"]
