"""공개 API.

본인 조회는 '이름 + 전화번호 전체'가 모두 일치할 때만 본인 1건을 돌려준다.
명단을 나열하는 엔드포인트는 존재하지 않는다.

입금 확인은 실시간이 아니다. 카카오뱅크 개인 계좌에는 공개 API가 없어
관리자가 거래내역 파일을 올린 시점까지만 반영되므로, 조회 응답에 그 시점을
함께 담아 참가자가 오해하지 않도록 한다.
"""

from __future__ import annotations

import re

from flask import Blueprint, current_app, jsonify, request

from ..assignments import active_fields
from ..attendance import (
    eligible_for,
    ensure_default_sessions,
    ensure_token,
    find_by_token,
    open_session,
    record_checkin,
)
from ..draw import assign_draw_no
from ..extensions import db, limiter
from ..models import (
    CHECKIN_SELF,
    ImportRecord,
    LookupAttempt,
    Participant,
    is_card_link_visible,
)
from ..security import client_ip
from ..utils import (
    normalize_name,
    normalize_phone,
    normalize_student_id,
    now_kst,
    phone_last4,
    to_iso,
)

public_bp = Blueprint("public", __name__)


def _sync_state() -> dict:
    """마지막 반영 시점. 참가자 화면에 그대로 노출한다."""
    latest = (
        db.session.query(ImportRecord)
        .order_by(ImportRecord.imported_at.desc())
        .first()
    )
    if latest is None:
        return {
            "hasData": False,
            "lastImportedAt": None,
            "coverageUntil": None,
        }
    return {
        "hasData": True,
        "lastImportedAt": to_iso(latest.imported_at),
        # 파일에 담긴 마지막 거래 시각이 가장 정확하고, 없으면 조회 종료일로 대신한다.
        "coverageUntil": to_iso(latest.latest_transaction_at or latest.period_to),
    }


@public_bp.get("/health")
def health():
    return jsonify({"status": "ok"})


@public_bp.get("/sync-status")
def sync_status():
    """입금 내역이 언제까지 반영되어 있는지 알려준다 (인증 불필요)."""
    return jsonify(_sync_state())


@public_bp.post("/status")
@limiter.limit(lambda: current_app.config["LOOKUP_RATE_LIMIT"])
def lookup_status():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name") or "").strip()
    phone = normalize_phone(payload.get("phone"))

    if not name or len(phone) < 10:
        return jsonify({
            "error": "invalid_input",
            "message": "이름과 전화번호를 정확히 입력해 주세요.",
        }), 400

    name_norm = normalize_name(name)
    participant = (
        db.session.query(Participant)
        .filter(Participant.phone == phone)
        .one_or_none()
    )
    matched = participant is not None and participant.name_norm == name_norm

    db.session.add(
        LookupAttempt(
            ip=client_ip(),
            name_norm=name_norm,
            phone_last4=phone_last4(phone),
            success=matched,
        )
    )
    db.session.commit()

    sync = _sync_state()

    if not matched:
        # 전화번호 존재 여부가 드러나지 않도록 동일한 응답을 준다.
        return jsonify({
            "found": False,
            "message": "입력하신 정보와 일치하는 신청 내역을 찾지 못했습니다.",
            "sync": sync,
        })

    return jsonify({
        "found": True,
        "participant": participant.to_public_dict(),
        "sync": sync,
    })


# ---------------------------------------------------------------------------
# 셀프 체크인
# ---------------------------------------------------------------------------

def _checkin_view(participant: Participant, session, at) -> dict:
    """체크인 성공 화면에 담을 것.

    스태프에게 보여 주고 명찰·간식을 받는 화면이므로 이름은 마스킹하지 않는다.
    이름+학번+전화 뒷자리 세 가지를 모두 맞춘 뒤이니 본인으로 본다.

    럭키드로우 번호를 함께 준다. 추첨 시각에 화면만 보고 자기 번호를 알아야 하고,
    당첨되면 이 화면을 스태프에게 보여 인증하는 근거가 된다.
    """
    values = participant.assignments
    return {
        "name": participant.name,
        # 어느 자리에 찍혔는지 그대로 보여 준다. 본 행사와 뒤풀이가 같은 QR 을
        # 쓰므로, 화면이 '본 행사 체크인 완료'라고 말해 주지 않으면 참가자는
        # 자기가 어디에 찍힌 것인지 알 수 없다.
        "sessionKey": session.key,
        "sessionLabel": session.label,
        "checkedInAt": to_iso(at),
        "drawNo": participant.draw_no,
        "drawLabel": participant.draw_label,
        # 개인 카드(/p/<token>) 주소. 명찰을 못 받았거나 두고 온 사람은 이 화면을
        # 다시 열어 자기 정보를 확인한다.
        "token": participant.card_token,
        "assignments": [
            {"key": field.key, "label": field.label, "value": values.get(field.key) or None}
            for field in active_fields()
            if field.show_on_checkin
        ],
    }


@public_bp.post("/checkin")
@limiter.limit(lambda: current_app.config["CHECKIN_RATE_LIMIT"])
def checkin():
    """집결지 QR 을 찍고 본인이 직접 출석 처리한다.

    조회(POST /status)와 달리 전화번호 전체를 묻지 않는다. 줄이 밀리는 자리에서
    입력을 최소화하되, 이름만으로는 동명이인·대리 체크인을 막을 수 없어
    학번과 전화 뒷자리를 함께 받는다.
    """
    ensure_default_sessions()
    session = open_session()
    if session is None:
        return jsonify({
            "ok": False,
            "reason": "closed",
            "message": "아직 체크인이 열리지 않았습니다. 안내된 시각에 다시 시도해 주세요.",
        })

    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name") or "").strip()
    student_id = normalize_student_id(payload.get("studentId"))
    last4 = re.sub(r"\D", "", str(payload.get("phoneLast4") or ""))[-4:]

    if not name or not student_id or len(last4) != 4:
        return jsonify({
            "ok": False,
            "reason": "invalid_input",
            "message": "이름 · 학번 · 전화번호 뒤 4자리를 모두 입력해 주세요.",
        }), 400

    name_norm = normalize_name(name)
    # 뒷자리는 인덱스가 걸려 있어 후보를 먼저 좁힌 뒤, 나머지 둘을 파이썬에서 맞춘다.
    candidates = (
        db.session.query(Participant)
        .filter(Participant.phone_last4 == last4)
        .all()
    )
    matched = [
        p for p in candidates
        if p.name_norm == name_norm and normalize_student_id(p.student_id) == student_id
    ]

    if len(matched) != 1:
        # 후보가 여럿이면 어느 쪽인지 특정할 수 없다. 스태프가 직접 처리해야 한다.
        return jsonify({
            "ok": False,
            "reason": "not_found",
            "message": "일치하는 신청 내역을 찾지 못했습니다. 스태프에게 문의해 주세요.",
        })

    participant = matched[0]

    if participant.is_cancelled:
        return jsonify({
            "ok": False,
            "reason": "cancelled",
            "message": "참가 취소로 처리된 신청입니다. 스태프에게 문의해 주세요.",
        })

    if not participant.is_confirmed:
        return jsonify({
            "ok": False,
            "reason": "not_confirmed",
            "message": "아직 참가가 확정되지 않았습니다. 스태프에게 문의해 주세요.",
        })

    # 뒤풀이처럼 대상이 좁은 회차. 신청하지 않은 사람이 줄에 섞여 들어온다.
    if not eligible_for(session, participant):
        return jsonify({
            "ok": False,
            "reason": "not_in_session",
            "message": f"{session.label} 신청자 명단에 없습니다. 스태프에게 문의해 주세요.",
        })

    row, created = record_checkin(session, participant, by=CHECKIN_SELF)
    db.session.commit()

    # 럭키드로우 번호는 체크인을 커밋한 뒤에 발급한다. 번호가 부딪히면 되돌리고
    # 다시 시도하는데, 그 rollback 이 체크인 기록까지 지워서는 안 된다.
    # 발급에 실패해도 체크인은 유효하다 (번호 없이 화면이 나오고, 다시 열면 받는다).
    #
    # 번호를 주는 회차는 하나뿐이다 — 회차마다 새로 매기면 참가자가 번호를 두 개
    # 외워야 한다. 뒤풀이 추첨은 본 행사에서 받은 번호를 그대로 쓴다.
    if session.gives_draw_no:
        assign_draw_no(participant)

    # 개인 카드 주소도 이 자리에서 만든다. 명찰을 나눠 주지 못한 사람도
    # 체크인만 하면 폰으로 자기 QR 을 띄울 수 있어야 한다.
    ensure_token(participant)
    db.session.commit()

    return jsonify({
        "ok": True,
        "reason": "ok",
        "alreadyCheckedIn": not created,
        "participant": _checkin_view(participant, session, row.at),
    })


@public_bp.get("/checkin/state")
def checkin_state():
    """체크인 화면이 '지금 열려 있는지'를 먼저 알아보는 용도.

    '내 QR 열기' 버튼을 보일지도 함께 준다. 체크인 완료 화면은 기기에 저장되어
    새로고침해도 그대로 열리므로, 버튼 표시 여부를 그 저장본에 박아 두면 나중에
    관리자가 내려도 이미 체크인한 사람의 화면에는 그대로 남는다. 그래서 저장본이
    아니라 **매번 이 응답을 보고** 결정한다.
    """
    ensure_default_sessions()
    session = open_session()
    return jsonify({
        "open": session is not None,
        # 지금 여는 자리의 이름. 화면이 '본 행사 체크인' / '뒤풀이 체크인' 으로 갈린다.
        "sessionKey": session.key if session else None,
        "sessionLabel": session.label if session else None,
        "cardLink": is_card_link_visible(),
    })


# ---------------------------------------------------------------------------
# 개인 카드
# ---------------------------------------------------------------------------

@public_bp.get("/p/<token>")
@limiter.limit(lambda: current_app.config["CARD_RATE_LIMIT"])
def personal_card(token: str):
    """명찰의 QR 이 가리키는 화면에 담을 것.

    **여기서 새로 드러나는 정보는 없다.** 이름 · 학과 · 조는 명찰 앞면에 이미
    인쇄되어 있고, 이 주소는 그 명찰을 손에 든 사람만 알 수 있다. 그래서
    전화번호 · 건강 정보 · 납입 내역처럼 명찰에 없는 것은 절대 담지 않는다.
    """
    participant = find_by_token(token)
    if participant is None or participant.is_cancelled:
        return jsonify({"found": False, "message": "확인할 수 없는 QR 입니다."}), 404

    ensure_default_sessions()
    values = participant.assignments

    return jsonify({
        "found": True,
        "token": participant.card_token,
        "name": participant.name,
        "department": participant.department,
        "checkedInAt": to_iso(participant.checked_in_at),
        "drawLabel": participant.draw_label,
        # 뒤풀이 참가 여부는 명찰에도 찍히는 값이라(띠 색으로 갈린다) 여기 담아도
        # 새로 드러나는 것이 없다. 자리를 옮길 때 본인이 확인하는 용도다.
        "joinsAfterparty": participant.joins_afterparty,
        "assignments": [
            {"key": field.key, "label": field.label, "value": values.get(field.key) or None}
            for field in active_fields()
            if field.show_on_checkin
        ],
        "checkins": [
            {"key": row.session.key, "label": row.session.label, "at": to_iso(row.at)}
            for row in participant.checkins
            if row.session and row.session.is_active
        ],
    })
