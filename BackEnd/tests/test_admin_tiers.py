"""로그인 등급 — 국장단 비밀번호와 국원 비밀번호.

ID 구분이 '누가 했는지'를 남기는 장치라면, 등급은 **진짜 문**이다. 국원에게
알려 준 비밀번호로 예산·명단·관리자 화면까지 열리면 나눈 의미가 없다.
그래서 이 파일이 지키는 계약은 두 줄이다.

    · 계정의 등급과 입력한 비밀번호의 등급이 같아야만 들어온다
    · 국원용 비밀번호를 아직 .env 에 넣지 않았다면 예전과 똑같이 동작한다
      (배포한 .env 를 못 고친 채 재배포되어도 아무도 문 밖에 서지 않는다)
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
from app.admins import (  # noqa: E402
    TIER_LEAD,
    TIER_STAFF,
    ensure_default_roles,
    ensure_role_tiers,
    ensure_super_admin,
)
from app.extensions import db  # noqa: E402
from app.models import AdminRole  # noqa: E402
from app.security import hash_password  # noqa: E402

LEAD_PASSWORD = "mt-lead-1234"
STAFF_PASSWORD = "mt-staff-1234"
SUPER_ID = "wont0309"


def make_client(*, staff_hash: str | None):
    application = create_app()
    application.config.update(
        TESTING=True,
        ADMIN_PASSWORD_HASH=hash_password(LEAD_PASSWORD),
        STAFF_PASSWORD_HASH=staff_hash or "",
        LOGIN_RATE_LIMIT="1000 per minute",
        LOOKUP_RATE_LIMIT="1000 per minute",
    )
    return application


@pytest.fixture()
def client():
    """등급이 실제로 나뉜 상태 — 비밀번호가 둘 다 있다."""
    application = make_client(staff_hash=hash_password(STAFF_PASSWORD))
    with application.app_context():
        db.drop_all()
        db.create_all()
        ensure_super_admin()
        ensure_default_roles()
        yield application.test_client()
        db.session.remove()


@pytest.fixture()
def shared_client():
    """국원용 비밀번호를 아직 넣지 않은 상태 — 등급을 나누기 전과 같아야 한다."""
    application = make_client(staff_hash=None)
    with application.app_context():
        db.drop_all()
        db.create_all()
        ensure_super_admin()
        ensure_default_roles()
        yield application.test_client()
        db.session.remove()


def login(client, username: str, password: str):
    return client.post("/api/admin/login", json={"username": username, "password": password})


def super_headers(client) -> dict:
    body = login(client, SUPER_ID, LEAD_PASSWORD).get_json()
    return {"Authorization": f"Bearer {body['token']}"}


def role_named(client, headers, name: str) -> dict:
    roles = client.get("/api/admin/admins", headers=headers).get_json()["roles"]
    return next(role for role in roles if role["name"] == name)


def add_admin(client, headers, username: str, role_id: int | None = None):
    return client.post(
        "/api/admin/admins",
        headers=headers,
        json={"username": username, "displayName": username, "roleId": role_id},
    )


# ---------------------------------------------------------------------------
# 두 비밀번호가 갈린다
# ---------------------------------------------------------------------------

def test_default_roles_are_split_into_two_tiers(client):
    headers = super_headers(client)
    tiers = {role["name"]: role["tier"] for role in
             client.get("/api/admin/admins", headers=headers).get_json()["roles"]}
    assert tiers == {
        "학생회장": TIER_LEAD,
        "국장": TIER_LEAD,
        "차장": TIER_LEAD,
        "국원": TIER_STAFF,
    }


def test_staff_member_uses_the_staff_password(client):
    headers = super_headers(client)
    member = role_named(client, headers, "국원")
    assert add_admin(client, headers, "김국원", member["id"]).status_code == 201

    body = login(client, "김국원", STAFF_PASSWORD)
    assert body.status_code == 200
    assert body.get_json()["tier"] == TIER_STAFF

    # 국장단 비밀번호로는 들어올 수 없다. 낮은 문에 높은 열쇠도 맞지 않는다 —
    # 어느 쪽 문에 어느 열쇠인지가 흐려지면 등급을 나눈 의미가 없다.
    rejected = login(client, "김국원", LEAD_PASSWORD)
    assert rejected.status_code == 401
    assert rejected.get_json()["error"] == "wrong_tier"


def test_the_staff_password_does_not_open_a_lead_account(client):
    """이 기능의 전부. 국원에게 알려 준 비밀번호로는 국장 화면이 열리지 않는다."""
    headers = super_headers(client)
    lead_role = role_named(client, headers, "국장")
    add_admin(client, headers, "박국장", lead_role["id"])

    response = login(client, "박국장", STAFF_PASSWORD)
    assert response.status_code == 401
    assert response.get_json()["error"] == "wrong_tier"
    assert "국장단" in response.get_json()["message"]

    assert login(client, "박국장", LEAD_PASSWORD).status_code == 200


def test_the_staff_password_does_not_open_the_super_admin(client):
    response = login(client, SUPER_ID, STAFF_PASSWORD)
    assert response.status_code == 401
    assert response.get_json()["error"] == "wrong_tier"


def test_account_without_a_role_is_treated_as_staff(client):
    """자리를 아직 못 정한 사람에게 높은 열쇠를 줄 이유가 없다."""
    headers = super_headers(client)
    add_admin(client, headers, "신입", None)

    assert login(client, "신입", LEAD_PASSWORD).status_code == 401
    assert login(client, "신입", STAFF_PASSWORD).get_json()["tier"] == TIER_STAFF


def test_changing_a_role_tier_changes_which_password_its_people_use(client):
    """사람이 아니라 역할군에 등급을 매기는 이유 — 한 번 고치면 전원이 함께 바뀐다."""
    headers = super_headers(client)
    member = role_named(client, headers, "국원")
    add_admin(client, headers, "김국원", member["id"])
    assert login(client, "김국원", STAFF_PASSWORD).status_code == 200

    response = client.patch(
        f"/api/admin/roles/{member['id']}", headers=headers, json={"tier": TIER_LEAD}
    )
    assert response.status_code == 200
    assert response.get_json()["tier"] == TIER_LEAD

    assert login(client, "김국원", STAFF_PASSWORD).status_code == 401
    assert login(client, "김국원", LEAD_PASSWORD).status_code == 200


def test_a_tier_change_cuts_off_the_session_already_in_hand(client):
    """탭 권한과 같은 원칙 — 내린 것이 상대가 로그아웃할 때까지 기다리면 안 된다."""
    headers = super_headers(client)
    member = role_named(client, headers, "국원")
    add_admin(client, headers, "김국원", member["id"])

    token = login(client, "김국원", STAFF_PASSWORD).get_json()["token"]
    mine = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/admin/participants", headers=mine).status_code == 200

    client.patch(f"/api/admin/roles/{member['id']}", headers=headers, json={"tier": TIER_LEAD})

    response = client.get("/api/admin/participants", headers=mine)
    assert response.status_code == 401
    assert response.get_json()["error"] == "tier_changed"
    assert client.get("/api/admin/session", headers=mine).status_code == 401

    # 올라간 사람은 위쪽 비밀번호를 안다는 것을 한 번 보여야 한다
    assert login(client, "김국원", LEAD_PASSWORD).status_code == 200


def test_tier_change_is_written_to_the_audit_log(client):
    """비밀번호가 바뀌는 변경이다. 탭을 고치는 것과 무게가 다르다."""
    headers = super_headers(client)
    member = role_named(client, headers, "국원")
    client.patch(f"/api/admin/roles/{member['id']}", headers=headers, json={"tier": TIER_LEAD})

    audit = client.get("/api/admin/audit", headers=headers).get_json()["items"]
    entry = next(item for item in audit if item["action"] == "admin_role.update")
    assert "등급" in str(entry["detail"])


def test_unknown_tier_is_rejected(client):
    """조용히 국원으로 떨어뜨리면 올렸다고 믿는 채로 아닌 상태가 된다."""
    headers = super_headers(client)
    member = role_named(client, headers, "국원")
    response = client.patch(
        f"/api/admin/roles/{member['id']}", headers=headers, json={"tier": "superuser"}
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_tier"


def test_new_role_defaults_to_staff(client):
    headers = super_headers(client)
    created = client.post(
        "/api/admin/roles", headers=headers, json={"name": "임시", "tabs": ["attendance"]}
    )
    assert created.get_json()["tier"] == TIER_STAFF


def test_wrong_password_still_hides_who_the_admins_are(client):
    """비밀번호부터 맞아야 계정 존재 여부를 알 수 있다는 성질은 그대로 남는다."""
    response = login(client, "박국장", "아무거나")
    assert response.status_code == 401
    assert response.get_json()["error"] == "invalid_credentials"


# ---------------------------------------------------------------------------
# 국원용 비밀번호를 아직 넣지 않았다면
# ---------------------------------------------------------------------------

def test_without_a_staff_hash_everyone_shares_the_admin_password(shared_client):
    headers = super_headers(shared_client)
    member = role_named(shared_client, headers, "국원")
    add_admin(shared_client, headers, "김국원", member["id"])

    assert login(shared_client, "김국원", LEAD_PASSWORD).status_code == 200
    assert login(shared_client, SUPER_ID, LEAD_PASSWORD).status_code == 200


def test_the_admin_screen_says_whether_the_tiers_are_really_split(client, shared_client):
    """화면이 '나눴다'고 말하는데 실제로는 안 나뉜 상태를 숨기면 안 된다."""
    assert client.get(
        "/api/admin/admins", headers=super_headers(client)
    ).get_json()["tiersSeparated"] is True
    assert shared_client.get(
        "/api/admin/admins", headers=super_headers(shared_client)
    ).get_json()["tiersSeparated"] is False


# ---------------------------------------------------------------------------
# 쓰던 DB 를 이어받을 때
# ---------------------------------------------------------------------------

def test_existing_roles_get_their_tier_back(client):
    """등급 컬럼은 뒤늦게 붙는다. 비어 있는 채로 두면 학생회장이 국원으로 밀린다."""
    custom = AdminRole(name="기획단", position=99)
    db.session.add(custom)
    db.session.query(AdminRole).update({AdminRole.tier: None})
    db.session.commit()

    filled = ensure_role_tiers()
    assert len(filled) == 5

    tiers = {role.name: role.tier for role in db.session.query(AdminRole).all()}
    assert tiers["학생회장"] == TIER_LEAD
    assert tiers["국장"] == TIER_LEAD
    assert tiers["차장"] == TIER_LEAD
    assert tiers["국원"] == TIER_STAFF
    # 학생회가 직접 만든 역할군은 모르는 것이므로 낮은 쪽에 둔다
    assert tiers["기획단"] == TIER_STAFF

    # 한 번 채운 뒤에는 건드리지 않는다 — 화면에서 내린 등급이 되살아나면 안 된다
    db.session.query(AdminRole).filter(AdminRole.name == "국장").update({AdminRole.tier: TIER_STAFF})
    db.session.commit()
    assert ensure_role_tiers() == []
    assert role_by_name("국장").tier == TIER_STAFF


def test_renamed_default_roles_keep_their_tier(client):
    """이름을 고쳐 쓰는 경우가 흔하다 — 이 학생회는 국장·국원을 '단장'·'단원'으로 쓴다.

    이름으로만 되짚으면 단장이 국원 비밀번호로 밀린다. 기본 역할군의 자리(10·20·30·40)는
    고정이고 새로 만든 역할군은 50 부터 붙으므로, 자리로 원래 무엇이었는지 알 수 있다.
    """
    renamed = {"국장": "단장", "국원": "단원"}
    for old_name, new_name in renamed.items():
        db.session.query(AdminRole).filter(AdminRole.name == old_name).update(
            {AdminRole.name: new_name, AdminRole.tier: None}
        )
    db.session.commit()

    ensure_role_tiers()
    assert role_by_name("단장").tier == TIER_LEAD
    assert role_by_name("단원").tier == TIER_STAFF


def role_by_name(name: str) -> AdminRole:
    return db.session.query(AdminRole).filter(AdminRole.name == name).one()
