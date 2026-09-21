"""현장 배정 항목.

'무엇을 배정하는가'를 코드가 아니라 데이터로 둔다(`AssignmentField`).
관리자 화면에서 항목을 늘려도 스키마는 그대로이고, 값은 참가자의
`assignments_json` 한 칸에 모인다.

이 모듈이 맡는 일은 세 가지다.
  1. 기본 항목(조) 시드 — 정의가 바뀌면 기존 DB 도 따라오게 한다
  2. 들어온 값 검증 — 정의에 없는 키, 선택지에 없는 값은 받지 않는다
  3. 값 적용 + 사본 컬럼(group_no) 동기화

당일 행사라 숙소 호수도 버스도 없다. 기본 항목은 **조 하나**로 시작하고,
그 밖에 필요한 것(자리·조끼 색·담당 스태프…)은 관리자 화면에서 만든다.
"""

from __future__ import annotations

import json
import re

from .extensions import db
from .models import AssignmentField, Participant

# 값 길이 상한. 조는 사본 컬럼이 String(20) 이라 더 짧게 잡는다.
_MAX_VALUE_LEN = 60
_MAX_MIRROR_LEN = 20

# 조의 값은 전용 컬럼에도 함께 써 둔다.
# 조 단위 집계와 CSV 고정 열, 인덱스 검색이 이 컬럼을 쓰기 때문이다.
# 쓰기는 apply_assignments 한 곳에서만 일어나므로 두 곳이 어긋날 여지는 없다.
MIRROR_COLUMNS = {"group": "group_no"}

# 조별 출석 현황의 기본 기준. 관리자가 다른 항목으로 바꿔 볼 수 있다.
DEFAULT_GROUP_KEY = "group"

DEFAULT_FIELDS = [
    {
        "key": "group",
        "label": "조",
        "kind": AssignmentField.KIND_CHOICE,
        "position": 10,
        # 조 이름은 학생회가 직접 만든다. 처음에는 비어 있고,
        # 관리자 화면에서 '1조', '2조' … 를 추가하면 그때부터 배정할 수 있다.
        "options": [],
    },
]

_KEY_SAFE = re.compile(r"[^a-z0-9_]")


class AssignmentError(ValueError):
    """사용자에게 그대로 보여줄 수 있는 배정 오류."""


# ---------------------------------------------------------------------------
# 정의
# ---------------------------------------------------------------------------

def ensure_default_fields() -> dict[str, list[str]]:
    """기본 항목을 채운다.

    이미 있는 항목은 라벨·선택지를 건드리지 않는다. 학생회가 화면에서 고친 것이기
    때문이다. 다만 **종류(kind)가 바뀌면 기존 DB 도 따라오게 한다.** 새 코드가
    기존 DB 위에 올라가는 배포 방식이라, 여기서 맞춰 주지 않으면 새로 설치한
    곳과 이미 돌던 곳의 동작이 갈린다.
    """
    existing = {row.key: row for row in db.session.query(AssignmentField).all()}
    created: list[str] = []
    converted: list[str] = []

    for spec in DEFAULT_FIELDS:
        field = existing.get(spec["key"])

        if field is None:
            db.session.add(
                AssignmentField(
                    key=spec["key"],
                    label=spec["label"],
                    kind=spec["kind"],
                    options_json=json.dumps(spec["options"], ensure_ascii=False),
                    position=spec["position"],
                    is_system=True,
                    show_on_checkin=True,
                    is_active=True,
                )
            )
            created.append(spec["key"])
            continue

        if field.kind != spec["kind"]:
            _convert_kind(field, spec["kind"])
            converted.append(spec["key"])

    if created or converted:
        db.session.commit()
    return {"created": created, "converted": converted}


def _convert_kind(field: AssignmentField, kind: str) -> None:
    """기본 항목의 종류를 바꾼다.

    자유 입력 → 선택지로 바꾸면 이미 적혀 있던 값이 선택지에 없어 유령이 된다.
    (그 사람의 배정은 남아 있는데 화면의 드롭다운에서는 고를 수 없는 상태)
    그래서 쓰이고 있는 값을 먼저 선택지로 끌어올린 뒤에 종류를 바꾼다.
    """
    if kind == AssignmentField.KIND_CHOICE:
        options = list(field.options)
        options += sorted(value for value in values_in_use(field.key) if value not in options)
        field.options_json = json.dumps(options, ensure_ascii=False)
    field.kind = kind


def values_in_use(key: str) -> set[str]:
    """이 항목으로 실제 배정된 값들. 선택지를 지워도 되는지 판단하는 근거다."""
    return {
        value
        for participant in db.session.query(Participant).all()
        for field_key, value in participant.assignments.items()
        if field_key == key and value
    }


def all_fields(include_inactive: bool = True) -> list[AssignmentField]:
    query = db.session.query(AssignmentField)
    if not include_inactive:
        query = query.filter(AssignmentField.is_active.is_(True))
    return query.order_by(AssignmentField.position.asc(), AssignmentField.id.asc()).all()


def active_fields() -> list[AssignmentField]:
    return all_fields(include_inactive=False)


def make_key(label: str, taken: set[str]) -> str:
    """라벨에서 값 딕셔너리의 키를 만든다.

    한글 라벨은 ASCII 로 옮길 방법이 마땅치 않으므로 `field_N` 으로 떨어뜨린다.
    키는 화면에 나오지 않으니 읽히지 않아도 문제되지 않는다.
    """
    base = _KEY_SAFE.sub("", str(label or "").strip().lower().replace(" ", "_")).strip("_")
    if base and base not in taken:
        return base[:40]

    index = 1
    while f"field_{index}" in taken:
        index += 1
    return f"field_{index}"


def next_position() -> int:
    highest = db.session.query(db.func.max(AssignmentField.position)).scalar()
    return int(highest or 0) + 10


def normalize_options(raw) -> list[str]:
    """선택지 목록 정리. 공백 제거 + 중복 제거 + 순서 보존."""
    if raw is None:
        return []
    if isinstance(raw, str):
        items = re.split(r"[\n,]", raw)
    elif isinstance(raw, list):
        items = raw
    else:
        raise AssignmentError("선택지 형식이 올바르지 않습니다.")

    seen: list[str] = []
    for item in items:
        text = str(item).strip()[:_MAX_VALUE_LEN]
        if text and text not in seen:
            seen.append(text)
    return seen


# ---------------------------------------------------------------------------
# 값
# ---------------------------------------------------------------------------

def _clean_value(field: AssignmentField, raw) -> str:
    """값 하나를 검증한다. 빈 값은 '' 로 돌려주고, 호출부가 배정 해제로 다룬다."""
    if raw is None:
        return ""
    text = str(raw).strip()
    if not text:
        return ""

    if field.kind == AssignmentField.KIND_CHOICE and text not in field.options:
        raise AssignmentError(f"'{field.label}' 에 없는 값입니다: {text}")

    limit = _MAX_MIRROR_LEN if field.key in MIRROR_COLUMNS else _MAX_VALUE_LEN
    if len(text) > limit:
        raise AssignmentError(f"'{field.label}' 값이 너무 깁니다 ({limit}자까지).")
    return text


def apply_assignments(participant: Participant, values: dict) -> dict:
    """참가자의 배정값을 병합한다. 빈 값이 오면 그 항목만 해제한다.

    반환값은 실제로 바뀐 항목만 담은 딕셔너리(감사 로그용).
    """
    if not isinstance(values, dict):
        raise AssignmentError("assignments 는 객체여야 합니다.")

    fields = {field.key: field for field in active_fields()}
    current = participant.assignments
    changes: dict = {}

    for key, raw in values.items():
        field = fields.get(str(key))
        if field is None:
            raise AssignmentError(f"없는 배정 항목입니다: {key}")

        cleaned = _clean_value(field, raw)
        before = current.get(field.key, "")
        if cleaned == before:
            continue

        if cleaned:
            current[field.key] = cleaned
        else:
            current.pop(field.key, None)
        changes[field.key] = cleaned or None

    if changes:
        _store(participant, current)
    return changes


def drop_field_values(key: str) -> int:
    """항목을 지울 때 참가자들에게 남은 값도 함께 치운다."""
    touched = 0
    for participant in db.session.query(Participant).all():
        current = participant.assignments
        if key in current:
            current.pop(key, None)
            _store(participant, current)
            touched += 1
    return touched


def _store(participant: Participant, values: dict) -> None:
    participant.assignments_json = json.dumps(values, ensure_ascii=False) if values else None
    for key, column in MIRROR_COLUMNS.items():
        setattr(participant, column, values.get(key) or None)
