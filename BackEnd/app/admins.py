"""관리자 계정 · 역할군 · 탭 권한 · 로그인 등급.

지금까지 관리자는 하나였다. 비밀번호를 아는 사람은 모두 같은 `admin` 이었고,
작업 기록도 전부 그 한 이름으로 남았다. 몇 달 뒤 "이건 누가 왜 이렇게 했지"를
되짚을 수 없다는 뜻이다.

그래서 **사람을 구분한다.** 구분은 두 겹이다.

    ┌ 비밀번호 : 등급마다 하나 (.env)   ← 진짜 문. 국원용과 국장단용이 다르다
    ├ 로그인 ID : 사람마다 다름          ← 누가 했는지 남기는 이름표
    └ 탭 권한   : 역할군/개인마다        ← 필요한 화면만 보이게 하는 정리

**등급(tier)** 은 역할군에 매긴다. 사람이 바뀌어도 역할군만 맞으면 되고, 예외가
필요하면 그 사람의 역할군을 바꾸면 된다. 등급은 둘뿐이다.

    lead  — 최고 관리자 · 국장단 (학생회장 · 국장 · 차장)
    staff — 국원

로그인은 **계정의 등급과 입력한 비밀번호의 등급이 같을 때만** 통과한다. 국원
비밀번호를 아는 사람이 국장 ID 를 넣어도 들어오지 못한다. 반대도 마찬가지다 —
등급이 곧 그 사람이 쓰는 열쇠라, 어느 쪽 문에 어느 열쇠가 맞는지가 분명해야 한다.

**탭 권한은 여전히 잠금장치가 아니다.** 화면을 가릴 뿐 API 를 막지 않는다(관리자·
역할군을 다루는 길만은 최고 관리자로 막는다 — 권한을 스스로 올리는 길까지 열어
두면 구분 자체가 무의미해지기 때문이다). 같은 등급 안에서는 서로의 화면에 들어갈
수 있고, 그것으로 충분하다고 본다. 등급 사이의 벽만 진짜다.
"""

from __future__ import annotations

import json
import re

from .extensions import db
from .models import AdminAccount, AdminRole

# 최고 관리자의 로그인 ID. 빈 DB 로 시작해도 이 계정만은 있어야 들어갈 수 있다.
SUPER_USERNAME = "wont0309"

# 로그인 등급. key 는 .env 의 해시와, 프론트의 표시와 짝을 이룬다.
TIER_LEAD = "lead"
TIER_STAFF = "staff"

TIERS: list[dict] = [
    {"key": TIER_LEAD, "label": "최고 관리자 · 국장단", "envKey": "ADMIN_PASSWORD_HASH"},
    {"key": TIER_STAFF, "label": "국원", "envKey": "STAFF_PASSWORD_HASH"},
]

TIER_KEYS = [tier["key"] for tier in TIERS]
TIER_LABELS = {tier["key"]: tier["label"] for tier in TIERS}

# 관리자 화면의 탭. **권한의 단위**이자 화면의 단위다.
#
# 프론트가 이 목록을 그대로 받아 탭을 그리므로, 탭을 늘리면 여기만 고치면 된다.
# key 는 프론트의 탭 id 와 같아야 한다 (pages/admin/AdminPage.tsx).
TABS: list[dict] = [
    {"key": "summary", "label": "대시보드"},
    {"key": "imports", "label": "거래내역 업로드"},
    {"key": "deposits", "label": "입금 내역"},
    {"key": "participants", "label": "참가자"},
    {"key": "assignments", "label": "배정"},
    {"key": "badges", "label": "명찰"},
    {"key": "attendance", "label": "출석"},
    {"key": "audit", "label": "작업 기록"},
    # 관리자·역할군을 다루는 탭. 최고 관리자에게만 열린다.
    {"key": "admins", "label": "관리자"},
]

TAB_KEYS = [tab["key"] for tab in TABS]
# 최고 관리자만 볼 수 있는 탭. 다른 사람에게 줘도 무시된다.
SUPER_ONLY_TABS = {"admins"}

# 처음 만들어 두는 역할군. 이름도 등급도 화면에서 고칠 수 있다.
DEFAULT_ROLES = [
    {"name": "학생회장", "position": 10, "tier": TIER_LEAD,
     "tabs": [k for k in TAB_KEYS if k != "admins"]},
    {"name": "국장", "position": 20, "tier": TIER_LEAD, "tabs": [
        "summary", "deposits", "participants", "assignments", "attendance",
    ]},
    {"name": "차장", "position": 30, "tier": TIER_LEAD,
     "tabs": ["summary", "participants", "attendance"]},
    {"name": "국원", "position": 40, "tier": TIER_STAFF, "tabs": ["attendance"]},
]

_USERNAME_SAFE = re.compile(r"[\s]+")


class AdminError(ValueError):
    """사용자에게 그대로 보여줄 수 있는 관리자 관리 오류."""


def normalize_username(raw: str | None) -> str:
    """로그인 ID 를 비교용으로 다듬는다.

    이름을 ID 로 쓰므로 '홍 길동' 처럼 띄어 쓰는 사람이 나온다. 공백을 걷어내고
    영문은 소문자로 맞춘다 — 문 앞에서 대소문자 때문에 못 들어가면 안 된다.
    """
    return _USERNAME_SAFE.sub("", str(raw or "")).strip().lower()


def ensure_super_admin() -> bool:
    """최고 관리자 계정을 보장한다. 새로 만들었으면 True.

    빈 DB 로 시작하면 아무도 들어올 수 없으므로 기동 때마다 확인한다. 이미 있으면
    이름도 권한도 건드리지 않는다 — 화면에서 고친 것이기 때문이다.
    """
    existing = (
        db.session.query(AdminAccount)
        .filter(AdminAccount.username == SUPER_USERNAME)
        .one_or_none()
    )
    if existing is not None:
        # 최고 관리자 표시만은 잃어버리면 안 된다. 잃으면 아무도 권한을 줄 수 없다.
        if not existing.is_super or not existing.is_active:
            existing.is_super = True
            existing.is_active = True
            db.session.commit()
        return False

    db.session.add(
        AdminAccount(
            username=SUPER_USERNAME,
            display_name="최고 관리자",
            is_super=True,
            is_active=True,
        )
    )
    db.session.commit()
    return True


def ensure_default_roles() -> list[str]:
    """역할군이 하나도 없을 때만 기본값을 넣는다.

    한 번 넣은 뒤에는 다시 채우지 않는다. 학생회가 지운 역할이 기동할 때마다
    되살아나면 화면에서 지울 방법이 없어진다.
    """
    if db.session.query(AdminRole).count() > 0:
        return []

    created: list[str] = []
    for spec in DEFAULT_ROLES:
        db.session.add(
            AdminRole(
                name=spec["name"],
                position=spec["position"],
                tier=spec["tier"],
                tabs_json=json.dumps(spec["tabs"], ensure_ascii=False),
            )
        )
        created.append(spec["name"])
    db.session.commit()
    return created


def ensure_role_tiers() -> list[str]:
    """등급이 비어 있는 역할군을 채운다. 채운 역할군 이름을 돌려준다.

    등급 컬럼은 뒤늦게 붙었다. 이미 쓰이던 DB 의 역할군은 전부 NULL 로 생기는데,
    그것을 일괄로 '국원'에 몰아넣으면 **학생회장이 국원 비밀번호로 밀려난다.**

    그래서 기본 역할군이었던 자리를 되짚어 그때 정한 등급을 되살린다. 되짚는 방법은
    둘이다.

      1. 이름 — '국원' 처럼 그대로 쓰고 있는 경우
      2. 자리(position) — **이름을 고쳐 쓰는 경우가 흔하다.** 실제로 이 학생회는
         국장·국원을 '단장'·'단원'으로 바꿔 쓰고 있다. 기본 역할군은 자리가
         10·20·30·40 으로 고정이고 새로 만든 역할군은 50 부터 붙으므로, 이름이
         바뀌어도 자리로 원래 무엇이었는지 알 수 있다.

    둘 다 아니면 국원으로 둔다 — 모르는 것은 낮은 쪽에 두는 편이 안전하다. 올릴 일이
    있으면 최고 관리자가 화면에서 올리면 되지만, 잘못 올려 둔 것은 아무도 눈치채지 못한다.

    한 번 값이 들어간 뒤에는 건드리지 않는다. 화면에서 국장을 국원으로 내렸는데
    기동할 때마다 되살아나면 고칠 방법이 없어진다.
    """
    by_name = {spec["name"]: spec["tier"] for spec in DEFAULT_ROLES}
    by_position = {spec["position"]: spec["tier"] for spec in DEFAULT_ROLES}
    filled: list[str] = []

    for role in db.session.query(AdminRole).filter(AdminRole.tier.is_(None)).all():
        role.tier = by_name.get(role.name) or by_position.get(role.position, TIER_STAFF)
        filled.append(f"{role.name}({TIER_LABELS[role.tier]})")

    if filled:
        db.session.commit()
    return filled


def clean_tier(raw) -> str:
    """받은 등급 값을 확인한다. 모르는 값은 거절한다 — 조용히 국원으로 떨어뜨리면
    최고 관리자가 국장단으로 올렸다고 믿는 채로 아닌 상태가 된다."""
    value = str(raw or "").strip().lower()
    if value not in TIER_KEYS:
        raise AdminError("등급은 '국장단' 또는 '국원' 중 하나여야 합니다.")
    return value


def tier_for(account: AdminAccount) -> str:
    """이 사람이 어느 비밀번호로 들어오는지.

    최고 관리자는 언제나 국장단이다. 나머지는 역할군을 따르고, 역할군이 없으면
    국원으로 본다 — 아직 자리를 못 정한 사람에게 높은 열쇠를 줄 이유가 없다.
    """
    if account.is_super:
        return TIER_LEAD
    if account.role is not None and account.role.tier in TIER_KEYS:
        return account.role.tier
    return TIER_STAFF


def tier_label(tier: str) -> str:
    return TIER_LABELS.get(tier, tier)


def find_account(username: str) -> AdminAccount | None:
    needle = normalize_username(username)
    if not needle:
        return None
    for account in db.session.query(AdminAccount).all():
        if normalize_username(account.username) == needle:
            return account
    return None


def tabs_for(account: AdminAccount) -> list[str]:
    """이 사람에게 열리는 탭.

    개인 지정이 있으면 그것이 이기고, 없으면 역할을 따른다. 최고 관리자는 전부다.
    순서는 화면의 탭 순서를 그대로 따라간다 — 사람마다 탭이 뒤죽박죽이면 안 된다.
    """
    if account.is_super:
        return list(TAB_KEYS)

    granted = account.own_tabs or (account.role.tabs if account.role else [])
    allowed = set(granted) - SUPER_ONLY_TABS
    return [key for key in TAB_KEYS if key in allowed]


def clean_tabs(raw) -> list[str]:
    """받은 탭 목록을 정리한다. 없는 키와 최고 관리자 전용은 조용히 버린다."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise AdminError("탭 목록 형식이 올바르지 않습니다.")
    wanted = {str(item) for item in raw}
    return [key for key in TAB_KEYS if key in wanted and key not in SUPER_ONLY_TABS]


def dump_tabs(tabs: list[str]) -> str | None:
    return json.dumps(tabs, ensure_ascii=False) if tabs else None
