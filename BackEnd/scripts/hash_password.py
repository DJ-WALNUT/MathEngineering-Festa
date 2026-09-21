"""관리자 비밀번호 해시 생성기.

비밀번호는 **등급마다 하나**다.

    python scripts/hash_password.py            # ADMIN_PASSWORD_HASH (최고 관리자·국장단)
    python scripts/hash_password.py --staff    # STAFF_PASSWORD_HASH (국원)

(입력한 비밀번호는 화면에 표시되지 않는다)
출력된 한 줄을 .env 의 같은 이름 항목에 그대로 넣는다.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.security import hash_password  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="관리자 비밀번호 해시 생성")
    parser.add_argument(
        "--staff",
        action="store_true",
        help="국원용 비밀번호 (STAFF_PASSWORD_HASH). 생략하면 국장단용",
    )
    args = parser.parse_args()

    env_key = "STAFF_PASSWORD_HASH" if args.staff else "ADMIN_PASSWORD_HASH"
    who = "국원" if args.staff else "최고 관리자·국장단"

    password = getpass.getpass(f"{who} 비밀번호: ")
    if len(password) < 8:
        print("8자 이상으로 설정해 주세요.", file=sys.stderr)
        return 1
    if password != getpass.getpass("한 번 더 입력: "):
        print("두 입력이 일치하지 않습니다.", file=sys.stderr)
        return 1

    print()
    print(f"{env_key}=" + hash_password(password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
