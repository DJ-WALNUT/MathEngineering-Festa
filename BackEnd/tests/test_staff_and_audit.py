"""스태프 요금 구분과 작업 기록.

요금 구분은 '총학생회비 납부 / 미납부' 두 갈래였다가 스태프가 하나 더 붙었다.
스태프 금액은 늦게 정해지고 바뀌므로 설정이 아니라 DB 에 두고 화면에서 고친다.

작업 기록은 몇 달 뒤에 "이거 누가 왜 이렇게 했지" 를 되짚는 데 쓴다.
필드 이름과 새 값만 남기면 그때 읽을 수 없으므로, 누구의 · 무엇을 ·
무엇에서 무엇으로 가 모두 남아야 한다.
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
from app.assignments import ensure_default_fields  # noqa: E402
from app.extensions import db  # noqa: E402
from app.security import hash_password  # noqa: E402

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
        ensure_default_fields()
        yield application.test_client()
        db.session.remove()


def auth_headers(client) -> dict:
    response = client.post("/api/admin/login", json={"username": SUPER_ID, "password": PASSWORD})
    return {"Authorization": f"Bearer {response.get_json()['token']}"}


def submit_form(client, name: str, phone: str, row: int = 2, member: bool = True):
    return client.post(
        "/api/ingest/form",
        headers=INGEST_HEADERS,
        json={
            "row": row,
            "values": {
                "타임스탬프": "2026-08-01T10:00:00",
                "이름": name,
                "전화번호": phone,
                "학과": "기계공학과",
                "학번": "20261234",
                "총학생회비를 납부하셨나요?": "납부" if member else "미납",
            },
        },
    )


def participant_id(client, headers, name: str) -> int:
    items = client.get(f"/api/admin/participants?query={name}", headers=headers).get_json()["items"]
    assert items, f"{name} 을 찾지 못했습니다."
    return items[0]["id"]


def pay(client, headers, depositor: str, amount: int = 5_000) -> None:
    client.post(
        "/api/admin/deposits",
        headers=headers,
        json={"rawName": depositor, "amount": amount, "occurredAt": "2026-08-02 11:00:00"},
    )


def audit(client, headers, action: str) -> list[dict]:
    entries = client.get("/api/admin/audit?limit=200", headers=headers).get_json()["items"]
    return [entry for entry in entries if entry["action"] == action]


def changes_of(entry: dict) -> dict[str, tuple]:
    return {item["label"]: (item["from"], item["to"]) for item in entry["detail"]["changes"]}


# ---------------------------------------------------------------------------
# 요금 구분
# ---------------------------------------------------------------------------

def test_fee_class_switches_between_three_kinds(client):
    headers = auth_headers(client)
    submit_form(client, "홍길동", "010-1234-5678")
    pid = participant_id(client, headers, "홍길동")

    payload = client.get(f"/api/admin/participants/{pid}", headers=headers).get_json()
    assert payload["feeClass"] == "member"
    assert payload["expectedAmount"] == 5_000

    payload = client.patch(
        f"/api/admin/participants/{pid}", headers=headers, json={"feeClass": "nonmember"}
    ).get_json()
    assert (payload["feeClass"], payload["expectedAmount"]) == ("nonmember", 7_000)

    payload = client.patch(
        f"/api/admin/participants/{pid}", headers=headers, json={"feeClass": "staff"}
    ).get_json()
    assert payload["isStaff"] is True
    assert payload["isCouncilMember"] is False

    assert client.patch(
        f"/api/admin/participants/{pid}", headers=headers, json={"feeClass": "인턴"}
    ).status_code == 400


def test_staff_without_a_fee_is_not_shown_as_unpaid(client):
    """금액이 아직 정해지지 않았다고 명단 내내 미납으로 뜨면 안 된다."""
    headers = auth_headers(client)
    submit_form(client, "홍길동", "010-1234-5678")
    pid = participant_id(client, headers, "홍길동")

    payload = client.patch(
        f"/api/admin/participants/{pid}", headers=headers, json={"feeClass": "staff"}
    ).get_json()
    assert payload["expectedAmount"] == 0
    assert payload["status"] == "WAIVED"
    # 면제는 납입이 끝난 것으로 보므로 바로 참가 확정을 누를 수 있다
    assert payload["isSettled"] is True


def test_staff_fee_change_follows_every_staff_member(client):
    """한 명씩 다시 손보게 두면 금액이 섞인 채로 남아 수납 집계가 어긋난다."""
    headers = auth_headers(client)
    for index, (name, phone) in enumerate([("홍길동", "010-1111-2222"), ("이순신", "010-3333-4444")]):
        submit_form(client, name, phone, row=index + 2)
        pid = participant_id(client, headers, name)
        client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"feeClass": "staff"})

    result = client.post("/api/admin/staff-fee", headers=headers, json={"amount": 20_000}).get_json()
    assert result == {"amount": 20_000, "applied": 2}

    items = client.get("/api/admin/participants?staff=true", headers=headers).get_json()["items"]
    assert [item["expectedAmount"] for item in items] == [20_000, 20_000]

    # 이후에 스태프가 되는 사람도 정해진 금액을 따른다
    submit_form(client, "김유신", "010-5555-6666", row=4)
    pid = participant_id(client, headers, "김유신")
    payload = client.patch(
        f"/api/admin/participants/{pid}", headers=headers, json={"feeClass": "staff"}
    ).get_json()
    assert payload["expectedAmount"] == 20_000

    assert client.post("/api/admin/staff-fee", headers=headers, json={"amount": -1}).status_code == 400


def test_form_resubmission_does_not_undo_staff(client):
    """스태프 지정은 관리자만 한다. 폼을 다시 내도 풀려서는 안 된다."""
    headers = auth_headers(client)
    submit_form(client, "홍길동", "010-1234-5678")
    pid = participant_id(client, headers, "홍길동")
    client.post("/api/admin/staff-fee", headers=headers, json={"amount": 20_000})
    client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"feeClass": "staff"})

    submit_form(client, "홍길동", "010-1234-5678", row=9)

    payload = client.get(f"/api/admin/participants/{pid}", headers=headers).get_json()
    assert payload["isStaff"] is True
    assert payload["expectedAmount"] == 20_000


# ---------------------------------------------------------------------------
# 필터
# ---------------------------------------------------------------------------

def test_filters_cover_waived_refunded_confirmed_and_staff(client):
    headers = auth_headers(client)
    people = [("홍길동", "010-1111-2222"), ("이순신", "010-3333-4444"), ("김유신", "010-5555-6666")]
    for index, (name, phone) in enumerate(people):
        submit_form(client, name, phone, row=index + 2)

    confirmed_id = participant_id(client, headers, "홍길동")
    pay(client, headers, "홍길동2222")
    client.patch(f"/api/admin/participants/{confirmed_id}", headers=headers, json={"isConfirmed": True})

    refunded_id = participant_id(client, headers, "이순신")
    client.patch(
        f"/api/admin/participants/{refunded_id}", headers=headers, json={"statusOverride": "REFUNDED"}
    )

    staff_id = participant_id(client, headers, "김유신")
    client.patch(f"/api/admin/participants/{staff_id}", headers=headers, json={"feeClass": "staff"})

    def names(query: str) -> list[str]:
        items = client.get(f"/api/admin/participants?{query}", headers=headers).get_json()["items"]
        return sorted(item["name"] for item in items)

    assert names("status=REFUNDED") == ["이순신"]
    # 스태프는 금액이 0원이라 면제로 잡힌다
    assert names("status=WAIVED") == ["김유신"]
    assert names("confirmed=true") == ["홍길동"]
    assert names("confirmed=false") == ["김유신", "이순신"]
    assert names("staff=true") == ["김유신"]
    assert names("staff=false") == ["이순신", "홍길동"]


def test_pending_filter_shows_only_people_ready_to_confirm(client):
    """'확정 대기' 는 미확정 전체가 아니라 납입이 끝난 미확정자다.

    미납자까지 섞이면 정작 확정을 눌러야 할 사람이 목록에 묻힌다.
    """
    headers = auth_headers(client)
    people = [("홍길동", "010-1111-2222"), ("이순신", "010-3333-4444"), ("김유신", "010-5555-6666")]
    for index, (name, phone) in enumerate(people):
        submit_form(client, name, phone, row=index + 2)

    # 홍길동: 납입 완료 + 확정까지 마침
    done = participant_id(client, headers, "홍길동")
    pay(client, headers, "홍길동2222")
    client.patch(f"/api/admin/participants/{done}", headers=headers, json={"isConfirmed": True})

    # 이순신: 납입은 끝났지만 아직 확정 전 — 이 사람만 나와야 한다
    pay(client, headers, "이순신4444")

    # 김유신: 미납 + 미확정
    def names(query: str) -> list[str]:
        items = client.get(f"/api/admin/participants?{query}", headers=headers).get_json()["items"]
        return sorted(item["name"] for item in items)

    assert names("confirmed=pending") == ["이순신"]
    # 미확정 전체는 미납자까지 포함한다 (API 로는 여전히 물어볼 수 있다)
    assert names("confirmed=false") == ["김유신", "이순신"]

    # 확정하고 나면 대기 목록에서 빠진다
    waiting = participant_id(client, headers, "이순신")
    client.patch(f"/api/admin/participants/{waiting}", headers=headers, json={"isConfirmed": True})
    assert names("confirmed=pending") == []


# ---------------------------------------------------------------------------
# 작업 기록
# ---------------------------------------------------------------------------

def test_audit_records_who_what_and_before_after(client):
    headers = auth_headers(client)
    submit_form(client, "홍길동", "010-1234-5678")
    pid = participant_id(client, headers, "홍길동")

    client.patch(
        f"/api/admin/participants/{pid}",
        headers=headers,
        json={"feeClass": "nonmember", "memo": "현금으로 받음"},
    )

    entry = audit(client, headers, "participant.update")[0]
    # 누구를 고쳤는지가 로그만 봐도 드러나야 한다
    assert entry["detail"]["target"] == "홍길동"

    changes = changes_of(entry)
    assert changes["요금 구분"] == ("총학생회비 납부자", "총학생회비 미납부자")
    assert changes["참가비"] == ("5,000원", "7,000원")
    assert changes["메모"] == ("(없음)", "현금으로 받음")


def test_audit_translates_codes_into_words(client):
    headers = auth_headers(client)
    submit_form(client, "홍길동", "010-1234-5678")
    pid = participant_id(client, headers, "홍길동")

    client.patch(
        f"/api/admin/participants/{pid}", headers=headers, json={"statusOverride": "WAIVED"}
    )
    changes = changes_of(audit(client, headers, "participant.update")[0])
    assert changes["납입 상태 강제 지정"] == ("자동 (입금 기준)", "면제")

    client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"isConfirmed": True})
    changes = changes_of(audit(client, headers, "participant.update")[0])
    assert changes["참가 확정"] == ("미확정", "확정")


def test_audit_skips_requests_that_changed_nothing(client):
    """아무것도 안 바뀐 요청까지 남으면 정작 볼 것을 못 찾는다."""
    headers = auth_headers(client)
    submit_form(client, "홍길동", "010-1234-5678")
    pid = participant_id(client, headers, "홍길동")

    client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"memo": "확인함"})
    assert len(audit(client, headers, "participant.update")) == 1

    # 같은 값을 다시 보내도 기록이 늘지 않는다
    client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"memo": "확인함"})
    client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"feeClass": "member"})
    assert len(audit(client, headers, "participant.update")) == 1


def test_audit_notes_actions_without_a_before_value(client):
    headers = auth_headers(client)
    submit_form(client, "홍길동", "010-1234-5678")
    pid = participant_id(client, headers, "홍길동")
    pay(client, headers, "홍길동5678")

    client.post("/api/admin/participants/confirm", headers=headers, json={})
    entry = audit(client, headers, "participant.confirm_bulk")[0]
    notes = {item["label"]: item["to"] for item in entry["detail"]["changes"]}
    assert notes["확정 처리"] == "1명 — 홍길동"

    client.post("/api/admin/checkin-window", headers=headers, json={"open": True})
    changes = changes_of(audit(client, headers, "checkin.window")[0])
    assert changes["1부 교류전 셀프 체크인 창구"] == ("닫힘", "열림")

    client.post("/api/admin/staff-fee", headers=headers, json={"amount": 15_000})
    changes = changes_of(audit(client, headers, "settings.staff_fee")[0])
    assert changes["스태프 참가비"] == ("0원", "15,000원")

    assert client.get(f"/api/admin/participants/{pid}", headers=headers).status_code == 200
