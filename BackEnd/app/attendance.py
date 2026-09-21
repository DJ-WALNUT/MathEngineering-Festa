"""출석 — 회차 정의 · 체크인 기록 · 개인 카드 토큰.

## 왜 '회차'인가

하루짜리 행사인데도 출석이 한 번으로 끝나지 않는다. 낮의 **본 행사**가 있고,
신청자 중 일부만 남는 **뒤풀이**가 저녁에 따로 있다. 두 자리의 인원이 다르고
여닫는 시각도 다르다.

이것을 참가자 테이블의 불리언 두 개(`checked_in_at`, `after_checked_in_at`)로
두면 회차가 하나 늘 때마다 컬럼을 늘리고 재배포해야 한다. 그래서 배정 항목과
같은 방식을 쓴다 — **무엇을 세는가 자체를 데이터로 둔다**(`CheckinSession`).
현장에서 '2부도 따로 세자'가 나와도 화면에서 회차를 하나 더 만들면 끝이다.

## 두 갈래로 들어온다

  - **셀프**: 참가자가 입구 QR 을 찍고 이름 · 학번 · 전화 뒷자리를 넣는다.
    회차가 열려 있을 때만 받는다. 본 행사처럼 인원이 많은 자리에 쓴다.
  - **수동**: 관리자가 명단에서 이름을 찾아 누른다. 회차가 닫혀 있어도 된다.
    뒤풀이처럼 인원이 적고 자리가 어수선한 데서는 이쪽이 빠르다.

어느 쪽으로 들어왔는지는 `CheckIn.by` 에 남는다. 회차 × 참가자 한 쌍에 한 행뿐이라
두 번 찍혀도 행이 늘지 않는다.

## 본 행사만 특별한 이유

럭키드로우 번호(`Participant.draw_no`)와 참가자 사본 컬럼(`checked_in_at`)이
본 행사 회차 하나를 전제로 한다. 번호를 회차마다 새로 매기면 참가자가 번호를
두 개 외워야 하므로, 번호는 **본 행사 체크인 순서** 하나로만 준다
(`CheckinSession.gives_draw_no`). 뒤풀이 추첨은 그 번호를 그대로 쓰되 후보를
뒤풀이 체크인자로 좁힌다 — draw.py 를 보라.
"""

from __future__ import annotations

import secrets

from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import (
    CHECKIN_SELF,
    CHECKIN_STAFF,
    SESSION_AFTERPARTY,
    SESSION_MAIN,
    CheckIn,
    CheckinSession,
    Participant,
)
from .utils import now_kst

# 사람이 눈으로 옮겨 적을 수도 있어야 해서 헷갈리는 글자(0·O·1·I)를 뺀다.
_TOKEN_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_TOKEN_LENGTH = 8


class AttendanceError(ValueError):
    """사용자에게 그대로 보여줄 수 있는 출석 오류."""


# ---------------------------------------------------------------------------
# 회차 정의
# ---------------------------------------------------------------------------

DEFAULT_SESSIONS = [
    {
        "key": SESSION_MAIN,
        "label": "1부 교류전",
        "position": 10,
        "afterparty_only": False,
        "gives_draw_no": True,
        "is_system": True,
    },
    {
        "key": SESSION_AFTERPARTY,
        "label": "2부 솔로파티",
        "position": 20,
        # 뒤풀이는 신청한 사람만 대상이다. 현황의 분모도 신청자 수가 된다.
        "afterparty_only": True,
        "gives_draw_no": False,
        "is_system": False,
    },
]


def ensure_default_sessions() -> list[str]:
    """기본 회차를 채운다. 이미 있으면 건드리지 않는다.

    라벨과 스위치는 학생회가 화면에서 고친 것이므로 덮어쓰지 않는다.
    반환값은 새로 만든 회차의 key 목록.
    """
    existing = {row.key for row in db.session.query(CheckinSession).all()}
    created: list[str] = []
    for spec in DEFAULT_SESSIONS:
        if spec["key"] in existing:
            continue
        db.session.add(
            CheckinSession(
                key=spec["key"],
                label=spec["label"],
                position=spec["position"],
                # 기본은 닫힘. QR 은 행사 며칠 전부터 돌아다니므로 열어 두면
                # 집결 전에 원격으로 체크인해 버리는 사람이 생긴다.
                is_open=False,
                afterparty_only=spec["afterparty_only"],
                gives_draw_no=spec["gives_draw_no"],
                is_system=spec["is_system"],
                is_active=True,
            )
        )
        created.append(spec["key"])
    if created:
        db.session.commit()
    return created


def active_sessions() -> list[CheckinSession]:
    return (
        db.session.query(CheckinSession)
        .filter(CheckinSession.is_active.is_(True))
        .order_by(CheckinSession.position.asc(), CheckinSession.id.asc())
        .all()
    )


def all_sessions() -> list[CheckinSession]:
    return (
        db.session.query(CheckinSession)
        .order_by(CheckinSession.position.asc(), CheckinSession.id.asc())
        .all()
    )


def session_by_key(key: str) -> CheckinSession | None:
    return (
        db.session.query(CheckinSession)
        .filter(CheckinSession.key == str(key or "").strip())
        .one_or_none()
    )


def main_session() -> CheckinSession | None:
    """본 행사 회차. 사본 컬럼과 럭키드로우 번호의 기준이다."""
    return session_by_key(SESSION_MAIN)


def draw_session() -> CheckinSession | None:
    """럭키드로우 번호를 매기는 회차. 없으면 본 행사로 본다."""
    row = (
        db.session.query(CheckinSession)
        .filter(
            CheckinSession.is_active.is_(True),
            CheckinSession.gives_draw_no.is_(True),
        )
        .order_by(CheckinSession.position.asc())
        .first()
    )
    return row or main_session()


def open_session() -> CheckinSession | None:
    """지금 셀프 체크인을 받고 있는 회차.

    참가자는 회차를 고르지 않는다. 같은 입구 QR 로 들어와 **지금 열려 있는**
    회차에 체크인한다. 둘을 동시에 열 일은 없지만, 열렸다면 앞선 것을 쓴다.
    """
    return (
        db.session.query(CheckinSession)
        .filter(CheckinSession.is_active.is_(True), CheckinSession.is_open.is_(True))
        .order_by(CheckinSession.position.asc())
        .first()
    )


# ---------------------------------------------------------------------------
# 체크인 기록
# ---------------------------------------------------------------------------

def eligible_for(session: CheckinSession, participant: Participant) -> bool:
    """이 회차의 대상인가. 확정 여부는 호출하는 쪽이 따로 본다."""
    if session.afterparty_only and not participant.joins_afterparty:
        return False
    return True


def find_checkin(session: CheckinSession, participant: Participant) -> CheckIn | None:
    return (
        db.session.query(CheckIn)
        .filter(
            CheckIn.session_id == session.id,
            CheckIn.participant_id == participant.id,
        )
        .one_or_none()
    )


def record_checkin(
    session: CheckinSession,
    participant: Participant,
    *,
    by: str = CHECKIN_SELF,
    actor: str | None = None,
) -> tuple[CheckIn, bool]:
    """출석을 남긴다. 반환은 (행, 새로 만들었는가).

    이미 있으면 시각을 덮어쓰지 않는다 — 처음 들어온 순간이 곧 럭키드로우
    번호의 근거이고, 두 번 찍었다고 순서가 뒤로 밀려서는 안 된다.

    **커밋하지 않는다.** 럭키드로우 번호 발급이 실패하면 되돌려야 하는데,
    그 rollback 이 체크인까지 지우지 않도록 호출하는 쪽이 순서를 정한다
    (public.checkin 의 주석 참고).
    """
    existing = find_checkin(session, participant)
    if existing is not None:
        return existing, False

    row = CheckIn(
        session_id=session.id,
        participant_id=participant.id,
        at=now_kst(),
        by=by if by in {CHECKIN_SELF, CHECKIN_STAFF} else CHECKIN_SELF,
        actor=actor,
    )
    db.session.add(row)
    _sync_mirror(session, participant)
    return row, True


def cancel_checkin(session: CheckinSession, participant: Participant) -> bool:
    """출석을 지운다. 반환은 실제로 지웠는가.

    **럭키드로우 번호는 회수하지 않는다.** 번호를 다시 쓰면 자기 번호를 외운 채
    추첨 화면을 보고 있는 사람과 어긋난다. 대신 추첨 후보에서는 빠진다.
    """
    existing = find_checkin(session, participant)
    if existing is None:
        return False
    db.session.delete(existing)
    db.session.flush()
    _sync_mirror(session, participant)
    return True


def _sync_mirror(session: CheckinSession, participant: Participant) -> None:
    """본 행사 회차의 출석을 참가자 사본 컬럼에 반영한다.

    명찰 · CSV · 대시보드가 회차를 따지지 않고 '왔는가'만 묻기 때문에 남겨 둔
    컬럼이다. 쓰기는 이 함수 한 곳뿐이라 두 곳이 어긋날 여지가 없다.
    """
    if session.key != SESSION_MAIN:
        return
    row = find_checkin(session, participant)
    participant.checked_in_at = row.at if row else None
    participant.checked_in_by = row.by if row else None


def checked_in_ids(session: CheckinSession) -> set[int]:
    rows = (
        db.session.query(CheckIn.participant_id)
        .filter(CheckIn.session_id == session.id)
        .all()
    )
    return {row[0] for row in rows}


# ---------------------------------------------------------------------------
# 개인 카드 토큰
# ---------------------------------------------------------------------------

def _new_token() -> str:
    return "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(_TOKEN_LENGTH))


def ensure_token(participant: Participant) -> str:
    """이 사람의 개인 토큰. 없으면 만들어 준다.

    한 번 준 토큰은 바꾸지 않는다. 명찰에 인쇄되어 목에 걸려 있기 때문이다.
    """
    if participant.card_token:
        return participant.card_token

    for _ in range(5):
        candidate = _new_token()
        participant.card_token = candidate
        try:
            db.session.flush()
        except IntegrityError:
            # 천만 분의 일로 겹쳤다. 다시 뽑는다.
            db.session.rollback()
            continue
        return candidate

    raise RuntimeError("개인 토큰을 만들지 못했습니다.")


def issue_tokens(participants: list[Participant]) -> int:
    """토큰이 없는 사람에게 한 번에 발급한다. 반환값은 새로 만든 수."""
    issued = 0
    for participant in participants:
        if not participant.card_token:
            ensure_token(participant)
            issued += 1
    if issued:
        db.session.commit()
    return issued


def find_by_token(raw: str) -> Participant | None:
    """QR 에서 읽은 값으로 사람을 찾는다.

    넘어오는 값은 토큰일 수도 있고 명찰에 인쇄된 주소(`.../p/AB12CD34`) 전체일
    수도 있다. 어느 쪽이든 받는다 — 참가자가 자기 폰 카메라로 명찰을 찍으면
    주소가 열리기 때문이다.
    """
    text = str(raw or "").strip()
    if not text:
        return None
    token = text.rstrip("/").rsplit("/", 1)[-1].strip().upper()
    if not token:
        return None
    return (
        db.session.query(Participant)
        .filter(Participant.card_token == token)
        .one_or_none()
    )
