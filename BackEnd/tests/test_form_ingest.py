"""실제 신청 폼 수집 테스트.

Apps Script 가 보내는 형태(정규화된 필드명)와, 만약 원본 헤더가 그대로 날아왔을
때의 방어를 함께 검증한다. 특히 주민등록번호는 어떤 경로로도 저장되면 안 된다.
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
from app.models import Participant  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services import is_sensitive, parse_boolean  # noqa: E402

PASSWORD = "mt-admin-1234"
# 최고 관리자 로그인 ID. 비밀번호는 모두 같고 ID 로 사람을 구분한다.
SUPER_ID = "wont0309"
INGEST_HEADERS = {"X-Ingest-Token": "test-token"}

# Apps Script 의 previewMapping 이 실제 폼에서 만들어낸 payload
EARLYBIRD_MEMBER = {
    "intakeRound": "earlybird",
    "submittedAt": "2026-08-01T10:00:00",
    "name": "홍길동",
    "studentId": "202612345",
    "gender": "남",
    "phone": "010-1234-5678",
    "emergencyPhone": "010-9999-8888 (부)",
    "department": "기계공학과",
    "hasHealthIssue": "예",
    "healthNote": "천식",
    "healthAction": "흡입기 사용 후 호전 없으면 119 신고",
    "allergy": "땅콩, 새우",
    "isCouncilMember": "납부",
    "portraitConsent": "동의합니다",
    "declaredPaid": "입금 완료했습니다",
}

# 스태프 전용 시트. 질문 구성은 참가자 폼과 거의 같고 총학생회비 항목만 없다.
# 스태프인지는 컬럼이 아니라 회차(intakeRound) 하나로 정해진다.
STAFF_SHEET = {
    "intakeRound": "staff",
    "submittedAt": "2026-08-14T21:00:00",
    "name": "김공대",
    "studentId": "202611111",
    "gender": "남",
    "phone": "010-7777-0711",
    "emergencyPhone": "010-5555-6666 (부)",
    "department": "컴퓨터정보공학부",
    "hasHealthIssue": "아니오",
    "allergy": "없음",
    "portraitConsent": "동의합니다",
    "declaredPaid": "입금 완료했습니다",
}

MAIN_NON_MEMBER = {
    "intakeRound": "main",
    "submittedAt": "2026-08-10T09:30:00",
    "name": "이순신",
    "studentId": "202654321",
    "gender": "여",
    "phone": "010-1111-2222",
    "emergencyPhone": "010-3333-4444 (모)",
    "department": "전자공학과",
    "hasHealthIssue": "아니오",
    "allergy": "없음",
    "isCouncilMember": "미납",
    "portraitConsent": "동의합니다",
    "declaredPaid": "아직 입금 전입니다",
}


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


def submit(client, values: dict, row: int = 2):
    return client.post(
        "/api/ingest/form",
        headers=INGEST_HEADERS,
        json={"row": row, "sheet": values.get("intakeRound", "main"), "values": values},
    )


# --- 값 해석 ------------------------------------------------------------

@pytest.mark.parametrize(
    "value,expected",
    [
        ("납부", True),
        ("미납", False),                       # '납부'를 포함하지만 거짓이어야 한다
        ("예", True),
        ("아니오", False),
        ("동의합니다", True),
        ("미동의", False),
        ("입금 완료했습니다", True),
        ("아직 입금 전입니다", False),          # 기본값(False)으로 떨어진다
        ("네 (2026.08.01 입금)", False),        # 한 글자 토큰 오작동 방지 (기본값)
    ],
)
def test_parse_boolean(value, expected):
    assert parse_boolean(value, default=False) is expected


def test_single_char_tokens_do_not_misfire():
    """'0' 이 들어간 답변이 거짓으로 뒤집히면 안 된다."""
    assert parse_boolean("완료 2026.08.01", default=False) is True
    assert parse_boolean("0", default=True) is False   # 완전 일치일 때만 거짓


# --- 민감 정보 차단 ------------------------------------------------------

def test_is_sensitive_detects_rrn_and_files():
    assert is_sensitive("주민등록번호 (13자리)", "990101-1234567") is True
    assert is_sensitive("아무컬럼", "990101-1234567") is True          # 값으로도 잡는다
    assert is_sensitive("스크린샷 업로드", "https://drive.google.com/x") is True
    assert is_sensitive("증빙자료", "") is True
    assert is_sensitive("이름", "홍길동") is False
    assert is_sensitive("학번", "202612345") is False                  # 9자리는 주민번호 아님


def test_rrn_is_never_stored_even_if_posted(client):
    """Apps Script 가 걸러도, 서버가 한 번 더 막아야 한다."""
    values = dict(EARLYBIRD_MEMBER)
    values["주민등록번호 (13자리)"] = "990101-1234567"
    values["납부 스크린샷"] = "https://drive.google.com/open?id=ABC"
    values["메모"] = "특이사항 없음"

    assert submit(client, values).status_code == 200

    with client.application.app_context():
        participant = db.session.query(Participant).one()
        stored = participant.extra_json or ""
        assert "990101" not in stored
        assert "drive.google.com" not in stored
        # 민감하지 않은 미매핑 항목은 그대로 남는다
        assert participant.extra.get("메모") == "특이사항 없음"


# --- 필드 반영 ------------------------------------------------------------

def test_all_form_fields_are_stored(client):
    assert submit(client, EARLYBIRD_MEMBER).status_code == 200

    with client.application.app_context():
        p = db.session.query(Participant).one()
        assert p.name == "홍길동"
        assert p.phone == "01012345678"
        assert p.student_id == "202612345"
        assert p.gender == "남"
        assert p.emergency_phone == "010-9999-8888 (부)"
        assert p.department == "기계공학과"
        assert p.intake_round == "earlybird"
        assert p.is_council_member is True
        assert p.expected_amount == 5_000
        assert p.has_health_issue is True
        assert p.health_note == "천식"
        assert "119" in p.health_action
        assert p.allergy == "땅콩, 새우"
        assert p.portrait_consent is True
        assert p.declared_paid is True


def test_non_member_gets_higher_fee(client):
    assert submit(client, MAIN_NON_MEMBER).status_code == 200

    with client.application.app_context():
        p = db.session.query(Participant).one()
        assert p.is_council_member is False
        assert p.expected_amount == 7_000
        assert p.intake_round == "main"
        assert p.has_health_issue is False
        assert p.declared_paid is False


# --- 두 스프레드시트 ------------------------------------------------------

def test_two_spreadsheets_merge_without_collision(client):
    """얼리버드·본모집 시트가 각각 2행을 보내도 서로 덮어쓰지 않아야 한다."""
    submit(client, EARLYBIRD_MEMBER, row=2)
    submit(client, MAIN_NON_MEMBER, row=2)

    with client.application.app_context():
        assert db.session.query(Participant).count() == 2
        keys = {p.form_row_key for p in db.session.query(Participant).all()}
        assert keys == {"earlybird:2", "main:2"}


def test_same_person_in_both_rounds_is_merged(client):
    """두 시트에 모두 신청한 경우 최신 응답으로 합쳐지고 중복 신청이 드러나야 한다."""
    submit(client, EARLYBIRD_MEMBER, row=2)

    late = dict(EARLYBIRD_MEMBER)
    late["intakeRound"] = "main"
    late["isCouncilMember"] = "미납"      # 나중에 정정한 응답
    submit(client, late, row=7)

    with client.application.app_context():
        participants = db.session.query(Participant).all()
        assert len(participants) == 1
        p = participants[0]
        assert p.submission_count == 2          # 중복 신청 표시
        assert p.intake_round == "main"         # 최신 회차로 갱신
        assert p.expected_amount == 7_000      # 정정된 값 반영


# --- 스태프 시트 ----------------------------------------------------------

def test_staff_sheet_marks_participant_as_staff(client):
    """스태프 시트로 들어온 사람은 받는 즉시 스태프여야 한다."""
    assert submit(client, STAFF_SHEET).status_code == 200

    with client.application.app_context():
        p = db.session.query(Participant).one()
        assert p.is_staff is True
        assert p.fee_class == "staff"
        assert p.intake_round == "staff"
        # 스태프 금액은 대시보드에서 늦게 정한다. 그전까지는 낼 것이 없는 상태.
        assert p.expected_amount == 0
        assert p.payment_status == "WAIVED"


def test_staff_fee_reaches_people_who_came_in_before_it_was_set(client):
    """금액을 나중에 정해도 이미 들어와 있던 스태프에게 함께 반영되어야 한다."""
    submit(client, STAFF_SHEET)

    token = client.post(
        "/api/admin/login", json={"username": SUPER_ID, "password": PASSWORD}
    ).get_json()["token"]
    response = client.post(
        "/api/admin/staff-fee",
        headers={"Authorization": f"Bearer {token}"},
        json={"amount": 39_000},
    )
    assert response.status_code == 200
    assert response.get_json()["applied"] == 1

    with client.application.app_context():
        assert db.session.query(Participant).one().expected_amount == 39_000


def test_staff_flag_survives_a_later_participant_submission(client):
    """스태프가 본모집 폼을 한 번 더 내도 스태프 지정이 풀려서는 안 된다."""
    submit(client, STAFF_SHEET, row=2)

    again = dict(STAFF_SHEET)
    again["intakeRound"] = "main"
    again["isCouncilMember"] = "납부"
    submit(client, again, row=9)

    with client.application.app_context():
        p = db.session.query(Participant).one()
        assert p.is_staff is True
        assert p.fee_class == "staff"          # 회비 구분보다 스태프가 우선한다
        assert p.intake_round == "main"        # 회차 자체는 최신 응답을 따른다


def test_declared_paid_conflicts_are_visible(client):
    """'입금했다'고 답했는데 은행 내역이 없는 사람을 찾을 수 있어야 한다."""
    submit(client, EARLYBIRD_MEMBER, row=2)      # declaredPaid = True
    submit(client, MAIN_NON_MEMBER, row=3)       # declaredPaid = False

    headers = {
        "Authorization": f"Bearer {client.post('/api/admin/login', json={'username': SUPER_ID, 'password': PASSWORD}).get_json()['token']}"
    }
    items = client.get("/api/admin/participants", headers=headers).get_json()["items"]
    conflicted = [i for i in items if i["declaredPaid"] and i["status"] == "UNPAID"]

    assert len(conflicted) == 1
    assert conflicted[0]["name"] == "홍길동"


def test_department_drops_the_form_guidance_note(client):
    """학과 선택지에 붙은 안내 문구는 학과 이름이 아니다.

    떼어 두지 않으면 명찰에 그 문장이 그대로 인쇄되고, 더 나쁘게는 같은 학과가
    '자연공학계열' 과 '자연공학계열 (26년도 …)' 둘로 갈려 조 편성이 어긋난다.
    """
    noted = dict(EARLYBIRD_MEMBER)
    noted["department"] = "자연공학계열 (26년도 기준, 1학년만 선택 가능)"
    submit(client, noted, row=2)

    plain = dict(MAIN_NON_MEMBER)
    plain["department"] = "자연공학계열"
    submit(client, plain, row=3)

    with client.application.app_context():
        departments = {p.department for p in db.session.query(Participant).all()}
        assert departments == {"자연공학계열"}    # 둘로 갈리지 않는다


# ---------------------------------------------------------------------------
# 이번 폼 — '[이과대 X 공과대] 이공공이(2002) 참여자 모집'
#
# apps_script/ 에 있는 응답 시트의 헤더와 답변 문구를 그대로 쓴다. Apps Script 가
# 열 이름을 필드명(joinsAfterparty …)으로 바꿔 보내지만, 백엔드는 한글 헤더로 와도
# 같은 결과가 나야 한다 (별칭 표). 부정형 답변('납부하지 않았습니다')이 '납부'로
# 참이 되지 않는 것이 이 묶음의 핵심이다.
# ---------------------------------------------------------------------------

def _festa_row(**overrides):
    row = {
        "타임스탬프": "2026-09-22T00:00:48",
        "[개인정보 수집·이용 및 초상권 활용 동의서]\n'2026학년도 가톨릭대학교 이과대학 X 공과대학 연합행사 [이공공이]'의 원활한 운영 … 동의를 받고 있습니다.": "동의합니다",
        "이름": "서유상",
        "학과": "화학과",
        "학번 \n\n(예시: 202600000)": 202620976.0,
        "전화번호\n\n(예시: 010-1234-5678)": "010-6470-3448",
        "총학생회비 납부여부": "납부하지 않았습니다",
        "참가비 입금\n\n- 총학생회비 납부자: 5,000원\n- 총학생회비 미납부자: 7,000원\n*솔로파티 비용은 추후 참여 확정 연락으로 안내드릴 예정입니다!": "입금하였습니다",
        "1부 교류전 - 조장 지원 여부 ": "조장을 해도 상관없다",
        "솔로파티 참가 여부": "참여하겠습니다",
        "솔로파티 사전 참여비": "확인하였습니다",
        "성별": "남자",
        "태어난 년도": "2004년",
        "닉네임": "은유",
    }
    row.update(overrides)
    return row


def test_festa_form_row_maps_every_column(client):
    from app.models import LEADER_OK, Participant

    response = client.post(
        "/api/ingest/form", headers=INGEST_HEADERS, json={"row": 2, "values": _festa_row()}
    )
    assert response.status_code == 200, response.get_json()

    with client.application.app_context():
        p = db.session.query(Participant).one()
        assert p.name == "서유상"
        assert p.department == "화학과"
        assert p.student_id == "202620976"          # 숫자로 온 학번이 '.0' 없이 들어온다
        assert p.phone == "01064703448"
        assert p.is_council_member is False          # '납부하지 않았습니다' 는 거짓
        assert p.declared_paid is True               # '입금하였습니다' 는 참
        assert p.joins_afterparty is True            # '참여하겠습니다'
        assert p.afterparty_fee_acknowledged is True # '확인하였습니다'
        assert p.leader_preference == LEADER_OK
        assert p.gender == "남자"
        assert p.birth_year == 2004
        assert p.nickname == "은유"
        assert p.portrait_consent is True
        assert p.expected_amount == 7_000 + 10_000


def test_festa_form_negative_answers(client):
    from app.models import LEADER_NO, LEADER_WANT, Participant

    client.post(
        "/api/ingest/form",
        headers=INGEST_HEADERS,
        json={"row": 3, "values": _festa_row(**{
            "이름": "강유민",
            "전화번호\n\n(예시: 010-1234-5678)": "010-9097-3612",
            "총학생회비 납부여부": "납부하였습니다",
            "참가비 입금\n\n- 총학생회비 납부자: 5,000원\n- 총학생회비 미납부자: 7,000원\n*솔로파티 비용은 추후 참여 확정 연락으로 안내드릴 예정입니다!": "입금하지 않았습니다",
            "1부 교류전 - 조장 지원 여부 ": "조장을 하고싶지 않다",
            "솔로파티 참가 여부": "참여하지 않겠습니다",
            "솔로파티 사전 참여비": "확인하지 않았습니다",
            "태어난 년도": 2006.0,
        })},
    )
    with client.application.app_context():
        p = db.session.query(Participant).one()
        assert p.is_council_member is True
        assert p.declared_paid is False
        assert p.joins_afterparty is False
        assert p.afterparty_fee_acknowledged is False
        assert p.leader_preference == LEADER_NO
        assert p.birth_year == 2006
        assert p.expected_amount == 5_000

    # '조장을 하고 싶다' 는 부정형이 아니다
    from app.services import parse_leader_preference
    assert parse_leader_preference("조장을 하고 싶다") == LEADER_WANT


def test_festa_form_resubmission_without_new_columns_keeps_nickname(client):
    """문항이 없는 폼(스태프 시트 등)으로 다시 내도 닉네임·조장 지원이 지워지지 않는다."""
    from app.models import LEADER_OK, Participant

    client.post("/api/ingest/form", headers=INGEST_HEADERS, json={"row": 2, "values": _festa_row()})
    client.post(
        "/api/ingest/form",
        headers=INGEST_HEADERS,
        json={"row": 9, "values": {
            "이름": "서유상", "전화번호": "010-6470-3448", "학과": "화학과",
        }},
    )
    with client.application.app_context():
        p = db.session.query(Participant).one()
        assert p.nickname == "은유"
        assert p.leader_preference == LEADER_OK
        assert p.joins_afterparty is True
