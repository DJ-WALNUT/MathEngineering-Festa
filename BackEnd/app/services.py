"""도메인 서비스: 구글폼 응답 반영, 입금 등록(중복 제거 포함)."""

from __future__ import annotations

import json
import re
from datetime import datetime

from flask import current_app
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .matching import fingerprint_for, match_deposit
from .models import INTAKE_STAFF, SRC_PUSH, Deposit, Participant
from .utils import (
    normalize_name,
    normalize_phone,
    now_kst,
    parse_datetime,
    phone_last4,
    split_depositor,
)

# 구글폼 컬럼명은 언제든 바뀔 수 있으므로 별칭으로 흡수한다.
_FORM_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "이름", "성명", "참가자이름", "신청자이름"),
    "phone": ("phone", "전화번호", "연락처", "휴대폰번호", "휴대전화", "핸드폰번호", "전화", "mobile"),
    "emergency_phone": ("emergencyphone", "비상연락처", "비상연락망", "보호자연락처"),
    "student_id": ("studentid", "학번", "학생번호", "studentnumber"),
    "department": ("department", "소속", "학과", "학부", "전공", "소속학과", "major"),
    "gender": ("gender", "성별"),
    "council": (
        "iscouncilmember", "councilfee",
        "총학생회비납부여부", "총학생회비", "학생회비납부여부", "학생회비",
        "회비납부여부", "총학생회비납부",
    ),
    # 본인이 폼에서 '입금했다'고 답한 값. 은행 내역과 다를 수 있으므로 참고용이다.
    "declared_paid": ("declaredpaid", "입금완료", "입금완료되셨을까요", "입금여부", "참가비입금"),
    "has_health_issue": ("hashealthissue", "지병유무", "지병"),
    "health_note": ("healthnote", "병명", "병명과증상"),
    "health_action": ("healthaction", "조치사항", "응급조치"),
    "allergy": ("allergy", "알레르기", "식품알레르기", "식재료알레르기"),
    "portrait_consent": ("portraitconsent", "초상이용동의", "초상권동의", "초상"),
    "intake_round": ("intakeround", "접수회차", "회차"),
    # 뒤풀이 참가 여부. 이 값이 켜지면 참가비에 뒤풀이비가 얹히고,
    # 뒤풀이 회차의 출석 대상이 된다.
    "joins_afterparty": (
        "joinsafterparty", "afterparty",
        "뒤풀이", "뒤풀이참가", "뒤풀이참가여부", "뒤풀이참석", "뒤풀이참석여부",
        "뒷풀이", "뒷풀이참가", "뒷풀이참여",
        # 이번 행사의 이름. 포스터가 '2부 솔로파티'라 부르므로 폼 문항도 이 말을 쓸 가능성이 크다.
        "솔로파티", "솔로파티참가", "솔로파티참가여부", "솔로파티참석", "2부참가", "2부솔로파티",
    ),
    "depositor": ("depositor", "입금자명", "입금자", "송금자명"),
    # 이번 폼에서 새로 받는 것들
    "leader_preference": ("leaderpreference", "조장지원여부", "조장지원", "조장희망", "조장"),
    "nickname": ("nickname", "닉네임", "별명", "활동명"),
    "birth_year": ("birthyear", "태어난년도", "태어난해", "출생년도", "출생연도", "생년"),
    "afterparty_fee_acknowledged": (
        "afterpartyfeeacknowledged", "솔로파티사전참여비", "사전참여비", "뒤풀이비안내확인",
    ),
    "submitted_at": ("submittedat", "타임스탬프", "timestamp", "응답일시", "제출시각", "제출일시"),
    "cancelled": ("cancelled", "취소여부", "참가취소"),
}

# 참/거짓 판정.
#
# 한 글자짜리 토큰('n', 'x', '0', '1')을 부분 문자열로 검사하면
# "네 (2026.08.01 입금)" 같은 답변이 '0' 때문에 거짓이 되어버린다.
# 그래서 한 글자 토큰은 완전 일치일 때만 쓰고, 부분 검사는 여러 글자 토큰으로만 한다.
_TRUE_EXACT = {"예", "네", "y", "yes", "true", "1", "o", "완료", "있음", "해당", "동의"}
_FALSE_EXACT = {"아니오", "아니요", "n", "no", "false", "0", "x", "없음", "미동의", "비동의"}

# 부분 검사는 거짓을 먼저 본다. '미납'이 '납부'를 포함하기 때문이다.
#
# '납부하지 않았습니다' 는 '납부' 를 품고 있다. 부정형 어미('않았' · '않겠' · '하지않')를
# 거짓 토큰으로 먼저 걸러야 '납부' 로 참이 되는 사고를 막는다.
_FALSE_CONTAINS = (
    "미납", "아니오", "아니요", "해당없음", "비해당", "없음", "미동의", "비동의",
    "않았", "않겠", "하지않", "안했", "안함", "불참", "아직",
)
# '입금' · '확인' · '참여' 같은 명사는 참 토큰으로 쓰지 않는다 — '아직 입금 전입니다' 가
# 참이 된다. 답변의 **어미**('하였습니다' · '하겠습니다')를 본다.
_TRUE_CONTAINS = (
    "입금완료", "납부완료", "완료", "납부", "있음", "해당", "동의",
    "하였", "했습니다", "하겠",
)

# 절대 저장하지 않는 항목.
#
# 주민등록번호는 개인정보보호법 제24조의2 에 따라 법령에 구체적 근거가 없으면
# 수집·보관 자체가 금지된다. 학생회 행사는 그 근거에 해당하지 않는다.
# 폼에서 받더라도 이 시스템에는 들이지 않는다 — 매칭에 쓸 일이 전혀 없고,
# DB가 유출되어도 주민번호는 없는 상태를 유지하기 위함이다.
#
# 납부 증빙 스크린샷(구글 드라이브 링크)도 마찬가지로 보관하지 않는다.
# 필요하면 원본 스프레드시트에서 직접 확인하면 된다.
_SENSITIVE_KEY_PATTERNS = (
    "주민등록",
    "주민번호",
    "residentregistration",
    "rrn",
    "여권",
    "passport",
    "계좌번호",
    "카드번호",
    "스크린샷",
    "screenshot",
    "증빙",
)
_SENSITIVE_VALUE_PATTERNS = ("drive.google.com", "docs.google.com/uc")
# 13자리 연속 숫자 = 주민번호일 가능성. 값 자체로도 한 번 더 거른다.
_RRN_LIKE = re.compile(r"\b\d{6}\s*[-–]?\s*[1-4]\d{6}\b")


def is_sensitive(key: str, value: object) -> bool:
    """저장해서는 안 되는 항목인지 판단한다 (키 이름과 값 양쪽으로)."""
    normalized = _norm_key(key)
    if any(pattern in normalized for pattern in _SENSITIVE_KEY_PATTERNS):
        return True

    text = str(value or "")
    if any(pattern in text for pattern in _SENSITIVE_VALUE_PATTERNS):
        return True
    return bool(_RRN_LIKE.search(text.replace(" ", "")))


def _norm_key(value) -> str:
    return re.sub(r"[\s_\-()\[\]/:?.]", "", str(value or "")).lower()


def _pick(values: dict, field: str) -> object | None:
    """별칭 표를 이용해 폼 응답에서 필드 값을 꺼낸다.

    정확히 일치하는 키를 먼저 찾고, 없으면 부분 포함으로 한 번 더 시도한다.
    ('총학생회비를 납부하셨나요?' 같은 서술형 질문 헤더를 잡기 위함)
    """
    aliases = _FORM_ALIASES[field]
    normalized = {_norm_key(key): value for key, value in values.items()}

    for alias in aliases:
        if alias in normalized and normalized[alias] not in (None, ""):
            return normalized[alias]
    for alias in aliases:
        for key, value in normalized.items():
            if alias in key and value not in (None, ""):
                return value
    return None


def parse_boolean(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = _norm_key(value)
    if not text:
        return default

    if text in _FALSE_EXACT:
        return False
    if text in _TRUE_EXACT:
        return True

    for token in _FALSE_CONTAINS:
        if token in text:
            return False
    for token in _TRUE_CONTAINS:
        if token in text:
            return True
    return default


def parse_leader_preference(value) -> str | None:
    """'조장을 하고 싶다 / 해도 상관없다 / 하고싶지 않다' 를 LEADER_* 로.

    부정형('싶지 않다')이 '싶다'를 품고 있으므로 부정을 먼저 본다.
    """
    from .models import LEADER_NO, LEADER_OK, LEADER_WANT

    text = _norm_key(value)
    if not text:
        return None
    if text in {LEADER_WANT, LEADER_OK, LEADER_NO}:
        return text
    if "않" in text or "싫" in text or "안하" in text:
        return LEADER_NO
    if "상관" in text or "괜찮" in text or "가능" in text:
        return LEADER_OK
    if "싶" in text or "희망" in text or "지원" in text or "원함" in text:
        return LEADER_WANT
    return None


def parse_birth_year(value) -> int | None:
    """'2004년' · '2006.0' · '2007년도' · 2003 → 2004 · 2006 · 2007 · 2003."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        year = int(value)
    else:
        found = re.search(r"(19|20)\d{2}", str(value))
        if not found:
            return None
        year = int(found.group(0))
    return year if 1900 <= year <= 2100 else None


def base_fee_for(is_council_member: bool, is_staff: bool = False) -> int:
    """본 행사 참가비. 총학생회비 납부 여부로 갈리고, 스태프는 따로 정한다."""
    if is_staff:
        # 스태프 금액은 늦게 정해지고 바뀔 수 있어 설정이 아니라 DB 에서 읽는다.
        from .models import staff_fee

        return staff_fee()
    if is_council_member:
        return current_app.config["FEE_COUNCIL_MEMBER"]
    return current_app.config["FEE_NON_MEMBER"]


def expected_amount_for(
    is_council_member: bool,
    is_staff: bool = False,
    joins_afterparty: bool = False,
) -> int:
    """총 청구액 = 본 행사비 + (뒤풀이에 가면) 뒤풀이비.

    뒤풀이비는 총학생회비 납부 여부와 무관하게 같은 금액이다. 두 겹을 어떻게
    갈라 세는지는 models.Participant 의 '참가비는 두 겹이다' 주석을 보라.
    """
    from .models import current_afterparty_fee

    total = base_fee_for(is_council_member, is_staff)
    if joins_afterparty:
        total += current_afterparty_fee()
    return total


def recalc_expected_amounts(participants: list[Participant]) -> int:
    """예상 금액을 다시 계산한다. 반환은 실제로 바뀐 사람 수.

    스태프 참가비나 뒤풀이비를 관리자 화면에서 고치면, 이미 명단에 들어와 있는
    사람들의 금액도 함께 따라가야 한다. 커밋은 호출자가 한다.
    """
    changed = 0
    for person in participants:
        amount = expected_amount_for(
            person.is_council_member, person.is_staff, person.joins_afterparty
        )
        if person.expected_amount != amount:
            person.expected_amount = amount
            changed += 1
    return changed


def upsert_participant(values: dict, row_key: str | None = None) -> tuple[Participant | None, str]:
    """폼 응답 1건을 반영한다. 반환: (참가자, 'created' | 'updated' | 'skipped:사유')

    전화번호를 자연키로 삼는다. 같은 사람이 폼을 두 번 내면 최신 응답으로 갱신한다.
    """
    name = str(_pick(values, "name") or "").strip()
    phone = normalize_phone(_pick(values, "phone"))

    if not name:
        return None, "skipped:이름 없음"
    if len(phone) < 10:
        return None, "skipped:전화번호 형식 오류"

    is_member = parse_boolean(_pick(values, "council"), default=False)
    submitted_at = parse_datetime(_pick(values, "submitted_at")) or now_kst()

    known_keys = {
        _norm_key(alias)
        for aliases in _FORM_ALIASES.values()
        for alias in aliases
    }
    # 매핑되지 않은 응답만 extra 에 남기되, 민감 항목은 무조건 버린다.
    # (Apps Script 가 이미 걸러서 보내지만, 여기서 한 번 더 막는다)
    extra = {
        key: value
        for key, value in values.items()
        if value not in (None, "")
        and not any(alias in _norm_key(key) for alias in known_keys)
        and not is_sensitive(key, value)
    }

    participant = db.session.query(Participant).filter(Participant.phone == phone).one_or_none()
    created = participant is None
    if created:
        participant = Participant(phone=phone)
        db.session.add(participant)
    else:
        participant.submission_count = (participant.submission_count or 1) + 1

    participant.name = name
    participant.name_norm = normalize_name(name)
    participant.phone_last4 = phone_last4(phone)
    participant.student_id = _str_or_none(_pick(values, "student_id"))
    participant.department = normalize_department(_pick(values, "department"))
    participant.gender = _str_or_none(_pick(values, "gender"))
    participant.emergency_phone = _str_or_none(_pick(values, "emergency_phone"))
    participant.is_council_member = is_member
    participant.declared_depositor = _str_or_none(_pick(values, "depositor"))
    participant.declared_paid = parse_boolean(_pick(values, "declared_paid"), default=False)
    participant.submitted_at = submitted_at

    # 현장 안전 정보
    participant.has_health_issue = parse_boolean(_pick(values, "has_health_issue"), default=False)
    participant.health_note = _str_or_none(_pick(values, "health_note"))
    participant.health_action = _str_or_none(_pick(values, "health_action"))
    participant.allergy = _str_or_none(_pick(values, "allergy"))

    portrait = _pick(values, "portrait_consent")
    if portrait is not None:
        participant.portrait_consent = parse_boolean(portrait, default=True)

    intake = _str_or_none(_pick(values, "intake_round"))
    if intake:
        participant.intake_round = intake

    # 뒤풀이 참가 여부. 폼에 문항이 없으면(값이 아예 오지 않으면) 건드리지 않는다 —
    # 관리자가 화면에서 켜 둔 것을 재제출 한 번으로 날려 버려서는 안 된다.
    afterparty = _pick(values, "joins_afterparty")
    if afterparty is not None:
        participant.joins_afterparty = parse_boolean(afterparty, default=False)

    acknowledged = _pick(values, "afterparty_fee_acknowledged")
    if acknowledged is not None:
        participant.afterparty_fee_acknowledged = parse_boolean(acknowledged, default=False)

    # 조 편성 · 명찰 · 솔로파티에 쓰는 것들. 폼에 문항이 없으면 건드리지 않는다 —
    # 관리자가 화면에서 적어 둔 닉네임을 재제출 한 번이 지워서는 안 된다.
    leader = _pick(values, "leader_preference")
    if leader is not None:
        participant.leader_preference = parse_leader_preference(leader)
    nickname = _pick(values, "nickname")
    if nickname is not None:
        participant.nickname = _str_or_none(nickname)
    birth = _pick(values, "birth_year")
    if birth is not None:
        participant.birth_year = parse_birth_year(birth)

    # 스태프 전용 폼(시트)으로 들어온 사람은 받는 즉시 스태프가 된다. 스태프는
    # 참가비가 다르고 럭키드로우에서도 빠지므로, 명단에 앉힌 뒤 관리자가 한 명씩
    # 다시 눌러 주게 두면 그 사이의 집계가 전부 어긋난다.
    #
    # 켜기만 하고 끄지는 않는다 — 같은 사람이 나중에 본모집 폼을 한 번 더 내도
    # 스태프 지정이 풀려서는 안 되고, 해제는 관리자 화면에서만 한다.
    if intake == INTAKE_STAFF:
        participant.is_staff = True

    participant.form_row_key = row_key or participant.form_row_key
    participant.extra_json = json.dumps(extra, ensure_ascii=False, default=str) if extra else None

    cancelled = _pick(values, "cancelled")
    if cancelled is not None:
        participant.is_cancelled = parse_boolean(cancelled, default=False)

    # 관리자가 금액을 직접 조정한 경우(override)는 건드리지 않는다.
    # 스태프 금액은 아직 0 일 수 있는데(대시보드에서 늦게 정한다), 그때는 '면제'로
    # 보이다가 금액을 정하는 순간 스태프 전원에게 함께 반영된다.
    if participant.status_override is None or not participant.expected_amount:
        participant.expected_amount = expected_amount_for(
            is_member, participant.is_staff, participant.joins_afterparty
        )

    db.session.flush()
    return participant, "created" if created else "updated"


def _str_or_none(value) -> str | None:
    if value is None:
        return None
    # 스프레드시트가 학번을 숫자로 바꿔 '202620976.0' 으로 넘기는 일이 있다.
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return text or None


#: 구글폼 학과 선택지에 붙어 있는 안내 문구. 학과 이름이 아니라 **폼을 채우는 사람에게
#: 하는 말**이라 그대로 두면 명찰과 명단에 그 문장이 그대로 인쇄된다. 더 나쁜 것은
#: 같은 학과가 둘로 갈린다는 점이다 — '자연공학계열' 과 '자연공학계열 (26년도 …)' 이
#: 서로 다른 값이 되어 조 편성과 집계가 어긋난다.
_DEPARTMENT_NOTE = re.compile(r"\s*\((?:[^()]*(?:학년|기준)[^()]*)\)\s*$")


def normalize_department(value) -> str | None:
    """학과명에서 폼 안내 문구를 떼어 낸다."""
    text = _str_or_none(value)
    if text is None:
        return None
    return _str_or_none(_DEPARTMENT_NOTE.sub("", text))


def register_deposit(
    *,
    occurred_at: datetime,
    amount: int,
    balance_after: int | None,
    raw_name: str,
    name_norm: str | None = None,
    digit_suffix: str | None = None,
    source: str = SRC_PUSH,
    raw_payload: object | None = None,
    run_match: bool = True,
) -> tuple[Deposit, bool]:
    """입금 1건 등록. 반환: (입금, 신규여부)

    푸시 알림과 엑셀 업로드가 같은 건을 중복 등록하는 것을 지문으로 막는다.
    """
    if name_norm is None or digit_suffix is None:
        name_part, digits = split_depositor(raw_name)
        name_norm = normalize_name(name_part) if name_norm is None else name_norm
        digit_suffix = digits if digit_suffix is None else digit_suffix

    fingerprint = fingerprint_for(occurred_at, amount, balance_after, raw_name)
    existing = db.session.query(Deposit).filter(Deposit.fingerprint == fingerprint).one_or_none()
    if existing is not None:
        # 푸시로 먼저 들어온 건에 엑셀이 잔액/정확한 시각을 보태줄 수 있다
        if existing.balance_after is None and balance_after is not None:
            existing.balance_after = balance_after
        if not existing.raw_name and raw_name:
            existing.raw_name = raw_name
            existing.name_norm = name_norm or ""
            existing.digit_suffix = digit_suffix or ""
        return existing, False

    payload_text = None
    if raw_payload is not None:
        payload_text = (
            raw_payload
            if isinstance(raw_payload, str)
            else json.dumps(raw_payload, ensure_ascii=False, default=str)
        )

    deposit = Deposit(
        fingerprint=fingerprint,
        occurred_at=occurred_at,
        amount=amount,
        balance_after=balance_after,
        raw_name=raw_name or "",
        name_norm=name_norm or "",
        digit_suffix=digit_suffix or "",
        source=source,
        raw_payload=payload_text,
    )
    db.session.add(deposit)

    try:
        db.session.flush()
    except IntegrityError:
        # 동시 요청으로 같은 지문이 먼저 들어온 경우
        db.session.rollback()
        existing = db.session.query(Deposit).filter(Deposit.fingerprint == fingerprint).one_or_none()
        if existing is not None:
            return existing, False
        raise

    if run_match:
        match_deposit(deposit)
    return deposit, True
