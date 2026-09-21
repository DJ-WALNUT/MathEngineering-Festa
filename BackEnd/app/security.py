"""관리자 인증 / ingest 토큰 검증.

- 관리자 비밀번호는 scrypt(표준 라이브러리) 해시만 저장한다. 평문은 서버에 없다.
- 비밀번호는 **등급마다 하나**다 (최고 관리자·국장단 / 국원). 어느 것을 요구할지는
  그 사람의 역할군이 정한다 (app/admins.py 의 tier_for).
- 세션은 쿠키가 아니라 서명된 Bearer 토큰을 쓴다.
  프론트(Cloudflare Pages)와 백엔드(시놀로지)가 서로 다른 사이트라
  SameSite 쿠키가 상황에 따라 막히기 때문이다.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from functools import wraps

from flask import current_app, g, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAXMEM = 96 * 1024 * 1024
_SCRYPT_DKLEN = 32
_SALT_BYTES = 16

_TOKEN_SALT = "admin-session-v1"


def hash_password(password: str) -> str:
    """'scrypt:n:r:p:salt_hex:hash_hex' 형태의 저장용 문자열 생성.

    구분자로 ':' 를 쓴다. 예전에는 '$' 를 썼는데, 이 값이 .env 를 거쳐
    docker compose 로 전달되는 과정에서 '$32768' 이 셸 변수로 해석되어
    통째로 사라지는 사고가 있었다. ':' 는 어떤 계층에서도 특별 취급되지 않는다.
    """
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        maxmem=_SCRYPT_MAXMEM,
        dklen=_SCRYPT_DKLEN,
    )
    return f"scrypt:{_SCRYPT_N}:{_SCRYPT_R}:{_SCRYPT_P}:{salt.hex()}:{derived.hex()}"


def _split_stored(stored: str) -> list[str] | None:
    """저장된 해시를 조각으로 나눈다. ':' 와 예전 '$' 형식을 모두 받는다."""
    for separator in (":", "$"):
        if separator in stored:
            parts = stored.strip().split(separator)
            if len(parts) == 6 and parts[0] == "scrypt":
                return parts
    return None


def describe_hash(stored: str) -> str:
    """해시 자체는 드러내지 않고 형식만 설명한다 (설정 점검용)."""
    if not stored:
        return "ADMIN_PASSWORD_HASH 가 비어 있습니다."

    parts = _split_stored(stored)
    if parts is None:
        return (
            f"형식이 올바르지 않습니다 (길이 {len(stored)}, 앞 12자 '{stored[:12]}…').\n"
            "  .env 를 거치며 값이 잘렸을 수 있습니다. "
            "특히 예전 '$' 구분자 해시는 docker compose 가 변수로 해석해 망가뜨립니다.\n"
            "  scripts/hash_password.py 로 새로 만들어 교체하세요."
        )

    _, n, r, p, salt_hex, hash_hex = parts
    return (
        f"형식 정상 (scrypt n={n} r={r} p={p}, "
        f"salt {len(salt_hex) // 2}바이트, 해시 {len(hash_hex) // 2}바이트)"
    )


def verify_password(password: str, stored: str) -> bool:
    if not stored or not password:
        return False

    parts = _split_stored(stored)
    if parts is None:
        return False

    _, n, r, p, salt_hex, hash_hex = parts
    try:
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            maxmem=_SCRYPT_MAXMEM,
            dklen=len(bytes.fromhex(hash_hex)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derived.hex(), hash_hex)


def tier_hashes() -> dict[str, str]:
    """등급별 저장 해시.

    국원용이 비어 있으면 **관리자 해시를 그대로 쓴다.** 등급을 나누기 전에 배포된
    `.env` 에는 국원용 값이 없는데, 그때 국원을 문 밖에 세워 두면 행사 당일 출석
    담당자가 통째로 못 들어온다. 값을 넣는 순간부터 두 문이 갈린다.
    """
    lead = current_app.config.get("ADMIN_PASSWORD_HASH", "") or ""
    staff = current_app.config.get("STAFF_PASSWORD_HASH", "") or lead
    return {"lead": lead, "staff": staff}


def tiers_matching(password: str) -> set[str]:
    """이 비밀번호로 열리는 등급들.

    두 등급이 같은 비밀번호를 쓰는 동안(국원용 미설정)에는 둘 다 열린다.
    비교는 등급을 알기 **전에** 끝내 둔다 — 그래야 '비밀번호부터 맞아야 계정
    존재 여부를 알 수 있다'는 지금의 성질이 그대로 남는다.
    """
    if not password:
        return set()
    return {tier for tier, stored in tier_hashes().items() if verify_password(password, stored)}


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=_TOKEN_SALT)


def issue_admin_token(
    actor: str = "admin", account_id: int | None = None, tier: str | None = None
) -> str:
    """세션 토큰.

    **계정 id 를 함께 담고 이름은 표시용으로만 쓴다.** 권한과 이름은 요청마다 DB 에서
    다시 읽으므로, 관리자가 권한을 바꾸거나 계정을 껐을 때 상대가 로그아웃할 때까지
    기다리지 않아도 된다.

    등급도 담는다. 그래야 역할군의 등급이 바뀐 순간 **어느 비밀번호로 들어온
    세션인지**를 지금의 등급과 견줄 수 있다.
    """
    payload: dict = {"actor": actor}
    if account_id is not None:
        payload["id"] = account_id
    if tier is not None:
        payload["tier"] = tier
    return _serializer().dumps(payload)


def verify_admin_token(token: str) -> dict | None:
    """유효하면 {'actor': str, 'id': int | None, 'tier': str | None}, 아니면 None."""
    try:
        data = _serializer().loads(token, max_age=current_app.config["ADMIN_SESSION_TTL"])
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(data, dict):
        return None
    actor = data.get("actor")
    if not isinstance(actor, str):
        return None
    account_id = data.get("id")
    tier = data.get("tier")
    return {
        "actor": actor,
        "id": account_id if isinstance(account_id, int) else None,
        "tier": tier if isinstance(tier, str) else None,
    }


def _bearer_token() -> str:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


def require_admin(view):
    """관리자 세션 토큰 필수.

    `g.actor` 에 작업 기록에 남길 이름을, `g.account` 에 계정을 넣어 준다.
    계정은 **요청마다 다시 읽는다** — 권한을 내리거나 계정을 끈 것이 곧바로 듣게
    하기 위해서다. 옛 토큰(계정 없이 발급된 것)은 이름만으로 통과시킨다.
    """

    @wraps(view)
    def wrapper(*args, **kwargs):
        claims = verify_admin_token(_bearer_token())
        if not claims:
            return jsonify({"error": "unauthorized", "message": "관리자 인증이 필요합니다."}), 401

        from .extensions import db
        from .models import AdminAccount

        account = db.session.get(AdminAccount, claims["id"]) if claims["id"] else None
        if account is not None and not account.is_active:
            return jsonify({
                "error": "account_disabled",
                "message": "사용이 중지된 계정입니다. 최고 관리자에게 문의해 주세요.",
            }), 401

        # 등급이 바뀌었으면 지금 손에 쥔 토큰도 그 순간부터 막힌다. 내려간 사람이
        # 남은 세션 시간 동안 위쪽 화면에 머무르면 등급을 나눈 의미가 없고, 올라간
        # 사람은 위쪽 비밀번호를 안다는 것을 한 번 보여야 한다.
        # (등급이 붙기 전에 발급된 옛 토큰은 이름만으로 통과시킨다)
        if account is not None and claims["tier"] is not None:
            from .admins import tier_for

            if claims["tier"] != tier_for(account):
                return jsonify({
                    "error": "tier_changed",
                    "message": "등급이 바뀌었습니다. 다시 로그인해 주세요.",
                }), 401

        g.account = account
        g.actor = account.display_name if account is not None else claims["actor"]
        return view(*args, **kwargs)

    return wrapper


def require_super(view):
    """최고 관리자 전용.

    관리자·역할군을 다루는 길만 서버에서 막는다. 탭 권한은 화면을 가릴 뿐이지만,
    **권한을 스스로 올리는 길**까지 열어 두면 구분 자체가 무의미해진다.
    """

    @wraps(view)
    @require_admin
    def wrapper(*args, **kwargs):
        account = getattr(g, "account", None)
        if account is None or not account.is_super:
            return jsonify({
                "error": "forbidden",
                "message": "최고 관리자만 할 수 있습니다.",
            }), 403
        return view(*args, **kwargs)

    return wrapper


def require_ingest_token(view):
    """Apps Script / 알림 포워더용 공유 시크릿 검증."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        expected = current_app.config.get("INGEST_TOKEN", "")
        if not expected:
            return jsonify({"error": "misconfigured", "message": "INGEST_TOKEN 미설정"}), 503
        supplied = request.headers.get("X-Ingest-Token", "") or _bearer_token()
        if not supplied or not hmac.compare_digest(supplied, expected):
            return jsonify({"error": "unauthorized"}), 401
        return view(*args, **kwargs)

    return wrapper


def client_ip() -> str:
    return request.remote_addr or "unknown"
