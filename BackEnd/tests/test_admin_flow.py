"""관리자 API 통합 테스트.

프론트엔드가 의존하는 계약(응답 형태·상태 전이)을 HTTP 수준에서 확인한다.

입금은 거래내역 파일 업로드로 들어온다. 카카오뱅크 개인 계좌에는 공개 API가 없고,
유심 없는 공기계로는 앱 로그인조차 되지 않아 알림 포워딩을 쓸 수 없기 때문이다.
따라서 테스트도 실제 운영과 같은 경로를 탄다.
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
from tests.test_statement import lock_xlsx  # noqa: E402

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
        # 테스트에서 429 에 걸리지 않도록 한도를 넉넉히 둔다
        LOGIN_RATE_LIMIT="1000 per minute",
        LOOKUP_RATE_LIMIT="1000 per minute",
        # 개발자 로컬 .env 에 실제 파일 비밀번호가 들어 있어도 결과가 달라지지 않도록
        # 비운 채로 시작한다. 필요한 테스트에서만 직접 채운다.
        STATEMENT_PASSWORDS=[],
    )
    with application.app_context():
        db.drop_all()
        db.create_all()
        yield application.test_client()
        db.session.remove()


def auth_headers(client) -> dict:
    response = client.post("/api/admin/login", json={"username": SUPER_ID, "password": PASSWORD})
    assert response.status_code == 200, response.get_json()
    return {"Authorization": f"Bearer {response.get_json()['token']}"}


def submit_form(client, name: str, phone: str, member: bool = True, row: int = 2):
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


def deposit_row(when: str, amount: int, balance: int, name: str) -> list:
    """카카오뱅크 거래내역의 입금 1행."""
    return [when, "입금", amount, balance, "일반입금", name, None]


def upload(client, headers, rows: list[list], filename: str = "카카오뱅크_거래내역.xlsx"):
    """거래내역 파일 업로드 — 현재의 유일한 입금 수집 경로."""
    return client.post(
        "/api/admin/deposits/import",
        headers=headers,
        data={"file": (io.BytesIO(build_real_format(rows)), filename)},
        content_type="multipart/form-data",
    )


def test_upload_locked_statement(client):
    """비밀번호가 걸린 파일을 손대지 않고 그대로 올릴 수 있어야 한다."""
    headers = auth_headers(client)
    submit_form(client, "홍길동", "010-1234-5678")

    rows = [deposit_row("2026.08.01 12:00:00", 5000, 1045000, "홍길동5678")]
    locked = lock_xlsx(build_real_format(rows), "test-lock-1234")

    # 비밀번호가 등록되어 있지 않으면 이유를 알려주며 거절한다 (500 이 아니라 400)
    response = client.post(
        "/api/admin/deposits/import",
        headers=headers,
        data={"file": (io.BytesIO(locked), "카카오뱅크_거래내역.xlsx")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400, response.get_json()
    assert "비밀번호" in response.get_json()["message"]

    client.application.config["STATEMENT_PASSWORDS"] = ["test-lock-1234"]
    response = client.post(
        "/api/admin/deposits/import",
        headers=headers,
        data={"file": (io.BytesIO(locked), "카카오뱅크_거래내역.xlsx")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["decrypted"] is True
    assert body["created"] == 1

    # 잠긴 파일이든 아니든 같은 경로를 타므로 매칭 결과도 같아야 한다
    participants = client.get("/api/admin/participants", headers=headers).get_json()
    assert participants["items"][0]["status"] == "PAID"


def test_login_required_and_rejects_wrong_password(client):
    assert client.get("/api/admin/summary").status_code == 401
    assert client.post("/api/admin/login", json={"password": "wrong"}).status_code == 401


def test_full_flow_form_to_status(client):
    headers = auth_headers(client)

    # 1) 폼 제출
    response = submit_form(client, "홍길동", "010-1234-5678")
    assert response.status_code == 200
    assert response.get_json()["result"]["created"] == 1

    # 2) 관리자가 거래내역 파일을 올린다
    result = upload(
        client,
        headers,
        [deposit_row("2026.08.02 11:00:00", 5000, 1045000, "홍길동5678")],
    ).get_json()
    assert result["created"] == 1

    # 3) 본인 조회
    response = client.post("/api/status", json={"name": "홍길동", "phone": "01012345678"})
    payload = response.get_json()
    assert payload["found"] is True
    assert payload["participant"]["status"] == "PAID"
    assert payload["participant"]["paidAmount"] == 5_000
    # 실시간이 아니므로 어디까지 반영됐는지 함께 알려준다
    assert payload["sync"]["coverageUntil"] == "2026-08-02T11:00:00"

    # 4) 요약
    summary = client.get("/api/admin/summary", headers=headers).get_json()
    assert summary["participants"]["active"] == 1
    assert summary["amounts"]["collectedTotal"] == 5_000
    assert summary["deposits"]["needsReview"] == 0


def test_overlapping_uploads_do_not_double_count(client):
    """기간이 겹치는 파일을 여러 번 올려도 입금이 중복되지 않아야 한다.

    실제 운영에서 가장 흔한 실수다. 매번 '이번 달 전체'를 받아 올리면
    앞서 올린 건이 그대로 다시 들어온다.
    """
    headers = auth_headers(client)
    submit_form(client, "이순신", "010-1111-2222", member=False, row=2)

    first = upload(
        client,
        headers,
        [
            deposit_row("2026.08.01 10:00:00", 7000, 1059000, "이순신2222"),
            deposit_row("2026.08.02 10:00:00", 12000, 1071000, "관계없는입금"),
        ],
    ).get_json()
    assert first["created"] == 2

    # 08/02 가 겹치는 두 번째 파일
    second = upload(
        client,
        headers,
        [
            deposit_row("2026.08.02 10:00:00", 12000, 1071000, "관계없는입금"),
            deposit_row("2026.08.03 10:00:00", 5000, 1076000, "새로운입금"),
        ],
    ).get_json()
    assert second["created"] == 1      # 08/03 만 신규
    assert second["duplicated"] == 1   # 08/02 는 중복으로 흡수

    status = client.post("/api/status", json={"name": "이순신", "phone": "01011112222"}).get_json()
    assert status["participant"]["paidAmount"] == 7_000


def test_manual_assignment_of_unmatched_deposit(client):
    """입금자명이 신청자와 다른 경우, 관리자가 참가자를 직접 지정한다."""
    headers = auth_headers(client)
    submit_form(client, "김일", "010-1000-0001", row=2)

    # 어머니 명의로 입금되어 이름 매칭 실패
    upload(client, headers, [deposit_row("2026.08.02 10:00:00", 5000, 1045000, "박모친")])

    deposits = client.get("/api/admin/deposits?status=REVIEW", headers=headers).get_json()["items"]
    assert len(deposits) == 1
    assert deposits[0]["status"] == "UNMATCHED"

    participants = client.get("/api/admin/participants", headers=headers).get_json()["items"]
    assigned = client.put(
        f"/api/admin/deposits/{deposits[0]['id']}/allocations",
        headers=headers,
        json={"allocations": [{"participantId": participants[0]["id"], "amount": 5_000}]},
    )
    assert assigned.status_code == 200
    assert assigned.get_json()["status"] == "MATCHED"
    assert assigned.get_json()["manualLocked"] is True
    assert assigned.get_json()["matchReason"] == "관리자가 직접 지정"

    status = client.post("/api/status", json={"name": "김일", "phone": "01010000001"}).get_json()
    assert status["participant"]["status"] == "PAID"


def test_participant_can_pay_in_two_installments(client):
    """입금 1건 = 참가자 1명이지만, 한 참가자가 여러 번 나눠 내는 것은 가능하다."""
    headers = auth_headers(client)
    submit_form(client, "정약용", "010-7777-8888")

    upload(
        client,
        headers,
        [
            deposit_row("2026.08.01 10:00:00", 3000, 1003000, "정약용8888"),
            deposit_row("2026.08.05 10:00:00", 2000, 1005000, "정약용8888"),
        ],
    )

    status = client.post("/api/status", json={"name": "정약용", "phone": "01077778888"}).get_json()
    assert status["participant"]["paidAmount"] == 5_000
    assert status["participant"]["status"] == "PAID"


def test_over_allocation_is_rejected(client):
    headers = auth_headers(client)
    submit_form(client, "박초과", "010-3000-4000")
    upload(client, headers, [deposit_row("2026.08.02 10:00:00", 3000, 1003000, "알수없음")])

    deposits = client.get("/api/admin/deposits", headers=headers).get_json()["items"]
    participants = client.get("/api/admin/participants", headers=headers).get_json()["items"]

    response = client.put(
        f"/api/admin/deposits/{deposits[0]['id']}/allocations",
        headers=headers,
        json={"allocations": [{"participantId": participants[0]["id"], "amount": 5_000}]},
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "over_allocation"


def test_status_override_and_audit(client):
    headers = auth_headers(client)
    submit_form(client, "면제자", "010-7000-8000")
    participants = client.get("/api/admin/participants", headers=headers).get_json()["items"]

    updated = client.patch(
        f"/api/admin/participants/{participants[0]['id']}",
        headers=headers,
        json={"statusOverride": "WAIVED", "memo": "학생회 임원 면제"},
    )
    assert updated.status_code == 200
    assert updated.get_json()["status"] == "WAIVED"

    status = client.post("/api/status", json={"name": "면제자", "phone": "01070008000"}).get_json()
    assert status["participant"]["status"] == "WAIVED"

    audit = client.get("/api/admin/audit", headers=headers).get_json()["items"]
    actions = {entry["action"] for entry in audit}
    assert "participant.update" in actions
    assert "login" in actions


def test_overridden_filter_lists_only_hand_set_statuses(client):
    """'수동 지정' 필터는 관리자가 손으로 눌러 둔 사람만 모아야 한다."""
    headers = auth_headers(client)
    submit_form(client, "면제자", "010-7000-8001", row=2)
    submit_form(client, "그대로", "010-7000-8002", row=3)

    items = client.get("/api/admin/participants", headers=headers).get_json()["items"]
    waived = next(item for item in items if item["name"] == "면제자")
    client.patch(
        f"/api/admin/participants/{waived['id']}", headers=headers, json={"statusOverride": "WAIVED"}
    )

    filtered = client.get(
        "/api/admin/participants?overridden=true", headers=headers
    ).get_json()["items"]
    assert [item["name"] for item in filtered] == ["면제자"]

    # 필터를 걸지 않으면 그대로 둘 다 나온다
    assert len(client.get("/api/admin/participants", headers=headers).get_json()["items"]) == 2


def test_resubmission_updates_instead_of_duplicating(client):
    headers = auth_headers(client)
    submit_form(client, "재신청", "010-9000-1000", member=True, row=2)
    submit_form(client, "재신청", "010-9000-1000", member=False, row=5)

    items = client.get("/api/admin/participants", headers=headers).get_json()["items"]
    assert len(items) == 1
    assert items[0]["expectedAmount"] == 7_000
    assert items[0]["submissionCount"] == 2


def test_participant_profile_can_be_corrected(client):
    """폼에 잘못 적어 낸 값을 관리자 페이지에서 고친다."""
    headers = auth_headers(client)
    submit_form(client, "홍길동", "010-1234-5678")
    pid = client.get("/api/admin/participants", headers=headers).get_json()["items"][0]["id"]

    response = client.patch(
        f"/api/admin/participants/{pid}",
        headers=headers,
        json={
            # 학번 칸에 생년월일을 적어 낸 것을 바로잡는다
            "studentId": "20269999",
            "department": "전자공학과",
            "gender": "남",
            "emergencyPhone": "010-9999-0000",
        },
    )
    assert response.status_code == 200, response.get_json()
    fixed = response.get_json()
    assert fixed["studentId"] == "20269999"
    assert fixed["department"] == "전자공학과"
    # 전화번호는 숫자만 남겨 보관한다
    assert fixed["emergencyPhone"] == "01099990000"

    audit = client.get("/api/admin/audit", headers=headers).get_json()["items"]
    entry = next(item for item in audit if item["action"] == "participant.update")
    assert {change["label"] for change in entry["detail"]["changes"]} == {
        "학번", "학과", "성별", "비상 연락처",
    }


def test_profile_edit_rejects_empty_name_and_duplicate_phone(client):
    """이름과 전화번호는 사람을 알아보는 기준이라 아무 값이나 받을 수 없다."""
    headers = auth_headers(client)
    submit_form(client, "홍길동", "010-1234-5678", row=2)
    submit_form(client, "이순신", "010-2222-3333", row=3)
    items = client.get("/api/admin/participants", headers=headers).get_json()["items"]
    target = next(item for item in items if item["name"] == "홍길동")

    taken = client.patch(
        f"/api/admin/participants/{target['id']}",
        headers=headers,
        json={"phone": "010-2222-3333"},
    )
    assert taken.status_code == 409
    assert taken.get_json()["error"] == "duplicate_phone"

    blank = client.patch(
        f"/api/admin/participants/{target['id']}", headers=headers, json={"name": "  "}
    )
    assert blank.status_code == 400
    assert blank.get_json()["error"] == "invalid_name"

    short = client.patch(
        f"/api/admin/participants/{target['id']}", headers=headers, json={"phone": "1234"}
    )
    assert short.status_code == 400
    assert short.get_json()["error"] == "invalid_phone"

    # 거절된 요청이 값을 반쯤 바꿔 놓고 가서는 안 된다
    unchanged = client.get(f"/api/admin/participants/{target['id']}", headers=headers).get_json()
    assert unchanged["name"] == "홍길동"
    assert unchanged["phone"] == "01012345678"


def test_name_correction_rescues_unmatched_deposit(client):
    """이름을 잘못 적어 붙지 못했던 입금이, 이름을 고치면 붙어야 한다."""
    headers = auth_headers(client)
    submit_form(client, "홍길똥", "010-1234-5678")
    upload(client, headers, [deposit_row("2026.08.02 10:00:00", 5000, 1045000, "홍길동5678")])

    pid = client.get("/api/admin/participants", headers=headers).get_json()["items"][0]["id"]
    assert client.get(f"/api/admin/participants/{pid}", headers=headers).get_json()["status"] == "UNPAID"

    fixed = client.patch(
        f"/api/admin/participants/{pid}", headers=headers, json={"name": "홍길동"}
    )
    assert fixed.status_code == 200
    assert fixed.get_json()["paidAmount"] == 5_000
    assert fixed.get_json()["status"] == "PAID"


def test_manual_participant_registration(client):
    """폼을 내지 않은 사람을 관리자가 직접 명단에 넣는다."""
    headers = auth_headers(client)

    response = client.post(
        "/api/admin/participants",
        headers=headers,
        json={
            "name": "현장합류",
            "phone": "010-5555-6666",
            "studentId": "20265555",
            "department": "전자공학과",
            "feeClass": "nonmember",
            "memo": "당일 합류",
        },
    )
    assert response.status_code == 201, response.get_json()
    created = response.get_json()["participant"]
    assert created["name"] == "현장합류"
    assert created["phone"] == "01055556666"
    assert created["expectedAmount"] == 7_000
    assert created["status"] == "UNPAID"

    # 폼으로 들어온 사람과 같은 명단에 있어야 한다
    items = client.get("/api/admin/participants", headers=headers).get_json()["items"]
    assert [item["name"] for item in items] == ["현장합류"]

    # 본인 조회도 폼 제출자와 똑같이 된다
    status = client.post("/api/status", json={"name": "현장합류", "phone": "01055556666"}).get_json()
    assert status["found"] is True

    audit = client.get("/api/admin/audit", headers=headers).get_json()["items"]
    assert "participant.create" in {entry["action"] for entry in audit}


def test_manual_participant_rejects_duplicate_and_bad_phone(client):
    """전화번호가 자연키다. 손으로 한 번 더 넣어 두 사람이 되는 일을 막는다."""
    headers = auth_headers(client)
    submit_form(client, "홍길동", "010-1234-5678")

    duplicated = client.post(
        "/api/admin/participants",
        headers=headers,
        json={"name": "홍길동", "phone": "01012345678"},
    )
    assert duplicated.status_code == 409
    assert duplicated.get_json()["error"] == "duplicate_phone"

    short = client.post(
        "/api/admin/participants",
        headers=headers,
        json={"name": "번호오류", "phone": "1234"},
    )
    assert short.status_code == 400
    assert short.get_json()["error"] == "invalid_phone"

    nameless = client.post(
        "/api/admin/participants",
        headers=headers,
        json={"name": "  ", "phone": "010-2222-3333"},
    )
    assert nameless.status_code == 400
    assert nameless.get_json()["error"] == "invalid_name"

    assert len(client.get("/api/admin/participants", headers=headers).get_json()["items"]) == 1


def test_manual_participant_picks_up_earlier_deposit(client):
    """먼저 들어와 미매칭으로 남아 있던 입금이 등록과 동시에 붙어야 한다.

    폼이 늦게 도착했을 때와 같은 처리다 — 손으로 넣었다고 입금을 다시
    찾아 지정하게 두면 그 단계에서 빠뜨린다.
    """
    headers = auth_headers(client)
    upload(client, headers, [deposit_row("2026.08.02 10:00:00", 7000, 1059000, "수기등록9999")])

    response = client.post(
        "/api/admin/participants",
        headers=headers,
        json={"name": "수기등록", "phone": "010-0000-9999", "feeClass": "nonmember"},
    )
    assert response.status_code == 201
    assert response.get_json()["participant"]["paidAmount"] == 7_000
    assert response.get_json()["participant"]["status"] == "PAID"


def test_late_form_submission_rescues_unmatched_deposit(client):
    """입금이 먼저 올라가고 폼이 나중에 제출되는 순서도 처리되어야 한다."""
    headers = auth_headers(client)
    upload(client, headers, [deposit_row("2026.08.02 10:00:00", 5000, 1045000, "늦은신청1234")])

    submit_form(client, "늦은신청", "010-0000-1234")

    status = client.post("/api/status", json={"name": "늦은신청", "phone": "01000001234"}).get_json()
    assert status["participant"]["status"] == "PAID"
