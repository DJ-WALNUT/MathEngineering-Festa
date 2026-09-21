"""참가 확정 · 현장 배정 · 셀프 체크인.

세 기능은 한 줄로 이어져 있다.

    납입 완료 ──▶ 참가 확정 ──▶ 조 배정 ──▶ 당일 셀프 체크인

앞 단계를 건너뛴 채 뒷 단계가 열리면 안 된다는 것이 이 파일이 지키는 계약이다.
확정되지 않은 사람에게 조를 배정할 수 없고, 배정 이전에 체크인이 되어서도 안 된다.
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
        CHECKIN_RATE_LIMIT="1000 per minute",
    )
    with application.app_context():
        db.drop_all()
        db.create_all()
        # 배정 항목은 데이터라서 테이블을 새로 만들면 함께 사라진다.
        ensure_default_fields()
        yield application.test_client()
        db.session.remove()


def auth_headers(client) -> dict:
    response = client.post("/api/admin/login", json={"username": SUPER_ID, "password": PASSWORD})
    assert response.status_code == 200, response.get_json()
    return {"Authorization": f"Bearer {response.get_json()['token']}"}


def submit_form(client, name: str, phone: str, student_id: str, row: int = 2):
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
                "학번": student_id,
                "총학생회비를 납부하셨나요?": "납부",
            },
        },
    )


def participant_id(client, headers, name: str) -> int:
    items = client.get(f"/api/admin/participants?query={name}", headers=headers).get_json()["items"]
    assert items, f"{name} 을 찾지 못했습니다."
    return items[0]["id"]


def pay(client, headers, depositor: str, amount: int = 5_000) -> None:
    """수기 입금 등록으로 납입을 완료시킨다 (자동 매칭을 그대로 탄다)."""
    response = client.post(
        "/api/admin/deposits",
        headers=headers,
        json={"rawName": depositor, "amount": amount, "occurredAt": "2026-08-02 11:00:00"},
    )
    assert response.status_code in (200, 201), response.get_json()


def settle(client, headers, name: str, phone: str, student_id: str, row: int = 2) -> int:
    """폼 제출 → 납입 완료까지. 반환값은 참가자 id."""
    assert submit_form(client, name, phone, student_id, row=row).status_code == 200
    pay(client, headers, f"{name}{phone[-4:]}")
    return participant_id(client, headers, name)


def add_options(client, headers, key: str, *values: str) -> None:
    """선택지를 추가한다. '조를 하나 만든다'는 곧 이 동작이다."""
    fields = client.get("/api/admin/assignment-fields", headers=headers).get_json()["items"]
    field = next(item for item in fields if item["key"] == key)
    response = client.patch(
        f"/api/admin/assignment-fields/{field['id']}",
        headers=headers,
        json={"options": [*field["options"], *values]},
    )
    assert response.status_code == 200, response.get_json()


def add_group(client, headers, *values: str) -> None:
    add_options(client, headers, "group", *values)


def add_choice_field(client, headers, label: str) -> str:
    """선택지형 배정 항목을 하나 만든다. 반환값은 값 딕셔너리의 key.

    기본 항목은 조 하나뿐이다. 당일 행사라 숙소 호수도 버스도 없지만 '자리'처럼
    그때그때 필요한 분류가 생기므로, 화면에서 만들 수 있어야 한다.
    """
    created = client.post(
        "/api/admin/assignment-fields",
        headers=headers,
        json={"label": label, "kind": "choice"},
    )
    assert created.status_code == 201, created.get_json()
    return created.get_json()["key"]


# ---------------------------------------------------------------------------
# 참가 확정
# ---------------------------------------------------------------------------

def test_confirm_requires_completed_payment(client):
    headers = auth_headers(client)
    submit_form(client, "홍길동", "010-1234-5678", "20261234")
    pid = participant_id(client, headers, "홍길동")

    # 아직 입금이 없다
    response = client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"isConfirmed": True})
    assert response.status_code == 400
    assert response.get_json()["error"] == "not_settled"

    pay(client, headers, "홍길동5678")
    response = client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"isConfirmed": True})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["isConfirmed"] is True
    assert payload["confirmedAt"] is not None


def test_bulk_confirm_skips_unpaid(client):
    headers = auth_headers(client)
    settle(client, headers, "홍길동", "010-1234-5678", "20261234", row=2)
    submit_form(client, "김미납", "010-9999-8888", "20265678", row=3)

    result = client.post("/api/admin/participants/confirm", headers=headers, json={}).get_json()
    assert result == {"confirmed": 1, "skipped": 1}

    # 두 번 눌러도 같은 사람이 다시 세어지지 않는다
    assert client.post("/api/admin/participants/confirm", headers=headers, json={}).get_json() == {
        "confirmed": 0,
        "skipped": 1,
    }


def test_cancelling_clears_confirmation(client):
    """취소자가 확정 명단에 남아 있으면 조 편성과 출석률이 어긋난다."""
    headers = auth_headers(client)
    pid = settle(client, headers, "홍길동", "010-1234-5678", "20261234")
    client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"isConfirmed": True})

    payload = client.patch(
        f"/api/admin/participants/{pid}", headers=headers, json={"isCancelled": True}
    ).get_json()
    assert payload["isConfirmed"] is False


def test_public_status_shows_confirmation_apart_from_payment(client):
    """납입 완료와 참가 확정은 화면에서 구분되어야 한다."""
    headers = auth_headers(client)
    pid = settle(client, headers, "홍길동", "010-1234-5678", "20261234")

    payload = client.post(
        "/api/status", json={"name": "홍길동", "phone": "01012345678"}
    ).get_json()["participant"]
    assert payload["status"] == "PAID"
    assert payload["isConfirmed"] is False

    client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"isConfirmed": True})
    payload = client.post(
        "/api/status", json={"name": "홍길동", "phone": "01012345678"}
    ).get_json()["participant"]
    assert payload["isConfirmed"] is True
    assert payload["confirmedAt"] is not None


# ---------------------------------------------------------------------------
# 배정
# ---------------------------------------------------------------------------

def test_assignment_needs_confirmation(client):
    headers = auth_headers(client)
    pid = settle(client, headers, "홍길동", "010-1234-5678", "20261234")
    add_group(client, headers, "1조")

    response = client.patch(
        f"/api/admin/participants/{pid}", headers=headers, json={"assignments": {"group": "1조"}}
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "not_confirmed"

    client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"isConfirmed": True})
    payload = client.patch(
        f"/api/admin/participants/{pid}", headers=headers, json={"assignments": {"group": "1조"}}
    ).get_json()
    assert payload["assignments"]["group"] == "1조"
    # 조 단위 집계와 CSV 를 위한 사본 컬럼도 함께 채워진다
    assert payload["groupNo"] == "1조"


def test_assignment_rejects_value_outside_options(client):
    headers = auth_headers(client)
    pid = settle(client, headers, "홍길동", "010-1234-5678", "20261234")
    client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"isConfirmed": True})
    add_group(client, headers, "1조")

    response = client.patch(
        f"/api/admin/participants/{pid}", headers=headers, json={"assignments": {"group": "9조"}}
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_assignment"

    # 직접 만든 항목도 마찬가지다. 손으로 적으면 'A' / 'A구역' 이 섞여 집계가 어긋난다.
    seat = add_choice_field(client, headers, "자리")
    assert client.patch(
        f"/api/admin/participants/{pid}", headers=headers, json={"assignments": {seat: "A구역"}}
    ).status_code == 400

    add_options(client, headers, seat, "A구역")
    payload = client.patch(
        f"/api/admin/participants/{pid}", headers=headers, json={"assignments": {seat: "A구역"}}
    ).get_json()
    assert payload["assignments"][seat] == "A구역"


def test_empty_value_clears_one_assignment_only(client):
    headers = auth_headers(client)
    pid = settle(client, headers, "홍길동", "010-1234-5678", "20261234")
    client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"isConfirmed": True})
    add_group(client, headers, "1조")
    seat = add_choice_field(client, headers, "자리")
    add_options(client, headers, seat, "A구역")
    client.patch(
        f"/api/admin/participants/{pid}",
        headers=headers,
        json={"assignments": {"group": "1조", seat: "A구역"}},
    )

    payload = client.patch(
        f"/api/admin/participants/{pid}", headers=headers, json={"assignments": {"group": ""}}
    ).get_json()
    assert "group" not in payload["assignments"]
    assert payload["groupNo"] is None
    assert payload["assignments"][seat] == "A구역"


def test_option_in_use_cannot_be_removed(client):
    """배정된 조를 선택지에서 빼면 그 사람의 조가 유령이 된다."""
    headers = auth_headers(client)
    pid = settle(client, headers, "홍길동", "010-1234-5678", "20261234")
    client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"isConfirmed": True})
    add_group(client, headers, "1조", "2조")
    client.patch(
        f"/api/admin/participants/{pid}", headers=headers, json={"assignments": {"group": "1조"}}
    )

    fields = client.get("/api/admin/assignment-fields", headers=headers).get_json()["items"]
    group = next(field for field in fields if field["key"] == "group")

    response = client.patch(
        f"/api/admin/assignment-fields/{group['id']}", headers=headers, json={"options": ["2조"]}
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "option_in_use"

    # 쓰이지 않는 선택지는 지울 수 있다
    assert client.patch(
        f"/api/admin/assignment-fields/{group['id']}", headers=headers, json={"options": ["1조"]}
    ).status_code == 200


def test_custom_field_can_be_added_and_removed(client):
    """항목을 늘리는 데 재배포가 필요하지 않아야 한다."""
    headers = auth_headers(client)
    pid = settle(client, headers, "홍길동", "010-1234-5678", "20261234")
    client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"isConfirmed": True})

    created = client.post(
        "/api/admin/assignment-fields",
        headers=headers,
        json={"label": "텐트 번호", "kind": "text"},
    ).get_json()
    assert created["isSystem"] is False

    payload = client.patch(
        f"/api/admin/participants/{pid}",
        headers=headers,
        json={"assignments": {created["key"]: "T-7"}},
    ).get_json()
    assert payload["assignments"][created["key"]] == "T-7"

    # 항목을 지우면 이미 배정된 값도 함께 치워진다
    result = client.delete(f"/api/admin/assignment-fields/{created['id']}", headers=headers).get_json()
    assert result["clearedValues"] == 1

    payload = client.get(f"/api/admin/participants/{pid}", headers=headers).get_json()
    assert created["key"] not in payload["assignments"]


def test_switching_a_field_to_choice_keeps_values_already_assigned(client):
    """기본 항목을 자유 입력에서 선택지로 바꾼 배포를 견뎌야 한다.

    이미 적혀 있던 값이 선택지에 없으면, 그 사람의 배정은 남아 있는데 화면에서는
    고를 수 없는 유령이 된다. 기동 시 쓰이던 값을 선택지로 끌어올려야 한다.
    """
    from app.assignments import ensure_default_fields
    from app.models import AssignmentField

    headers = auth_headers(client)
    pid = settle(client, headers, "홍길동", "010-1234-5678", "20261234")
    client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"isConfirmed": True})

    # 예전 배포 상태를 흉내낸다 — 조가 자유 입력이던 시절
    group = db.session.query(AssignmentField).filter_by(key="group").one()
    group.kind = AssignmentField.KIND_TEXT
    db.session.commit()

    client.patch(
        f"/api/admin/participants/{pid}", headers=headers, json={"assignments": {"group": "3조"}}
    )

    result = ensure_default_fields()
    assert result["converted"] == ["group"]

    group = db.session.query(AssignmentField).filter_by(key="group").one()
    assert group.kind == AssignmentField.KIND_CHOICE
    assert "3조" in group.options

    # 이미 배정된 값이라 선택지에서 뺄 수도 없다
    assert client.patch(
        f"/api/admin/assignment-fields/{group.id}", headers=headers, json={"options": []}
    ).status_code == 400


def test_seeding_does_not_overwrite_options_the_council_set(client):
    """이미 만들어 둔 조 목록을 재기동이 지워 버리면 안 된다."""
    from app.assignments import ensure_default_fields

    headers = auth_headers(client)
    add_group(client, headers, "1조", "2조")

    assert ensure_default_fields() == {"created": [], "converted": []}

    fields = client.get("/api/admin/assignment-fields", headers=headers).get_json()["items"]
    group = next(field for field in fields if field["key"] == "group")
    assert group["options"] == ["1조", "2조"]


def test_system_fields_are_protected(client):
    headers = auth_headers(client)
    fields = client.get("/api/admin/assignment-fields", headers=headers).get_json()["items"]
    group = next(field for field in fields if field["key"] == "group")

    assert client.delete(f"/api/admin/assignment-fields/{group['id']}", headers=headers).status_code == 400
    assert client.patch(
        f"/api/admin/assignment-fields/{group['id']}", headers=headers, json={"isActive": False}
    ).status_code == 400


# ---------------------------------------------------------------------------
# 셀프 체크인
# ---------------------------------------------------------------------------

def open_checkin(client, headers, open_: bool = True) -> None:
    response = client.post("/api/admin/checkin-window", headers=headers, json={"open": open_})
    assert response.status_code == 200


def test_checkin_is_closed_until_staff_opens_it(client):
    """QR 인쇄물은 며칠 전부터 돌아다닌다. 기본은 닫힘이어야 한다."""
    headers = auth_headers(client)
    pid = settle(client, headers, "홍길동", "010-1234-5678", "20261234")
    client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"isConfirmed": True})

    assert client.get("/api/checkin/state").get_json()["open"] is False

    payload = client.post(
        "/api/checkin",
        json={"name": "홍길동", "studentId": "20261234", "phoneLast4": "5678"},
    ).get_json()
    assert payload["ok"] is False
    assert payload["reason"] == "closed"

    open_checkin(client, headers)
    assert client.get("/api/checkin/state").get_json()["open"] is True


def test_self_checkin_marks_attendance_and_shows_group(client):
    headers = auth_headers(client)
    pid = settle(client, headers, "홍길동", "010-1234-5678", "20261234")
    client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"isConfirmed": True})
    add_group(client, headers, "3조")
    client.patch(
        f"/api/admin/participants/{pid}",
        headers=headers,
        json={"assignments": {"group": "3조"}},
    )
    open_checkin(client, headers)

    payload = client.post(
        "/api/checkin",
        json={"name": "홍길동", "studentId": "2026-1234", "phoneLast4": "5678"},
    ).get_json()

    assert payload["ok"] is True
    assert payload["alreadyCheckedIn"] is False
    # 스태프에게 보여 주는 화면이므로 이름을 가리지 않는다
    assert payload["participant"]["name"] == "홍길동"
    values = {item["label"]: item["value"] for item in payload["participant"]["assignments"]}
    assert values["조"] == "3조"
    # 어느 자리에 찍혔는지도 함께 온다. 본 행사와 뒤풀이가 같은 QR 을 쓰기 때문이다.
    assert payload["participant"]["sessionKey"] == "main"
    assert payload["participant"]["sessionLabel"] == "1부 교류전"

    # 다시 열어도 같은 화면이 나와야 명찰을 받을 수 있다
    again = client.post(
        "/api/checkin",
        json={"name": "홍길동", "studentId": "20261234", "phoneLast4": "5678"},
    ).get_json()
    assert again["ok"] is True
    assert again["alreadyCheckedIn"] is True


def test_self_checkin_needs_all_three_factors(client):
    """이름만으로는 동명이인·대리 체크인을 막을 수 없다."""
    headers = auth_headers(client)
    pid = settle(client, headers, "홍길동", "010-1234-5678", "20261234")
    client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"isConfirmed": True})
    open_checkin(client, headers)

    wrong_id = client.post(
        "/api/checkin",
        json={"name": "홍길동", "studentId": "20269999", "phoneLast4": "5678"},
    ).get_json()
    assert wrong_id["reason"] == "not_found"

    wrong_phone = client.post(
        "/api/checkin",
        json={"name": "홍길동", "studentId": "20261234", "phoneLast4": "0000"},
    ).get_json()
    assert wrong_phone["reason"] == "not_found"

    missing = client.post("/api/checkin", json={"name": "홍길동", "studentId": "20261234"})
    assert missing.status_code == 400

    # 아무것도 출석 처리되지 않았다
    assert client.get(f"/api/admin/participants/{pid}", headers=headers).get_json()["checkedInAt"] is None


def test_fixing_a_wrong_student_id_makes_checkin_work(client):
    """학번 칸에 생년월일을 적어 낸 사람.

    본인 확인이 이름 + 학번 + 전화 뒷자리라, 고쳐 두지 않으면 당일 문 앞에서 튕긴다.
    """
    headers = auth_headers(client)
    pid = settle(client, headers, "홍길동", "010-1234-5678", "060101")
    client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"isConfirmed": True})
    open_checkin(client, headers)

    payload = client.post(
        "/api/checkin",
        json={"name": "홍길동", "studentId": "20261234", "phoneLast4": "5678"},
    ).get_json()
    assert payload["ok"] is False
    assert payload["reason"] == "not_found"

    fixed = client.patch(
        f"/api/admin/participants/{pid}", headers=headers, json={"studentId": "20261234"}
    )
    assert fixed.status_code == 200, fixed.get_json()
    assert fixed.get_json()["studentId"] == "20261234"

    payload = client.post(
        "/api/checkin",
        json={"name": "홍길동", "studentId": "2026-1234", "phoneLast4": "5678"},
    ).get_json()
    assert payload["ok"] is True, payload


def test_unconfirmed_participant_cannot_check_in(client):
    headers = auth_headers(client)
    settle(client, headers, "홍길동", "010-1234-5678", "20261234")
    open_checkin(client, headers)

    payload = client.post(
        "/api/checkin",
        json={"name": "홍길동", "studentId": "20261234", "phoneLast4": "5678"},
    ).get_json()
    assert payload["ok"] is False
    assert payload["reason"] == "not_confirmed"


# ---------------------------------------------------------------------------
# 출석 현황
# ---------------------------------------------------------------------------

def test_attendance_counts_confirmed_as_denominator(client):
    headers = auth_headers(client)
    add_group(client, headers, "1조", "2조")

    people = [
        ("홍길동", "010-1234-5678", "20261111", "1조"),
        ("이순신", "010-2222-3333", "20262222", "1조"),
        ("김유신", "010-4444-5555", "20263333", "2조"),
    ]
    for index, (name, phone, student_id, group) in enumerate(people):
        pid = settle(client, headers, name, phone, student_id, row=index + 2)
        client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"isConfirmed": True})
        client.patch(
            f"/api/admin/participants/{pid}", headers=headers, json={"assignments": {"group": group}}
        )

    # 확정하지 않은 신청자는 분모에 들어가지 않는다
    submit_form(client, "박미납", "010-7777-8888", "20264444", row=5)

    open_checkin(client, headers)
    client.post("/api/checkin", json={"name": "홍길동", "studentId": "20261111", "phoneLast4": "5678"})

    payload = client.get("/api/admin/attendance", headers=headers).get_json()
    assert payload["overall"]["applicants"] == 4
    assert payload["overall"]["confirmed"] == 3
    assert payload["overall"]["checkedIn"] == 1
    assert payload["overall"]["notCheckedIn"] == 2
    assert payload["overall"]["rate"] == 33.3

    groups = {group["label"]: group for group in payload["groups"]}
    assert groups["1조"]["confirmed"] == 2
    assert groups["1조"]["checkedIn"] == 1
    assert groups["1조"]["rate"] == 50.0
    assert groups["2조"]["checkedIn"] == 0

    assert [row["name"] for row in payload["checkedIn"]] == ["홍길동"]
    assert {row["name"] for row in payload["notCheckedIn"]} == {"이순신", "김유신"}


def test_attendance_can_group_by_any_field(client):
    headers = auth_headers(client)
    pid = settle(client, headers, "홍길동", "010-1234-5678", "20261234")
    client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"isConfirmed": True})
    seat = add_choice_field(client, headers, "자리")
    add_options(client, headers, seat, "A구역")
    client.patch(
        f"/api/admin/participants/{pid}", headers=headers, json={"assignments": {seat: "A구역"}}
    )

    payload = client.get(f"/api/admin/attendance?groupBy={seat}", headers=headers).get_json()
    assert payload["groupBy"]["key"] == seat
    assert payload["groups"][0]["label"] == "A구역"


def test_unassigned_participants_land_in_their_own_bucket(client):
    headers = auth_headers(client)
    pid = settle(client, headers, "홍길동", "010-1234-5678", "20261234")
    client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"isConfirmed": True})

    payload = client.get("/api/admin/attendance", headers=headers).get_json()
    assert payload["groups"] == [
        {"value": None, "label": "미배정", "confirmed": 1, "checkedIn": 0, "notCheckedIn": 1, "rate": 0.0}
    ]


def test_staff_can_check_in_by_hand(client):
    """휴대폰이 없거나 QR 을 못 찍는 사람이 반드시 나온다."""
    headers = auth_headers(client)
    pid = settle(client, headers, "홍길동", "010-1234-5678", "20261234")
    client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"isConfirmed": True})

    payload = client.patch(
        f"/api/admin/participants/{pid}", headers=headers, json={"isCheckedIn": True}
    ).get_json()
    assert payload["checkedInAt"] is not None
    assert payload["checkedInBy"] == "staff"

    payload = client.patch(
        f"/api/admin/participants/{pid}", headers=headers, json={"isCheckedIn": False}
    ).get_json()
    assert payload["checkedInAt"] is None


def test_unassigned_filter_finds_people_without_a_group(client):
    headers = auth_headers(client)
    add_group(client, headers, "1조")
    first = settle(client, headers, "홍길동", "010-1234-5678", "20261111", row=2)
    second = settle(client, headers, "이순신", "010-2222-3333", "20262222", row=3)
    for pid in (first, second):
        client.patch(f"/api/admin/participants/{pid}", headers=headers, json={"isConfirmed": True})
    client.patch(
        f"/api/admin/participants/{first}", headers=headers, json={"assignments": {"group": "1조"}}
    )

    items = client.get(
        "/api/admin/participants?confirmed=true&unassigned=group", headers=headers
    ).get_json()["items"]
    assert [item["name"] for item in items] == ["이순신"]
