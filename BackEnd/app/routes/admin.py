"""관리자 API.

원칙: 자동 매칭은 보조 수단이고, 모든 건은 관리자가 손으로 뒤집을 수 있어야 한다.
대신 수동 조작은 전부 감사 로그에 남는다.
"""

from __future__ import annotations

import csv
import io
import json
import re

from flask import Blueprint, Response, current_app, g, jsonify, request
from sqlalchemy.exc import IntegrityError

from ..admins import (
    SUPER_USERNAME,
    TABS,
    TIER_STAFF,
    TIERS,
    AdminError,
    clean_tabs,
    clean_tier,
    dump_tabs,
    ensure_super_admin,
    find_account,
    normalize_username,
    tabs_for,
    tier_for,
    tier_label,
)
from ..assignment_sheet import build_template, parse_assignment_sheet
from ..attendance import (
    active_sessions,
    all_sessions,
    cancel_checkin,
    checked_in_ids,
    eligible_for,
    ensure_default_sessions,
    issue_tokens,
    main_session,
    record_checkin,
    session_by_key,
)
from ..assignments import (
    DEFAULT_GROUP_KEY,
    AssignmentError,
    active_fields,
    all_fields,
    apply_assignments,
    drop_field_values,
    make_key,
    next_position,
    normalize_options,
    values_in_use,
)
from ..draw import (
    assign_draw_no,
    present_ids_for,
    draw_digits,
    eligible_participants,
    find_prize,
    issued_participants,
    next_round_no,
    out_reason,
    prize_view,
    run_draw,
    save_prizes,
    won_participant_ids,
)
from ..extensions import db, limiter
from ..matching import match_deposit, rematch_deposits
from ..models import (
    AFTER_PAID,
    CHECKIN_STAFF,
    LEADER_PREFERENCES,
    LEADER_WANT,
    LEADER_OK,
    DEP_AMBIGUOUS,
    DEP_IGNORED,
    DEP_MATCHED,
    DEP_MINOR,
    DEP_UNMATCHED,
    FEE_CLASSES,
    FEE_MEMBER,
    FEE_NON_MEMBER,
    FEE_STAFF,
    OVERRIDABLE_STATUSES,
    REQUEUE_STATUSES,
    PAY_PAID,
    SETTING_AFTERPARTY_FEE,
    SETTING_CARD_LINK,
    SETTING_STAFF_FEE,
    SRC_IMPORT,
    SRC_MANUAL,
    SRC_ONSITE,
    SRC_PUSH,
    AdminAccount,
    AdminRole,
    Allocation,
    AssignmentField,
    AuditLog,
    CheckIn,
    CheckinSession,
    Deposit,
    ImportRecord,
    LuckyDraw,
    Participant,
    UnparsedNotification,
    current_afterparty_fee,
    is_card_link_visible,
    set_setting,
    staff_fee,
    write_audit,
)
from ..parsers import parse_push_payload, parse_statement
from ..security import (
    issue_admin_token,
    require_admin,
    require_super,
    tier_hashes,
    tiers_matching,
    verify_admin_token,
)
from ..services import expected_amount_for, recalc_expected_amounts, register_deposit
from ..utils import (
    mask_phone,
    normalize_name,
    normalize_phone,
    normalize_student_id,
    now_kst,
    parse_amount,
    parse_datetime,
    phone_last4,
    split_depositor,
    to_iso,
)

admin_bp = Blueprint("admin", __name__)

_PAGE_SIZE_MAX = 500

# 한 번의 일괄 작업이 남기는 변경 줄 수의 상한. 300명을 한 파일로 배정하면
# 기록 하나가 감사 로그 화면을 통째로 덮어 정작 볼 것을 가린다.
_AUDIT_CHANGE_LIMIT = 100


# --------------------------------------------------------------------------
# 변경 기록
# --------------------------------------------------------------------------
#
# 감사 로그는 몇 달 뒤에 "이거 누가 왜 이렇게 했지" 를 되짚는 데 쓴다.
# 필드 이름과 새 값만 남기면 그때 읽을 수 없으므로, **누구의 · 무엇을 ·
# 무엇에서 무엇으로** 를 사람이 읽을 수 있는 문장 재료로 남긴다.
#
# 표시 문구를 프론트가 아니라 여기서 만드는 이유는, 로그가 그 자체로 완결된
# 기록이어야 하기 때문이다. 나중에 화면의 라벨이 바뀌어도 예전 기록은
# 그때의 표현 그대로 읽혀야 한다.

_PAYMENT_STATUS_LABELS = {
    "UNPAID": "미납",
    "PAID": "납입 완료",
    "UNDERPAID": "부분 입금",
    "OVERPAID": "초과 납입",
    "REFUNDED": "환불",
    "WAIVED": "면제",
}

_DEPOSIT_STATUS_LABELS = {
    DEP_UNMATCHED: "미매칭",
    DEP_AMBIGUOUS: "판단 보류",
    DEP_MATCHED: "확인 완료",
    DEP_IGNORED: "무관 입금",
    DEP_MINOR: "기타 입금",
}

_FEE_CLASS_LABELS = {
    FEE_MEMBER: "총학생회비 납부자",
    FEE_NON_MEMBER: "총학생회비 미납부자",
    FEE_STAFF: "스태프",
}


_LEADER_LABELS = {
    LEADER_WANT: "조장 희망",
    LEADER_OK: "조장 가능",
    "no": "조장 사양",
}


def _won(value) -> str:
    return f"{int(value):,}원"


def _yes_no(value, yes: str = "예", no: str = "아니오") -> str:
    return yes if value else no


class Changes:
    """한 요청에서 실제로 바뀐 것만 모은다.

    값이 그대로면 기록하지 않는다. '수정' 을 눌렀지만 아무것도 안 바뀐 요청까지
    남으면 로그가 잡음으로 차서 정작 볼 것을 못 찾는다.
    """

    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, field: str, label: str, before: str, after: str) -> None:
        if before == after:
            return
        self.items.append({"field": field, "label": label, "from": before, "to": after})

    def note(self, label: str, text: str) -> None:
        """전후가 없는 단발성 기록 (예: '재매칭 12건')."""
        self.items.append({"field": None, "label": label, "from": None, "to": text})

    def __bool__(self) -> bool:
        return bool(self.items)

    def detail(self, target: str | None = None) -> dict:
        payload: dict = {"changes": self.items}
        if target:
            payload["target"] = target
        return payload


# --------------------------------------------------------------------------
# 인증
# --------------------------------------------------------------------------

def _session_view(account: AdminAccount) -> dict:
    tabs = tabs_for(account)
    tier = tier_for(account)
    return {
        "authenticated": True,
        "actor": account.display_name,
        "username": account.username,
        "isSuper": account.is_super,
        "roleName": account.role.name if account.role else None,
        "tier": tier,
        "tierLabel": tier_label(tier),
        "tabs": tabs,
        # 탭 이름표는 서버가 단일 진실이다. 탭이 늘어도 프론트의 목록을 따로 고치지 않는다.
        "tabLabels": [tab for tab in TABS if tab["key"] in tabs],
    }


@admin_bp.post("/login")
@limiter.limit(lambda: current_app.config["LOGIN_RATE_LIMIT"])
def login():
    """ID + 등급별 비밀번호.

    비밀번호는 **등급마다 하나**다 — 최고 관리자·국장단이 쓰는 것과 국원이 쓰는 것
    (`.env` 의 `ADMIN_PASSWORD_HASH` / `STAFF_PASSWORD_HASH`). 어느 쪽을 요구할지는
    그 계정의 역할군에 매긴 등급이 정한다(app/admins.py 의 설명 참조).

    순서가 중요하다. **비밀번호부터 확인하고 계정을 찾는다.** 그래야 아무 비밀번호도
    모르는 사람이 ID 만 넣어 보며 '누가 관리자인지'를 알아내지 못한다.
    """
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username") or "")
    password = str(payload.get("password") or "")

    if not tier_hashes()["lead"]:
        return jsonify({"error": "misconfigured", "message": "ADMIN_PASSWORD_HASH 미설정"}), 503

    opened = tiers_matching(password)
    if not opened:
        return jsonify({"error": "invalid_credentials", "message": "비밀번호가 올바르지 않습니다."}), 401

    account = find_account(username)
    if account is None and normalize_username(username) == SUPER_USERNAME:
        # 최고 관리자는 언제나 들어올 수 있어야 한다. DB 를 직접 손대다 이 행이
        # 사라지면 아무도 권한을 줄 수 없게 되므로, 그 자리에서 되살린다.
        ensure_super_admin()
        account = find_account(username)

    if account is None:
        return jsonify({
            "error": "unknown_admin",
            "message": "등록되지 않은 관리자 ID 입니다. 최고 관리자에게 계정 추가를 요청해 주세요.",
        }), 401
    if not account.is_active:
        return jsonify({
            "error": "account_disabled",
            "message": "사용이 중지된 계정입니다. 최고 관리자에게 문의해 주세요.",
        }), 401

    # 계정의 등급과 입력한 비밀번호의 등급이 같아야 한다. 여기가 진짜 문이다.
    tier = tier_for(account)
    if tier not in opened:
        return jsonify({
            "error": "wrong_tier",
            "message": (
                f"'{account.display_name}' 님은 {tier_label(tier)} 비밀번호로 들어와야 합니다."
            ),
        }), 401

    account.last_login_at = now_kst()
    token = issue_admin_token(account.display_name, account.id, tier)
    # 어느 비밀번호로 들어왔는지도 남긴다. 등급을 옮긴 뒤 누가 아직 옛 등급으로
    # 들어오고 있는지가 기록만 보고도 드러난다.
    entered = Changes()
    entered.note("등급", tier_label(tier))
    write_audit(account.display_name, "login", "admin_account", account.id,
                entered.detail(account.username))
    db.session.commit()

    return jsonify({
        "token": token,
        "expiresIn": current_app.config["ADMIN_SESSION_TTL"],
        **_session_view(account),
    })


@admin_bp.get("/session")
def session_info():
    header = request.headers.get("Authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    claims = verify_admin_token(token) if token else None
    if not claims:
        return jsonify({"authenticated": False}), 401

    account = db.session.get(AdminAccount, claims["id"]) if claims["id"] else None
    if account is None:
        # 계정이 붙기 전에 발급된 옛 토큰. 최고 관리자로 다시 로그인하게 한다.
        return jsonify({"authenticated": False, "error": "stale_token"}), 401
    if not account.is_active:
        return jsonify({"authenticated": False, "error": "account_disabled"}), 401
    if claims["tier"] is not None and claims["tier"] != tier_for(account):
        # 등급이 바뀌면 다시 로그인해야 한다 — 바뀐 등급의 비밀번호로.
        return jsonify({"authenticated": False, "error": "tier_changed"}), 401

    return jsonify(_session_view(account))


# --------------------------------------------------------------------------
# 관리자 · 역할군 (최고 관리자 전용)
# --------------------------------------------------------------------------
#
# 탭 권한은 화면을 가리는 것이지 API 를 막는 것이 아니다. 다만 **권한을 스스로
# 올리는 길**만은 서버에서 막는다 — 그것까지 열어 두면 구분 자체가 무의미해진다.

@admin_bp.get("/admins")
@require_super
def list_admins():
    accounts = (
        db.session.query(AdminAccount)
        .order_by(AdminAccount.is_super.desc(), AdminAccount.display_name.asc())
        .all()
    )
    roles = (
        db.session.query(AdminRole)
        .order_by(AdminRole.position.asc(), AdminRole.id.asc())
        .all()
    )
    return jsonify({
        "accounts": [
            {**account.to_admin_dict(), "tabs": tabs_for(account)} for account in accounts
        ],
        "roles": [role.to_admin_dict() for role in roles],
        "tabs": TABS,
        # 등급 목록과 이름표도 서버가 단일 진실이다.
        "tiers": TIERS,
        # 국원용 비밀번호가 아직 .env 에 없으면 두 등급이 같은 비밀번호를 쓴다.
        # 화면이 "나눴다"고 말하는데 실제로는 안 나뉜 상태를 숨기면 안 된다.
        "tiersSeparated": bool(current_app.config.get("STAFF_PASSWORD_HASH")),
        "superUsername": SUPER_USERNAME,
    })


@admin_bp.post("/admins")
@require_super
def create_admin():
    """관리자 추가.

    ID 는 보통 본인 이름이다. 이름으로 로그인하고 이름으로 기록이 남는 것이
    이 기능의 전부라, 따로 아이디 규칙을 두지 않는다.
    """
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username") or "").strip()
    display_name = str(payload.get("displayName") or "").strip() or username

    if not normalize_username(username):
        return jsonify({"error": "invalid_username", "message": "로그인 ID 를 입력해 주세요."}), 400
    if find_account(username) is not None:
        return jsonify({
            "error": "duplicate_username",
            "message": f"'{username}' 은(는) 이미 쓰이고 있는 ID 입니다.",
        }), 409

    role_id = payload.get("roleId")
    role = db.session.get(AdminRole, int(role_id)) if role_id else None
    try:
        tabs = clean_tabs(payload.get("tabs"))
    except AdminError as exc:
        return jsonify({"error": "invalid_tabs", "message": str(exc)}), 400

    account = AdminAccount(
        username=username,
        display_name=display_name,
        role_id=role.id if role else None,
        tabs_json=dump_tabs(tabs),
        is_super=False,
        is_active=True,
    )
    db.session.add(account)
    db.session.flush()

    changes = Changes()
    changes.note("로그인 ID", account.username)
    changes.note("역할군", role.name if role else "(없음)")
    write_audit(g.actor, "admin_account.create", "admin_account", account.id,
                changes.detail(account.display_name))
    db.session.commit()

    return jsonify({**account.to_admin_dict(), "tabs": tabs_for(account)}), 201


@admin_bp.patch("/admins/<int:account_id>")
@require_super
def update_admin(account_id: int):
    account = db.session.get(AdminAccount, account_id)
    if account is None:
        return jsonify({"error": "not_found"}), 404

    payload = request.get_json(silent=True) or {}
    changes = Changes()

    if "displayName" in payload:
        name = str(payload["displayName"] or "").strip()
        if not name:
            return jsonify({"error": "invalid_name", "message": "이름을 비울 수 없습니다."}), 400
        changes.add("displayName", "이름", account.display_name, name)
        account.display_name = name

    if "roleId" in payload:
        raw = payload["roleId"]
        role = db.session.get(AdminRole, int(raw)) if raw else None
        if raw and role is None:
            return jsonify({"error": "role_not_found"}), 400
        changes.add(
            "role", "역할군",
            account.role.name if account.role else "(없음)",
            role.name if role else "(없음)",
        )
        account.role_id = role.id if role else None

    if "tabs" in payload:
        try:
            tabs = clean_tabs(payload["tabs"])
        except AdminError as exc:
            return jsonify({"error": "invalid_tabs", "message": str(exc)}), 400
        changes.add(
            "tabs", "개인 지정 탭",
            ", ".join(account.own_tabs) or "(역할군을 따름)",
            ", ".join(tabs) or "(역할군을 따름)",
        )
        account.tabs_json = dump_tabs(tabs)

    if "isActive" in payload:
        want = bool(payload["isActive"])
        if account.is_super and not want:
            return jsonify({
                "error": "super_protected",
                "message": "최고 관리자 계정은 중지할 수 없습니다.",
            }), 400
        changes.add("isActive", "사용", _yes_no(account.is_active, "사용", "중지"),
                    _yes_no(want, "사용", "중지"))
        account.is_active = want

    if changes:
        write_audit(g.actor, "admin_account.update", "admin_account", account.id,
                    changes.detail(account.display_name))
    db.session.commit()
    return jsonify({**account.to_admin_dict(), "tabs": tabs_for(account)})


@admin_bp.delete("/admins/<int:account_id>")
@require_super
def delete_admin(account_id: int):
    account = db.session.get(AdminAccount, account_id)
    if account is None:
        return jsonify({"error": "not_found"}), 404
    if account.is_super:
        return jsonify({
            "error": "super_protected",
            "message": "최고 관리자 계정은 지울 수 없습니다.",
        }), 400

    # 지워도 작업 기록의 이름은 남는다. 로그는 그 자체로 완결된 기록이어야 한다.
    write_audit(g.actor, "admin_account.delete", "admin_account", account.id,
                {"target": account.display_name})
    db.session.delete(account)
    db.session.commit()
    return jsonify({"ok": True})


@admin_bp.post("/roles")
@require_super
def create_role():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name") or "").strip()
    if not name:
        return jsonify({"error": "invalid_name", "message": "역할군 이름을 입력해 주세요."}), 400
    if db.session.query(AdminRole).filter(AdminRole.name == name).one_or_none() is not None:
        return jsonify({"error": "duplicate_name", "message": f"'{name}' 은(는) 이미 있습니다."}), 409

    try:
        tabs = clean_tabs(payload.get("tabs"))
        # 등급을 안 주면 국원이다. 모르는 것은 낮은 쪽에 둔다.
        tier = clean_tier(payload.get("tier") or TIER_STAFF)
    except AdminError as exc:
        key = "invalid_tier" if "등급" in str(exc) else "invalid_tabs"
        return jsonify({"error": key, "message": str(exc)}), 400

    highest = db.session.query(db.func.max(AdminRole.position)).scalar()
    role = AdminRole(
        name=name,
        tabs_json=dump_tabs(tabs),
        tier=tier,
        position=int(highest or 0) + 10,
    )
    db.session.add(role)
    db.session.flush()

    changes = Changes()
    changes.note("등급", tier_label(tier))
    changes.note("탭", ", ".join(tabs) or "(없음)")
    write_audit(g.actor, "admin_role.create", "admin_role", role.id, changes.detail(name))
    db.session.commit()
    return jsonify(role.to_admin_dict()), 201


@admin_bp.patch("/roles/<int:role_id>")
@require_super
def update_role(role_id: int):
    role = db.session.get(AdminRole, role_id)
    if role is None:
        return jsonify({"error": "not_found"}), 404

    payload = request.get_json(silent=True) or {}
    changes = Changes()

    if "name" in payload:
        name = str(payload["name"] or "").strip()
        if not name:
            return jsonify({"error": "invalid_name", "message": "이름을 비울 수 없습니다."}), 400
        changes.add("name", "이름", role.name, name)
        role.name = name

    if "tabs" in payload:
        try:
            tabs = clean_tabs(payload["tabs"])
        except AdminError as exc:
            return jsonify({"error": "invalid_tabs", "message": str(exc)}), 400
        # 이 역할을 쓰는 사람 전원의 화면이 함께 바뀐다. 그것이 역할군을 두는 이유다.
        changes.add("tabs", "탭", ", ".join(role.tabs) or "(없음)", ", ".join(tabs) or "(없음)")
        role.tabs_json = dump_tabs(tabs)

    if "tier" in payload:
        try:
            tier = clean_tier(payload["tier"])
        except AdminError as exc:
            return jsonify({"error": "invalid_tier", "message": str(exc)}), 400
        # 등급을 바꾸면 **이 역할군의 사람들이 쓰는 비밀번호가 바뀐다.**
        # 탭을 고치는 것과 무게가 다르므로 기록에 또렷이 남긴다.
        changes.add("tier", "등급",
                    tier_label(role.tier or TIER_STAFF), tier_label(tier))
        role.tier = tier

    if changes:
        write_audit(g.actor, "admin_role.update", "admin_role", role.id, changes.detail(role.name))
    db.session.commit()
    return jsonify(role.to_admin_dict())


@admin_bp.delete("/roles/<int:role_id>")
@require_super
def delete_role(role_id: int):
    role = db.session.get(AdminRole, role_id)
    if role is None:
        return jsonify({"error": "not_found"}), 404
    if role.accounts:
        names = ", ".join(account.display_name for account in role.accounts[:3])
        return jsonify({
            "error": "role_in_use",
            "message": (
                f"'{role.name}' 을(를) 쓰는 관리자가 {len(role.accounts)}명 있습니다 ({names}"
                f"{' 외' if len(role.accounts) > 3 else ''}). 먼저 다른 역할군으로 옮겨 주세요."
            ),
        }), 400

    write_audit(g.actor, "admin_role.delete", "admin_role", role.id, {"target": role.name})
    db.session.delete(role)
    db.session.commit()
    return jsonify({"ok": True})


# --------------------------------------------------------------------------
# 요약
# --------------------------------------------------------------------------

@admin_bp.get("/summary")
@require_admin
def summary():
    participants = db.session.query(Participant).all()
    active = [p for p in participants if not p.is_cancelled]
    afterparty = [p for p in active if p.joins_afterparty]

    status_counts: dict[str, int] = {}
    for participant in active:
        key = participant.payment_status
        status_counts[key] = status_counts.get(key, 0) + 1

    deposit_counts: dict[str, int] = {}
    for status, count in (
        db.session.query(Deposit.status, db.func.count(Deposit.id))
        .group_by(Deposit.status)
        .all()
    ):
        deposit_counts[status] = count

    total_deposited = db.session.query(db.func.coalesce(db.func.sum(Deposit.amount), 0)).filter(
        Deposit.status != DEP_IGNORED
    ).scalar()
    total_allocated = db.session.query(db.func.coalesce(db.func.sum(Allocation.amount), 0)).scalar()
    last_deposit_at = db.session.query(db.func.max(Deposit.occurred_at)).scalar()

    expected_total = sum(p.expected_amount for p in active)
    paid_count = status_counts.get(PAY_PAID, 0)
    unparsed_count = (
        db.session.query(db.func.count(UnparsedNotification.id))
        .filter(UnparsedNotification.resolved.is_(False))
        .scalar()
    )
    last_import = (
        db.session.query(ImportRecord).order_by(ImportRecord.imported_at.desc()).first()
    )

    return jsonify({
        "participants": {
            "total": len(participants),
            "active": len(active),
            "cancelled": len(participants) - len(active),
            "byStatus": status_counts,
            "paidRate": round(paid_count / len(active) * 100, 1) if active else 0.0,
            # 납입 완료와 참가 확정은 다르다. 확정을 눌러야 조 배정과 체크인이 열린다.
            "settled": sum(1 for p in active if p.is_settled),
            "confirmed": sum(1 for p in active if p.is_confirmed),
            "awaitingConfirm": sum(1 for p in active if p.is_settled and not p.is_confirmed),
            "checkedIn": sum(1 for p in active if p.is_confirmed and p.checked_in_at is not None),
        },
        # 뒤풀이는 참가비도 출석도 본 행사와 따로 센다.
        # 뒤풀이비는 별도 안내로 걷으므로 '아직 안 낸 사람'이 곧 안내 대상이다.
        "afterparty": {
            "fee": current_afterparty_fee(),
            "joining": len(afterparty),
            "paid": sum(1 for p in afterparty if p.afterparty_status == AFTER_PAID),
            "unpaid": sum(1 for p in afterparty if p.afterparty_status != AFTER_PAID),
            # 안내가 나가기 전에 본 행사비와 한 번에 보낸 사람. 다시 걷으러 가지 않는다.
            "prepaid": sum(1 for p in afterparty if p.afterparty_prepaid),
            "expectedTotal": sum(p.afterparty_fee for p in afterparty),
            "collectedTotal": sum(min(p.afterparty_paid, p.afterparty_fee) for p in afterparty),
        },
        "amounts": {
            "expectedTotal": expected_total,
            "collectedTotal": int(total_allocated or 0),
            "depositedTotal": int(total_deposited or 0),
            "unallocatedTotal": int((total_deposited or 0) - (total_allocated or 0)),
        },
        "deposits": {
            "byStatus": deposit_counts,
            # 기타 입금(MINOR)은 확인 필요 건수에서 뺀다. 그러라고 갈라놓은 것이다.
            "needsReview": deposit_counts.get(DEP_UNMATCHED, 0) + deposit_counts.get(DEP_AMBIGUOUS, 0),
            "minorCount": deposit_counts.get(DEP_MINOR, 0),
            "minorThreshold": current_app.config["MINOR_DEPOSIT_THRESHOLD"],
            "lastDepositAt": to_iso(last_deposit_at),
            "unparsedCount": int(unparsed_count or 0),
        },
        "fees": {
            "councilMember": current_app.config["FEE_COUNCIL_MEMBER"],
            "nonMember": current_app.config["FEE_NON_MEMBER"],
            # 스태프 금액만 화면에서 고칠 수 있다 (늦게 정해지고 바뀌는 값이라).
            "staff": staff_fee(),
            "staffCount": sum(1 for p in active if p.is_staff),
            # 뒤풀이비도 화면에서 고친다 (스태프 금액과 같은 이유).
            "afterparty": current_afterparty_fee(),
        },
        "sync": {
            "hasData": last_import is not None,
            "lastImportedAt": to_iso(last_import.imported_at) if last_import else None,
            "lastFilename": last_import.filename if last_import else None,
            "coverageUntil": to_iso(
                (last_import.latest_transaction_at or last_import.period_to)
                if last_import
                else None
            ),
            "pushIngestEnabled": bool(current_app.config.get("PUSH_INGEST_ENABLED", False)),
        },
        "generatedAt": to_iso(now_kst()),
    })


# --------------------------------------------------------------------------
# 참가자
# --------------------------------------------------------------------------

def _paginate(items: list, page: int, page_size: int) -> tuple[list, dict]:
    total = len(items)
    page = max(page, 1)
    page_size = max(1, min(page_size, _PAGE_SIZE_MAX))
    start = (page - 1) * page_size
    return items[start : start + page_size], {
        "page": page,
        "pageSize": page_size,
        "total": total,
        "totalPages": max(1, -(-total // page_size)),
    }


@admin_bp.get("/participants")
@require_admin
def list_participants():
    query = (request.args.get("query") or "").strip()
    status = (request.args.get("status") or "").strip().upper()
    include_cancelled = request.args.get("includeCancelled", "true").lower() != "false"

    participants = db.session.query(Participant).order_by(Participant.name.asc()).all()

    if query:
        needle_name = normalize_name(query)
        needle_phone = normalize_phone(query)
        participants = [
            p for p in participants
            if (needle_name and needle_name in p.name_norm)
            or (needle_phone and needle_phone in p.phone)
            or (p.student_id and query in p.student_id)
            or (p.department and query in p.department)
        ]
    if not include_cancelled:
        participants = [p for p in participants if not p.is_cancelled]
    if status:
        # 납입 상태는 연결된 입금 합계에서 파생되므로 파이썬에서 거른다 (규모가 작아 문제없다).
        participants = [p for p in participants if p.payment_status == status]

    confirmed = (request.args.get("confirmed") or "").strip().lower()
    if confirmed == "pending":
        # 손볼 대상은 '납입이 끝나 확정을 누르기만 하면 되는 사람' 이다.
        # 미확정 전체를 보여주면 아직 돈이 안 들어온 사람까지 섞여 정작 볼 것이 묻힌다.
        participants = [p for p in participants if p.is_settled and not p.is_confirmed]
    elif confirmed in ("true", "false"):
        want = confirmed == "true"
        participants = [p for p in participants if p.is_confirmed == want]

    staff = (request.args.get("staff") or "").strip().lower()
    if staff in ("true", "false"):
        participants = [p for p in participants if p.is_staff == (staff == "true")]

    # 조장 지원자. 조를 짤 때 '하고 싶다'를 먼저 앉히고 '상관없다'로 채운다.
    leader = (request.args.get("leader") or "").strip().lower()
    if leader == "want":
        participants = [p for p in participants if p.leader_preference == LEADER_WANT]
    elif leader == "any":
        participants = [p for p in participants if p.leader_preference in (LEADER_WANT, LEADER_OK)]

    # 뒤풀이 신청자 / 그중 뒤풀이비가 아직 안 들어온 사람.
    # 뒤풀이비는 별도 안내로 걷으므로 '누구에게 안내를 보낼지' 를 이 필터로 추린다.
    afterparty = (request.args.get("afterparty") or "").strip().lower()
    if afterparty in ("true", "false"):
        participants = [p for p in participants if p.joins_afterparty == (afterparty == "true")]
    elif afterparty == "unpaid":
        participants = [
            p for p in participants
            if p.joins_afterparty and p.afterparty_status != AFTER_PAID
        ]

    # 폼을 두 번 이상 낸 사람. 마지막 응답만 남아 있어 답이 엇갈릴 수 있으므로,
    # 마감 후 지병·알레르기 같은 항목을 원본 시트와 대조할 대상을 추리는 데 쓴다.
    if (request.args.get("resubmitted") or "").strip().lower() == "true":
        participants = [p for p in participants if (p.submission_count or 1) > 1]

    # 관리자가 납입 상태를 손으로 눌러 둔 사람. 입금 내역이 아니라 사람의 판단으로
    # 서 있는 값이라, 정산을 닫기 전에 '왜 이렇게 두었는지'를 한 번 훑을 대상이다.
    if (request.args.get("overridden") or "").strip().lower() == "true":
        participants = [p for p in participants if p.status_override]

    # 배정 화면에서 '아직 조가 없는 사람'만 추려 보기 위한 필터.
    unassigned = (request.args.get("unassigned") or "").strip()
    if unassigned:
        participants = [p for p in participants if not p.assignments.get(unassigned)]

    page_items, meta = _paginate(
        participants,
        int(request.args.get("page", 1) or 1),
        int(request.args.get("pageSize", 50) or 50),
    )
    return jsonify({"items": [p.to_admin_dict() for p in page_items], "pagination": meta})


def _text_or_none(value) -> str | None:
    text = str(value or "").strip()
    return text or None


@admin_bp.post("/participants")
@require_admin
def create_participant():
    """참가자 수기 등록.

    폼을 내지 않은 사람이 반드시 나온다 — 현장 합류, 대리 신청, 폼 응답 유실.
    입금 수기 등록과 같은 이유로 명단에도 손으로 넣는 길을 열어 둔다.

    전화번호가 자연키다. 나중에 같은 번호로 폼 응답이 도착하면 새 행이 생기지
    않고 이 행이 갱신되므로(services.upsert_participant), 중복 인원이 남지 않는다.
    """
    payload = request.get_json(silent=True) or {}

    name = str(payload.get("name") or "").strip()
    if not name:
        return jsonify({"error": "invalid_name", "message": "이름을 입력해 주세요."}), 400

    phone = normalize_phone(payload.get("phone"))
    if len(phone) < 10:
        return jsonify({
            "error": "invalid_phone",
            "message": "전화번호를 확인해 주세요. 숫자 10자리 이상이어야 합니다.",
        }), 400

    # 같은 번호가 이미 있으면 새로 만들지 않는다. 폼으로 들어온 사람을 손으로 한 번 더
    # 넣어 두 사람이 되는 것이 이 기능에서 가장 흔한 사고다.
    duplicate = db.session.query(Participant).filter(Participant.phone == phone).one_or_none()
    if duplicate is not None:
        return jsonify({
            "error": "duplicate_phone",
            "message": f"이 번호는 이미 '{duplicate.name}' 님으로 등록되어 있습니다.",
            "participantId": duplicate.id,
        }), 409

    fee_class = str(payload.get("feeClass") or FEE_NON_MEMBER)
    if fee_class not in FEE_CLASSES:
        return jsonify({"error": "invalid_fee_class"}), 400

    participant = Participant(
        phone=phone,
        phone_last4=phone_last4(phone),
        name=name,
        name_norm=normalize_name(name),
        student_id=_text_or_none(payload.get("studentId")),
        department=_text_or_none(payload.get("department")),
        gender=_text_or_none(payload.get("gender")),
        emergency_phone=normalize_phone(payload.get("emergencyPhone")) or None,
        declared_depositor=_text_or_none(payload.get("declaredDepositor")),
        is_council_member=fee_class == FEE_MEMBER,
        is_staff=fee_class == FEE_STAFF,
        joins_afterparty=bool(payload.get("joinsAfterparty")),
        memo=_text_or_none(payload.get("memo")),
        # 폼이 아니라 관리자 화면에서 들어온 행이다. '신청 시각'은 등록한 때로 둔다.
        submitted_at=now_kst(),
    )
    participant.expected_amount = expected_amount_for(
        participant.is_council_member, participant.is_staff, participant.joins_afterparty
    )

    if payload.get("expectedAmount") is not None:
        amount = parse_amount(payload["expectedAmount"])
        if amount is None or amount < 0:
            return jsonify({"error": "invalid_amount", "message": "참가비를 확인해 주세요."}), 400
        participant.expected_amount = amount

    db.session.add(participant)
    try:
        db.session.flush()
    except IntegrityError:
        # 같은 번호가 동시에 들어온 경우
        db.session.rollback()
        return jsonify({
            "error": "duplicate_phone",
            "message": "이 번호는 이미 등록되어 있습니다.",
        }), 409

    changes = Changes()
    changes.note("등록", f"{name} · {mask_phone(phone)}")
    changes.note("요금 구분", _FEE_CLASS_LABELS[participant.fee_class])
    if participant.joins_afterparty:
        changes.note("뒤풀이", f"참가 (+{_won(participant.afterparty_fee)})")
    changes.note("참가비", _won(participant.expected_amount))

    write_audit(g.actor, "participant.create", "participant", participant.id, changes.detail(name))
    db.session.commit()

    # 이 사람 이름으로 이미 들어와 있던 입금이 미매칭으로 남아 있을 수 있다.
    # 폼 응답이 들어왔을 때와 같은 처리를 해 준다.
    rematch = rematch_deposits(only_unresolved=True)

    return jsonify({"participant": participant.to_admin_dict(), "rematch": rematch}), 201


@admin_bp.get("/participants/<int:participant_id>")
@require_admin
def get_participant(participant_id: int):
    participant = db.session.get(Participant, participant_id)
    if participant is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(participant.to_admin_dict())


@admin_bp.patch("/participants/<int:participant_id>")
@require_admin
def update_participant(participant_id: int):
    participant = db.session.get(Participant, participant_id)
    if participant is None:
        return jsonify({"error": "not_found"}), 404

    payload = request.get_json(silent=True) or {}
    changes = Changes()

    # --- 신청 정보 정정 ---
    #
    # 폼에 잘못 적어 내는 사람이 반드시 나온다 — 학번 칸에 생년월일, 이름 오타,
    # 번호 한 자리 누락. 원본 시트를 고쳐 다시 흘려보내는 길은 접수가 끝난 뒤엔
    # 막혀 있으므로 여기서 고칠 수 있어야 한다.
    #
    # 이름과 전화번호는 입금 매칭(name_norm)과 본인 확인(phone_last4)의 기준이라,
    # 고치면 파생값을 함께 맞추고 미매칭 입금을 다시 태운다.
    identity_changed = False

    if "name" in payload:
        name = str(payload["name"] or "").strip()
        if not name:
            return jsonify({"error": "invalid_name", "message": "이름을 비울 수 없습니다."}), 400
        changes.add("name", "이름", participant.name, name)
        identity_changed = identity_changed or name != participant.name
        participant.name = name
        participant.name_norm = normalize_name(name)

    if "phone" in payload:
        phone = normalize_phone(payload["phone"])
        if len(phone) < 10:
            return jsonify({
                "error": "invalid_phone",
                "message": "전화번호를 확인해 주세요. 숫자 10자리 이상이어야 합니다.",
            }), 400
        if phone != participant.phone:
            taken = (
                db.session.query(Participant)
                .filter(Participant.phone == phone, Participant.id != participant.id)
                .one_or_none()
            )
            if taken is not None:
                return jsonify({
                    "error": "duplicate_phone",
                    "message": f"이 번호는 이미 '{taken.name}' 님으로 등록되어 있습니다.",
                    "participantId": taken.id,
                }), 409
            identity_changed = True
        # 로그에는 가리지 않은 번호를 남긴다. 가리면 가운데 자리만 고친 정정이
        # '바뀐 것이 없다'로 보여 기록 자체가 사라진다.
        changes.add("phone", "전화번호", participant.phone, phone)
        participant.phone = phone
        participant.phone_last4 = phone_last4(phone)

    if "emergencyPhone" in payload:
        emergency = normalize_phone(payload["emergencyPhone"]) or None
        changes.add(
            "emergencyPhone", "비상 연락처",
            participant.emergency_phone or "(없음)", emergency or "(없음)",
        )
        participant.emergency_phone = emergency

    for key, column, label in (
        ("studentId", "student_id", "학번"),
        ("department", "department", "학과"),
        ("gender", "gender", "성별"),
    ):
        if key in payload:
            after = _text_or_none(payload[key])
            changes.add(key, label, getattr(participant, column) or "(없음)", after or "(없음)")
            setattr(participant, column, after)

    if "statusOverride" in payload:
        value = payload["statusOverride"]
        if value in (None, ""):
            after = None
        elif str(value).upper() in OVERRIDABLE_STATUSES:
            after = str(value).upper()
        else:
            return jsonify({"error": "invalid_status"}), 400
        changes.add(
            "statusOverride", "납입 상태 강제 지정",
            _PAYMENT_STATUS_LABELS.get(participant.status_override, "자동 (입금 기준)"),
            _PAYMENT_STATUS_LABELS.get(after, "자동 (입금 기준)"),
        )
        participant.status_override = after

    # 요금 구분은 총학생회비 납부 여부와 스태프 여부를 한 값으로 다룬다.
    # 화면의 드롭다운이 이것 하나만 보내면 되도록 하기 위함이다.
    fee_class = payload.get("feeClass")
    if fee_class is None and "isCouncilMember" in payload:
        fee_class = FEE_MEMBER if payload["isCouncilMember"] else FEE_NON_MEMBER

    if fee_class is not None:
        if fee_class not in FEE_CLASSES:
            return jsonify({"error": "invalid_fee_class"}), 400
        before_class, before_amount = participant.fee_class, participant.expected_amount

        participant.is_staff = fee_class == FEE_STAFF
        participant.is_council_member = fee_class == FEE_MEMBER
        participant.expected_amount = expected_amount_for(
            participant.is_council_member, participant.is_staff, participant.joins_afterparty
        )

        changes.add(
            "feeClass", "요금 구분",
            _FEE_CLASS_LABELS[before_class], _FEE_CLASS_LABELS[participant.fee_class],
        )
        changes.add(
            "expectedAmount", "참가비",
            _won(before_amount), _won(participant.expected_amount),
        )

    # 뒤풀이 참가 여부. 켜면 참가비에 뒤풀이비가 얹히고, 뒤풀이 회차의 출석 대상이 된다.
    # 끄면 그 자리의 출석 기록도 함께 지운다 — 대상이 아닌 사람이 명단에 남아 있으면
    # 출석률의 분모와 분자가 어긋난다.
    if "joinsAfterparty" in payload:
        want = bool(payload["joinsAfterparty"])
        if want != participant.joins_afterparty:
            before_amount = participant.expected_amount
            participant.joins_afterparty = want
            participant.expected_amount = expected_amount_for(
                participant.is_council_member, participant.is_staff, want
            )
            changes.add("joinsAfterparty", "뒤풀이 참가",
                        _yes_no(not want, "참가", "미참가"), _yes_no(want, "참가", "미참가"))
            changes.add("expectedAmount", "참가비",
                        _won(before_amount), _won(participant.expected_amount))
            if not want:
                for session in all_sessions():
                    if session.afterparty_only and cancel_checkin(session, participant):
                        changes.note("함께 지운 출석", session.label)

    if "expectedAmount" in payload:
        amount = parse_amount(payload["expectedAmount"])
        if amount is None or amount < 0:
            return jsonify({"error": "invalid_amount"}), 400
        changes.add("expectedAmount", "참가비", _won(participant.expected_amount), _won(amount))
        participant.expected_amount = amount

    if "isCancelled" in payload:
        want = bool(payload["isCancelled"])
        changes.add(
            "isCancelled", "참가 취소",
            _yes_no(participant.is_cancelled, "취소됨", "정상"),
            _yes_no(want, "취소됨", "정상"),
        )
        participant.is_cancelled = want
        if want and participant.confirmed_at is not None:
            # 취소된 사람이 확정 명단에 남아 있으면 조 편성과 출석률이 어긋난다.
            participant.confirmed_at = None
            participant.confirmed_by = None
            changes.add("isConfirmed", "참가 확정", "확정", "미확정 (취소에 따라 자동 해제)")

    if "isConfirmed" in payload:
        want = bool(payload["isConfirmed"])
        if want and not participant.is_settled:
            return jsonify({
                "error": "not_settled",
                "message": "납입이 완료된 참가자만 확정할 수 있습니다.",
            }), 400
        changes.add(
            "isConfirmed", "참가 확정",
            _yes_no(participant.is_confirmed, "확정", "미확정"),
            _yes_no(want, "확정", "미확정"),
        )
        participant.confirmed_at = now_kst() if want else None
        participant.confirmed_by = g.actor if want else None

    if "assignments" in payload:
        if not participant.is_confirmed:
            return jsonify({
                "error": "not_confirmed",
                "message": "참가가 확정된 사람에게만 배정할 수 있습니다.",
            }), 400
        labels = {field.key: field.label for field in active_fields()}
        before_values = participant.assignments
        try:
            applied = apply_assignments(participant, payload["assignments"])
        except AssignmentError as exc:
            return jsonify({"error": "invalid_assignment", "message": str(exc)}), 400
        for key, value in applied.items():
            changes.add(
                f"assignments.{key}", labels.get(key, key),
                before_values.get(key) or "미배정", value or "미배정",
            )

    if "isCheckedIn" in payload:
        # 현장 예외 처리용. 휴대폰이 없거나 QR 을 못 찍는 사람이 반드시 나온다.
        # 회차를 지정하지 않으면 본 행사다 (출석 탭의 수동 체크는 /attendance/check).
        session = _current_session()
        want = bool(payload["isCheckedIn"])
        if session is not None:
            changes.add(
                "isCheckedIn", f"{session.label} 출석",
                _yes_no(participant.checked_in_at, "도착", "미도착"),
                _yes_no(want, "도착 (스태프 처리)", "미도착"),
            )
            if want:
                record_checkin(session, participant, by=CHECKIN_STAFF, actor=g.actor)
            else:
                cancel_checkin(session, participant)

    if "nickname" in payload:
        nickname = _text_or_none(payload["nickname"])
        changes.add("nickname", "닉네임", participant.nickname or "(없음)", nickname or "(없음)")
        participant.nickname = nickname

    if "leaderPreference" in payload:
        value = payload["leaderPreference"]
        after = str(value).strip().lower() if value not in (None, "") else None
        if after is not None and after not in LEADER_PREFERENCES:
            return jsonify({"error": "invalid_leader_preference"}), 400
        changes.add(
            "leaderPreference", "조장 지원",
            _LEADER_LABELS.get(participant.leader_preference, "(없음)"),
            _LEADER_LABELS.get(after, "(없음)"),
        )
        participant.leader_preference = after

    if "memo" in payload:
        memo = str(payload["memo"] or "") or None
        changes.add("memo", "메모", participant.memo or "(없음)", memo or "(없음)")
        participant.memo = memo

    # 아무것도 달라지지 않았으면 로그를 남기지 않는다.
    if changes:
        write_audit(g.actor, "participant.update", "participant", participant.id,
                    changes.detail(participant.name))
    db.session.commit()

    # 이름 · 전화번호를 고쳤으면 매칭 근거가 달라진 것이다. 이름을 잘못 적어 내
    # 미매칭으로 남아 있던 입금이 이 정정으로 붙는다 — 폼이 늦게 도착했을 때와
    # 같은 처리다. 이미 확인 완료거나 손으로 고정한 건은 건드리지 않는다.
    if identity_changed:
        rematch_deposits(only_unresolved=True)

    # 럭키드로우 번호는 위의 커밋이 끝난 뒤에 발급한다. 번호가 부딪히면 되돌리고
    # 다시 시도하므로, 세션에 다른 변경이 남아 있는 동안 부르면 그것까지 날아간다.
    # (스태프가 대신 출석 처리한 사람도 셀프 체크인과 똑같이 번호를 받아야 한다)
    if participant.checked_in_at is not None:
        assign_draw_no(participant)

    return jsonify(participant.to_admin_dict())


@admin_bp.post("/participants/confirm")
@require_admin
def confirm_participants():
    """참가 확정 일괄 처리.

    participantIds 를 주면 그 사람들만, 없으면 '납입 완료 + 미확정' 전원을 확정한다.
    납입이 끝나지 않은 사람은 조용히 건너뛰고 몇 명이 걸러졌는지 돌려준다.
    """
    payload = request.get_json(silent=True) or {}
    raw_ids = payload.get("participantIds")

    if isinstance(raw_ids, list) and raw_ids:
        targets = [p for p in (db.session.get(Participant, int(i or 0)) for i in raw_ids) if p]
    else:
        targets = db.session.query(Participant).all()

    confirmed: list[str] = []
    skipped = 0
    for participant in targets:
        if participant.is_confirmed:
            continue
        if not participant.is_settled:
            skipped += 1
            continue
        participant.confirmed_at = now_kst()
        participant.confirmed_by = g.actor
        confirmed.append(participant.name)

    changes = Changes()
    changes.note("확정 처리", f"{len(confirmed)}명 — {', '.join(confirmed)}" if confirmed else "0명")
    if skipped:
        changes.note("건너뜀", f"납입 미완료 {skipped}명")

    write_audit(g.actor, "participant.confirm_bulk", None, None, changes.detail())
    db.session.commit()
    return jsonify({"confirmed": len(confirmed), "skipped": skipped})


@admin_bp.post("/staff-fee")
@require_admin
def update_staff_fee():
    """스태프 참가비를 정한다.

    금액이 늦게 정해지고 바뀔 수 있어 `.env` 가 아니라 여기서 고친다.
    고치면 **스태프 전원의 예상 금액이 함께 따라간다.** 한 명씩 다시 손보게 두면
    금액이 섞인 채로 남아 수납 집계가 어긋난다.
    """
    payload = request.get_json(silent=True) or {}
    amount = parse_amount(payload.get("amount"))
    if amount is None or amount < 0:
        return jsonify({"error": "invalid_amount", "message": "금액을 확인해 주세요."}), 400

    before = staff_fee()
    set_setting(SETTING_STAFF_FEE, str(amount))

    targets = [p for p in db.session.query(Participant).all() if p.is_staff]
    # 스태프도 뒤풀이에 가면 뒤풀이비가 얹히므로, 금액을 통째로 다시 계산한다.
    applied = recalc_expected_amounts(targets)

    changes = Changes()
    changes.add("staffFee", "스태프 참가비", _won(before), _won(amount))
    changes.note("반영 대상", f"스태프 {len(targets)}명 (금액이 달라진 사람 {applied}명)")

    write_audit(g.actor, "settings.staff_fee", None, None, changes.detail())
    db.session.commit()
    return jsonify({"amount": amount, "applied": len(targets)})


@admin_bp.post("/afterparty-fee")
@require_admin
def update_afterparty_fee():
    """뒤풀이 참가비를 정한다.

    스태프 참가비와 같은 이유로 `.env` 가 아니라 여기서 고친다. 고치면
    **뒤풀이 신청자 전원의 예상 금액이 함께 따라간다.** 한 명씩 다시 손보게 두면
    금액이 섞인 채로 남아 수납 집계가 어긋난다.

    이미 들어온 입금은 건드리지 않는다. 금액이 오르면 그만큼 뒤풀이비가 덜 찬
    것으로 보이고, 내리면 완납으로 바뀐다 — 파생값이라 자동으로 따라간다.
    """
    payload = request.get_json(silent=True) or {}
    amount = parse_amount(payload.get("amount"))
    if amount is None or amount < 0:
        return jsonify({"error": "invalid_amount", "message": "금액을 확인해 주세요."}), 400

    before = current_afterparty_fee()
    set_setting(SETTING_AFTERPARTY_FEE, str(amount))

    targets = [p for p in db.session.query(Participant).all() if p.joins_afterparty]
    applied = recalc_expected_amounts(targets)

    changes = Changes()
    changes.add("afterpartyFee", "뒤풀이 참가비", _won(before), _won(amount))
    changes.note("반영 대상", f"뒤풀이 신청자 {len(targets)}명 (금액이 달라진 사람 {applied}명)")

    write_audit(g.actor, "settings.afterparty_fee", None, None, changes.detail())
    db.session.commit()
    return jsonify({"amount": amount, "applied": len(targets)})


# --------------------------------------------------------------------------
# 배정 항목
# --------------------------------------------------------------------------

@admin_bp.get("/assignment-fields")
@require_admin
def list_assignment_fields():
    return jsonify({"items": [field.to_admin_dict() for field in all_fields()]})


@admin_bp.post("/assignment-fields")
@require_admin
def create_assignment_field():
    """배정 항목을 새로 만든다. 조·방·버스 외에 필요한 것이 생겼을 때 쓴다."""
    payload = request.get_json(silent=True) or {}
    label = str(payload.get("label") or "").strip()
    if not label:
        return jsonify({"error": "invalid_label", "message": "항목 이름을 입력해 주세요."}), 400

    kind = str(payload.get("kind") or AssignmentField.KIND_TEXT)
    if kind not in AssignmentField.KINDS:
        return jsonify({"error": "invalid_kind"}), 400

    try:
        options = normalize_options(payload.get("options"))
    except AssignmentError as exc:
        return jsonify({"error": "invalid_options", "message": str(exc)}), 400

    taken = {row.key for row in db.session.query(AssignmentField.key).all()}
    field = AssignmentField(
        key=make_key(label, taken),
        label=label[:60],
        kind=kind,
        options_json=json.dumps(options, ensure_ascii=False),
        position=next_position(),
        is_system=False,
        show_on_checkin=payload.get("showOnCheckin", True) is not False,
        is_active=True,
    )
    db.session.add(field)

    changes = Changes()
    changes.note("종류", "선택지에서 고르기" if kind == AssignmentField.KIND_CHOICE else "자유 입력")
    if options:
        changes.note("선택지", ", ".join(options))

    write_audit(g.actor, "assignment_field.create", "assignment_field", None,
                changes.detail(field.label))
    db.session.commit()
    return jsonify(field.to_admin_dict()), 201


@admin_bp.patch("/assignment-fields/<int:field_id>")
@require_admin
def update_assignment_field(field_id: int):
    """이름·선택지·표시 여부를 고친다. key 와 kind 는 만든 뒤에 바꾸지 않는다.

    (바꾸면 이미 배정된 값이 갈 곳을 잃는다)
    """
    field = db.session.get(AssignmentField, field_id)
    if field is None:
        return jsonify({"error": "not_found"}), 404

    payload = request.get_json(silent=True) or {}
    changes = Changes()
    original_label = field.label

    if "label" in payload:
        label = str(payload["label"] or "").strip()
        if not label:
            return jsonify({"error": "invalid_label"}), 400
        changes.add("label", "항목 이름", field.label, label[:60])
        field.label = label[:60]

    if "options" in payload:
        try:
            options = normalize_options(payload["options"])
        except AssignmentError as exc:
            return jsonify({"error": "invalid_options", "message": str(exc)}), 400
        # 이미 배정에 쓰이고 있는 값을 빼면 그 사람들의 배정이 유령이 된다.
        missing = sorted(values_in_use(field.key) - set(options))
        if missing:
            return jsonify({
                "error": "option_in_use",
                "message": f"이미 배정된 값이라 지울 수 없습니다: {', '.join(missing)}",
            }), 400
        changes.add(
            "options", "선택지",
            ", ".join(field.options) or "(없음)", ", ".join(options) or "(없음)",
        )
        field.options_json = json.dumps(options, ensure_ascii=False)

    if "showOnCheckin" in payload:
        want = bool(payload["showOnCheckin"])
        changes.add(
            "showOnCheckin", "체크인 화면 표시",
            _yes_no(field.show_on_checkin, "표시", "숨김"), _yes_no(want, "표시", "숨김"),
        )
        field.show_on_checkin = want

    if "isActive" in payload:
        if field.is_system and not payload["isActive"]:
            return jsonify({
                "error": "system_field",
                "message": "조 · 방 호수 · 버스는 끌 수 없습니다.",
            }), 400
        want = bool(payload["isActive"])
        changes.add("isActive", "사용 여부", _yes_no(field.is_active, "사용", "중지"),
                    _yes_no(want, "사용", "중지"))
        field.is_active = want

    if "position" in payload:
        position = int(payload["position"] or 0)
        changes.add("position", "표시 순서", str(field.position), str(position))
        field.position = position

    if changes:
        write_audit(g.actor, "assignment_field.update", "assignment_field", field.id,
                    changes.detail(original_label))
    db.session.commit()
    return jsonify(field.to_admin_dict())


@admin_bp.delete("/assignment-fields/<int:field_id>")
@require_admin
def delete_assignment_field(field_id: int):
    field = db.session.get(AssignmentField, field_id)
    if field is None:
        return jsonify({"error": "not_found"}), 404
    if field.is_system:
        return jsonify({
            "error": "system_field",
            "message": "조 · 방 호수 · 버스는 지울 수 없습니다.",
        }), 400

    cleared = drop_field_values(field.key)
    label = field.label
    db.session.delete(field)

    changes = Changes()
    changes.note("함께 지운 배정", f"{cleared}명")
    write_audit(g.actor, "assignment_field.delete", "assignment_field", field_id,
                changes.detail(label))
    db.session.commit()
    return jsonify({"ok": True, "clearedValues": cleared})


# --------------------------------------------------------------------------
# 배정 엑셀
# --------------------------------------------------------------------------
#
# 조 편성은 대개 엑셀에서 끝난다. 그 결과를 화면에서 한 명씩 다시 고르게 두면
# 편성을 두 번 하는 셈이라, 명단 그대로 내려받아 값만 채워 올리는 길을 둔다.
# 항목이 운영 중에 늘어나므로 양식도 그때의 정의를 보고 만든다.

def _confirmed_participants() -> list[Participant]:
    return [
        participant
        for participant in db.session.query(Participant).order_by(Participant.name.asc()).all()
        if participant.is_confirmed
    ]


@admin_bp.get("/assignments/template.xlsx")
@require_admin
def download_assignment_template():
    """지금 항목 정의와 확정자 명단으로 배정 양식을 만들어 내려준다."""
    fields = active_fields()
    participants = _confirmed_participants()
    data = build_template(fields, participants)

    changes = Changes()
    changes.note("담긴 인원", f"{len(participants)}명")
    changes.note("항목", ", ".join(field.label for field in fields) or "(없음)")
    write_audit(g.actor, "export.assignment_template", None, None, changes.detail())
    db.session.commit()

    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=assignments.xlsx"},
    )


def _find_participant(row, by_id: dict, by_student: dict, by_name: dict):
    """엑셀 한 행이 누구인지 찾는다. 반환: (참가자, 못 찾은 이유).

    참가자ID → 학번 → 이름 순으로 좁힌다. 뒤로 갈수록 흔들리는 값이라,
    **여럿에 걸리면 고르지 않고 건너뛴다.** 엉뚱한 사람을 조에 넣는 것보다
    한 줄 건너뛰고 알려 주는 편이 낫다.
    """
    if row.participant_id is not None:
        participant = by_id.get(row.participant_id)
        if participant is None:
            return None, f"참가자ID {row.participant_id} 를 명단에서 찾지 못했습니다"
        return participant, ""

    if row.student_id:
        found = by_student.get(normalize_student_id(row.student_id), [])
        if len(found) == 1:
            return found[0], ""
        if len(found) > 1:
            return None, f"학번 {row.student_id} 인 사람이 여럿입니다"

    if row.name:
        found = by_name.get(normalize_name(row.name), [])
        if len(found) == 1:
            return found[0], ""
        if len(found) > 1:
            return None, f"'{row.name}' 이름이 여럿입니다. 학번 열을 채워 주세요"

    return None, "명단에서 찾지 못했습니다 (참가자ID · 학번 · 이름을 확인해 주세요)"


@admin_bp.post("/assignments/import")
@require_admin
def import_assignments():
    """채워 온 배정 엑셀을 반영한다.

    빈 칸은 건드리지 않는다. 반쯤 채운 파일을 올렸다고 나머지 배정이 지워지면
    안 되기 때문이다. 배정을 푸는 것은 `-` 같은 표시를 적었을 때만 한다.
    """
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return jsonify({"error": "file_required", "message": "파일을 선택해 주세요."}), 400

    fields = active_fields()
    try:
        parsed = parse_assignment_sheet(uploaded.read(), uploaded.filename, fields)
    except ValueError as exc:
        return jsonify({"error": "parse_failed", "message": str(exc)}), 400

    by_id: dict[int, Participant] = {}
    by_student: dict[str, list[Participant]] = {}
    by_name: dict[str, list[Participant]] = {}
    for participant in db.session.query(Participant).all():
        by_id[participant.id] = participant
        if participant.student_id:
            by_student.setdefault(normalize_student_id(participant.student_id), []).append(participant)
        by_name.setdefault(participant.name_norm, []).append(participant)

    labels = {field.key: field.label for field in fields}
    changes = Changes()
    skipped = list(parsed.skipped)
    updated = 0
    unchanged = 0
    changed_values = 0

    for row in parsed.rows:
        participant, reason = _find_participant(row, by_id, by_student, by_name)
        if participant is None:
            skipped.append({"row": row.row_number, "reason": reason})
            continue
        if not participant.is_confirmed:
            skipped.append({
                "row": row.row_number,
                "reason": f"{participant.name} 님은 참가 확정 전이라 배정할 수 없습니다",
            })
            continue

        before = participant.assignments
        try:
            applied = apply_assignments(participant, row.values)
        except AssignmentError as exc:
            # 값 하나가 틀리면 그 행만 통째로 넘어간다 (apply_assignments 는
            # 중간에 멈춰도 참가자를 건드리지 않는다). 반쯤 반영된 행을 남기면
            # 무엇을 다시 채워야 하는지 알 수 없다.
            skipped.append({"row": row.row_number, "reason": str(exc)})
            continue

        if not applied:
            unchanged += 1
            continue

        updated += 1
        changed_values += len(applied)
        # 한 줄씩 participant.update 로 남기면 로그가 이 업로드 하나로 가득 찬다.
        # 대신 '누구의 무엇이 무엇에서 무엇으로' 를 이 기록 하나에 모은다.
        if len(changes.items) < _AUDIT_CHANGE_LIMIT:
            for key, value in applied.items():
                changes.add(
                    f"assignments.{key}",
                    f"{participant.name} · {labels.get(key, key)}",
                    before.get(key) or "미배정",
                    value or "미배정",
                )

    if changed_values > _AUDIT_CHANGE_LIMIT:
        changes.note("···", f"이 외 {changed_values - len(changes.items)}건은 줄여서 기록했습니다")
    changes.note("결과", f"반영 {updated}명 · 그대로 {unchanged}명 · 건너뜀 {len(skipped)}행")

    write_audit(g.actor, "assignment.import", None, None, changes.detail(uploaded.filename))
    db.session.commit()

    return jsonify({
        "filename": uploaded.filename,
        "rows": len(parsed.rows),
        "updated": updated,
        "unchanged": unchanged,
        "changedValues": changed_values,
        "fields": parsed.field_labels,
        "skipped": skipped[:50],
        "skippedCount": len(skipped),
    })


# --------------------------------------------------------------------------
# 개인 QR · 명찰 명단
# --------------------------------------------------------------------------
#
# 명찰 뒷면의 QR 이 가리키는 개인 카드(`/p/<token>`)와, 명찰 인쇄 화면이 쓰는
# 명단이다. 토큰은 명찰에 인쇄되어 목에 걸리므로 한 번 준 것은 바꾸지 않는다.

def _roster_row(participant: Participant) -> dict:
    return {
        "id": participant.id,
        "token": participant.card_token,
        "name": participant.name,
        "department": participant.department,
        "studentId": participant.student_id,
        # 명찰 앞면이 STAFF 띠로 갈릴지 GUEST 띠로 갈릴지를 이 값 하나가 정한다.
        "isStaff": participant.is_staff,
        "groupValue": participant.group_no,
        "joinsAfterparty": participant.joins_afterparty,
        # 솔로파티에서 부를 이름. 명찰에 실을지는 인쇄 화면이 정한다.
        "nickname": participant.nickname,
        "drawLabel": participant.draw_label,
    }


@admin_bp.get("/roster")
@require_admin
def badge_roster():
    """개인 토큰이 붙은 확정자 명단.

    명찰 인쇄가 여기서 이름 · 학과 · 조 · QR 주소를 가져간다.
    토큰이 없는 사람은 이 요청에서 발급된다.
    """
    participants = _confirmed_participants()
    issued = issue_tokens(participants)
    if issued:
        changes = Changes()
        changes.note("새 개인 QR", f"{issued}명")
        write_audit(g.actor, "card.issue_tokens", None, None, changes.detail())
        db.session.commit()

    return jsonify({
        "items": [_roster_row(participant) for participant in participants],
        "issued": issued,
        "cardLinkVisible": is_card_link_visible(),
        "generatedAt": to_iso(now_kst()),
    })


@admin_bp.post("/card-link")
@require_admin
def set_card_link():
    """체크인 완료 화면에 '내 QR 열기' 버튼을 보일지 정한다.

    명찰을 나눠 주기 전이라 헷갈릴 것 같을 때만 내린다. 기본은 보임이다.
    """
    payload = request.get_json(silent=True) or {}
    want = bool(payload.get("visible"))

    changes = Changes()
    changes.add("cardLink", "내 QR 열기 버튼",
                _yes_no(is_card_link_visible(), "보임", "숨김"),
                _yes_no(want, "보임", "숨김"))
    set_setting(SETTING_CARD_LINK, "1" if want else "0")

    write_audit(g.actor, "card.link", None, None, changes.detail())
    db.session.commit()
    return jsonify({"visible": want})


# --------------------------------------------------------------------------
# 출석
# --------------------------------------------------------------------------
#
# 회차가 둘이다 — 낮의 본 행사, 저녁의 뒤풀이. 왜 코드가 아니라 데이터로 두는지는
# app/attendance.py 의 머리말에 적어 두었다.
#
# 들어오는 길도 둘이다. 인원이 많은 본 행사는 참가자가 직접 찍는 **셀프 체크인**,
# 인원이 적고 자리가 어수선한 뒤풀이는 관리자가 명단에서 누르는 **수동 체크**.
# 어느 회차든 두 길이 모두 열려 있고, 수동 체크는 창구가 닫혀 있어도 된다.

def _rate(part: int, whole: int) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def _attendance_row(
    participant: Participant,
    group_key: str | None,
    at: object = None,
    by: str | None = None,
) -> dict:
    return {
        "id": participant.id,
        "name": participant.name,
        # 미도착자에게 전화를 돌려야 하므로 번호를 가리지 않는다 (관리자 인증 뒤다).
        "phone": participant.phone,
        "department": participant.department,
        "studentId": participant.student_id,
        "groupValue": participant.assignments.get(group_key) if group_key else None,
        "checkedInAt": to_iso(at),
        "checkedInBy": by,
        "joinsAfterparty": participant.joins_afterparty,
        "afterpartyStatus": participant.afterparty_status,
        # 현장에서 "내 번호가 뭐냐"는 질문이 반드시 나온다.
        "drawLabel": participant.draw_label,
    }


def _session_key(label: str, taken: set[str]) -> str:
    """회차 라벨에서 key 를 만든다. 한글은 ASCII 로 옮길 방법이 없어 번호로 떨어뜨린다."""
    base = re.sub(r"[^a-z0-9_]", "", str(label or "").strip().lower().replace(" ", "_")).strip("_")
    if base and base not in taken:
        return base[:40]
    index = 1
    while f"session_{index}" in taken:
        index += 1
    return f"session_{index}"


def _current_session() -> CheckinSession | None:
    """요청이 가리키는 회차. 지정하지 않으면 본 행사."""
    ensure_default_sessions()
    requested = (request.args.get("session") or "").strip()
    if not requested:
        payload = request.get_json(silent=True) if request.method != "GET" else None
        requested = str((payload or {}).get("session") or "").strip()
    return session_by_key(requested) if requested else main_session()


@admin_bp.get("/checkin-sessions")
@require_admin
def list_checkin_sessions():
    ensure_default_sessions()
    return jsonify({"items": [row.to_admin_dict() for row in all_sessions()]})


@admin_bp.post("/checkin-sessions")
@require_admin
def create_checkin_session():
    """회차를 하나 더 만든다 (2부, 뒤풀이 2차 …)."""
    payload = request.get_json(silent=True) or {}
    label = str(payload.get("label") or "").strip()[:60]
    if not label:
        return jsonify({"error": "invalid_label", "message": "회차 이름을 입력해 주세요."}), 400

    key = _session_key(payload.get("key") or label, {row.key for row in all_sessions()})
    session = CheckinSession(
        key=key,
        label=label,
        position=(max([row.position for row in all_sessions()], default=0) + 10),
        is_open=False,
        afterparty_only=bool(payload.get("afterpartyOnly")),
        # 번호를 매기는 회차는 하나뿐이다. 새로 만든 회차가 가져가면 참가자가
        # 번호를 두 개 외워야 하므로 여기서는 늘 꺼진 채로 만든다.
        gives_draw_no=False,
        is_system=False,
        is_active=True,
    )
    db.session.add(session)

    changes = Changes()
    changes.note("회차 추가", label)
    if session.afterparty_only:
        changes.note("대상", "뒤풀이 신청자만")
    write_audit(g.actor, "checkin.session_create", None, None, changes.detail(label))
    db.session.commit()
    return jsonify(session.to_admin_dict()), 201


@admin_bp.patch("/checkin-sessions/<int:session_id>")
@require_admin
def update_checkin_session(session_id: int):
    """회차의 이름 · 창구 개폐 · 대상 범위를 고친다.

    창구를 여닫는 것이 행사 당일 가장 자주 쓰는 조작이다. QR 인쇄물은 며칠 전부터
    돌아다니므로 기본은 닫힘이고, 집결 시각에 스태프가 연다.
    """
    session = db.session.get(CheckinSession, session_id)
    if session is None:
        return jsonify({"error": "not_found"}), 404

    payload = request.get_json(silent=True) or {}
    changes = Changes()

    if "label" in payload:
        label = str(payload["label"] or "").strip()[:60]
        if not label:
            return jsonify({"error": "invalid_label"}), 400
        changes.add("label", "회차 이름", session.label, label)
        session.label = label

    if "isOpen" in payload:
        want = bool(payload["isOpen"])
        changes.add("isOpen", f"{session.label} 셀프 체크인 창구",
                    _yes_no(session.is_open, "열림", "닫힘"),
                    _yes_no(want, "열림", "닫힘"))
        if want:
            # 참가자는 회차를 고르지 않는다 — 같은 입구 QR 로 들어와 '지금 열린'
            # 회차에 찍힌다. 둘이 동시에 열려 있으면 어디에 찍힌 것인지 알 수 없다.
            for other in all_sessions():
                if other.id != session.id and other.is_open:
                    other.is_open = False
                    changes.note("함께 닫음", other.label)
        session.is_open = want

    if "afterpartyOnly" in payload:
        want = bool(payload["afterpartyOnly"])
        changes.add("afterpartyOnly", f"{session.label} 대상",
                    _yes_no(session.afterparty_only, "뒤풀이 신청자만", "확정자 전체"),
                    _yes_no(want, "뒤풀이 신청자만", "확정자 전체"))
        session.afterparty_only = want

    if "isActive" in payload:
        want = bool(payload["isActive"])
        if session.is_system and not want:
            return jsonify({
                "error": "system_session",
                "message": "본 행사 회차는 끌 수 없습니다.",
            }), 400
        changes.add("isActive", f"{session.label} 사용",
                    _yes_no(session.is_active, "사용", "미사용"),
                    _yes_no(want, "사용", "미사용"))
        session.is_active = want

    if changes:
        write_audit(g.actor, "checkin.session_update", None, None, changes.detail(session.label))
    db.session.commit()
    return jsonify(session.to_admin_dict())


@admin_bp.delete("/checkin-sessions/<int:session_id>")
@require_admin
def delete_checkin_session(session_id: int):
    session = db.session.get(CheckinSession, session_id)
    if session is None:
        return jsonify({"error": "not_found"}), 404
    if session.is_system:
        return jsonify({
            "error": "system_session",
            "message": "본 행사 회차는 지울 수 없습니다.",
        }), 400

    taken = len(checked_in_ids(session))
    if taken and not (request.args.get("force") or "").strip().lower() == "true":
        return jsonify({
            "error": "in_use",
            "message": f"이미 {taken}명이 출석한 회차입니다. 지우면 기록도 함께 사라집니다.",
            "count": taken,
        }), 409

    changes = Changes()
    changes.note("회차 삭제", session.label)
    if taken:
        changes.note("함께 지운 출석", f"{taken}건")
    label = session.label
    db.session.delete(session)

    write_audit(g.actor, "checkin.session_delete", None, None, changes.detail(label))
    db.session.commit()
    return jsonify({"ok": True})


@admin_bp.get("/attendance")
@require_admin
def attendance():
    """한 회차의 출석 현황.

    분모는 '참가 확정자'다. 확정되지 않은 사람은 체크인 자체가 막혀 있어
    전체 신청자를 분모로 잡으면 출석률이 영원히 100%에 닿지 않는다.
    뒤풀이 회차는 분모가 한 번 더 좁아진다 — 뒤풀이를 신청한 사람만이다.
    groupBy 로 조 등 어떤 배정 항목 기준으로든 쪼개 볼 수 있다.
    """
    session = _current_session()
    if session is None:
        return jsonify({"error": "no_session", "message": "출석 회차가 없습니다."}), 404

    fields = active_fields()
    by_key = {field.key: field for field in fields}
    requested = (request.args.get("groupBy") or "").strip()
    group_field = by_key.get(requested) or by_key.get(DEFAULT_GROUP_KEY) or (fields[0] if fields else None)
    group_key = group_field.key if group_field else None

    participants = db.session.query(Participant).order_by(Participant.name.asc()).all()
    targets = [p for p in participants if p.is_confirmed and eligible_for(session, p)]

    rows = {
        row.participant_id: row
        for row in db.session.query(CheckIn).filter(CheckIn.session_id == session.id).all()
    }
    checked_in = [p for p in targets if p.id in rows]
    not_checked_in = [p for p in targets if p.id not in rows]

    buckets: dict[str | None, dict] = {}
    for participant in targets:
        value = (participant.assignments.get(group_key) if group_key else None) or None
        bucket = buckets.setdefault(value, {"confirmed": 0, "checkedIn": 0})
        bucket["confirmed"] += 1
        if participant.id in rows:
            bucket["checkedIn"] += 1

    # 선택지 순서를 그대로 따르고, 목록에 없는 값과 미배정은 뒤로 보낸다.
    ordered = [value for value in (group_field.options if group_field else []) if value in buckets]
    ordered += sorted(v for v in buckets if v is not None and v not in ordered)
    if None in buckets:
        ordered.append(None)

    groups = [
        {
            "value": value,
            "label": value or "미배정",
            "confirmed": buckets[value]["confirmed"],
            "checkedIn": buckets[value]["checkedIn"],
            "notCheckedIn": buckets[value]["confirmed"] - buckets[value]["checkedIn"],
            "rate": _rate(buckets[value]["checkedIn"], buckets[value]["confirmed"]),
        }
        for value in ordered
    ]

    checked_in.sort(key=lambda p: rows[p.id].at, reverse=True)

    return jsonify({
        "session": session.to_admin_dict(),
        "sessions": [row.to_admin_dict() for row in active_sessions()],
        "open": session.is_open,
        "overall": {
            "applicants": len([p for p in participants if not p.is_cancelled]),
            "confirmed": len(targets),
            "checkedIn": len(checked_in),
            "notCheckedIn": len(not_checked_in),
            "rate": _rate(len(checked_in), len(targets)),
        },
        "groupBy": {"key": group_key, "label": group_field.label if group_field else None},
        "fields": [{"key": f.key, "label": f.label} for f in fields],
        "groups": groups,
        "checkedIn": [
            _attendance_row(p, group_key, rows[p.id].at, rows[p.id].by) for p in checked_in
        ],
        "notCheckedIn": [_attendance_row(p, group_key) for p in not_checked_in],
        "generatedAt": to_iso(now_kst()),
    })


@admin_bp.post("/attendance/check")
@require_admin
def manual_checkin():
    """관리자가 명단에서 눌러 출석을 남기거나 지운다.

    뒤풀이는 인원이 적고 자리가 어수선해 QR 을 세우는 것보다 이쪽이 빠르다.
    본 행사에서도 폰이 없거나 QR 을 못 찍는 사람에게 쓴다.
    **창구가 닫혀 있어도 된다** — 사람이 직접 확인하고 누르는 것이기 때문이다.
    """
    session = _current_session()
    if session is None:
        return jsonify({"error": "no_session", "message": "출석 회차가 없습니다."}), 404

    payload = request.get_json(silent=True) or {}
    participant = db.session.get(Participant, int(payload.get("participantId") or 0))
    if participant is None:
        return jsonify({"error": "not_found"}), 404

    want = bool(payload.get("present", True))

    if want:
        if participant.is_cancelled:
            return jsonify({
                "error": "cancelled",
                "message": "참가 취소로 처리된 사람입니다.",
            }), 400
        if not participant.is_confirmed:
            return jsonify({
                "error": "not_confirmed",
                "message": "참가가 확정된 사람만 출석 처리할 수 있습니다.",
            }), 400
        if not eligible_for(session, participant):
            return jsonify({
                "error": "not_in_session",
                "message": f"{participant.name} 님은 뒤풀이 신청자가 아닙니다. "
                           "참가자 탭에서 뒤풀이 참가로 바꾼 뒤 다시 시도해 주세요.",
            }), 400
        row, created = record_checkin(
            session, participant, by=CHECKIN_STAFF, actor=g.actor
        )
        changed = created
    else:
        changed = cancel_checkin(session, participant)
        row = None

    if changed:
        changes = Changes()
        changes.add(
            "isCheckedIn", f"{session.label} 출석",
            _yes_no(not want, "도착", "미도착"),
            _yes_no(want, "도착 (스태프 처리)", "미도착"),
        )
        write_audit(g.actor, "checkin.manual", "participant", participant.id,
                    changes.detail(participant.name))
    db.session.commit()

    # 럭키드로우 번호는 커밋한 뒤에 발급한다. 번호가 부딪히면 되돌리고 다시
    # 시도하는데, 그 rollback 이 출석 기록까지 지워서는 안 된다.
    # (스태프가 대신 처리한 사람도 셀프 체크인과 똑같이 번호를 받아야 한다)
    if want and session.gives_draw_no:
        assign_draw_no(participant)
        db.session.commit()

    return jsonify({
        "ok": True,
        "changed": changed,
        "participantId": participant.id,
        "checkedInAt": to_iso(row.at) if row else None,
        "drawLabel": participant.draw_label,
    })


@admin_bp.post("/checkin-window")
@require_admin
def set_checkin_window():
    """체크인 창구를 열고 닫는다 (회차를 지정하지 않으면 본 행사).

    회차 PATCH 로도 되지만, 당일 가장 자주 쓰는 조작이라 짧은 길을 따로 둔다.
    """
    session = _current_session()
    if session is None:
        return jsonify({"error": "no_session", "message": "출석 회차가 없습니다."}), 404

    payload = request.get_json(silent=True) or {}
    want = bool(payload.get("open"))

    changes = Changes()
    changes.add("open", f"{session.label} 셀프 체크인 창구",
                _yes_no(session.is_open, "열림", "닫힘"),
                _yes_no(want, "열림", "닫힘"))
    if want:
        for other in all_sessions():
            if other.id != session.id and other.is_open:
                other.is_open = False
                changes.note("함께 닫음", other.label)
    session.is_open = want

    write_audit(g.actor, "checkin.window", None, None, changes.detail(session.label))
    db.session.commit()
    return jsonify({"open": want, "session": session.to_admin_dict()})


# --------------------------------------------------------------------------
# 럭키드로우
# --------------------------------------------------------------------------

def _draw_group_key() -> str | None:
    """당첨자를 부를 때 함께 보여줄 배정 항목 (기본은 조)."""
    fields = active_fields()
    by_key = {field.key: field for field in fields}
    field = by_key.get(DEFAULT_GROUP_KEY) or (fields[0] if fields else None)
    return field.key if field else None


def _draw_options() -> tuple[bool, bool, str | None]:
    """추첨 조건. 스태프 제외 · 중복 당첨 허용 · 후보를 좁힐 출석 회차.

    `poolSession` 은 뒤풀이 추첨을 위한 것이다. 번호는 본 행사 체크인 순서로만
    주지만(그래야 참가자가 번호 하나만 외운다), 뒤풀이 자리에서 뽑을 때 낮에만
    왔던 사람이 당첨되면 상품을 줄 사람이 없다. 그래서 번호는 그대로 두고
    **그 자리에 출석한 사람으로 후보를 좁힌다.**
    """
    exclude_staff = (request.args.get("excludeStaff") or "").strip().lower() == "true"
    allow_repeat = (request.args.get("allowRepeat") or "").strip().lower() == "true"
    pool_session = (request.args.get("poolSession") or "").strip() or None
    if request.method != "GET":
        payload = request.get_json(silent=True) or {}
        exclude_staff = bool(payload.get("excludeStaff", exclude_staff))
        allow_repeat = bool(payload.get("allowRepeat", allow_repeat))
        if "poolSession" in payload:
            pool_session = str(payload.get("poolSession") or "").strip() or None
    return exclude_staff, allow_repeat, pool_session


def _draw_state(exclude_staff: bool, allow_repeat: bool, pool_session: str | None = None) -> dict:
    """추첨 화면이 필요한 것 전부.

    번호 타일에는 **번호만 담는다.** 이름을 함께 내리면 스크린에 명단이 뜨는 셈이고,
    개발자 도구를 열지 않아도 누가 후보인지 드러난다.
    """
    ensure_default_sessions()
    issued = issued_participants()
    won_ids = won_participant_ids()
    present = present_ids_for(pool_session)

    tiles = []
    for participant in issued:
        reason = out_reason(
            participant, won_ids,
            exclude_staff=exclude_staff, allow_repeat=allow_repeat, present_ids=present,
        )
        tiles.append({
            "no": participant.draw_no,
            "label": participant.draw_label,
            "eligible": reason is None,
            "out": reason,
        })

    group_key = _draw_group_key()
    history = (
        db.session.query(LuckyDraw)
        .order_by(LuckyDraw.drawn_at.desc(), LuckyDraw.id.desc())
        .all()
    )

    return {
        "digits": draw_digits([p.draw_no for p in issued if p.draw_no]),
        "prizes": prize_view(),
        "counts": {
            "issued": len(issued),
            "eligible": sum(1 for tile in tiles if tile["eligible"]),
            "checkedIn": sum(1 for p in issued if p.checked_in_at is not None),
            "present": len(present) if present is not None else None,
            "staff": sum(1 for p in issued if p.is_staff),
            "won": len(won_ids),
        },
        "options": {
            "excludeStaff": exclude_staff,
            "allowRepeat": allow_repeat,
            "poolSession": pool_session,
        },
        # 어느 자리에서 뽑는지 고를 수 있게 회차 목록을 함께 준다.
        "sessions": [row.to_admin_dict() for row in active_sessions()],
        "nextRoundNo": next_round_no(),
        "pool": tiles,
        "history": [entry.to_admin_dict(group_key) for entry in history],
    }


@admin_bp.get("/draw")
@require_admin
def draw_state():
    """추첨 화면의 현재 상태. 번호 타일 · 후보 수 · 당첨 이력."""
    exclude_staff, allow_repeat, pool_session = _draw_options()
    return jsonify(_draw_state(exclude_staff, allow_repeat, pool_session))


@admin_bp.put("/draw/prizes")
@require_admin
def update_prizes():
    """상품 목록을 통째로 갈아끼운다.

    행사 전에 미리 등록해 두고 당일에는 고르기만 하도록 하기 위한 것이다.
    진행자가 회차마다 이름을 타이핑하게 두면 '1등 에어팟'과 '1등에어팟'이 섞여
    남은 수량 집계가 어긋난다.

    이미 나간 당첨 기록은 건드리지 않는다. 상품을 목록에서 지워도 그때 무엇을
    걸었는지는 `lucky_draws.prize` 에 이름 그대로 남아 있다.
    """
    payload = request.get_json(silent=True) or {}
    before = [f"{p['label']}×{p['count']}" for p in prize_view()]
    prizes = save_prizes(payload.get("prizes"))
    after = [f"{p['label']}×{p['count']}" for p in prizes]

    if before != after:
        changes = Changes()
        changes.add("prizes", "럭키드로우 상품", ", ".join(before) or "(없음)",
                    ", ".join(after) or "(없음)")
        write_audit(g.actor, "draw.prizes", None, None, changes.detail())
    db.session.commit()

    exclude_staff, allow_repeat, pool_session = _draw_options()
    return jsonify({"ok": True, "state": _draw_state(exclude_staff, allow_repeat, pool_session)})


@admin_bp.post("/draw")
@require_admin
def create_draw():
    """한 명을 뽑는다.

    뽑는 순간 결과가 DB 에 박힌다. 화면의 슬롯머신은 이 결과를 자릿수별로
    드러내는 연출이므로, '돌려 보고 마음에 안 들면 다시' 가 성립하지 않는다.
    자리에 없는 사람이 뽑혔다면 무효 처리(POST /draw/<id>/void)를 남기고 다시 뽑는다.
    """
    exclude_staff, allow_repeat, pool_session = _draw_options()
    payload = request.get_json(silent=True) or {}
    prize = str(payload.get("prize") or "").strip()

    # 등록된 상품을 골랐다면 이름은 서버가 정한다. 화면이 보낸 문자열을 그대로
    # 믿으면 목록과 어긋난 이름이 기록되어 남은 수량이 맞지 않게 된다.
    prize_id = str(payload.get("prizeId") or "").strip() or None
    if prize_id:
        chosen = find_prize(prize_id)
        if chosen is None:
            return jsonify({
                "error": "unknown_prize",
                "message": "등록되지 않은 상품입니다. 목록을 새로 불러와 주세요.",
            }), 400
        if chosen["remaining"] <= 0:
            return jsonify({
                "error": "prize_exhausted",
                "message": f"'{chosen['label']}' 은 준비된 {chosen['count']}개가 모두 나갔습니다.",
            }), 400
        prize = chosen["label"]

    # 애니메이션은 '뽑기 전' 후보 판을 기준으로 돌아야 한다. 뽑은 뒤의 판을 주면
    # 당첨자 타일이 이미 '당첨됨'으로 흐려진 상태에서 그 번호가 나오게 된다.
    pool_before = _draw_state(exclude_staff, allow_repeat, pool_session)

    entry = run_draw(
        prize=prize, prize_id=prize_id, actor=g.actor,
        exclude_staff=exclude_staff, allow_repeat=allow_repeat, pool_session=pool_session,
    )
    if entry is None:
        return jsonify({
            "ok": False,
            "error": "empty_pool",
            "message": (
                "추첨할 후보가 없습니다. 체크인한 사람이 있어야 번호가 발급됩니다."
                if pool_before["counts"]["issued"] == 0
                else "남은 후보가 없습니다. 중복 당첨을 허용하거나 조건을 풀어 주세요."
            ),
            "state": pool_before,
        }), 400

    changes = Changes()
    changes.note("회차", f"{entry.round_no}회")
    if entry.prize:
        changes.note("상품", entry.prize)
    changes.note("당첨 번호", entry.draw_label)
    changes.note("후보 수", f"{entry.pool_size}명")
    write_audit(g.actor, "draw.create", "lucky_draw", entry.id,
                changes.detail(entry.participant.name if entry.participant else None))
    db.session.commit()

    return jsonify({
        "ok": True,
        "draw": entry.to_admin_dict(_draw_group_key()),
        # 연출에 쓰는 판. 당첨 번호가 아직 후보로 남아 있는 상태다.
        "state": pool_before,
    })


@admin_bp.post("/draw/<int:draw_id>/void")
@require_admin
def void_draw(draw_id: int):
    """당첨을 무효로 돌린다 (당첨자가 자리에 없는 경우 등).

    행을 지우지 않고 표시만 남긴다. 누가 언제 무효로 했는지가 보여야 뒷말이 없다.
    무효가 되면 그 사람은 다시 후보로 돌아오고, 회차 번호도 비워진다.
    """
    entry = db.session.get(LuckyDraw, draw_id)
    if entry is None:
        return jsonify({"error": "not_found"}), 404
    if entry.voided:
        return jsonify({"error": "already_voided", "message": "이미 무효 처리된 건입니다."}), 400

    payload = request.get_json(silent=True) or {}
    reason = str(payload.get("reason") or "").strip()[:200] or "사유 미기재"

    entry.voided = True
    entry.voided_reason = reason

    changes = Changes()
    changes.note("무효 처리", f"{entry.round_no}회 · {entry.draw_label}")
    changes.note("사유", reason)
    write_audit(g.actor, "draw.void", "lucky_draw", entry.id,
                changes.detail(entry.participant.name if entry.participant else None))
    db.session.commit()

    exclude_staff, allow_repeat, pool_session = _draw_options()
    return jsonify({"ok": True, "state": _draw_state(exclude_staff, allow_repeat, pool_session)})


@admin_bp.delete("/draw")
@require_admin
def clear_draws():
    """당첨 기록을 전부 지운다.

    시연으로 몇 번 돌려 본 뒤 진짜 추첨을 시작하기 위한 것이다. 무효 처리로는
    안 된다 — 무효는 '이런 일이 있었고 취소했다'를 남기는 것이라, 시연 흔적이
    이력에 그대로 쌓인 채 본 추첨이 시작된다.

    **되돌릴 수 없다.** 대신 무엇을 지웠는지는 감사 로그에 남는다. 기록을 지운
    행위 자체가 기록의 일부이고, 그것까지 지울 수 있으면 이력이 의미를 잃는다.

    번호(`participants.draw_no`)는 건드리지 않는다. 번호는 체크인의 부산물이라
    출석 기록과 함께 있어야 한다. 여기서 같이 지우면 '체크인은 되어 있는데
    번호가 없는' 상태가 되어, 자기 번호를 이미 본 사람과 어긋난다.
    """
    exclude_staff, allow_repeat, pool_session = _draw_options()
    entries = db.session.query(LuckyDraw).order_by(LuckyDraw.id.asc()).all()

    if not entries:
        return jsonify({
            "ok": True,
            "deleted": 0,
            "state": _draw_state(exclude_staff, allow_repeat, pool_session),
        })

    # 지운 내용을 로그에 알아볼 수 있게 남긴다. 건수가 많으면 앞쪽만 적는다.
    listed = [
        f"{entry.round_no}회 {entry.draw_label}"
        f"{' ' + entry.participant.name if entry.participant else ''}"
        f"{' (무효)' if entry.voided else ''}"
        for entry in entries[:20]
    ]
    if len(entries) > len(listed):
        listed.append(f"외 {len(entries) - len(listed)}건")

    deleted = len(entries)
    for entry in entries:
        db.session.delete(entry)

    changes = Changes()
    changes.note("지운 당첨 기록", f"{deleted}건")
    changes.note("내용", " / ".join(listed))
    write_audit(g.actor, "draw.clear", None, None, changes.detail())
    db.session.commit()

    return jsonify({
        "ok": True,
        "deleted": deleted,
        "state": _draw_state(exclude_staff, allow_repeat, pool_session),
    })


# --------------------------------------------------------------------------
# 입금
# --------------------------------------------------------------------------

@admin_bp.get("/deposits")
@require_admin
def list_deposits():
    status = (request.args.get("status") or "").strip().upper()
    query = (request.args.get("query") or "").strip()

    stmt = db.session.query(Deposit)
    if status == "REVIEW":
        # 확인 필요 큐에는 기타 입금을 넣지 않는다
        stmt = stmt.filter(Deposit.status.in_([DEP_UNMATCHED, DEP_AMBIGUOUS]))
    elif status:
        stmt = stmt.filter(Deposit.status == status)
    if query:
        needle = normalize_name(query)
        if needle:
            stmt = stmt.filter(Deposit.name_norm.contains(needle))
        else:
            amount = parse_amount(query)
            if amount is not None:
                stmt = stmt.filter(Deposit.amount == amount)

    deposits = stmt.order_by(Deposit.occurred_at.desc(), Deposit.id.desc()).all()
    page_items, meta = _paginate(
        deposits,
        int(request.args.get("page", 1) or 1),
        int(request.args.get("pageSize", 50) or 50),
    )
    return jsonify({"items": [d.to_admin_dict() for d in page_items], "pagination": meta})


@admin_bp.post("/deposits")
@require_admin
def create_deposit():
    """수기 입금 등록 (알림 누락분 보정용)."""
    payload = request.get_json(silent=True) or {}
    amount = parse_amount(payload.get("amount"))
    if amount is None or amount <= 0:
        return jsonify({"error": "invalid_amount", "message": "금액을 확인해 주세요."}), 400

    occurred_at = parse_datetime(payload.get("occurredAt")) or now_kst()
    deposit, created = register_deposit(
        occurred_at=occurred_at,
        amount=amount,
        balance_after=parse_amount(payload.get("balanceAfter")),
        raw_name=str(payload.get("rawName") or "").strip(),
        source=SRC_MANUAL,
        raw_payload={"enteredBy": g.actor, "memo": payload.get("memo")},
    )
    if payload.get("memo"):
        deposit.memo = str(payload["memo"])

    changes = Changes()
    changes.note("금액", _won(amount))
    changes.note("결과", "새 입금으로 등록" if created else "이미 있는 입금 (지문 일치)")

    write_audit(g.actor, "deposit.create", "deposit", deposit.id,
                changes.detail(deposit.raw_name or "이름 없음"))
    db.session.commit()
    return jsonify({"created": created, "deposit": deposit.to_admin_dict()}), 201 if created else 200


@admin_bp.post("/participants/<int:participant_id>/onsite-payment")
@require_admin
def onsite_payment(participant_id: int):
    """행사 당일 접수대에서 현금·간편송금으로 받은 참가비를 넣는다.

    당일 행사라 미납자가 문 앞에서 내는 일이 반드시 생긴다. 그때 계좌로 다시
    보내게 하면 거래내역 파일을 또 내려받아 올릴 때까지 확정이 열리지 않아
    줄이 선다. 그래서 **받은 즉시 이 자리에서 입금 1건으로 남긴다.**

    거래내역 업로드로 들어온 것과 같은 테이블에 들어가되 출처(`SRC_ONSITE`)가
    달라, 정산할 때 '계좌로 들어온 돈'과 '손에 쥔 현금'을 갈라 볼 수 있다.
    금액을 비워 두면 아직 안 낸 만큼을 그대로 채운다.
    """
    participant = db.session.get(Participant, participant_id)
    if participant is None:
        return jsonify({"error": "not_found"}), 404
    if participant.is_cancelled:
        return jsonify({
            "error": "cancelled",
            "message": "참가 취소로 처리된 사람입니다.",
        }), 400

    payload = request.get_json(silent=True) or {}
    remaining = max(participant.expected_amount - participant.paid_amount, 0)
    amount = parse_amount(payload.get("amount"))
    if amount is None:
        amount = remaining
    if amount <= 0:
        return jsonify({
            "error": "invalid_amount",
            "message": "받을 금액이 없습니다. 금액을 직접 입력해 주세요.",
        }), 400

    method = str(payload.get("method") or "현금").strip()[:20]
    occurred_at = now_kst()

    # 지문은 (시각, 금액, 잔액)/(시각, 금액, 이름)으로 만들어진다. 현장 납부는
    # 계좌를 거치지 않아 잔액이 없고, 같은 사람이 같은 금액을 두 번 낼 일도
    # 드물지만, 접수대에서 두 번 눌리는 사고는 흔하다. 그래서 이름에 참가자
    # 번호를 박아 사람이 다르면 지문도 확실히 갈리게 한다.
    deposit, created = register_deposit(
        occurred_at=occurred_at,
        amount=amount,
        balance_after=None,
        raw_name=f"{participant.name}(현장{participant.id})",
        name_norm=participant.name_norm,
        digit_suffix=participant.phone_last4 or "",
        source=SRC_ONSITE,
        raw_payload={
            "onsite": True,
            "method": method,
            "participantId": participant.id,
            "receivedBy": g.actor,
        },
        # 자동 매칭에 태우지 않는다. 누구에게서 받았는지 이미 알고 있다.
        run_match=False,
    )
    if not created:
        return jsonify({
            "error": "duplicate",
            "message": "방금 같은 금액이 이미 등록되었습니다. 입금 내역에서 확인해 주세요.",
            "depositId": deposit.id,
        }), 409

    deposit.status = DEP_MATCHED
    deposit.manual_locked = True
    deposit.match_reason = f"현장 납부 · {method} · {g.actor}"
    deposit.memo = str(payload.get("memo") or "").strip() or None
    db.session.add(
        Allocation(
            deposit_id=deposit.id,
            participant_id=participant.id,
            amount=amount,
            created_by=g.actor,
        )
    )
    db.session.flush()

    changes = Changes()
    changes.note("현장 납부", f"{_won(amount)} · {method}")
    changes.note("납입 상태", _PAYMENT_STATUS_LABELS.get(participant.payment_status, "?"))
    write_audit(g.actor, "deposit.onsite", "participant", participant.id,
                changes.detail(participant.name))
    db.session.commit()

    return jsonify({
        "ok": True,
        "amount": amount,
        "deposit": deposit.to_admin_dict(),
        "participant": participant.to_admin_dict(),
    }), 201


@admin_bp.patch("/deposits/<int:deposit_id>")
@require_admin
def update_deposit(deposit_id: int):
    deposit = db.session.get(Deposit, deposit_id)
    if deposit is None:
        return jsonify({"error": "not_found"}), 404

    payload = request.get_json(silent=True) or {}
    changes = Changes()
    name_changed = False

    if "memo" in payload:
        memo = str(payload["memo"] or "") or None
        changes.add("memo", "메모", deposit.memo or "(없음)", memo or "(없음)")
        deposit.memo = memo

    if "rawName" in payload:
        raw_name = str(payload["rawName"] or "").strip()
        changes.add("rawName", "입금자명", deposit.raw_name or "(없음)", raw_name or "(없음)")
        name_changed = raw_name != deposit.raw_name
        deposit.raw_name = raw_name
        name_part, digits = split_depositor(deposit.raw_name)
        deposit.name_norm = normalize_name(name_part)
        deposit.digit_suffix = digits

    if "status" in payload:
        value = str(payload["status"] or "").upper()
        before_status = deposit.status
        if value == DEP_IGNORED:
            for alloc in list(deposit.allocations):
                db.session.delete(alloc)
            deposit.allocations.clear()
            deposit.status = DEP_IGNORED
            deposit.manual_locked = True
            deposit.match_reason = "관리자가 무관 입금으로 처리"
        elif value in REQUEUE_STATUSES:
            deposit.manual_locked = False
            deposit.status = value
        else:
            return jsonify({"error": "invalid_status"}), 400
        changes.add(
            "status", "입금 상태",
            _DEPOSIT_STATUS_LABELS.get(before_status, before_status),
            _DEPOSIT_STATUS_LABELS.get(deposit.status, deposit.status),
        )

    if name_changed and not deposit.manual_locked:
        match_deposit(deposit)

    if changes:
        write_audit(g.actor, "deposit.update", "deposit", deposit.id,
                    changes.detail(f"{deposit.raw_name or '이름 없음'} {_won(deposit.amount)}"))
    db.session.commit()
    return jsonify(deposit.to_admin_dict())


@admin_bp.put("/deposits/<int:deposit_id>/allocations")
@require_admin
def set_allocations(deposit_id: int):
    """입금을 참가자에게 직접 연결한다.

    보통은 참가자 1명이다. 스키마상 여러 명에게 나누는 것도 가능하지만
    실제 운영에서는 쓰이지 않는다.
    """
    deposit = db.session.get(Deposit, deposit_id)
    if deposit is None:
        return jsonify({"error": "not_found"}), 404

    payload = request.get_json(silent=True) or {}
    raw_items = payload.get("allocations")
    if not isinstance(raw_items, list) or not raw_items:
        return jsonify({"error": "invalid_payload", "message": "allocations 배열이 필요합니다."}), 400

    prepared: list[tuple[Participant, int]] = []
    seen: set[int] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            return jsonify({"error": "invalid_payload"}), 400
        participant = db.session.get(Participant, item.get("participantId") or 0)
        if participant is None:
            return jsonify({
                "error": "participant_not_found",
                "message": f"참가자 {item.get('participantId')} 를 찾을 수 없습니다.",
            }), 400
        if participant.id in seen:
            return jsonify({"error": "duplicate_participant"}), 400
        seen.add(participant.id)

        amount = parse_amount(item.get("amount"))
        if amount is None:
            amount = participant.expected_amount
        if amount <= 0:
            return jsonify({"error": "invalid_amount"}), 400
        prepared.append((participant, amount))

    total = sum(amount for _, amount in prepared)
    if total > deposit.amount and not payload.get("allowOverAllocation"):
        return jsonify({
            "error": "over_allocation",
            "message": f"지정 금액({total:,}원)이 입금액({deposit.amount:,}원)을 초과합니다.",
        }), 400

    for alloc in list(deposit.allocations):
        db.session.delete(alloc)
    deposit.allocations.clear()
    db.session.flush()

    for participant, amount in prepared:
        db.session.add(
            Allocation(
                deposit=deposit,
                participant=participant,
                amount=amount,
                created_by=g.actor,
            )
        )

    deposit.manual_locked = True
    deposit.status = DEP_MATCHED
    deposit.match_reason = (
        "관리자가 직접 지정"
        if len(prepared) == 1
        else f"관리자가 직접 지정 ({len(prepared)}명에게 나눔)"
    )

    changes = Changes()
    for participant, amount in prepared:
        changes.note("연결", f"{participant.name} · {_won(amount)}")

    write_audit(g.actor, "deposit.allocate", "deposit", deposit.id,
                changes.detail(f"{deposit.raw_name or '이름 없음'} {_won(deposit.amount)}"))
    db.session.commit()
    return jsonify(deposit.to_admin_dict())


@admin_bp.delete("/deposits/<int:deposit_id>/allocations")
@require_admin
def clear_allocations(deposit_id: int):
    """수동 지정을 해제하고 자동 매칭에 다시 태운다."""
    deposit = db.session.get(Deposit, deposit_id)
    if deposit is None:
        return jsonify({"error": "not_found"}), 404

    for alloc in list(deposit.allocations):
        db.session.delete(alloc)
    deposit.allocations.clear()
    deposit.manual_locked = False
    deposit.status = DEP_UNMATCHED
    db.session.flush()
    match_deposit(deposit)

    changes = Changes()
    changes.note("처리", "수동 지정을 풀고 자동 매칭에 다시 태움")
    write_audit(g.actor, "deposit.clear_allocations", "deposit", deposit.id,
                changes.detail(f"{deposit.raw_name or '이름 없음'} {_won(deposit.amount)}"))
    db.session.commit()
    return jsonify(deposit.to_admin_dict())


@admin_bp.post("/deposits/import")
@require_admin
def import_statement():
    """카카오뱅크 거래내역 파일 업로드 (xlsx / csv). 중복은 지문으로 자동 제거된다.

    내려받은 파일에 걸린 열기 비밀번호는 STATEMENT_PASSWORDS 로 서버가 풀어 준다.
    """
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return jsonify({"error": "file_required", "message": "파일을 선택해 주세요."}), 400

    data = uploaded.read()
    try:
        parsed = parse_statement(
            data, uploaded.filename, passwords=current_app.config["STATEMENT_PASSWORDS"]
        )
    except ValueError as exc:
        return jsonify({"error": "parse_failed", "message": str(exc)}), 400

    created = 0
    duplicated = 0
    for row in parsed.rows:
        _, is_new = register_deposit(
            occurred_at=row.occurred_at,
            amount=row.amount,
            balance_after=row.balance_after,
            raw_name=row.raw_name,
            name_norm=row.name_norm,
            digit_suffix=row.digit_suffix,
            source=SRC_IMPORT,
            raw_payload=row.raw,
            run_match=False,
        )
        if is_new:
            created += 1
        else:
            duplicated += 1

    db.session.commit()
    rematch = rematch_deposits(only_unresolved=True)

    # 참가자에게 '어디까지 반영됐는지' 알리기 위해 업로드 시점과 범위를 남긴다.
    record = ImportRecord(
        actor=g.actor,
        filename=uploaded.filename,
        parsed_rows=len(parsed.rows),
        created_count=created,
        duplicated_count=duplicated,
        skipped_count=len(parsed.skipped),
        period_from=parsed.period_from,
        period_to=parsed.period_to,
        latest_transaction_at=parsed.latest_transaction_at,
    )
    db.session.add(record)

    changes = Changes()
    changes.note("새 입금", f"{created}건")
    changes.note("중복 제외", f"{duplicated}건")
    if parsed.skipped:
        changes.note("건너뜀", f"{len(parsed.skipped)}행")

    write_audit(g.actor, "deposit.import", None, None, changes.detail(uploaded.filename))
    db.session.commit()

    return jsonify({
        "filename": uploaded.filename,
        "decrypted": parsed.decrypted,
        "headerRow": parsed.header_row,
        "parsedRows": len(parsed.rows),
        "created": created,
        "duplicated": duplicated,
        "skipped": parsed.skipped[:50],
        "skippedCount": len(parsed.skipped),
        "periodFrom": to_iso(parsed.period_from),
        "periodTo": to_iso(parsed.period_to),
        "latestTransactionAt": to_iso(parsed.latest_transaction_at),
        "rematch": rematch,
    })


@admin_bp.get("/imports")
@require_admin
def list_imports():
    """거래내역 업로드 이력."""
    records = (
        db.session.query(ImportRecord)
        .order_by(ImportRecord.imported_at.desc())
        .limit(50)
        .all()
    )
    return jsonify({"items": [record.to_admin_dict() for record in records]})


@admin_bp.post("/rematch")
@require_admin
def rematch():
    payload = request.get_json(silent=True) or {}
    only_unresolved = payload.get("onlyUnresolved", True) is not False
    result = rematch_deposits(only_unresolved=only_unresolved)

    changes = Changes()
    changes.note("범위", "미해결 건만" if only_unresolved else "이미 매칭된 건까지 전부")
    changes.note("처리", f"{result['processed']}건")
    for status, count in result["byStatus"].items():
        changes.note(_DEPOSIT_STATUS_LABELS.get(status, status), f"{count}건")

    write_audit(g.actor, "rematch", None, None, changes.detail())
    db.session.commit()
    return jsonify(result)


# --------------------------------------------------------------------------
# 읽지 못한 알림
# --------------------------------------------------------------------------

@admin_bp.get("/notifications")
@require_admin
def list_unparsed():
    """파싱하지 못한 알림 원문 목록.

    포워더를 처음 붙일 때 실제 카카오뱅크 문구를 확인하는 용도이자,
    앱 업데이트로 문구가 바뀌었을 때 놓친 입금을 찾는 용도다.
    """
    include_resolved = request.args.get("includeResolved", "false").lower() == "true"
    stmt = db.session.query(UnparsedNotification)
    if not include_resolved:
        stmt = stmt.filter(UnparsedNotification.resolved.is_(False))
    entries = stmt.order_by(UnparsedNotification.last_received_at.desc()).limit(200).all()
    return jsonify({"items": [entry.to_admin_dict() for entry in entries]})


def _try_reparse(entry: UnparsedNotification) -> bool:
    """현재 규칙으로 다시 해석해 성공하면 입금으로 등록한다."""
    parsed = parse_push_payload(entry.payload)
    if not parsed.ok:
        entry.reason = parsed.reason
        return False

    deposit, _ = register_deposit(
        occurred_at=parsed.occurred_at,
        amount=parsed.amount,
        balance_after=parsed.balance_after,
        raw_name=parsed.raw_name,
        name_norm=parsed.name_norm,
        digit_suffix=parsed.digit_suffix,
        source=SRC_PUSH,
        raw_payload=entry.payload,
    )
    entry.resolved = True
    entry.deposit_id = deposit.id
    return True


@admin_bp.post("/notifications/reparse")
@require_admin
def reparse_notifications():
    """미해결 알림 전체를 현재 파싱 규칙으로 재시도한다.

    `app/parsers/push.py` 의 패턴을 고친 뒤 이걸 눌러 되살린다.
    """
    entries = (
        db.session.query(UnparsedNotification)
        .filter(UnparsedNotification.resolved.is_(False))
        .all()
    )
    recovered = sum(1 for entry in entries if _try_reparse(entry))
    db.session.commit()

    changes = Changes()
    changes.note("다시 해석", f"{len(entries)}건")
    changes.note("되살림", f"{recovered}건")

    write_audit(g.actor, "notification.reparse", None, None, changes.detail())
    db.session.commit()
    return jsonify({"attempted": len(entries), "recovered": recovered})


@admin_bp.delete("/notifications/<int:notification_id>")
@require_admin
def dismiss_notification(notification_id: int):
    """MT와 무관한 알림을 목록에서 치운다 (원문은 남긴다)."""
    entry = db.session.get(UnparsedNotification, notification_id)
    if entry is None:
        return jsonify({"error": "not_found"}), 404

    entry.resolved = True
    changes = Changes()
    changes.note("치운 알림", entry.preview[:120] or "(내용 없음)")
    write_audit(g.actor, "notification.dismiss", "notification", entry.id, changes.detail())
    db.session.commit()
    return jsonify({"ok": True})


# --------------------------------------------------------------------------
# 감사 로그 / 내보내기
# --------------------------------------------------------------------------

@admin_bp.get("/audit")
@require_admin
def audit_log():
    limit = min(int(request.args.get("limit", 100) or 100), 500)
    entries = (
        db.session.query(AuditLog)
        .order_by(AuditLog.at.desc(), AuditLog.id.desc())
        .limit(limit)
        .all()
    )
    return jsonify({"items": [entry.to_dict() for entry in entries]})


@admin_bp.get("/export/participants.csv")
@require_admin
def export_participants():
    participants = db.session.query(Participant).order_by(Participant.name.asc()).all()
    # 배정 항목과 출석 회차는 운영 중에 늘어나므로 열도 정의를 보고 만든다.
    fields = active_fields()
    sessions = active_sessions()
    attended = {row.key: checked_in_ids(row) for row in sessions}

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "이름", "전화번호", "학번", "학과", "성별", "요금구분", "총학생회비납부",
        "본행사비", "뒤풀이참가", "뒤풀이비", "예상금액", "납입금액", "상태",
        "뒤풀이납입", "뒤풀이합산납부", "참가확정", "확정시각",
        "조장지원", "닉네임", "출생년도",
        *[field.label for field in fields],
        *[f"{row.label} 출석" for row in sessions],
        "럭키드로우번호", "취소여부", "메모",
    ])
    for p in participants:
        values = p.assignments
        writer.writerow([
            p.name, p.phone, p.student_id or "", p.department or "", p.gender or "",
            _FEE_CLASS_LABELS[p.fee_class],
            "Y" if p.is_council_member else "N",
            p.base_fee,
            "Y" if p.joins_afterparty else "N",
            p.afterparty_fee,
            p.expected_amount, p.paid_amount, p.payment_status,
            p.afterparty_status,
            "Y" if p.afterparty_prepaid else "N",
            "Y" if p.is_confirmed else "N", to_iso(p.confirmed_at) or "",
            _LEADER_LABELS.get(p.leader_preference, ""), p.nickname or "", p.birth_year or "",
            *[values.get(field.key, "") for field in fields],
            *["Y" if p.id in attended[row.key] else "N" for row in sessions],
            p.draw_label or "",
            "Y" if p.is_cancelled else "N", p.memo or "",
        ])

    changes = Changes()
    changes.note("내려받은 인원", f"{len(participants)}명")
    write_audit(g.actor, "export.participants", None, None, changes.detail())
    db.session.commit()

    return Response(
        "﻿" + buffer.getvalue(),  # 엑셀에서 한글이 깨지지 않도록 BOM
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=participants.csv"},
    )
