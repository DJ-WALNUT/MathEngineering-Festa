"""배포용 .env 를 만들어 주는 스크립트.

SECRET_KEY · INGEST_TOKEN 을 난수로 만들고, 관리자 비밀번호를 받아 해시로 바꾼 뒤
붙여넣기만 하면 되는 .env 전문을 출력한다.

    python scripts/make_env.py                     # 화면에 출력만
    python scripts/make_env.py --out .env.prod     # 파일로 저장

주의
  - 생성된 값은 이 컴퓨터 밖으로 내보내지 말 것. 채팅·이슈·슬랙에 붙여넣지 않는다.
  - 개발용과 배포용은 반드시 다른 값을 쓴다.
  - 비밀번호는 화면에 표시되지 않는다(입력해도 커서가 움직이지 않는 것이 정상).
"""

from __future__ import annotations

import argparse
import getpass
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.security import hash_password  # noqa: E402

TEMPLATE = """\
# ---------------------------------------------------------------------------
# 수리공학 페스타 백엔드 — 배포용 설정
# 이 파일은 절대 커밋하지 않는다 (.gitignore 처리되어 있음).
# ---------------------------------------------------------------------------

SECRET_KEY={secret_key}

# 관리자 로그인 비밀번호의 해시. 평문은 어디에도 저장되지 않는다.
# 비밀번호는 등급마다 하나다 — 어느 쪽을 요구할지는 그 사람의 역할군이 정한다.
#
#   ADMIN_PASSWORD_HASH : 최고 관리자 · 국장단 (학생회장 · 국장 · 차장)
#   STAFF_PASSWORD_HASH : 국원
#
# 바꾸려면 python scripts/hash_password.py [--staff] 로 새 해시를 만들어 교체한다.
# STAFF_PASSWORD_HASH 를 비우면 국원도 위 비밀번호를 쓴다(등급이 나뉘지 않는다).
ADMIN_PASSWORD_HASH={admin_hash}
STAFF_PASSWORD_HASH={staff_hash}

# Apps Script 가 폼 응답을 보낼 때 쓰는 공유 시크릿.
# 신청 스프레드시트의 스크립트 속성에 같은 값을 넣는다.
INGEST_TOKEN={ingest_token}

# 참가비 (원). 본 행사비 위에 뒤풀이비가 얹힌다.
FEE_COUNCIL_MEMBER=5000
FEE_NON_MEMBER=7000
FEE_AFTERPARTY=10000

# 이름이 안 맞으면서 이 금액 미만인 입금은 '기타 입금'으로 분리한다. 0 이면 끈다.
# 참가비(5,000원)보다 낮게 잡아야 정상 입금이 여기로 갈리지 않는다.
MINOR_DEPOSIT_THRESHOLD=3000

# 프론트엔드 도메인. Cloudflare Pages 기본 주소와 커스텀 도메인을 모두 넣는다.
CORS_ORIGINS={cors_origins}

# 컨테이너 안의 DB 경로. docker-compose 의 volumes 와 짝을 이룬다.
DATA_DIR=/data

# 관리자 세션 유효시간(초) — 8시간
ADMIN_SESSION_TTL=28800

# 조회/로그인 rate limit
LOOKUP_RATE_LIMIT=10 per 10 minutes
LOGIN_RATE_LIMIT=10 per 15 minutes

# 신뢰할 프록시 홉 수.
# Cloudflare 프록시(주황 구름) + 시놀로지 역방향 프록시 = 2
# Cloudflare 를 DNS 전용(회색 구름)으로 쓰면 1
TRUSTED_PROXY_HOPS={proxy_hops}

# 자동 매칭을 끄고 전부 수동으로 처리하려면 false
AUTO_MATCH_ENABLED=true

# 알림 포워딩 경로. 유심 없는 공기계로는 카카오뱅크 로그인이 되지 않아 꺼 둔다.
PUSH_INGEST_ENABLED=false
"""


def ask_password(who: str) -> str:
    while True:
        password = getpass.getpass(f"{who} 비밀번호 (화면에 표시되지 않음): ")
        if len(password) < 8:
            print("  10자 이상으로 정해 주세요. 학생회에서 공유해 쓸 비밀번호입니다.\n")
            continue
        if password != getpass.getpass("한 번 더 입력: "):
            print("  두 입력이 일치하지 않습니다.\n")
            continue
        return password


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="배포용 .env 생성")
    parser.add_argument("--out", help="저장할 파일 경로 (생략하면 화면에만 출력)")
    parser.add_argument(
        "--cors",
        # 예시 값에 한글을 넣으면 안 된다 — 그대로 두면 응답 헤더 인코딩에서 서버가 죽는다.
        default="https://festa.pages.dev,https://festa.example.com,http://localhost:5173",
        help="프론트엔드 도메인 (쉼표 구분)",
    )
    parser.add_argument(
        "--proxy-hops", default="2", help="신뢰할 프록시 홉 수 (기본 2)"
    )
    args = parser.parse_args()

    if args.out:
        target = Path(args.out)
        if target.exists():
            print(f"{target} 이 이미 있습니다. 덮어쓰지 않습니다.", file=sys.stderr)
            return 1

    print("배포용 시크릿을 만듭니다. 개발용과 다른 값이 생성됩니다.\n")
    print("비밀번호는 둘입니다. 국원에게는 아래 두 번째 것만 알려 주세요.\n")
    lead_password = ask_password("최고 관리자 · 국장단")
    print()
    staff_password = ask_password("국원")
    if staff_password == lead_password:
        print("\n  두 비밀번호가 같습니다. 등급을 나눈 의미가 없어집니다.", file=sys.stderr)

    content = TEMPLATE.format(
        secret_key=secrets.token_urlsafe(48),
        admin_hash=hash_password(lead_password),
        staff_hash=hash_password(staff_password),
        ingest_token=secrets.token_urlsafe(32),
        cors_origins=args.cors,
        proxy_hops=args.proxy_hops,
    )

    if args.out:
        target = Path(args.out)
        target.write_text(content, encoding="utf-8")
        print(f"\n생성 완료: {target.resolve()}")
        print("이 파일을 NAS 의 프로젝트 폴더에 '.env' 라는 이름으로 올리세요.")
    else:
        print("\n" + "=" * 70)
        print(content)
        print("=" * 70)
        print("위 내용을 NAS 프로젝트 폴더의 '.env' 파일로 저장하세요.")

    print("\n남은 할 일:")
    print("  1. CORS_ORIGINS 를 실제 프론트엔드 주소로 교체")
    print("  2. Cloudflare 를 DNS 전용으로 쓴다면 TRUSTED_PROXY_HOPS 를 1 로")
    print("  3. INGEST_TOKEN 을 두 스프레드시트의 Apps Script 속성에 등록")
    print("  4. 관리자 화면 > 관리자 탭에서 역할군마다 등급(국장단 / 국원) 확인")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
