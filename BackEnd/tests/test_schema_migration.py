"""스키마 자동 반영 테스트.

배포가 '컨테이너 삭제 → 이미지 재빌드' 방식이고 모델이 아직 계속 바뀌는 단계라,
기존 DB 파일 위에 새 코드가 올라가는 상황이 반복된다.
`create_all()` 은 기존 테이블에 컬럼을 추가해 주지 않으므로,
그대로 두면 필드를 하나 늘릴 때마다 `no such column` 으로 죽는다.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("INGEST_TOKEN", "test-token")

from app import create_app  # noqa: E402
from app.database import backup_sqlite, diff_schema, row_counts, sqlite_path  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Participant  # noqa: E402

# 신규 컬럼이 없던 시절의 participants 테이블
LEGACY_SCHEMA = """
CREATE TABLE participants (
    id INTEGER PRIMARY KEY,
    phone VARCHAR(20) UNIQUE NOT NULL,
    phone_last4 VARCHAR(4),
    name VARCHAR(80) NOT NULL,
    name_norm VARCHAR(80),
    student_id VARCHAR(40),
    department VARCHAR(80),
    gender VARCHAR(20),
    is_council_member BOOLEAN,
    expected_amount INTEGER,
    declared_depositor VARCHAR(80),
    form_row_key VARCHAR(120),
    submitted_at DATETIME,
    submission_count INTEGER,
    extra_json TEXT,
    status_override VARCHAR(20),
    memo TEXT,
    is_cancelled BOOLEAN,
    created_at DATETIME,
    updated_at DATETIME
)
"""


@pytest.fixture()
def legacy_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """예전 스키마 + 관리자가 손으로 넣은 데이터가 들어 있는 DB 파일."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db_path = tmp_path / "mt.db"

    connection = sqlite3.connect(db_path)
    connection.execute(LEGACY_SCHEMA)
    connection.execute(
        "INSERT INTO participants "
        "(phone, name, name_norm, expected_amount, is_council_member, "
        " is_cancelled, submission_count, memo, status_override) "
        "VALUES ('01012345678', '홍길동', '홍길동', 5000, 1, 0, 1, "
        "        '현금으로 받음 - 회계 확인', 'PAID')"
    )
    connection.commit()
    connection.close()
    return db_path


def build_app(db_path: Path):
    application = create_app()
    application.config.update(TESTING=True)
    assert str(db_path) in str(application.config["SQLALCHEMY_DATABASE_URI"])
    return application


@pytest.fixture()
def app(legacy_db: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{legacy_db.as_posix()}")
    application = create_app()
    application.config.update(TESTING=True)
    with application.app_context():
        yield application
        db.session.remove()


def test_missing_columns_are_added_on_startup(app):
    """모델에 늘어난 컬럼이 기존 테이블에 자동으로 붙어야 한다."""
    participant = db.session.query(Participant).one()

    assert participant.name == "홍길동"
    # 새 컬럼이 조회 가능해야 한다 (예전에는 여기서 OperationalError)
    assert participant.group_no is None
    assert participant.joins_afterparty is False
    assert participant.checked_in_at is None
    assert participant.confirmed_at is None
    assert participant.assignments == {}


def test_assignment_fields_are_seeded_on_an_existing_db(app):
    """배정 항목은 데이터라서, 기존 DB 에 새 코드가 올라가도 채워져야 한다."""
    from app.models import AssignmentField

    keys = {row.key for row in db.session.query(AssignmentField).all()}
    assert {"group"} <= keys


def test_existing_data_survives(app):
    """관리자가 손으로 넣은 값이 마이그레이션으로 사라지면 안 된다."""
    participant = db.session.query(Participant).one()

    assert participant.memo == "현금으로 받음 - 회계 확인"
    assert participant.status_override == "PAID"
    assert participant.expected_amount == 5_000
    assert participant.payment_status == "PAID"


def test_defaults_are_backfilled_not_null(app):
    """기본값이 있는 컬럼은 기존 행에도 채워져야 한다 (NULL 이면 필터가 깨진다)."""
    participant = db.session.query(Participant).one()

    assert participant.has_health_issue is False
    assert participant.portrait_consent is True
    assert participant.declared_paid is False

    # NULL 이 아니어야 is_(False) 필터에 걸린다
    matched = (
        db.session.query(Participant)
        .filter(Participant.has_health_issue.is_(False))
        .count()
    )
    assert matched == 1


def test_new_columns_are_writable(app):
    participant = db.session.query(Participant).one()
    participant.group_no = "3"
    participant.joins_afterparty = True
    participant.has_health_issue = True
    db.session.commit()

    reloaded = db.session.query(Participant).one()
    assert (reloaded.group_no, reloaded.joins_afterparty) == ("3", True)
    assert reloaded.has_health_issue is True


def test_backup_is_taken_before_migration(app):
    """스키마를 건드리기 전에 반드시 복사본이 남아야 한다."""
    backups = list((sqlite_path(db.engine).parent / "backups").glob("*-premigrate.db"))
    assert len(backups) == 1

    # 백업본은 마이그레이션 전 상태 그대로여야 한다
    connection = sqlite3.connect(backups[0])
    columns = {row[1] for row in connection.execute("PRAGMA table_info(participants)")}
    connection.close()
    assert "group_no" not in columns
    assert "memo" in columns


def test_schema_matches_model_after_startup(app):
    diff = diff_schema(db.engine, db.metadata)
    assert diff["missing_tables"] == []
    assert diff["missing_columns"] == []
    assert diff["missing_indexes"] == []


def test_missing_indexes_are_created_on_startup(app):
    """인덱스도 함께 챙겨야 한다.

    SQLite 의 `ALTER TABLE ADD COLUMN` 은 UNIQUE 제약을 붙일 수 없어서
    럭키드로우 번호의 유일성은 별도 인덱스로 선언되어 있다. 그런데 create_all()
    은 이미 있는 테이블을 건너뛰므로, 인덱스를 따로 챙기지 않으면 기존 DB 에서는
    영영 만들어지지 않고 번호가 중복될 수 있다.
    """
    indexes = {
        row[0]
        for row in db.session.execute(
            db.text("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'participants'")
        )
    }
    assert "uq_participants_draw_no" in indexes

    # 실제로 중복을 막는지 확인한다 (이름만 있고 unique 가 아니면 의미가 없다)
    db.session.execute(db.text("UPDATE participants SET draw_no = 1"))
    db.session.commit()
    with pytest.raises(Exception):
        db.session.execute(
            db.text(
                "INSERT INTO participants (phone, name, name_norm, draw_no) "
                "VALUES ('01099998888', '중복이', '중복이', 1)"
            )
        )
        db.session.commit()
    db.session.rollback()


def test_new_tables_are_created_on_an_existing_db(app):
    """모델에 테이블이 새로 생겨도 기존 DB 에 자동으로 만들어져야 한다."""
    from app.models import LuckyDraw

    assert db.session.query(LuckyDraw).count() == 0


def test_second_startup_is_a_no_op(legacy_db: Path, monkeypatch: pytest.MonkeyPatch):
    """이미 맞춰진 DB로 다시 띄우면 백업도 변경도 없어야 한다."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{legacy_db.as_posix()}")

    first = create_app()
    with first.app_context():
        db.session.remove()
    backup_dir = legacy_db.parent / "backups"
    after_first = len(list(backup_dir.glob("*.db")))

    second = create_app()
    with second.app_context():
        diff = diff_schema(db.engine, db.metadata)
        assert diff["missing_columns"] == []
        db.session.remove()

    assert len(list(backup_dir.glob("*.db"))) == after_first


def test_unknown_columns_are_left_alone(legacy_db: Path, monkeypatch: pytest.MonkeyPatch):
    """모델에서 사라진 컬럼은 지우지 않고 보고만 한다 (데이터 보호)."""
    connection = sqlite3.connect(legacy_db)
    connection.execute("ALTER TABLE participants ADD COLUMN old_field TEXT")
    connection.execute("UPDATE participants SET old_field = '남아있어야 함'")
    connection.commit()
    connection.close()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{legacy_db.as_posix()}")
    application = create_app()
    with application.app_context():
        diff = diff_schema(db.engine, db.metadata)
        assert ("participants", "old_field") in diff["unknown_columns"]

        value = db.session.execute(
            db.text("SELECT old_field FROM participants")
        ).scalar_one()
        assert value == "남아있어야 함"
        db.session.remove()


def test_wal_mode_is_enabled(app):
    """짧은 시간에 요청이 몰려도 'database is locked' 가 나지 않도록."""
    mode = db.session.execute(db.text("PRAGMA journal_mode")).scalar_one()
    assert mode.lower() == "wal"


def test_manual_backup_includes_latest_writes(app):
    """WAL 체크포인트를 돌린 뒤 복사해야 최신 내용이 백업에 담긴다."""
    participant = db.session.query(Participant).one()
    participant.memo = "백업 직전 수정"
    db.session.commit()

    target = backup_sqlite(db.engine, reason="manual")
    assert target is not None and target.exists()

    connection = sqlite3.connect(target)
    memo = connection.execute("SELECT memo FROM participants").fetchone()[0]
    connection.close()
    assert memo == "백업 직전 수정"


def test_row_counts_reports_state(app):
    counts = row_counts(db)
    assert counts["participants"] == 1
    assert counts["deposits"] == 0
