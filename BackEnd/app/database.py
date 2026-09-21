"""DB 준비 · 스키마 자동 반영 · 백업.

배포 방식이 '컨테이너 중지 → 삭제 → 이미지 재빌드' 이고, 관리자 페이지에서
어떤 정보를 다룰지가 아직 확정되지 않아 **모델이 계속 바뀐다.**
이 두 조건이 겹치면 두 가지가 터진다.

  1. 데이터 소실 — DB 파일이 컨테이너 안에 있으면 재빌드와 함께 사라진다
     → 볼륨으로 빼고, 기동 시 실제 행 수를 로그로 찍어 확인할 수 있게 한다.

  2. 스키마 불일치 — `create_all()` 은 **없는 테이블만** 만든다.
     기존 테이블에 컬럼을 추가해 주지 않아서, 모델에 필드를 하나 늘리는 순간
     `no such column` 으로 죽는다.
     → 기동 시 모델과 실제 스키마를 비교해 빠진 컬럼을 ALTER TABLE 로 채운다.

컬럼 추가와 인덱스 생성만 자동으로 처리한다. 삭제·타입 변경은 데이터가 날아갈 수 있어
로그로 알리기만 하고 손대지 않는다.

인덱스를 함께 챙기는 이유: SQLite 의 `ALTER TABLE ADD COLUMN` 은 UNIQUE 제약을
붙일 수 없다. 그래서 유일성이 필요한 컬럼(럭키드로우 번호 등)은 컬럼이 아니라
별도 인덱스로 선언하는데, `create_all()` 은 이미 있는 테이블을 건너뛰므로
그 인덱스가 영영 만들어지지 않는다. 그 구멍을 여기서 메운다.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from flask import Flask
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

BACKUP_KEEP = 20


# ---------------------------------------------------------------------------
# SQLite 설정
# ---------------------------------------------------------------------------

def configure_sqlite(engine: Engine) -> None:
    """연결마다 PRAGMA 를 건다.

    WAL: 읽기와 쓰기가 서로를 막지 않는다. 체크인처럼 짧은 시간에 요청이
    몰릴 때 'database is locked' 를 크게 줄여 준다.
    busy_timeout: 그래도 잠기면 즉시 실패하지 않고 잠시 기다린다.
    """
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()


def sqlite_path(engine: Engine) -> Path | None:
    if engine.dialect.name != "sqlite":
        return None
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    return Path(database)


# ---------------------------------------------------------------------------
# 백업
# ---------------------------------------------------------------------------

def backup_sqlite(engine: Engine, reason: str = "manual") -> Path | None:
    """WAL 을 정리한 뒤 DB 파일을 통째로 복사한다.

    체크포인트를 먼저 돌리지 않으면 -wal 파일에만 있는 최신 내용이 빠진다.
    """
    path = sqlite_path(engine)
    if path is None or not path.exists():
        return None

    with engine.begin() as connection:
        connection.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))

    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"{path.stem}-{stamp}-{reason}.db"
    shutil.copy2(path, target)

    # 오래된 백업 정리
    backups = sorted(backup_dir.glob(f"{path.stem}-*.db"))
    for stale in backups[:-BACKUP_KEEP]:
        stale.unlink(missing_ok=True)

    return target


# ---------------------------------------------------------------------------
# 스키마 비교 · 반영
# ---------------------------------------------------------------------------

def _sql_literal(value: object) -> str | None:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    return None


def _default_clause(column: sa.Column) -> str | None:
    """추가할 컬럼의 DEFAULT 절. 기존 행을 이 값으로 채우게 된다."""
    if column.server_default is not None:
        return None  # 이미 DDL 에 포함된다
    default = column.default
    if default is None or not getattr(default, "is_scalar", False):
        return None
    return _sql_literal(default.arg)


def _add_column_ddl(table: sa.Table, column: sa.Column, dialect) -> str:  # noqa: ANN001
    type_sql = column.type.compile(dialect)
    parts = [f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {type_sql}']

    default_sql = _default_clause(column)
    if default_sql is not None:
        # NOT NULL 은 기본값이 있을 때만 안전하게 붙일 수 있다
        if not column.nullable:
            parts.append("NOT NULL")
        parts.append(f"DEFAULT {default_sql}")
    return " ".join(parts)


def diff_schema(engine: Engine, metadata: sa.MetaData) -> dict:
    """모델과 실제 DB의 차이를 조사한다 (변경하지 않음)."""
    inspector = sa.inspect(engine)
    existing_tables = set(inspector.get_table_names())

    missing_tables: list[str] = []
    missing_columns: list[tuple[sa.Table, sa.Column]] = []
    missing_indexes: list[sa.Index] = []
    unknown_columns: list[tuple[str, str]] = []

    for table in metadata.sorted_tables:
        if table.name not in existing_tables:
            missing_tables.append(table.name)
            continue
        actual = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name not in actual:
                missing_columns.append((table, column))
        for name in actual - {c.name for c in table.columns}:
            unknown_columns.append((table.name, name))

        # 인덱스는 이름으로 비교한다. 컬럼이 아직 없는 인덱스는 컬럼을 먼저
        # 추가해야 만들 수 있으므로, 순서는 ensure_schema 가 지킨다.
        actual_indexes = {idx["name"] for idx in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name not in actual_indexes:
                missing_indexes.append(index)

    return {
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
        "missing_indexes": missing_indexes,
        "unknown_columns": unknown_columns,
    }


def ensure_schema(app: Flask, db) -> dict:  # noqa: ANN001
    """기동 시 스키마를 모델에 맞춘다.

    - 없는 테이블은 만든다
    - 기존 테이블에 빠진 컬럼은 ALTER TABLE 로 추가한다 (기존 데이터 보존)
    - 모델에 없는 컬럼은 건드리지 않고 알리기만 한다

    반환값은 무엇을 했는지 요약한 딕셔너리다.
    """
    engine = db.engine
    metadata = db.metadata
    diff = diff_schema(engine, metadata)

    applied: list[str] = []
    backup: Path | None = None

    if diff["missing_columns"]:
        # 스키마를 건드리기 전에 항상 복사본을 남긴다
        backup = backup_sqlite(engine, reason="premigrate")

    # 새 테이블 생성
    db.create_all()

    # 기존 테이블의 빠진 컬럼 추가
    if diff["missing_columns"]:
        with engine.begin() as connection:
            for table, column in diff["missing_columns"]:
                ddl = _add_column_ddl(table, column, engine.dialect)
                connection.execute(text(ddl))
                applied.append(f"{table.name}.{column.name}")

    # 빠진 인덱스 생성. 컬럼을 추가한 뒤라야 만들 수 있어 순서가 중요하다.
    #
    # 실패해도 기동은 계속한다. UNIQUE 인덱스는 기존 데이터에 이미 중복이 있으면
    # 만들어지지 않는데, 그 때문에 서버가 아예 뜨지 않으면 손쓸 방법이 없어진다.
    indexed: list[str] = []
    for index in diff["missing_indexes"]:
        try:
            with engine.begin() as connection:
                connection.execute(sa.schema.CreateIndex(index, if_not_exists=True))
            indexed.append(index.name)
        except sa.exc.SQLAlchemyError as exc:
            app.logger.error("인덱스 생성 실패: %s — %s", index.name, exc)

    result = {
        "createdTables": diff["missing_tables"],
        "addedColumns": applied,
        "createdIndexes": indexed,
        "unknownColumns": [f"{t}.{c}" for t, c in diff["unknown_columns"]],
        "backup": str(backup) if backup else None,
    }

    if result["createdTables"]:
        app.logger.info("테이블 생성: %s", ", ".join(result["createdTables"]))
    if indexed:
        app.logger.info("인덱스 생성: %s", ", ".join(indexed))
    if applied:
        app.logger.warning(
            "스키마 반영 — 컬럼 %d개 추가: %s (백업: %s)",
            len(applied), ", ".join(applied), backup,
        )
    if result["unknownColumns"]:
        app.logger.info(
            "모델에 없는 컬럼(그대로 둠): %s", ", ".join(result["unknownColumns"])
        )

    return result


# ---------------------------------------------------------------------------
# 상태 확인
# ---------------------------------------------------------------------------

def row_counts(db) -> dict[str, int]:  # noqa: ANN001
    counts: dict[str, int] = {}
    for table in db.metadata.sorted_tables:
        try:
            counts[table.name] = db.session.execute(
                sa.select(sa.func.count()).select_from(table)
            ).scalar_one()
        except sa.exc.SQLAlchemyError:
            counts[table.name] = -1
    return counts


def log_startup_state(app: Flask, db) -> None:  # noqa: ANN001
    """기동 시 DB 위치와 행 수를 남긴다.

    재배포 후 이 로그만 보면 볼륨이 제대로 붙었는지(=데이터가 살아있는지)
    바로 알 수 있다. 0으로 찍히면 볼륨 마운트를 의심해야 한다.
    """
    path = sqlite_path(db.engine)
    counts = row_counts(db)
    summary = " · ".join(f"{name} {count}" for name, count in counts.items() if count)

    app.logger.info("DB 위치: %s", path or db.engine.url)
    app.logger.info("보관 중인 데이터: %s", summary or "(비어 있음)")

    if path is not None and counts.get("participants", 0) == 0:
        app.logger.warning(
            "참가자 데이터가 0건입니다. 재배포 직후라면 볼륨 마운트를 확인하세요 "
            "(docker-compose.yml 의 volumes 가 DATA_DIR 로 연결되어야 합니다)."
        )
