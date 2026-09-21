"""수집 API.

- /ingest/form   : 구글 시트 Apps Script 가 폼 제출 시 호출
- /ingest/deposit: 안드로이드 공기계의 알림 포워더가 카카오뱅크 입금 알림을 전달
- /ingest/ping   : 포워더 배선 점검용 (저장하지 않고 해석 결과만 돌려준다)

셋 다 X-Ingest-Token 공유 시크릿으로 보호한다.
"""

from __future__ import annotations

import hashlib
import json

from flask import Blueprint, current_app, jsonify, request

from ..extensions import db
from ..matching import rematch_deposits
from ..models import SRC_PUSH, UnparsedNotification
from ..parsers import parse_push_payload
from ..security import require_ingest_token
from ..services import register_deposit, upsert_participant
from ..utils import now_kst

ingest_bp = Blueprint("ingest", __name__)

_PREVIEW_KEYS = ("title", "text", "body", "message", "content", "bigText", "raw")


def _payload_from_request() -> dict:
    """요청 본문을 dict 로 만든다.

    포워더(MacroDroid 등)가 알림 원문을 JSON 문자열에 그대로 끼워 넣으면,
    본문에 큰따옴표나 줄바꿈이 섞이는 순간 JSON 이 깨진다. 그때 본문을 통째로
    버리면 입금 1건이 사라지므로, 파싱에 실패하면 원문 전체를 raw 로 받는다.
    덕분에 Content-Type: text/plain 으로 알림 문구만 보내도 동작한다.
    """
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        return payload

    body = request.get_data(as_text=True).strip()
    if not body:
        return {}
    return {"raw": body, "_malformed": True}


def _preview_of(payload: dict) -> str:
    parts = [
        str(payload[key]).strip()
        for key in _PREVIEW_KEYS
        if isinstance(payload.get(key), str) and payload[key].strip()
    ]
    return " / ".join(parts)[:400] if parts else json.dumps(payload, ensure_ascii=False)[:400]


def _store_unparsed(payload: dict, reason: str) -> UnparsedNotification:
    """읽지 못한 알림을 원문 그대로 보관한다.

    같은 문구가 반복 전송되면 새 행을 만들지 않고 횟수만 올린다.
    """
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    fingerprint = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    entry = (
        db.session.query(UnparsedNotification)
        .filter(UnparsedNotification.fingerprint == fingerprint)
        .one_or_none()
    )
    if entry is not None:
        entry.receive_count += 1
        entry.last_received_at = now_kst()
        entry.reason = reason
        return entry

    entry = UnparsedNotification(
        fingerprint=fingerprint,
        payload_json=serialized,
        preview=_preview_of(payload),
        reason=reason,
    )
    db.session.add(entry)
    return entry


@ingest_bp.post("/form")
@require_ingest_token
def ingest_form():
    """폼 응답 1건 또는 여러 건을 반영한다.

    기대 형식:
      {"row": 12, "values": {"이름": "홍길동", "전화번호": "010-...", ...}}
      {"rows": [{"row": 12, "values": {...}}, ...]}          (전체 동기화용)
    """
    payload = request.get_json(silent=True) or {}
    entries = payload.get("rows")
    if not isinstance(entries, list):
        entries = [payload]

    results = {"created": 0, "updated": 0, "skipped": 0}
    problems: list[dict] = []

    for entry in entries:
        if not isinstance(entry, dict):
            results["skipped"] += 1
            continue
        values = entry.get("values")
        if not isinstance(values, dict):
            values = {k: v for k, v in entry.items() if k not in ("row", "sheet")}
        row_key = None
        if entry.get("row") is not None:
            row_key = f"{entry.get('sheet') or 'form'}:{entry.get('row')}"

        participant, outcome = upsert_participant(values, row_key=row_key)
        if participant is None:
            results["skipped"] += 1
            problems.append({"row": entry.get("row"), "reason": outcome.split(":", 1)[-1]})
        else:
            results[outcome] += 1

    db.session.commit()

    # 새 신청자가 생겼으니, 먼저 들어와 있던 미매칭 입금을 다시 태운다.
    rematch = rematch_deposits(only_unresolved=True)

    return jsonify({"ok": True, "result": results, "problems": problems, "rematch": rematch})


@ingest_bp.post("/deposit")
@require_ingest_token
def ingest_deposit():
    """카카오뱅크 입금 알림 1건.

    포워더는 알림 원문만 넘겨도 되고, 파싱이 가능하면
    name / amount / balance / occurred_at 을 함께 넘겨도 된다.

    읽지 못한 알림도 원문을 보관한다. 입금 1건이 조용히 사라지면 안 되기 때문이다.

    카카오뱅크가 유심 없는 기기에서 로그인을 막고 있어 공기계 포워딩은 현재 불가능하다.
    그래서 이 경로는 기본적으로 꺼져 있고, 입금 수집은 거래내역 파일 업로드로 한다.
    """
    if not current_app.config.get("PUSH_INGEST_ENABLED", False):
        return jsonify({
            "ok": False,
            "error": "push_ingest_disabled",
            "message": (
                "알림 포워딩 경로가 꺼져 있습니다. "
                "입금 확인은 관리자 페이지의 거래내역 파일 업로드로 처리합니다. "
                "(유심이 꽂힌 전용 기기를 쓰려면 PUSH_INGEST_ENABLED=true 로 켜세요)"
            ),
        }), 503

    payload = _payload_from_request()
    parsed = parse_push_payload(payload)

    if not parsed.ok:
        entry = _store_unparsed(payload, parsed.reason)
        db.session.commit()
        # 포워더 입장에서는 '전달 성공'이므로 재시도를 유도하지 않는다.
        return jsonify({
            "ok": False,
            "stored": True,
            "unparsedId": entry.id,
            "receiveCount": entry.receive_count,
            "reason": parsed.reason,
        }), 202

    deposit, created = register_deposit(
        occurred_at=parsed.occurred_at,
        amount=parsed.amount,
        balance_after=parsed.balance_after,
        raw_name=parsed.raw_name,
        name_norm=parsed.name_norm,
        digit_suffix=parsed.digit_suffix,
        source=SRC_PUSH,
        raw_payload=payload,
    )
    db.session.commit()

    return jsonify({
        "ok": True,
        "created": created,
        "depositId": deposit.id,
        "status": deposit.status,
        "matchReason": deposit.match_reason,
    })


@ingest_bp.post("/ping")
@require_ingest_token
def ingest_ping():
    """포워더 배선 점검용.

    토큰·헤더·본문이 제대로 도착하는지 확인하고, 보낸 알림이 현재 규칙으로
    해석되는지까지 즉시 알려준다. 아무것도 저장하지 않으므로 몇 번을 눌러도 안전하다.
    """
    payload = _payload_from_request()
    if not payload:
        return jsonify({
            "ok": False,
            "message": "본문이 비어 있습니다. MacroDroid 의 본문(Body) 칸을 확인해 주세요.",
        }), 400

    parsed = parse_push_payload(payload)
    return jsonify({
        "ok": True,
        "message": "연결 정상입니다. 저장은 하지 않았습니다.",
        "bodyWasValidJson": not payload.pop("_malformed", False),
        "receivedKeys": sorted(payload.keys()),
        "preview": _preview_of(payload),
        "parse": {
            "ok": parsed.ok,
            "reason": parsed.reason,
            "depositorName": parsed.raw_name,
            "amount": parsed.amount,
            "balanceAfter": parsed.balance_after,
        },
    })
