"""럭키드로우 — 번호 발급과 추첨.

이 파일이 지키는 계약은 셋이다.

  1. 번호는 **체크인한 순서대로** 001 부터 붙고, 한 번 받으면 바뀌지 않는다.
     스태프가 출석을 취소해도 번호를 회수하지 않는다 — 번호를 다시 쓰면
     자기 번호를 외운 채 추첨 화면을 보고 있는 사람과 어긋난다.

  2. 추첨은 **실제로 발급된 번호 중에서만** 나온다. 무작위 세 자리를 만들어
     맞는 사람을 찾는 방식이면 250명 자리에서 287번이 나온다.

  3. 결과는 뽑는 순간 남는다. 무효 처리는 행을 지우지 않고 표시만 남긴다.
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
        ensure_default_fields()
        yield application.test_client()
        db.session.remove()


def auth_headers(client) -> dict:
    response = client.post("/api/admin/login", json={"username": SUPER_ID, "password": PASSWORD})
    assert response.status_code == 200, response.get_json()
    return {"Authorization": f"Bearer {response.get_json()['token']}"}


def arrive(client, headers, name: str, phone: str, student_id: str, row: int) -> int:
    """폼 제출 → 납입 → 확정까지. 반환값은 참가자 id (체크인은 아직 안 한 상태)."""
    assert client.post(
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
    ).status_code == 200

    assert client.post(
        "/api/admin/deposits",
        headers=headers,
        json={"rawName": f"{name}{phone[-4:]}", "amount": 45_000, "occurredAt": "2026-08-02 11:00:00"},
    ).status_code in (200, 201)

    items = client.get(f"/api/admin/participants?query={name}", headers=headers).get_json()["items"]
    assert items, f"{name} 을 찾지 못했습니다."
    pid = items[0]["id"]

    assert client.patch(
        f"/api/admin/participants/{pid}", headers=headers, json={"isConfirmed": True}
    ).status_code == 200
    return pid


# 입금자명 파싱은 '이름 + 전화번호 뒷자리' 를 가정한다. 이름에 숫자가 섞이면
# ('사람0' 같은 식) 이름과 뒷자리의 경계가 흐려져 매칭이 어긋난다.
NAMES = ["가람", "나래", "다솜", "라온", "마루", "바다", "새롬", "아라", "차슬", "하늘"]


def nth(index: int) -> tuple[str, str, str, str]:
    """n번째 가상 참가자. (이름, 전화번호, 학번, 뒷자리)"""
    last4 = f"{1001 + index:04d}"
    return NAMES[index], f"010-4000-{last4}", f"2027{index:04d}", last4


def open_window(client, headers, want: bool = True) -> None:
    assert client.post(
        "/api/admin/checkin-window", headers=headers, json={"open": want}
    ).status_code == 200


def self_checkin(client, name: str, student_id: str, last4: str):
    return client.post(
        "/api/checkin",
        json={"name": name, "studentId": student_id, "phoneLast4": last4},
    )


# ---------------------------------------------------------------------------
# 번호 발급
# ---------------------------------------------------------------------------

def test_numbers_follow_checkin_order(client):
    """먼저 체크인한 사람이 001. 신청 순서나 이름 순서가 아니다."""
    headers = auth_headers(client)
    arrive(client, headers, "가나다", "010-1111-1111", "20260001", row=2)
    arrive(client, headers, "하버지", "010-2222-2222", "20260002", row=3)
    open_window(client, headers)

    # 이름 순으로는 '가나다'가 먼저지만, 체크인은 '하버지'가 먼저 했다.
    second = self_checkin(client, "하버지", "20260002", "2222").get_json()
    first = self_checkin(client, "가나다", "20260001", "1111").get_json()

    assert second["participant"]["drawLabel"] == "001"
    assert first["participant"]["drawLabel"] == "002"


def test_number_is_kept_across_repeat_checkins(client):
    """같은 사람이 화면을 다시 열어도 번호가 바뀌지 않는다."""
    headers = auth_headers(client)
    arrive(client, headers, "홍길동", "010-1234-5678", "20261234", row=2)
    open_window(client, headers)

    first = self_checkin(client, "홍길동", "20261234", "5678").get_json()
    again = self_checkin(client, "홍길동", "20261234", "5678").get_json()

    assert again["alreadyCheckedIn"] is True
    assert again["participant"]["drawLabel"] == first["participant"]["drawLabel"] == "001"


def test_number_survives_attendance_cancellation(client):
    """스태프가 출석을 취소해도 번호는 회수하지 않는다. 대신 후보에서 빠진다."""
    headers = auth_headers(client)
    pid = arrive(client, headers, "홍길동", "010-1234-5678", "20261234", row=2)
    open_window(client, headers)
    assert self_checkin(client, "홍길동", "20261234", "5678").get_json()["participant"]["drawNo"] == 1

    payload = client.patch(
        f"/api/admin/participants/{pid}", headers=headers, json={"isCheckedIn": False}
    ).get_json()
    assert payload["drawNo"] == 1          # 번호는 그대로
    assert payload["checkedInAt"] is None

    state = client.get("/api/admin/draw", headers=headers).get_json()
    assert state["counts"]["issued"] == 1
    assert state["counts"]["eligible"] == 0        # 후보에서는 빠졌다
    assert state["pool"][0]["out"] == "not_checked_in"


def test_staff_checkin_also_issues_a_number(client):
    """휴대폰이 없어 스태프가 대신 처리한 사람도 똑같이 번호를 받아야 한다."""
    headers = auth_headers(client)
    pid = arrive(client, headers, "홍길동", "010-1234-5678", "20261234", row=2)

    payload = client.patch(
        f"/api/admin/participants/{pid}", headers=headers, json={"isCheckedIn": True}
    ).get_json()
    assert payload["drawLabel"] == "001"


def test_numbers_are_unique(client):
    """번호가 겹치면 추첨 자체가 성립하지 않는다."""
    headers = auth_headers(client)
    prepare_pool(client, headers, 5)

    state = client.get("/api/admin/draw", headers=headers).get_json()
    labels = [tile["label"] for tile in state["pool"]]
    assert labels == ["001", "002", "003", "004", "005"]


# ---------------------------------------------------------------------------
# 추첨
# ---------------------------------------------------------------------------

def prepare_pool(client, headers, count: int) -> None:
    """count 명이 확정 → 체크인까지 끝난 상태를 만든다. 번호는 001 부터 순서대로."""
    for index in range(count):
        name, phone, student_id, _ = nth(index)
        arrive(client, headers, name, phone, student_id, row=index + 2)
    open_window(client, headers)
    for index in range(count):
        name, _, student_id, last4 = nth(index)
        response = self_checkin(client, name, student_id, last4)
        assert response.get_json()["ok"] is True, response.get_json()


def test_winner_is_always_an_issued_number(client):
    """뽑힌 번호는 반드시 발급된 번호 중 하나다."""
    headers = auth_headers(client)
    prepare_pool(client, headers, 6)

    for _ in range(10):
        response = client.post("/api/admin/draw", headers=headers, json={"allowRepeat": True})
        assert response.status_code == 200, response.get_json()
        assert response.get_json()["draw"]["drawNo"] in range(1, 7)


def test_draw_excludes_previous_winners_by_default(client):
    """중복 당첨은 기본적으로 막는다. 세 명이면 세 번째까지만 뽑힌다."""
    headers = auth_headers(client)
    prepare_pool(client, headers, 3)

    winners = []
    for _ in range(3):
        response = client.post("/api/admin/draw", headers=headers, json={"prize": "간식"})
        assert response.status_code == 200, response.get_json()
        winners.append(response.get_json()["draw"]["drawNo"])

    assert sorted(winners) == [1, 2, 3]          # 서로 다른 세 명

    # 남은 후보가 없다
    response = client.post("/api/admin/draw", headers=headers, json={})
    assert response.status_code == 400
    assert response.get_json()["error"] == "empty_pool"


def test_draw_without_anyone_checked_in_fails_clearly(client):
    headers = auth_headers(client)
    arrive(client, headers, "홍길동", "010-1234-5678", "20261234", row=2)

    response = client.post("/api/admin/draw", headers=headers, json={})
    assert response.status_code == 400
    assert response.get_json()["error"] == "empty_pool"
    assert "체크인" in response.get_json()["message"]


def test_animation_pool_still_contains_the_winner(client):
    """연출은 '뽑기 전' 판으로 돌아야 한다.

    뽑은 뒤의 판을 주면 당첨자 타일이 이미 '당첨됨'으로 흐려진 상태에서
    그 번호가 나오게 되어, 화면이 스스로 답을 부정한다.
    """
    headers = auth_headers(client)
    prepare_pool(client, headers, 4)

    payload = client.post("/api/admin/draw", headers=headers, json={}).get_json()
    winner = payload["draw"]["drawNo"]
    tile = next(item for item in payload["state"]["pool"] if item["no"] == winner)
    assert tile["eligible"] is True

    # 다음 조회에서는 후보에서 빠져 있다
    state = client.get("/api/admin/draw", headers=headers).get_json()
    tile = next(item for item in state["pool"] if item["no"] == winner)
    assert tile["eligible"] is False
    assert tile["out"] == "already_won"


def test_digits_narrow_the_pool_to_exactly_one(client):
    """연출이 성립하기 위한 조건.

    추첨 화면은 자릿수를 왼쪽부터 하나씩 잠그면서, 그때까지 잠긴 숫자로 시작하지
    않는 번호를 판에서 꺼 나간다. 그래서 마지막 자리가 잠기는 순간 **정확히 한 명**이
    남아야 한다. 한 명이 아니면 화면이 스스로 답을 부정하게 된다.
    """
    headers = auth_headers(client)
    prepare_pool(client, headers, 10)

    payload = client.post("/api/admin/draw", headers=headers, json={}).get_json()
    label = payload["draw"]["drawLabel"]
    pool = payload["state"]["pool"]
    assert payload["state"]["digits"] == len(label) == 3

    counts = []
    for step in range(1, len(label) + 1):
        prefix = label[:step]
        alive = [t for t in pool if t["eligible"] and t["label"].startswith(prefix)]
        counts.append(len(alive))

    assert counts[-1] == 1                                  # 마지막엔 한 명
    assert alive[0]["label"] == label                        # 그 한 명이 당첨자
    assert counts == sorted(counts, reverse=True)            # 단계마다 좁혀지기만 한다


def test_exclude_staff_option(client):
    headers = auth_headers(client)
    prepare_pool(client, headers, 3)
    # 001 번(가장 먼저 체크인한 사람)을 스태프로 돌린다
    items = client.get(f"/api/admin/participants?query={NAMES[0]}", headers=headers).get_json()["items"]
    client.patch(
        f"/api/admin/participants/{items[0]['id']}", headers=headers, json={"feeClass": "staff"}
    )

    state = client.get("/api/admin/draw?excludeStaff=true", headers=headers).get_json()
    assert state["counts"]["eligible"] == 2
    assert next(t for t in state["pool"] if t["no"] == 1)["out"] == "staff"

    # 스태프를 제외하고 두 번 뽑으면 스태프는 나오지 않는다
    for _ in range(2):
        payload = client.post(
            "/api/admin/draw", headers=headers, json={"excludeStaff": True}
        ).get_json()
        assert payload["draw"]["drawNo"] != 1


def test_round_numbers_and_prize_are_recorded(client):
    headers = auth_headers(client)
    prepare_pool(client, headers, 3)

    first = client.post("/api/admin/draw", headers=headers, json={"prize": "1등 에어팟"}).get_json()
    second = client.post("/api/admin/draw", headers=headers, json={"prize": "2등 텀블러"}).get_json()

    assert (first["draw"]["roundNo"], first["draw"]["prize"]) == (1, "1등 에어팟")
    assert (second["draw"]["roundNo"], second["draw"]["prize"]) == (2, "2등 텀블러")
    assert first["draw"]["poolSize"] == 3
    assert second["draw"]["poolSize"] == 2      # 1등 당첨자가 빠졌다
    assert first["draw"]["name"] is not None    # 당첨자를 부를 수 있어야 한다


def test_voiding_returns_the_winner_to_the_pool(client):
    """자리에 없는 사람이 뽑혔을 때. 기록은 남고 후보로는 돌아온다."""
    headers = auth_headers(client)
    prepare_pool(client, headers, 2)

    payload = client.post("/api/admin/draw", headers=headers, json={"prize": "1등"}).get_json()
    draw_id, winner = payload["draw"]["id"], payload["draw"]["drawNo"]

    response = client.post(
        f"/api/admin/draw/{draw_id}/void", headers=headers, json={"reason": "자리에 없음"}
    )
    assert response.status_code == 200
    state = response.get_json()["state"]

    assert state["counts"]["eligible"] == 2                     # 둘 다 다시 후보
    assert state["nextRoundNo"] == 1                            # 회차도 비워졌다
    voided = next(item for item in state["history"] if item["id"] == draw_id)
    assert voided["voided"] is True
    assert voided["voidedReason"] == "자리에 없음"
    assert voided["drawNo"] == winner                           # 기록은 지워지지 않는다

    # 두 번 무효로 하지는 못한다
    assert client.post(f"/api/admin/draw/{draw_id}/void", headers=headers, json={}).status_code == 400


def test_draw_actions_are_audited(client):
    headers = auth_headers(client)
    prepare_pool(client, headers, 2)
    payload = client.post("/api/admin/draw", headers=headers, json={"prize": "1등"}).get_json()
    client.post(
        f"/api/admin/draw/{payload['draw']['id']}/void", headers=headers, json={"reason": "부재"}
    )

    actions = [row["action"] for row in client.get("/api/admin/audit", headers=headers).get_json()["items"]]
    assert "draw.create" in actions
    assert "draw.void" in actions


def test_pool_tiles_carry_no_personal_information(client):
    """추첨 화면은 스크린에 띄운다. 번호 판에 이름이 섞이면 명단이 공개된다."""
    headers = auth_headers(client)
    prepare_pool(client, headers, 3)

    state = client.get("/api/admin/draw", headers=headers).get_json()
    assert state["pool"]
    for tile in state["pool"]:
        assert set(tile) == {"no", "label", "eligible", "out"}


def test_draw_requires_admin(client):
    assert client.get("/api/admin/draw").status_code == 401
    assert client.post("/api/admin/draw", json={}).status_code == 401
    assert client.put("/api/admin/draw/prizes", json={"prizes": []}).status_code == 401
    assert client.delete("/api/admin/draw").status_code == 401


# ---------------------------------------------------------------------------
# 시연 후 정리
# ---------------------------------------------------------------------------

def test_clearing_history_resets_the_draw(client):
    """시연으로 몇 번 돌려 본 뒤 진짜 추첨을 처음부터 시작할 수 있어야 한다."""
    headers = auth_headers(client)
    prizes = set_prizes(client, headers, [{"label": "1등 에어팟", "count": 1}])
    prepare_pool(client, headers, 3)

    client.post("/api/admin/draw", headers=headers, json={"prizeId": prizes[0]["id"]})
    client.post("/api/admin/draw", headers=headers, json={})

    response = client.delete("/api/admin/draw", headers=headers)
    assert response.status_code == 200
    body = response.get_json()
    assert body["deleted"] == 2

    state = body["state"]
    assert state["history"] == []
    assert state["nextRoundNo"] == 1
    assert state["counts"]["won"] == 0
    assert state["counts"]["eligible"] == 3            # 전원 다시 후보
    assert state["prizes"][0]["remaining"] == 1        # 상품도 되돌아온다
    assert all(tile["eligible"] for tile in state["pool"])


def test_clearing_history_keeps_the_numbers(client):
    """번호는 체크인의 부산물이다. 함께 지우면 자기 번호를 이미 본 사람과 어긋난다."""
    headers = auth_headers(client)
    prepare_pool(client, headers, 3)
    client.post("/api/admin/draw", headers=headers, json={})

    before = [tile["label"] for tile in
              client.get("/api/admin/draw", headers=headers).get_json()["pool"]]
    after = client.delete("/api/admin/draw", headers=headers).get_json()["state"]["pool"]

    assert [tile["label"] for tile in after] == before == ["001", "002", "003"]


def test_clearing_history_is_itself_recorded(client):
    """기록을 지운 행위까지 지울 수 있으면 이력이 의미를 잃는다."""
    headers = auth_headers(client)
    prepare_pool(client, headers, 2)
    payload = client.post("/api/admin/draw", headers=headers, json={"prize": "1등"}).get_json()
    winner = payload["draw"]["drawLabel"]

    client.delete("/api/admin/draw", headers=headers)

    rows = client.get("/api/admin/audit", headers=headers).get_json()["items"]
    cleared = next(row for row in rows if row["action"] == "draw.clear")
    notes = " ".join(str(note) for note in cleared["detail"].values())
    assert "1건" in notes
    assert winner in notes           # 무엇을 지웠는지가 남는다


def test_clearing_an_empty_history_is_harmless(client):
    headers = auth_headers(client)
    response = client.delete("/api/admin/draw", headers=headers)
    assert response.status_code == 200
    assert response.get_json()["deleted"] == 0


# ---------------------------------------------------------------------------
# 상품 목록
# ---------------------------------------------------------------------------

def set_prizes(client, headers, prizes: list[dict]) -> list[dict]:
    response = client.put("/api/admin/draw/prizes", headers=headers, json={"prizes": prizes})
    assert response.status_code == 200, response.get_json()
    return response.get_json()["state"]["prizes"]


def test_prizes_are_registered_once_and_kept(client):
    """행사 전에 등록해 두고 당일에는 고르기만 한다."""
    headers = auth_headers(client)
    saved = set_prizes(client, headers, [
        {"label": "1등 에어팟", "count": 1},
        {"label": "2등 텀블러", "count": 3},
    ])

    assert [(p["label"], p["count"], p["remaining"]) for p in saved] == [
        ("1등 에어팟", 1, 1),
        ("2등 텀블러", 3, 3),
    ]
    assert all(p["id"] for p in saved)

    # 다시 조회해도 그대로 (관리자가 미리 넣어 두고 당일 다른 기기에서 연다)
    state = client.get("/api/admin/draw", headers=headers).get_json()
    assert [p["label"] for p in state["prizes"]] == ["1등 에어팟", "2등 텀블러"]


def test_prize_id_survives_a_label_change(client):
    """이름을 고쳐도 이미 나간 개수는 따라와야 한다 (집계는 id 로 센다)."""
    headers = auth_headers(client)
    prizes = set_prizes(client, headers, [{"label": "간식", "count": 5}])
    prize_id = prizes[0]["id"]

    prepare_pool(client, headers, 3)
    client.post("/api/admin/draw", headers=headers, json={"prizeId": prize_id})

    renamed = set_prizes(client, headers, [{"id": prize_id, "label": "간식 세트", "count": 5}])
    assert renamed[0]["drawn"] == 1
    assert renamed[0]["remaining"] == 4


def test_prize_name_comes_from_the_registered_list(client):
    """화면이 보낸 이름을 그대로 믿지 않는다. 목록과 어긋나면 수량이 맞지 않는다."""
    headers = auth_headers(client)
    prizes = set_prizes(client, headers, [{"label": "1등 에어팟", "count": 1}])
    prepare_pool(client, headers, 3)

    payload = client.post("/api/admin/draw", headers=headers, json={
        "prizeId": prizes[0]["id"],
        "prize": "내 마음대로 적은 이름",
    }).get_json()

    assert payload["draw"]["prize"] == "1등 에어팟"
    assert payload["draw"]["prizeId"] == prizes[0]["id"]


def test_exhausted_prize_is_refused(client):
    """준비한 개수를 넘겨 뽑으면 시상식에서 물건이 모자란다."""
    headers = auth_headers(client)
    prizes = set_prizes(client, headers, [{"label": "1등 에어팟", "count": 1}])
    prize_id = prizes[0]["id"]
    prepare_pool(client, headers, 4)

    assert client.post(
        "/api/admin/draw", headers=headers, json={"prizeId": prize_id}
    ).status_code == 200

    response = client.post("/api/admin/draw", headers=headers, json={"prizeId": prize_id})
    assert response.status_code == 400
    assert response.get_json()["error"] == "prize_exhausted"

    # 상품을 고르지 않으면 제한 없이 뽑을 수 있다
    assert client.post("/api/admin/draw", headers=headers, json={}).status_code == 200


def test_voiding_returns_the_prize_too(client):
    """당첨이 무효면 상품도 다시 걸 수 있어야 한다."""
    headers = auth_headers(client)
    prizes = set_prizes(client, headers, [{"label": "1등 에어팟", "count": 1}])
    prize_id = prizes[0]["id"]
    prepare_pool(client, headers, 3)

    payload = client.post("/api/admin/draw", headers=headers, json={"prizeId": prize_id}).get_json()
    body = client.post(
        f"/api/admin/draw/{payload['draw']['id']}/void", headers=headers, json={"reason": "부재"}
    ).get_json()

    prize = next(p for p in body["state"]["prizes"] if p["id"] == prize_id)
    assert (prize["drawn"], prize["remaining"]) == (0, 1)


def test_unknown_prize_is_refused(client):
    headers = auth_headers(client)
    prepare_pool(client, headers, 3)
    response = client.post("/api/admin/draw", headers=headers, json={"prizeId": "deadbeef"})
    assert response.status_code == 400
    assert response.get_json()["error"] == "unknown_prize"


def test_broken_prize_entries_are_dropped_not_fatal(client):
    """이름 없는 줄이나 이상한 수량이 섞여도 화면이 죽어서는 안 된다."""
    headers = auth_headers(client)
    saved = set_prizes(client, headers, [
        {"label": "  ", "count": 1},          # 이름 없음 → 버린다
        {"label": "간식", "count": 0},         # 0개 → 최소 1
        {"label": "쿠폰", "count": "셋"},      # 숫자가 아님 → 1
        "이건 문자열",                          # 형식 자체가 틀림 → 버린다
    ])
    assert [(p["label"], p["count"]) for p in saved] == [("간식", 1), ("쿠폰", 1)]
