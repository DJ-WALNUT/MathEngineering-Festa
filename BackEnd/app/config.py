"""애플리케이션 설정.

모든 민감 값은 환경변수로 주입한다. 시놀로지 Container Manager에서는
docker-compose.yml 의 env_file 로 .env 를 연결하면 된다.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# 아래 Config 클래스 본문은 import 시점에 os.getenv 를 읽는다.
# 따라서 .env 로드는 반드시 그보다 먼저, 이 자리에서 일어나야 한다.
# (create_app 안에서 부르면 이미 늦어 모든 값이 빈 문자열이 된다)
# 도커에서는 env_file 이 실제 환경변수를 넣어 주므로 이 호출은 무시된다.
load_dotenv(BASE_DIR / ".env")


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.replace(",", "").strip())
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(key: str, default: list[str]) -> list[str]:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


def _ascii_origin(origin: str) -> str:
    """'https://mt.도메인' → 'https://mt.xn--hq1bm8jm9l'. ASCII 면 그대로."""
    if origin.isascii():
        return origin
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(origin)
    host = parts.hostname or ""
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        ascii_host = host.encode("ascii", "ignore").decode("ascii") or "invalid.invalid"
    netloc = ascii_host + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _resolve_dir(raw: str | None, default: Path) -> Path:
    if raw is None or raw.strip() == "":
        return default
    path = Path(raw.strip())
    return path if path.is_absolute() else (BASE_DIR / path).resolve()


class Config:
    # --- 기본 ---
    SECRET_KEY = os.getenv("SECRET_KEY", "")
    # 상대 경로로 줘도 되도록 BASE_DIR 기준으로 절대화한다.
    # (그러지 않으면 실행 위치에 따라 DB 파일이 엉뚱한 데 생긴다)
    DATA_DIR = _resolve_dir(os.getenv("DATA_DIR"), BASE_DIR / "data")
    MAX_CONTENT_LENGTH = _env_int("MAX_UPLOAD_BYTES", 8 * 1024 * 1024)

    # --- DB ---
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- 참가비 (원) ---
    #
    # 참가비는 두 겹이다. 본 행사비가 아래에 깔리고, 뒤풀이에 가는 사람만 그 위에
    # 뒤풀이비가 얹힌다. 어떻게 갈라 세는지는 app/models.py 의 Participant 를 보라.
    #
    # 본 행사비 — 총학생회비 납부자 / 미납부자
    FEE_COUNCIL_MEMBER = _env_int("FEE_COUNCIL_MEMBER", 5_000)
    FEE_NON_MEMBER = _env_int("FEE_NON_MEMBER", 7_000)
    # 스태프 참가비의 최초값. 아직 정해지지 않은 값이라 기본은 0(면제)이고,
    # 실제 운영에서는 관리자 페이지 > 대시보드에서 고친다. 고친 값이 DB 에 남아
    # 이 설정보다 우선하므로, 재배포해도 화면에서 정한 금액이 유지된다.
    FEE_STAFF = _env_int("FEE_STAFF", 0)
    # 뒤풀이비. 총학생회비 납부 여부와 무관하게 같은 금액이고, 스태프 참가비와
    # 같은 이유로 관리자 페이지에서 고칠 수 있다(고친 값이 이 설정보다 우선한다).
    FEE_AFTERPARTY = _env_int("FEE_AFTERPARTY", 10_000)

    # 이 금액 미만이면서 이름도 매칭되지 않는 입금은 '기타 입금'으로 분리한다.
    # 계좌를 참가비 전용으로 쓰지 않으면 소액 잡음이 확인 필요 큐를 가득 채우기 때문이다.
    # 버리는 것이 아니라 분류일 뿐이라 언제든 다시 꺼내 볼 수 있다. 0 이면 기능을 끈다.
    #
    # 참가비가 5,000원까지 내려가 예전 기본값(10,000)을 그대로 두면 **정상 참가비가
    # 통째로 기타 입금으로 갈린다.** 참가비보다 낮게 잡아야 한다.
    MINOR_DEPOSIT_THRESHOLD = _env_int("MINOR_DEPOSIT_THRESHOLD", 3_000)

    # --- 인증 ---
    # 비밀번호는 **두 단계**다. 최고 관리자·국장단이 쓰는 것과 국원이 쓰는 것.
    # 어느 쪽을 요구할지는 그 사람의 역할군에 매긴 등급이 정한다(app/admins.py).
    #
    # scripts/hash_password.py 로 생성한 scrypt 해시 문자열을 넣는다.
    ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "")
    # 국원용. **비워 두면 국원도 위 비밀번호를 쓴다** — 이 값을 넣기 전과 똑같이
    # 동작하므로, 배포한 .env 를 아직 고치지 못했어도 아무도 문 밖에 서지 않는다.
    STAFF_PASSWORD_HASH = os.getenv("STAFF_PASSWORD_HASH", "")
    ADMIN_SESSION_TTL = _env_int("ADMIN_SESSION_TTL", 60 * 60 * 8)  # 8시간
    # Apps Script / 안드로이드 알림 포워더가 사용할 공유 시크릿
    INGEST_TOKEN = os.getenv("INGEST_TOKEN", "")

    # 거래내역 엑셀의 열기 비밀번호 (쉼표로 여러 개).
    # 카카오뱅크에서 내려받은 파일에는 비밀번호가 걸려 있는데, 여기에 적어 두면
    # 업로드할 때 서버가 풀어서 읽는다. 담당자가 매번 손으로 해제하지 않아도 된다.
    # 여러 개를 두는 것은 비밀번호가 바뀐 뒤에도 옛 파일을 다시 올릴 수 있게 하기 위함이다.
    # 비워 두면 잠긴 파일은 거절되고, 예전처럼 풀어서 올려야 한다.
    STATEMENT_PASSWORDS = _env_list("STATEMENT_PASSWORDS", [])

    # --- CORS ---
    #
    # 도메인에 한글이 섞여 있으면(예: 예시 값을 그대로 둔 .env) Flask-CORS 가 그 값을
    # Access-Control-Allow-Origin 헤더에 실어 보내다가 latin-1 인코딩에서 죽고,
    # **모든 응답이 끊긴다.** 요청은 200 으로 처리된 뒤라 로그만 보면 원인을 알 수 없다.
    # 그래서 호스트를 punycode 로 바꿔 헤더에 실을 수 있게 만들고, 기동 로그에 알린다.
    CORS_ORIGINS = [_ascii_origin(item) for item in _env_list("CORS_ORIGINS", ["http://localhost:5173"])]

    # --- Rate limit ---
    LOOKUP_RATE_LIMIT = os.getenv("LOOKUP_RATE_LIMIT", "10 per 10 minutes")
    LOGIN_RATE_LIMIT = os.getenv("LOGIN_RATE_LIMIT", "10 per 15 minutes")
    # 셀프 체크인은 조회와 성격이 다르다. 집결지에서 수백 명이 같은 기지국·와이파이를
    # 타면 IP 가 통째로 겹치므로, 조회와 같은 값(10회/10분)을 걸면 정상 체크인이
    # 줄줄이 막힌다. 넉넉히 두고, 본인 확인은 이름+학번+전화 뒷자리 3요소로 받는다.
    CHECKIN_RATE_LIMIT = os.getenv("CHECKIN_RATE_LIMIT", "300 per 10 minutes")
    # 개인 카드(/api/p/<token>)도 체크인 쪽이다.
    #
    # 본인 조회와 성격이 다르다. 조회는 이름+전화번호를 넣어 보며 명단을 훑을 수 있어
    # 조여야 하지만, 개인 카드는 **무작위 토큰을 이미 알고 있어야** 열린다 — 훑을 수가
    # 없다. 반대로 문 앞에서 자기 QR 을 띄우려고 몇 번씩 새로 열고, 수백 명이 같은
    # 와이파이·기지국을 타 IP 가 통째로 겹친다. 조회와 같은 값(10회/10분)을 걸면
    # 정작 나가려는 사람이 자기 QR 을 못 연다.
    CARD_RATE_LIMIT = os.getenv("CARD_RATE_LIMIT", "300 per 10 minutes")
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
    # Cloudflare 뒤에 있으므로 신뢰할 프록시 홉 수
    TRUSTED_PROXY_HOPS = _env_int("TRUSTED_PROXY_HOPS", 1)

    # --- 동작 옵션 ---
    # 자동 매칭을 끄고 전부 수동으로 처리하고 싶을 때 false
    AUTO_MATCH_ENABLED = _env_bool("AUTO_MATCH_ENABLED", True)

    # 안드로이드 알림 포워딩 경로.
    # 카카오뱅크는 유심이 없는 기기에서 로그인이 되지 않아 공기계로는 알림을 받을 수 없다.
    # 그래서 기본값은 꺼짐이고, 입금 수집은 거래내역 파일 업로드로만 이루어진다.
    # 유심이 꽂힌 전용 기기를 마련하면 그때 켜면 된다.
    PUSH_INGEST_ENABLED = _env_bool("PUSH_INGEST_ENABLED", False)


def resolve_database_uri(config: type[Config]) -> str:
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit
    data_dir = config.DATA_DIR
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise RuntimeError(_data_dir_help(data_dir, str(error))) from error
    # SQLite 는 폴더에 쓸 수 없으면 'unable to open database file' 한 줄만 남기고
    # 죽는다. 무엇이 문제인지 여기서 먼저 확인해 사람이 읽을 수 있게 알린다.
    if not os.access(data_dir, os.W_OK):
        raise RuntimeError(_data_dir_help(data_dir, "쓰기 권한 없음"))
    return f"sqlite:///{(data_dir / 'mt.db').as_posix()}"


def _data_dir_help(data_dir: Path, reason: str) -> str:
    import pwd

    try:
        who = f"{pwd.getpwuid(os.getuid()).pw_name}(uid {os.getuid()})"
    except (KeyError, AttributeError):
        who = f"uid {os.getuid()}"
    return (
        f"DB 폴더 {data_dir} 에 {who} 가 쓸 수 없습니다 — {reason}.\n"
        "  · 도커라면 docker-compose.yml 의 volumes 왼쪽(NAS 실제 폴더)이 존재하고 "
        "컨테이너 사용자(uid 1000)가 쓸 수 있어야 합니다. 진입점이 소유자를 맞추지 "
        "못했다면 NAS 에서 `sudo chown -R 1000:1000 <볼륨경로>` 를 한 번 실행하세요.\n"
        "  · 로컬이라면 .env 의 DATA_DIR 경로를 확인하세요."
    )
