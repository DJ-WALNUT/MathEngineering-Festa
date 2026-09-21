"""럭키드로우 — 번호 발급과 추첨.

번호는 **체크인한 순서대로** 001, 002, 003 … 으로 준다. 미리 뿌려 두는 것이 아니라
도착한 순서가 곧 번호이므로, 참가자는 체크인 화면에서 자기 번호를 바로 확인하고
추첨 시각에 그 번호만 들고 오면 된다.

추첨은 **실제로 발급된 번호 중에서 하나를 고른다.** 무작위 세 자리를 만들어
그 번호가 있는지 확인하는 방식이 아니다. 거꾸로 하면 250명이 체크인한 자리에서
287번이 나오는 일이 생긴다. 화면의 슬롯머신은 이미 정해진 번호를 자릿수별로
드러내는 연출이고, 결과는 뽑는 순간 DB 에 박힌다.

## 번호는 하나, 후보는 자리마다

이 행사는 낮의 본 행사와 저녁의 뒤풀이로 나뉘고, 두 자리 모두에서 추첨을 한다.
그렇다고 회차마다 번호를 새로 매기면 **참가자가 번호를 두 개 외워야 한다.**

그래서 번호는 본 행사 체크인 순서 하나로만 주고(`assign_draw_no`), 뒤풀이
추첨에서는 같은 번호를 쓰되 **후보를 그 자리에 있는 사람으로 좁힌다**
(`pool_session`). 그 자리에 없는 번호는 추첨 화면 아래 번호판에서 처음부터
꺼져 있으므로, 참가자는 자기가 후보인지 한눈에 안다.
"""

from __future__ import annotations

import json
import secrets

from flask import current_app
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, OperationalError

from .extensions import db
from .models import (
    SETTING_DRAW_PRIZES,
    LuckyDraw,
    Participant,
    get_setting,
    set_setting,
)

# 번호가 부딪혔을 때 다시 시도하는 횟수. 8번이면 동시 체크인 8건이 겹쳐도 뚫린다.
_ASSIGN_TRIES = 8

# 슬롯의 기본 자릿수. 001 ~ 999.
_BASE_DIGITS = 3

# 후보에서 빠진 이유. 화면에서 번호 타일을 어떻게 흐릴지 결정한다.
OUT_NOT_CHECKED_IN = "not_checked_in"
OUT_CANCELLED = "cancelled"
OUT_STAFF = "staff"
OUT_ALREADY_WON = "already_won"
# 번호는 받았지만 지금 추첨하는 자리(뒤풀이 등)에 출석하지 않은 사람.
OUT_NOT_IN_SESSION = "not_in_session"


def assign_draw_no(participant: Participant) -> int | None:
    """체크인한 사람에게 다음 번호를 준다. 이미 가진 번호는 그대로 둔다.

    **부르는 시점에 주의한다** — 세션에 다른 변경이 걸려 있지 않을 때 불러야 한다.
    번호가 부딪히면 되돌린 뒤 다음 번호로 다시 시도하는데, 그 rollback 이 같은
    요청의 다른 변경(체크인 기록·배정)까지 함께 지워 버리기 때문이다.
    그래서 두 호출자 모두 **체크인을 커밋한 다음에** 부른다.
    """
    if participant.draw_no is not None:
        return participant.draw_no

    for _ in range(_ASSIGN_TRIES):
        current = db.session.query(func.max(Participant.draw_no)).scalar() or 0
        participant.draw_no = current + 1
        try:
            db.session.commit()
            return participant.draw_no
        except (IntegrityError, OperationalError):
            # 그 번호를 같은 순간에 다른 사람이 가져갔다. 최댓값을 다시 읽는다.
            # (유일 인덱스 uq_participants_draw_no 가 중복을 막아 준다)
            db.session.rollback()

    current_app.logger.error(
        "럭키드로우 번호 발급 실패 — participant=%s. 체크인 자체는 정상 처리되었습니다.",
        participant.id,
    )
    return None


def issued_participants() -> list[Participant]:
    """번호를 받은 사람 전체. 번호 순."""
    return (
        db.session.query(Participant)
        .filter(Participant.draw_no.isnot(None))
        .order_by(Participant.draw_no.asc())
        .all()
    )


def won_participant_ids() -> set[int]:
    """이미 당첨된 사람. 무효 처리된 건은 세지 않는다 (다시 뽑을 수 있어야 한다)."""
    rows = (
        db.session.query(LuckyDraw.participant_id)
        .filter(LuckyDraw.voided.is_(False), LuckyDraw.participant_id.isnot(None))
        .all()
    )
    return {row[0] for row in rows}


def out_reason(
    participant: Participant,
    won_ids: set[int],
    *,
    exclude_staff: bool,
    allow_repeat: bool,
    present_ids: set[int] | None = None,
) -> str | None:
    """후보에서 빠진 이유. 후보면 None.

    `present_ids` 를 주면 그 자리에 출석한 사람으로 후보를 좁힌다 (뒤풀이 추첨).
    None 이면 번호를 받은 사람 전체가 대상이다 (본 행사 추첨).
    """
    if participant.checked_in_at is None:
        # 번호는 받았는데 체크인 기록이 없는 경우. 스태프가 출석을 취소했거나,
        # 번호 발급 직후 체크인 커밋이 실패한 흔적이다.
        return OUT_NOT_CHECKED_IN
    if participant.is_cancelled:
        return OUT_CANCELLED
    if present_ids is not None and participant.id not in present_ids:
        return OUT_NOT_IN_SESSION
    if exclude_staff and participant.is_staff:
        return OUT_STAFF
    if not allow_repeat and participant.id in won_ids:
        return OUT_ALREADY_WON
    return None


def present_ids_for(session_key: str | None) -> set[int] | None:
    """그 회차에 출석한 사람의 id. 회차를 지정하지 않으면 None (제한 없음)."""
    if not session_key:
        return None
    # 순환 import 를 피해 부르는 자리에서 늦게 가져온다.
    from .attendance import checked_in_ids, session_by_key

    session = session_by_key(session_key)
    if session is None:
        return None
    return checked_in_ids(session)


def eligible_participants(
    *,
    exclude_staff: bool,
    allow_repeat: bool,
    pool_session: str | None = None,
) -> list[Participant]:
    won_ids = won_participant_ids()
    present = present_ids_for(pool_session)
    return [
        p
        for p in issued_participants()
        if out_reason(
            p,
            won_ids,
            exclude_staff=exclude_staff,
            allow_repeat=allow_repeat,
            present_ids=present,
        )
        is None
    ]


def draw_digits(numbers: list[int] | None = None) -> int:
    """슬롯 자릿수. 기본 3자리이고, 1000번을 넘기면 그만큼 늘린다."""
    highest = max(numbers) if numbers else 0
    return max(_BASE_DIGITS, len(str(highest)))


def next_round_no() -> int:
    """다음 회차. 무효 처리된 건은 세지 않아 '1등·2등' 순서가 흐트러지지 않는다."""
    used = (
        db.session.query(func.count(LuckyDraw.id))
        .filter(LuckyDraw.voided.is_(False))
        .scalar()
    )
    return int(used or 0) + 1


# ---------------------------------------------------------------------------
# 상품 목록
# ---------------------------------------------------------------------------
#
# 행사 전에 '1등 에어팟 1개 · 2등 텀블러 3개 · 간식 10개' 를 미리 등록해 두고,
# 당일에는 회차마다 고르기만 한다. 진행자가 매번 상품 이름을 타이핑하게 두면
# '1등 에어팟' 과 '1등에어팟' 이 섞여 남은 수량 집계가 어긋난다.

_PRIZE_LABEL_MAX = 80
_PRIZE_COUNT_MAX = 999


def _normalize_prize(item: object, used_ids: set[str]) -> dict | None:
    if not isinstance(item, dict):
        return None
    label = str(item.get("label") or "").strip()[:_PRIZE_LABEL_MAX]
    if not label:
        return None

    try:
        count = int(item.get("count") or 1)
    except (TypeError, ValueError):
        count = 1
    count = max(1, min(count, _PRIZE_COUNT_MAX))

    prize_id = str(item.get("id") or "").strip()[:20]
    # id 는 당첨 기록이 붙잡고 있는 값이라 함부로 새로 만들지 않는다.
    # 비어 있거나 목록 안에서 겹칠 때만 새로 뽑는다.
    while not prize_id or prize_id in used_ids:
        prize_id = secrets.token_hex(4)
    used_ids.add(prize_id)

    return {"id": prize_id, "label": label, "count": count}


def load_prizes() -> list[dict]:
    """등록된 상품 목록. 값이 깨져 있으면 빈 목록으로 본다 (화면이 죽지 않도록)."""
    raw = get_setting(SETTING_DRAW_PRIZES, "")
    if not raw:
        return []
    try:
        loaded = json.loads(raw)
    except (ValueError, TypeError):
        current_app.logger.warning("럭키드로우 상품 목록을 읽지 못했습니다. 빈 목록으로 봅니다.")
        return []

    used_ids: set[str] = set()
    items = [_normalize_prize(item, used_ids) for item in (loaded if isinstance(loaded, list) else [])]
    return [item for item in items if item is not None]


def save_prizes(items: object) -> list[dict]:
    """상품 목록을 통째로 갈아끼운다. 커밋은 호출자가 한다."""
    used_ids: set[str] = set()
    normalized = [
        item
        for item in (
            _normalize_prize(entry, used_ids) for entry in (items if isinstance(items, list) else [])
        )
        if item is not None
    ]
    set_setting(SETTING_DRAW_PRIZES, json.dumps(normalized, ensure_ascii=False))
    return normalized


def prize_draw_counts() -> dict[str, int]:
    """상품별로 이미 나간 개수. 무효 처리된 건은 세지 않는다."""
    rows = (
        db.session.query(LuckyDraw.prize_id, func.count(LuckyDraw.id))
        .filter(LuckyDraw.voided.is_(False), LuckyDraw.prize_id.isnot(None))
        .group_by(LuckyDraw.prize_id)
        .all()
    )
    return {prize_id: int(count) for prize_id, count in rows}


def prize_view() -> list[dict]:
    """상품 목록 + 소진 현황."""
    drawn = prize_draw_counts()
    return [
        {
            **prize,
            "drawn": drawn.get(prize["id"], 0),
            "remaining": max(prize["count"] - drawn.get(prize["id"], 0), 0),
        }
        for prize in load_prizes()
    ]


def find_prize(prize_id: str) -> dict | None:
    for prize in prize_view():
        if prize["id"] == prize_id:
            return prize
    return None


# ---------------------------------------------------------------------------
# 추첨
# ---------------------------------------------------------------------------

def run_draw(
    *,
    prize: str = "",
    prize_id: str | None = None,
    actor: str,
    exclude_staff: bool = False,
    allow_repeat: bool = False,
    pool_session: str | None = None,
) -> LuckyDraw | None:
    """후보 중에서 한 명을 뽑아 기록한다. 후보가 없으면 None.

    커밋은 호출자가 한다 (감사 로그를 같은 트랜잭션에 묶기 위해).
    """
    pool = eligible_participants(
        exclude_staff=exclude_staff,
        allow_repeat=allow_repeat,
        pool_session=pool_session,
    )
    if not pool:
        return None

    # random 대신 secrets. 상품이 걸린 추첨에서 예측 가능한 난수를 쓸 이유가 없다.
    winner = secrets.choice(pool)

    entry = LuckyDraw(
        round_no=next_round_no(),
        prize=prize.strip()[:_PRIZE_LABEL_MAX],
        prize_id=prize_id or None,
        draw_no=winner.draw_no,
        participant_id=winner.id,
        pool_size=len(pool),
        actor=actor,
    )
    db.session.add(entry)
    db.session.flush()
    return entry
