"""이름/전화번호/금액/일시 정규화 유틸.

입금자명과 구글폼 응답을 대조하려면 표기 흔들림을 먼저 흡수해야 한다.
여기서 하는 정규화가 매칭 정확도를 사실상 결정한다.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

# 이름에서 제거할 흔한 접미/장식 (카카오뱅크 입금자명에 종종 붙는다)
_NAME_NOISE = re.compile(r"(주식회사|\(주\)|㈜|님)")
# 이름 정규화 시 살릴 문자: 한글/영문/숫자
_NAME_KEEP = re.compile(r"[^0-9A-Za-z가-힣]")
_TRAILING_DIGITS = re.compile(r"(\d+)\s*$")
_LEADING_DIGITS = re.compile(r"^\s*(\d+)")
_AMOUNT_RE = re.compile(r"-?[\d,]+(?:\.\d+)?")


def now_kst() -> datetime:
    """KST 기준 naive datetime.

    전 구간을 KST naive 로 통일한다. 국내 전용 서비스이고,
    카카오뱅크 알림/엑셀이 모두 KST 로 내려오므로 변환 지점을 없애는 편이 안전하다.
    """
    return datetime.now(KST).replace(tzinfo=None)


def normalize_name(raw: str | None) -> str:
    """비교용 이름 키. 공백/기호 제거 + 영문 대문자화 + NFC 정규화."""
    if not raw:
        return ""
    text = unicodedata.normalize("NFC", str(raw))
    text = _NAME_NOISE.sub("", text)
    text = _NAME_KEEP.sub("", text)
    return text.upper()


def normalize_phone(raw: str | None) -> str:
    """숫자만 남긴 전화번호. +82 / 82 접두는 0 으로 되돌린다."""
    if not raw:
        return ""
    digits = re.sub(r"\D", "", str(raw))
    if digits.startswith("82") and len(digits) >= 11:
        digits = "0" + digits[2:]
    return digits


def phone_last4(phone: str | None) -> str:
    digits = normalize_phone(phone)
    return digits[-4:] if len(digits) >= 4 else ""


def normalize_student_id(raw: str | None) -> str:
    """비교용 학번 키.

    폼에는 '2026-1234', '20261234', 'A1234' 처럼 제각각 적힌다.
    구분자를 걷어내고 대문자로 맞춰야 체크인에서 헛되이 튕기지 않는다.
    """
    if not raw:
        return ""
    return re.sub(r"[^0-9A-Za-z]", "", str(raw)).upper()


def mask_name(name: str | None) -> str:
    """홍길동 -> 홍*동, 김하 -> 김*, 외자/영문도 안전하게 처리."""
    if not name:
        return ""
    text = str(name).strip()
    if len(text) <= 1:
        return text
    if len(text) == 2:
        return text[0] + "*"
    return text[0] + "*" * (len(text) - 2) + text[-1]


def mask_phone(phone: str | None) -> str:
    digits = normalize_phone(phone)
    if len(digits) < 4:
        return ""
    return f"{digits[:3]}-****-{digits[-4:]}" if len(digits) >= 10 else f"****{digits[-4:]}"


def split_depositor(raw: str | None) -> tuple[str, str]:
    """입금자명을 (이름부분, 숫자꼬리) 로 분리한다.

    '홍길동5678' -> ('홍길동', '5678')
    '홍길동 5678' -> ('홍길동', '5678')
    '5678홍길동' -> ('홍길동', '5678')
    '홍길동' -> ('홍길동', '')
    """
    if not raw:
        return "", ""
    text = unicodedata.normalize("NFC", str(raw)).strip()
    text = _NAME_NOISE.sub("", text).strip()

    match = _TRAILING_DIGITS.search(text)
    if match:
        name_part = text[: match.start()].strip()
        if name_part:  # 숫자만 있는 입금자명은 이름으로 보지 않는다
            return name_part, match.group(1)

    match = _LEADING_DIGITS.match(text)
    if match:
        name_part = text[match.end() :].strip()
        if name_part:
            return name_part, match.group(1)

    return text, ""


def parse_amount(raw) -> int | None:
    """'45,000원', '45000', 45000.0 -> 45000. 실패 시 None."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(round(raw))
    match = _AMOUNT_RE.search(str(raw))
    if not match:
        return None
    try:
        return int(round(float(match.group(0).replace(",", ""))))
    except ValueError:
        return None


_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y.%m.%d %H:%M:%S",
    "%Y.%m.%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y%m%d%H%M%S",
    "%Y-%m-%d",
    "%Y.%m.%d",
    "%Y/%m/%d",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y",
)


def parse_datetime(raw) -> datetime | None:
    """다양한 표기의 일시를 KST naive datetime 으로."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.astimezone(KST).replace(tzinfo=None) if raw.tzinfo else raw
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        return parsed.astimezone(KST).replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def to_iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None
