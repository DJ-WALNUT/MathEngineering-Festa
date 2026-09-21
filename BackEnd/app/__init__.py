"""Flask 앱 팩토리."""

from __future__ import annotations

import logging
import os
import secrets

from flask import Flask, jsonify
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config, resolve_database_uri
from .extensions import db, limiter

__all__ = ["create_app"]


def create_app(config_object: type[Config] | None = None) -> Flask:
    # .env 로드는 app.config 모듈이 import 될 때 이미 끝나 있다.
    app = Flask(__name__)
    config_object = config_object or Config
    app.config.from_object(config_object)
    app.config["SQLALCHEMY_DATABASE_URI"] = resolve_database_uri(config_object)

    _ensure_secret_key(app)

    # 한글이 \uXXXX 로 이스케이프되지 않게 한다.
    # (Flask 2.3 부터 JSON_AS_ASCII 설정은 무시되고 이 속성이 대신한다)
    app.json.ensure_ascii = False

    # Cloudflare → 시놀로지 리버스 프록시를 거치므로 원 IP 를 복원해야
    # rate limit 이 의미를 갖는다.
    hops = app.config.get("TRUSTED_PROXY_HOPS", 1)
    if hops > 0:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops)

    db.init_app(app)
    limiter.init_app(app)

    CORS(
        app,
        resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}},
        allow_headers=["Content-Type", "Authorization", "X-Ingest-Token"],
        methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        supports_credentials=False,
        max_age=3600,
    )

    from .routes import admin_bp, ingest_bp, public_bp

    app.register_blueprint(public_bp, url_prefix="/api")
    app.register_blueprint(ingest_bp, url_prefix="/api/ingest")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")

    _register_error_handlers(app)
    _register_cli(app)

    with app.app_context():
        from . import models  # noqa: F401  테이블 등록
        from .database import configure_sqlite, ensure_schema, log_startup_state

        configure_sqlite(db.engine)
        # 모델이 계속 바뀌는 단계라, 기동 때마다 스키마를 맞춘다.
        # (create_all 만으로는 기존 테이블에 컬럼이 추가되지 않는다)
        ensure_schema(app, db)

        # 배정 항목은 데이터라서, 빈 DB 로 시작하면 조차 없다.
        from .assignments import ensure_default_fields

        seeded = ensure_default_fields()
        if seeded["created"]:
            app.logger.info("배정 항목 기본값 생성: %s", ", ".join(seeded["created"]))
        if seeded["converted"]:
            app.logger.info(
                "배정 항목 종류 변경: %s (이미 배정된 값은 선택지로 옮겼습니다)",
                ", ".join(seeded["converted"]),
            )

        # 출석 회차도 데이터다. 없으면 셀프 체크인이 열릴 자리 자체가 없다.
        from .attendance import ensure_default_sessions

        new_sessions = ensure_default_sessions()
        if new_sessions:
            app.logger.info("출석 회차 기본값 생성: %s", ", ".join(new_sessions))

        # 관리자도 마찬가지다. 최고 관리자 계정이 없으면 아무도 들어올 수 없다.
        from .admins import (
            SUPER_USERNAME,
            ensure_default_roles,
            ensure_role_tiers,
            ensure_super_admin,
        )

        if ensure_super_admin():
            app.logger.info("최고 관리자 계정 생성: %s", SUPER_USERNAME)
        created_roles = ensure_default_roles()
        if created_roles:
            app.logger.info("관리자 역할군 기본값 생성: %s", ", ".join(created_roles))
        # 등급 컬럼이 뒤늦게 붙어, 쓰던 DB 의 역할군은 등급이 비어 있다.
        # 비워 두면 전원이 국원 비밀번호로 밀리므로 이름을 보고 되살린다.
        filled_tiers = ensure_role_tiers()
        if filled_tiers:
            app.logger.info("관리자 역할군 등급 채움: %s", ", ".join(filled_tiers))

        log_startup_state(app, db)

    _check_admin_hash(app)
    if not app.config.get("INGEST_TOKEN"):
        app.logger.warning("INGEST_TOKEN 이 비어 있어 폼/입금 수집이 차단됩니다.")

    return app


def _check_admin_hash(app: Flask) -> None:
    """관리자 해시가 온전한지 기동 시 확인한다.

    .env 를 거치며 값이 잘리면 로그인만 계속 실패하고 원인은 드러나지 않는다.
    (예전 '$' 구분자 해시는 docker compose 가 변수로 해석해 망가뜨렸다)
    그래서 형식 자체를 확인해 로그에 남긴다.

    비밀번호가 둘(국장단 / 국원)이라 둘 다 본다. 국원용은 없어도 되지만,
    **없다는 사실은 알려야 한다** — 화면에서는 등급을 나눠 놓고 실제로는 한
    비밀번호로 다 열리는 상태를 조용히 두면 나눴다고 믿게 된다.
    """
    from .security import _split_stored

    stored = app.config.get("ADMIN_PASSWORD_HASH", "")
    if not stored:
        app.logger.warning("ADMIN_PASSWORD_HASH 가 비어 있어 관리자 로그인이 불가합니다.")
        return

    if _split_stored(stored) is None:
        app.logger.error(
            "ADMIN_PASSWORD_HASH 형식이 올바르지 않습니다 (길이 %d). "
            "값이 .env 를 거치며 잘렸을 수 있습니다. "
            "컨테이너 안에서 'flask check-password' 로 확인하세요.",
            len(stored),
        )

    staff = app.config.get("STAFF_PASSWORD_HASH", "")
    if not staff:
        app.logger.warning(
            "STAFF_PASSWORD_HASH 가 비어 있습니다. 국원도 국장단과 같은 비밀번호로 "
            "들어옵니다. 나누려면 scripts/hash_password.py --staff 로 만들어 .env 에 넣으세요."
        )
    elif _split_stored(staff) is None:
        app.logger.error(
            "STAFF_PASSWORD_HASH 형식이 올바르지 않습니다 (길이 %d). "
            "국원 로그인이 계속 실패합니다.",
            len(staff),
        )


def _ensure_secret_key(app: Flask) -> None:
    if app.config.get("SECRET_KEY"):
        return
    if os.getenv("FLASK_ENV") == "production" or os.getenv("FLASK_DEBUG") not in ("1", "true"):
        app.logger.warning(
            "SECRET_KEY 가 없어 임시 키를 생성합니다. 재시작하면 관리자 세션이 모두 만료됩니다."
        )
    app.config["SECRET_KEY"] = secrets.token_urlsafe(48)


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(400)
    def bad_request(error):  # noqa: ANN001
        return jsonify({"error": "bad_request", "message": "요청 형식을 확인해 주세요."}), 400

    @app.errorhandler(404)
    def not_found(error):  # noqa: ANN001
        return jsonify({"error": "not_found"}), 404

    @app.errorhandler(413)
    def too_large(error):  # noqa: ANN001
        return jsonify({"error": "payload_too_large", "message": "업로드 파일이 너무 큽니다."}), 413

    @app.errorhandler(429)
    def rate_limited(error):  # noqa: ANN001
        return jsonify({
            "error": "rate_limited",
            "message": "요청이 너무 잦습니다. 잠시 후 다시 시도해 주세요.",
        }), 429

    @app.errorhandler(500)
    def server_error(error):  # noqa: ANN001
        app.logger.exception("unhandled error")
        db.session.rollback()
        return jsonify({"error": "server_error", "message": "서버 오류가 발생했습니다."}), 500


def _register_cli(app: Flask) -> None:
    import click

    @app.cli.command("init-db")
    def init_db() -> None:
        """테이블을 생성하고 모델과 스키마를 맞춘다."""
        from .database import ensure_schema

        result = ensure_schema(app, db)
        click.echo(f"DB 준비 완료: {result}")

    @app.cli.command("db-info")
    def db_info() -> None:
        """DB 위치 · 보관 중인 행 수 · 모델과의 스키마 차이를 출력한다."""
        from .database import diff_schema, row_counts, sqlite_path

        click.echo(f"DB 위치 : {sqlite_path(db.engine) or db.engine.url}")
        click.echo("행 수 :")
        for name, count in row_counts(db).items():
            click.echo(f"   {name:<24} {count}")

        diff = diff_schema(db.engine, db.metadata)
        if diff["missing_tables"]:
            click.echo(f"없는 테이블 : {', '.join(diff['missing_tables'])}")
        if diff["missing_columns"]:
            names = [f"{t.name}.{c.name}" for t, c in diff["missing_columns"]]
            click.echo(f"없는 컬럼 (기동 시 자동 추가됨) : {', '.join(names)}")
        if diff["missing_indexes"]:
            names = [index.name for index in diff["missing_indexes"]]
            click.echo(f"없는 인덱스 (기동 시 자동 생성됨) : {', '.join(names)}")
        if diff["unknown_columns"]:
            names = [f"{t}.{c}" for t, c in diff["unknown_columns"]]
            click.echo(f"모델에 없는 컬럼 (그대로 둠) : {', '.join(names)}")
        if not any(diff.values()):
            click.echo("스키마가 모델과 일치합니다.")

    @app.cli.command("backup")
    def backup_cmd() -> None:
        """DB 파일을 data/backups/ 로 복사한다."""
        from .database import backup_sqlite

        target = backup_sqlite(db.engine, reason="manual")
        click.echo(f"백업 완료: {target}" if target else "백업할 SQLite 파일이 없습니다.")

    @app.cli.command("hash-password")
    @click.argument("password")
    def hash_password_cmd(password: str) -> None:
        """관리자 비밀번호 해시를 출력한다."""
        from .security import hash_password

        click.echo(hash_password(password))

    @app.cli.command("check-password")
    def check_password_cmd() -> None:
        """지금 컨테이너가 들고 있는 해시를 점검하고, 비밀번호가 맞는지 확인한다."""
        import getpass

        from .admins import TIERS
        from .security import describe_hash, tiers_matching

        stored = {
            "lead": app.config.get("ADMIN_PASSWORD_HASH", ""),
            "staff": app.config.get("STAFF_PASSWORD_HASH", ""),
        }
        for tier in TIERS:
            value = stored[tier["key"]]
            click.echo(f"[{tier['label']}] {tier['envKey']}")
            if tier["key"] == "staff" and not value:
                click.echo("  비어 있습니다 → 국원도 국장단과 같은 비밀번호를 씁니다.")
            else:
                click.echo("  " + describe_hash(value))

        if not stored["lead"]:
            return

        password = getpass.getpass("확인할 비밀번호 (화면에 표시되지 않음): ")
        opened = tiers_matching(password)
        if opened:
            names = ", ".join(t["label"] for t in TIERS if t["key"] in opened)
            click.echo(f"일치합니다. 이 비밀번호로 들어올 수 있는 등급: {names}")
        else:
            click.echo(
                "어느 등급과도 일치하지 않습니다.\n"
                "  해시 형식이 정상인데도 틀리다면, 해시를 만든 비밀번호와 다른 것입니다.\n"
                "  scripts/hash_password.py 로 새로 만들어 .env 를 교체하세요."
            )

    @app.cli.command("rematch")
    @click.option("--all", "match_all", is_flag=True, help="이미 매칭된 건까지 전부 재처리")
    def rematch_cmd(match_all: bool) -> None:
        """입금 재매칭."""
        from .matching import rematch_deposits

        result = rematch_deposits(only_unresolved=not match_all)
        click.echo(result)


logging.getLogger("flask_limiter").setLevel(logging.ERROR)
