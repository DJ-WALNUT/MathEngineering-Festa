"""배정 엑셀 양식 만들기 · 읽기.

조 편성은 대개 엑셀에서 끝난다. 명단을 늘어놓고 자르고 붙이며 짠 다음, 그
결과를 시스템에 옮긴다. 그 옮기는 일을 화면에서 한 명씩 다시 고르게 두면
편성을 두 번 하는 셈이 되므로, **지금 명단 그대로 양식을 내려받아 값만 채워
올리는** 길을 둔다.

배정 항목은 운영 중에 늘어난다(`assignment_fields`). 그래서 고정된 서식 파일을
두지 않고 **양식도 그때의 항목 정의를 보고 만든다.** 선택지가 있는 항목은
엑셀 드롭다운으로 걸어 두어, `302` / `302호` / `3-2` 가 섞이는 것을 파일 단계에서
막는다 — 값을 손으로 적게 두지 않는 것이 배정 설계의 전제다.

읽을 때의 규칙은 두 가지다.

  - **빈 칸은 건드리지 않는다.** 아직 안 짠 사람이 그대로 남아 있는 것이
    보통이고, 반쯤 채운 파일을 올렸다고 나머지 배정이 지워지면 안 된다.
  - 배정을 **풀려면** `-` 또는 `미배정` 이라고 적는다.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field as dataclass_field
from datetime import date, datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .models import AssignmentField, Participant
from .parsers.statement import OLE_MAGIC, read_csv_table, read_xlsx_table

SHEET_TITLE = "배정"
GUIDE_SHEET_TITLE = "사용법"
OPTIONS_SHEET_TITLE = "선택지"

ID_HEADER = "참가자ID"
NAME_HEADER = "이름"
STUDENT_ID_HEADER = "학번"
# 배정 항목의 라벨과 부딪히지 않게 괄호를 달아 둔다. '학과'라는 이름의 배정 항목을
# 만들어도 이 열이 그 항목으로 읽히지 않는다.
DEPARTMENT_HEADER = "학과(참고)"

_INFO_HEADERS = (ID_HEADER, NAME_HEADER, STUDENT_ID_HEADER, DEPARTMENT_HEADER)

_ID_ALIASES = ("참가자id", "참가자아이디", "참가자번호", "id")
_NAME_ALIASES = ("이름", "성명", "참가자이름", "name")
_STUDENT_ALIASES = ("학번", "학생번호", "studentid", "studentnumber")
# 참고용으로 실어 보내는 열. 배정 항목과 헷갈리지 않도록 먼저 걸러 낸다.
_IGNORED_ALIASES = ("학과참고", "학과", "전화번호", "연락처", "phone", "비고", "메모")

# 배정을 푸는 표시. 빈 칸은 '건드리지 않음'이라 해제할 방법이 따로 있어야 한다.
CLEAR_TOKENS = {"-", "–", "—", "미배정", "해제"}

_HEADER_SCAN_ROWS = 20
# 사람을 손으로 몇 줄 더 붙여도 드롭다운이 따라오도록 넉넉히 걸어 둔다.
_VALIDATION_SPARE_ROWS = 200

_HEADER_FILL = PatternFill("solid", fgColor="E8F0E3")
_INFO_FILL = PatternFill("solid", fgColor="F5F3EE")


def _norm_header(value) -> str:
    if value is None:
        return ""
    return re.sub(r"[\s_\-()\[\]]", "", str(value)).lower()


# ---------------------------------------------------------------------------
# 양식 만들기
# ---------------------------------------------------------------------------

def build_template(fields: list[AssignmentField], participants: list[Participant]) -> bytes:
    """지금 명단과 항목 정의로 배정 양식(xlsx)을 만든다.

    이미 배정된 값은 채워서 내려준다. 파일을 고쳐 다시 올리는 것이 자연스러워야
    하고, '지금 어디까지 짜였는지'를 파일 하나로 볼 수 있어야 한다.
    """
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = SHEET_TITLE

    headers = [*_INFO_HEADERS, *[field.label for field in fields]]
    sheet.append(headers)

    for participant in participants:
        values = participant.assignments
        sheet.append([
            participant.id,
            participant.name,
            participant.student_id or "",
            participant.department or "",
            *[values.get(field.key, "") for field in fields],
        ])

    _style(sheet, len(headers), len(_INFO_HEADERS))
    _add_dropdowns(workbook, sheet, fields, len(participants))
    _add_guide(workbook, fields)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _style(sheet, column_count: int, info_count: int) -> None:
    for index in range(1, column_count + 1):
        cell = sheet.cell(row=1, column=index)
        cell.font = Font(bold=True)
        cell.fill = _INFO_FILL if index <= info_count else _HEADER_FILL
        cell.alignment = Alignment(horizontal="center")
        sheet.column_dimensions[get_column_letter(index)].width = 10 if index == 1 else 14

    # 사람이 늘어나면 헤더가 화면 밖으로 밀려 어느 열이 무엇인지 알 수 없게 된다.
    sheet.freeze_panes = "E2"


def _add_dropdowns(workbook, sheet, fields: list[AssignmentField], row_count: int) -> None:
    """선택지가 있는 항목에 엑셀 드롭다운을 건다.

    목록을 수식에 직접 박으면 255자 제한에 걸리므로(조가 20개만 넘어도 넘친다)
    숨긴 시트에 적어 두고 범위로 가리킨다.
    """
    options_sheet = workbook.create_sheet(OPTIONS_SHEET_TITLE)
    options_sheet.sheet_state = "hidden"
    last_row = row_count + 1 + _VALIDATION_SPARE_ROWS

    for index, field in enumerate(fields):
        if field.kind != AssignmentField.KIND_CHOICE or not field.options:
            continue

        source_column = get_column_letter(index + 1)
        options_sheet.cell(row=1, column=index + 1, value=field.label)
        for offset, option in enumerate(field.options, start=2):
            options_sheet.cell(row=offset, column=index + 1, value=option)

        validation = DataValidation(
            type="list",
            formula1=(
                f"='{OPTIONS_SHEET_TITLE}'!"
                f"${source_column}$2:${source_column}${len(field.options) + 1}"
            ),
            allow_blank=True,
        )
        validation.errorTitle = "목록에 없는 값"
        validation.error = (
            f"'{field.label}' 은 목록에서 골라 주세요. 새 값이 필요하면 관리자 페이지 →"
            " 배정 → 항목에 선택지를 먼저 추가한 뒤 양식을 다시 내려받으면 됩니다."
        )
        sheet.add_data_validation(validation)

        target_column = get_column_letter(len(_INFO_HEADERS) + index + 1)
        validation.add(f"{target_column}2:{target_column}{last_row}")


def _add_guide(workbook, fields: list[AssignmentField]) -> None:
    guide = workbook.create_sheet(GUIDE_SHEET_TITLE)
    lines = [
        "배정 엑셀 사용법",
        "",
        f"1. '{SHEET_TITLE}' 시트에서 항목 칸을 채우고 그대로 올리면 반영됩니다.",
        "2. 빈 칸은 건드리지 않습니다. 반쯤 채워 올려도 나머지 배정은 그대로 남습니다.",
        "3. 배정을 풀려면 그 칸에 -  (또는 '미배정') 이라고 적어 주세요.",
        "4. 선택지가 있는 항목은 목록에서 골라 주세요. 목록에 없는 값은 반영되지 않습니다.",
        "5. 참가자ID 열은 사람을 알아보는 열쇠입니다. 지우거나 고치지 마세요.",
        "   (지웠다면 학번으로, 학번도 없으면 이름으로 찾습니다. 동명이인은 건너뜁니다)",
        "6. 참가가 확정된 사람만 배정됩니다. 확정 전인 사람은 건너뛰고 알려 드립니다.",
        "",
        "지금 양식에 들어 있는 항목",
    ]
    for field in fields:
        if field.kind == AssignmentField.KIND_CHOICE:
            options = ", ".join(field.options) if field.options else "(선택지 없음)"
            lines.append(f"  · {field.label} — 목록에서 고르기: {options}")
        else:
            lines.append(f"  · {field.label} — 자유 입력")

    for line in lines:
        guide.append([line])
    guide.column_dimensions["A"].width = 100
    guide.cell(row=1, column=1).font = Font(bold=True, size=13)


# ---------------------------------------------------------------------------
# 읽기
# ---------------------------------------------------------------------------

@dataclass
class SheetRow:
    row_number: int
    participant_id: int | None
    name: str
    student_id: str
    #: 배정 항목 key -> 값. 빈 문자열이면 '배정 해제'다.
    values: dict[str, str]


@dataclass
class SheetResult:
    rows: list[SheetRow] = dataclass_field(default_factory=list)
    skipped: list[dict] = dataclass_field(default_factory=list)
    header_row: int | None = None
    #: 파일에서 알아본 배정 항목의 라벨. 열 이름을 고쳐 버린 경우를 알리는 데 쓴다.
    field_labels: list[str] = dataclass_field(default_factory=list)


def _cell(row: list, index: int | None):
    if index is None or index >= len(row):
        return None
    return row[index]


def _text(value) -> str:
    """셀 하나를 문자열로. 엑셀이 숫자로 바꿔 버린 학번·조 번호를 되돌린다."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    return str(value).strip()


def _map_header(row: list, fields: list[AssignmentField]) -> tuple[dict, dict]:
    """헤더 한 줄 → (기본 열 위치, {열 번호: 배정 항목})."""
    base: dict[str, int] = {}
    columns: dict[int, AssignmentField] = {}
    taken: set[str] = set()

    for index, cell in enumerate(row):
        key = _norm_header(cell)
        if not key:
            continue
        if "id" not in base and key in _ID_ALIASES:
            base["id"] = index
            continue
        if "name" not in base and key in _NAME_ALIASES:
            base["name"] = index
            continue
        if "student_id" not in base and key in _STUDENT_ALIASES:
            base["student_id"] = index
            continue
        if key in _IGNORED_ALIASES:
            continue
        for field in fields:
            # 라벨이 같은 항목이 둘이면 나온 순서대로 하나씩 짝지어 준다.
            if field.key in taken:
                continue
            if key in (_norm_header(field.label), field.key.lower()):
                columns[index] = field
                taken.add(field.key)
                break

    return base, columns


def _read_table(data: bytes, filename: str) -> list[list]:
    lowered = (filename or "").lower()
    if lowered.endswith((".xlsx", ".xlsm")):
        if data[:8] == OLE_MAGIC:
            raise ValueError(
                "비밀번호가 걸린 엑셀 파일입니다. 비밀번호를 풀고 다시 올려 주세요."
            )
        return read_xlsx_table(io.BytesIO(data))
    if lowered.endswith((".csv", ".txt")):
        return read_csv_table(data)
    if lowered.endswith(".xls"):
        raise ValueError("구형 .xls 는 지원하지 않습니다. .xlsx 로 저장해 주세요.")
    raise ValueError("지원하지 않는 파일 형식입니다 (.xlsx / .csv)")


def parse_assignment_sheet(
    data: bytes, filename: str, fields: list[AssignmentField]
) -> SheetResult:
    """배정 엑셀을 읽어 행 목록으로 만든다. 명단 대조는 호출부가 한다."""
    table = _read_table(data, filename)
    result = SheetResult()

    base: dict[str, int] = {}
    columns: dict[int, AssignmentField] = {}
    for index, row in enumerate(table[:_HEADER_SCAN_ROWS]):
        found_base, found_columns = _map_header(list(row), fields)
        # 사람을 알아볼 열 하나와 배정 항목 하나는 있어야 쓸 수 있는 헤더다.
        if found_columns and (found_base.keys() & {"id", "name", "student_id"}):
            result.header_row = index
            base, columns = found_base, found_columns
            break

    if result.header_row is None:
        raise ValueError(
            "배정 표의 헤더를 찾지 못했습니다. '참가자ID'(또는 이름 · 학번) 열과 배정 항목"
            " 열이 있는지 확인해 주세요. 양식을 내려받아 그 파일에 채우면 가장 안전합니다."
        )

    result.field_labels = [field.label for field in columns.values()]

    for offset, raw_row in enumerate(table[result.header_row + 1:], start=result.header_row + 2):
        row = list(raw_row)
        if not any(cell not in (None, "") for cell in row):
            continue

        values: dict[str, str] = {}
        for index, field in columns.items():
            text = _text(_cell(row, index))
            if not text:
                # 빈 칸은 건드리지 않는다. 아직 안 짠 사람이 그대로 남아 있는 것이 보통이다.
                continue
            values[field.key] = "" if text in CLEAR_TOKENS else text

        if not values:
            continue

        raw_id = _text(_cell(row, base.get("id")))
        participant_id = int(raw_id) if raw_id.isdigit() else None
        result.rows.append(
            SheetRow(
                row_number=offset,
                participant_id=participant_id,
                name=_text(_cell(row, base.get("name"))),
                student_id=_text(_cell(row, base.get("student_id"))),
                values=values,
            )
        )

    return result
