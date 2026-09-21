"""출석 회차 · 뒤풀이 · 현장 납부.

이 행사는 하루짜리인데도 출석이 한 번으로 끝나지 않는다. 낮의 본 행사가 있고,
신청자 중 일부만 남는 뒤풀이가 저녁에 따로 있다. 참가비도 두 겹이다.

이 파일이 지키는 계약은 세 가지다.

  1. **뒤풀이비가 본 행사를 막지 않는다.** 뒤풀이비는 별도 안내로 나중에 걷으므로,
     아직 안 낸 것이 본 행사의 '미납'으로 번져 확정을 막아서는 안 된다.
  2. **회차는 데이터다.** 회차를 하나 더 만드는 데 재배포가 필요하지 않다.
  3. **번호는 하나, 후보는 자리마다.** 럭키드로우 번호는 본 행사 체크인 순서로만
     주고, 뒤풀이 추첨에서는 그 자리에 온 사람으로 후보를 좁힌다.
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
from app.attendance import ensure_default_sessions  # noqa: E402
from app.extensions import db  # noqa: E402
from app.security import hash_password  # noqa: E402

PASSWORD = "mt-admin-1234"
SUPER_ID = "wont0309"
INGEST_HEADERS = {"X-Ingest-Token": "test-token"}


@pytest.fixture()
def client():
    application = create_app()
    application.config.update(
        TESTING=True,
        ADMIN_PASSWORD_HASH=hash_password(PASSWORD),
        STAFF_PASSWORD_HASH=hash_password(PASSWORD),
        LOGIN_RATE_LIMIT="1000 per minute",
        LOOKUP_RATE_LIMIT="1000 per minute",
        CHECKIN_RATE_LIMIT="1000 per minute",
    )
    with application.app_context():
        db.drop_all()
        db.create_all()
        ensure_default_fields()
        ensure_default_sessions()
        yield application.test_client()
        db.session.remove()


def auth_headers(client) -> dict:
    response = client.post("/api/admin/login", json={"username": SUPER_ID, "password": PASSWORD})
    assert response.status_code == 200, response.get_json()
    return {"Authorization": f"Bearer {response.get_json()['token']}"}


def submit_form(client, name, phone, student_id, *, afterparty=False, row=2):
    values = {
        "타임스탬프": "2026-08-01T10:00:00",
        "이름": name,
        "전화번호": phone,
        "학과": "기계공학과",
        "학번": student_id,
        "총학생회비를 납부하셨나요?": "납부",
        "뒤풀이에 참가하시나요?": "예" if afterparty else "아니오",
    }
    response = client.post(
        "/api/ingest/form", headers=INGEST_HEADERS, json={"row": row, "values": values}
    )
    assert response.status_code == 200, response.get_json()


def participant(client, headers, name: str) -> dict:
    items = client.get(f"/api/admin/participants?query={name}", headers=headers).get_json()["items"]
    assert items, f"{name} 을 찾지 못했습니다."
    return items[0]


def onsite(client, headers, pid: int, **body) -> dict:
    response = client.post(
        f"/api/admin/participants/{pid}/onsite-payment", headers=headers, json=body
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def enrol(client, headers, name, phone, student_id, *, afterparty=False, row=2) -> dict:
    """폼 제출 → 현장 납부 → 참가 확정까지. 반환은 참가자 dict."""
    submit_form(client, name, phone, student_id, afterparty=afterparty, row=row)
    person = participant(client, headers, name)
    onsite(client, headers, person["id"], amount=person["baseFee"])
    client.patch(
        f"/api/admin/participants/{person['id']}", headers=headers, json={"isConfirmed": True}
    )
    return participant(client, headers, name)


def sessions(client, headers) -> dict:
    items = client.get("/api/admin/checkin-sessions", headers=headers).get_json()["items"]
    return {item["key"]: item for item in items}


def open_session(client, headers, key: str, open_: bool = True) -> None:
    response = client.post(
        f"/api/admin/checkin-window?session={key}", headers=headers, json={"open": open_}
    )
    assert response.status_code == 200, response.get_json()


# ---------------------------------------------------------------------------
# 참가비 두 겹
# ---------------------------------------------------------------------------

def test_afterparty_adds_its_fee_on_top(client):
    headers = auth_headers(client)
    submit_form(client, "홍길동", "010-1234-5678", "20261111")
    submit_form(client, "이순신", "010-2222-3333", "20262222", afterparty=True, row=3)

    plain = participant(client, headers, "홍길동")
    joining = participant(client, headers, "이순신")

    assert (plain["baseFee"], plain["expectedAmount"]) == (5_000, 5_000)
    assert plain["joinsAfterparty"] is False
    assert plain["afterpartyStatus"] == "NONE"

    assert (joining["baseFee"], joining["afterpartyFee"]) == (5_000, 10_000)
    assert joining["expectedAmount"] == 15_000


def test_unpaid_afterparty_fee_does_not_block_confirmation(client):
    """뒤풀이비는 별도 안내로 나중에 걷는다. 본 행사 확정을 막으면 안 된다."""
    headers = auth_headers(client)
    submit_form(client, "이순신", "010-2222-3333", "20262222", afterparty=True)
    person = participant(client, headers, "이순신")

    onsite(client, headers, person["id"], amount=5_000)
    person = participant(client, headers, "이순신")

    assert person["status"] == "PAID"          # 본 행사비는 다 냈다
    assert person["afterpartyStatus"] == "UNPAID"
    assert person["isSettled"] is True

    confirmed = client.patch(
        f"/api/admin/participants/{person['id']}", headers=headers, json={"isConfirmed": True}
    )
    assert confirmed.status_code == 200
    assert confirmed.get_json()["isConfirmed"] is True


def test_dashboard_separates_afterparty_collection(client):
    headers = auth_headers(client)
    submit_form(client, "홍길동", "010-1234-5678", "20261111")
    submit_form(client, "이순신", "010-2222-3333", "20262222", afterparty=True, row=3)
    submit_form(client, "김유신", "010-4444-5555", "20263333", afterparty=True, row=4)

    # 한 명은 본 행사비만, 한 명은 합쳐서 한 번에 냈다.
    onsite(client, headers, participant(client, headers, "이순신")["id"], amount=5_000)
    onsite(client, headers, participant(client, headers, "김유신")["id"], amount=15_000)

    after = client.get("/api/admin/summary", headers=headers).get_json()["afterparty"]
    assert after["fee"] == 10_000
    assert after["joining"] == 2
    assert after["paid"] == 1
    assert after["unpaid"] == 1
    assert after["prepaid"] == 1              # 합산 납부 배지가 붙는 사람
    assert (after["expectedTotal"], after["collectedTotal"]) == (20_000, 10_000)


def test_afterparty_fee_change_follows_every_joiner(client):
    headers = auth_headers(client)
    submit_form(client, "이순신", "010-2222-3333", "20262222", afterparty=True)

    response = client.post("/api/admin/afterparty-fee", headers=headers, json={"amount": 12_000})
    assert response.status_code == 200
    assert response.get_json()["applied"] == 1

    person = participant(client, headers, "이순신")
    assert (person["afterpartyFee"], person["expectedAmount"]) == (12_000, 17_000)


def test_turning_afterparty_off_refunds_the_expectation(client):
    headers = auth_headers(client)
    submit_form(client, "이순신", "010-2222-3333", "20262222", afterparty=True)
    pid = participant(client, headers, "이순신")["id"]

    updated = client.patch(
        f"/api/admin/participants/{pid}", headers=headers, json={"joinsAfterparty": False}
    ).get_json()
    assert updated["joinsAfterparty"] is False
    assert updated["expectedAmount"] == 5_000
    assert updated["afterpartyStatus"] == "NONE"


# ---------------------------------------------------------------------------
# 현장 납부
# ---------------------------------------------------------------------------

def test_onsite_payment_settles_immediately(client):
    """당일 문 앞에서 낸 돈이 계좌 입금과 같은 자리에 들어가야 한다."""
    headers = auth_headers(client)
    submit_form(client, "홍길동", "010-1234-5678", "20261111")
    pid = participant(client, headers, "홍길동")["id"]

    # 금액을 비우면 아직 안 낸 만큼을 그대로 채운다
    body = onsite(client, headers, pid, method="현금")
    assert body["amount"] == 5_000

    person = participant(client, headers, "홍길동")
    assert person["status"] == "PAID"
    assert person["isSettled"] is True

    deposit = body["deposit"]
    assert deposit["source"] == "onsite"
    assert deposit["status"] == "MATCHED"
    # 사람이 직접 받아 넣은 것이라 자동 매칭이 덮어쓰지 못하게 잠근다
    assert deposit["manualLocked"] is True

    audit = client.get("/api/admin/audit", headers=headers).get_json()["items"]
    assert any(item["action"] == "deposit.onsite" for item in audit)


def test_onsite_payment_rejects_an_accidental_second_press(client):
    headers = auth_headers(client)
    submit_form(client, "홍길동", "010-1234-5678", "20261111")
    pid = participant(client, headers, "홍길동")["id"]

    onsite(client, headers, pid, amount=5_000)
    again = client.post(
        f"/api/admin/participants/{pid}/onsite-payment", headers=headers, json={"amount": 5_000}
    )
    assert again.status_code == 409
    assert again.get_json()["error"] == "duplicate"


# ---------------------------------------------------------------------------
# 회차
# ---------------------------------------------------------------------------

def test_two_sessions_exist_and_start_closed(client):
    headers = auth_headers(client)
    rows = sessions(client, headers)

    assert set(rows) == {"main", "afterparty"}
    assert rows["main"]["isOpen"] is False
    assert rows["main"]["givesDrawNo"] is True
    assert rows["main"]["isSystem"] is True
    assert rows["afterparty"]["afterpartyOnly"] is True
    assert rows["afterparty"]["givesDrawNo"] is False


def test_only_one_session_takes_self_checkins_at_a_time(client):
    """참가자는 회차를 고르지 않는다. 같은 QR 로 '지금 열린' 자리에 찍힌다."""
    headers = auth_headers(client)
    enrol(client, headers, "이순신", "010-2222-3333", "20262222", afterparty=True)

    open_session(client, headers, "main")
    assert client.get("/api/checkin/state").get_json()["sessionKey"] == "main"

    open_session(client, headers, "afterparty")
    state = client.get("/api/checkin/state").get_json()
    assert state["sessionKey"] == "afterparty"
    assert sessions(client, headers)["main"]["isOpen"] is False


def test_self_checkin_lands_in_the_open_session(client):
    headers = auth_headers(client)
    enrol(client, headers, "이순신", "010-2222-3333", "20262222", afterparty=True)
    open_session(client, headers, "main")

    payload = client.post(
        "/api/checkin",
        json={"name": "이순신", "studentId": "20262222", "phoneLast4": "3333"},
    ).get_json()
    assert payload["ok"] is True
    assert payload["participant"]["sessionLabel"] == "1부 교류전"
    assert payload["participant"]["drawLabel"] == "001"

    open_session(client, headers, "afterparty")
    second = client.post(
        "/api/checkin",
        json={"name": "이순신", "studentId": "20262222", "phoneLast4": "3333"},
    ).get_json()
    assert second["ok"] is True
    # 같은 사람이 두 자리에 각각 찍혔다. 뒤풀이는 새 번호를 주지 않는다.
    assert second["participant"]["sessionKey"] == "afterparty"
    assert second["participant"]["drawLabel"] == "001"

    row = participant(client, headers, "이순신")
    assert set(row["checkins"]) == {"main", "afterparty"}


def test_afterparty_session_turns_away_people_who_did_not_sign_up(client):
    headers = auth_headers(client)
    enrol(client, headers, "홍길동", "010-1234-5678", "20261111")
    open_session(client, headers, "afterparty")

    payload = client.post(
        "/api/checkin",
        json={"name": "홍길동", "studentId": "20261111", "phoneLast4": "5678"},
    ).get_json()
    assert payload["ok"] is False
    assert payload["reason"] == "not_in_session"


def test_manual_check_works_while_the_window_is_shut(client):
    """뒤풀이는 인원이 적고 자리가 어수선해 명단에서 누르는 편이 빠르다."""
    headers = auth_headers(client)
    person = enrol(client, headers, "이순신", "010-2222-3333", "20262222", afterparty=True)
    assert sessions(client, headers)["afterparty"]["isOpen"] is False

    response = client.post(
        "/api/admin/attendance/check?session=afterparty",
        headers=headers,
        json={"participantId": person["id"], "present": True},
    )
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["changed"] is True

    payload = client.get("/api/admin/attendance?session=afterparty", headers=headers).get_json()
    assert payload["overall"]["checkedIn"] == 1
    assert payload["checkedIn"][0]["checkedInBy"] == "staff"

    # 눌러서 취소하면 그 회차에서만 빠진다
    client.post(
        "/api/admin/attendance/check?session=afterparty",
        headers=headers,
        json={"participantId": person["id"], "present": False},
    )
    payload = client.get("/api/admin/attendance?session=afterparty", headers=headers).get_json()
    assert payload["overall"]["checkedIn"] == 0


def test_manual_check_refuses_someone_outside_the_session(client):
    headers = auth_headers(client)
    person = enrol(client, headers, "홍길동", "010-1234-5678", "20261111")

    response = client.post(
        "/api/admin/attendance/check?session=afterparty",
        headers=headers,
        json={"participantId": person["id"], "present": True},
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "not_in_session"


def test_afterparty_denominator_counts_only_those_who_signed_up(client):
    headers = auth_headers(client)
    enrol(client, headers, "홍길동", "010-1234-5678", "20261111", row=2)
    enrol(client, headers, "이순신", "010-2222-3333", "20262222", afterparty=True, row=3)

    main = client.get("/api/admin/attendance?session=main", headers=headers).get_json()
    after = client.get("/api/admin/attendance?session=afterparty", headers=headers).get_json()

    assert main["overall"]["confirmed"] == 2
    assert after["overall"]["confirmed"] == 1
    assert after["session"]["label"] == "2부 솔로파티"


def test_a_session_can_be_added_without_redeploying(client):
    headers = auth_headers(client)
    created = client.post(
        "/api/admin/checkin-sessions", headers=headers, json={"label": "2부"}
    )
    assert created.status_code == 201
    key = created.get_json()["key"]

    # 번호를 매기는 회차는 늘 하나뿐이다
    assert created.get_json()["givesDrawNo"] is False
    assert key in sessions(client, headers)

    assert client.delete(
        f"/api/admin/checkin-sessions/{created.get_json()['id']}", headers=headers
    ).status_code == 200
    assert key not in sessions(client, headers)


def test_main_session_cannot_be_deleted(client):
    headers = auth_headers(client)
    main_id = sessions(client, headers)["main"]["id"]
    assert client.delete(f"/api/admin/checkin-sessions/{main_id}", headers=headers).status_code == 400


def test_deleting_a_used_session_needs_confirmation(client):
    headers = auth_headers(client)
    person = enrol(client, headers, "이순신", "010-2222-3333", "20262222", afterparty=True)
    after_id = sessions(client, headers)["afterparty"]["id"]
    client.post(
        "/api/admin/attendance/check?session=afterparty",
        headers=headers,
        json={"participantId": person["id"], "present": True},
    )

    blocked = client.delete(f"/api/admin/checkin-sessions/{after_id}", headers=headers)
    assert blocked.status_code == 409
    assert blocked.get_json()["count"] == 1

    assert client.delete(
        f"/api/admin/checkin-sessions/{after_id}?force=true", headers=headers
    ).status_code == 200


# ---------------------------------------------------------------------------
# 럭키드로우 — 번호는 하나, 후보는 자리마다
# ---------------------------------------------------------------------------

def test_afterparty_draw_pool_is_limited_to_who_is_there(client):
    headers = auth_headers(client)
    stayed = enrol(client, headers, "이순신", "010-2222-3333", "20262222", afterparty=True, row=2)
    went_home = enrol(client, headers, "홍길동", "010-1234-5678", "20261111", row=3)

    open_session(client, headers, "main")
    for name, student_id, last4 in (
        ("이순신", "20262222", "3333"),
        ("홍길동", "20261111", "5678"),
    ):
        client.post(
            "/api/checkin", json={"name": name, "studentId": student_id, "phoneLast4": last4}
        )

    # 낮에는 둘 다 후보다
    state = client.get("/api/admin/draw", headers=headers).get_json()
    assert state["counts"]["eligible"] == 2
    assert state["counts"]["present"] is None

    # 뒤풀이 자리에 남은 사람만 체크인했다
    client.post(
        "/api/admin/attendance/check?session=afterparty",
        headers=headers,
        json={"participantId": stayed["id"], "present": True},
    )

    state = client.get("/api/admin/draw?poolSession=afterparty", headers=headers).get_json()
    assert state["counts"]["eligible"] == 1
    assert state["counts"]["present"] == 1
    outs = {tile["label"]: tile["out"] for tile in state["pool"]}
    # 집에 간 사람의 번호는 처음부터 꺼져 있다
    assert outs[participant(client, headers, "홍길동")["drawLabel"]] == "not_in_session"

    won = client.post(
        "/api/admin/draw", headers=headers, json={"prize": "간식", "poolSession": "afterparty"}
    ).get_json()
    assert won["ok"] is True
    assert won["draw"]["name"] == "이순신"
    assert went_home["id"] != stayed["id"]
