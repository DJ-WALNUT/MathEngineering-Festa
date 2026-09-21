"""이미 들어와 있는 학과명에서 폼 안내 문구를 떼어 낸다.

구글폼 학과 선택지 중 몇 개에는 `자연공학계열 (26년도 기준, 1학년만 선택 가능)` 처럼
**폼을 채우는 사람에게 하는 말**이 괄호로 붙어 있다. 학과 이름이 아니므로 명찰과
명단에 그대로 인쇄되면 곤란하고, 더 나쁜 것은 같은 학과가 둘로 갈린다는 점이다 —
`자연공학계열` 과 `자연공학계열 (26년도 …)` 이 서로 다른 값이 되어 조 편성과 집계가
어긋난다.

앞으로 들어오는 응답은 수집 경로(`app/services.py`)에서 알아서 떼어 낸다. 이 스크립트는
**그 전에 이미 들어와 있는 것들**을 한 번 정리하기 위한 것이다.

    python scripts/clean_departments.py          # 무엇이 바뀔지 보여주기만 한다
    python scripts/clean_departments.py --apply   # 실제로 고친다 (미리 사본을 남긴다)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402
from app.database import backup_sqlite  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Participant  # noqa: E402
from app.services import normalize_department  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="학과명에서 폼 안내 문구 제거")
    parser.add_argument("--apply", action="store_true", help="실제로 고친다 (기본은 미리보기)")
    args = parser.parse_args()

    application = create_app()
    with application.app_context():
        people = db.session.query(Participant).order_by(Participant.name.asc()).all()
        changes = [
            (person, person.department, normalize_department(person.department))
            for person in people
            if normalize_department(person.department) != person.department
        ]

        if not changes:
            print("고칠 것이 없습니다.")
            return 0

        # 같은 값끼리 묶어 보여 준다. 한 줄씩 137번 지나가면 무엇이 바뀌는지 안 보인다.
        grouped: dict[tuple[str | None, str | None], int] = {}
        for _, before, after in changes:
            grouped[(before, after)] = grouped.get((before, after), 0) + 1

        for (before, after), count in sorted(grouped.items(), key=lambda item: -item[1]):
            print(f"{count:3d}명  {before!r}\n       → {after!r}")
        print(f"\n합계 {len(changes)}명")

        if not args.apply:
            print("\n미리보기입니다. 실제로 고치려면 --apply 를 붙이세요.")
            return 0

        backup = backup_sqlite(db.engine, reason="clean-departments")
        for person, _, after in changes:
            person.department = after
        db.session.commit()
        print(f"\n{len(changes)}명을 고쳤습니다. 사본: {backup}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
