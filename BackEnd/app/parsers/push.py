"""카카오뱅크 입금 푸시 알림 파서.

안드로이드 공기계의 알림 포워더(MacroDroid / Tasker / 커스텀 앱)가 보내는
JSON 을 해석한다. 카카오뱅크 알림 문구는 앱 버전에 따라 바뀌므로

  1) 포워더가 구조화된 필드를 보내주면 그걸 최우선으로 쓰고
  2) 아니면 알려진 패턴들을 순서대로 시도하고
  3) 그래도 안 되면 토큰 휴리스틱으로 이름을 추린다.

어느 경로든 원문은 통째로 저장하므로, 규칙을 고친 뒤 재파싱할 수 있다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from ..utils import normalize_name, now_kst, parse_amount, parse_datetime, split_depositor

# 입금으로 간주할 키워드 / 명백히 입금이 아닌 키워드
_DEPOSIT_HINTS = ("입금", "보냈어요", "받았어요", "이체받", "송금받")
_NON_DEPOSIT_HINTS = ("출금", "결제", "인출", "이체했", "보냈습니다", "취소")

_BALANCE_RE = re.compile(r"잔액\s*[:은는]?\s*([\d,]+)")
_AMOUNT_AFTER_DEPOSIT_RE = re.compile(r"입금\s*[:]?\s*([\d,]+)\s*원?")
_AMOUNT_BEFORE_DEPOSIT_RE = re.compile(r"([\d,]+)\s*원\s*(?:을)?\s*(?:입금|송금|이체)")
_ANY_AMOUNT_RE = re.compile(r"([\d,]+)\s*원")

# 이름이 특정되는 대표 문형들.
# 이름 그룹은 lazy 로 두고 '님/님이/님께서' 만 따로 떼어낸다.
# '이' 를 단독 조사로 허용하면 '김민이' 같은 이름의 끝 글자를 잘라먹는다.
_NAME_PATTERNS = (
    re.compile(r"(?P<name>[가-힣A-Za-z][가-힣A-Za-z0-9]{0,29}?)\s*(?:님(?:이|께서|께)?|씨)?\s*[\d,]+\s*원"),
    re.compile(r"입금\s*[\d,]+\s*원\s*[\n\|·/,]+\s*(?P<name>[가-힣A-Za-z][가-힣A-Za-z0-9]{0,29})"),
    re.compile(r"입금\s*[\d,]+\s*원\s+(?P<name>[가-힣A-Za-z][가-힣A-Za-z0-9]{0,29})"),
    re.compile(r"(?P<name>[가-힣A-Za-z][가-힣A-Za-z0-9]{0,29})\s*[\d,]+\s*원?\s*입금"),
    re.compile(r"입금\s*(?P<name>[가-힣A-Za-z][가-힣A-Za-z0-9]{0,29})\s*[\d,]+"),
)

# 이름 후보에서 제외할 잡음 토큰
_STOPWORDS = {
    "입금", "출금", "잔액", "카카오뱅크", "카뱅", "알림", "원", "님", "계좌",
    "모임통장", "세이프박스", "적요", "내용", "확인", "이체", "송금", "거래",
}
_TIME_TOKEN_RE = re.compile(r"^\d{1,4}([:/.\-]\d{1,2})+$")
_DECORATION_RE = re.compile(r"[\[\]()<>{}※★☆·|/,]")


@dataclass
class ParsedDeposit:
    ok: bool
    reason: str = ""
    raw_name: str = ""
    name_norm: str = ""
    digit_suffix: str = ""
    amount: int | None = None
    balance_after: int | None = None
    occurred_at: datetime | None = None


def _collect_text(payload: dict) -> str:
    parts: list[str] = []
    for key in ("title", "subtitle", "text", "body", "message", "content", "bigText", "raw"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    # 중복 문구(제목이 본문에 그대로 포함되는 경우)는 접어둔다
    unique: list[str] = []
    for part in parts:
        if not any(part in existing for existing in unique):
            unique.append(part)
    return "\n".join(unique)


def _looks_like_deposit(text: str) -> bool:
    has_deposit = any(hint in text for hint in _DEPOSIT_HINTS)
    if has_deposit:
        return True
    return False


def _extract_balance(text: str) -> int | None:
    match = _BALANCE_RE.search(text)
    return parse_amount(match.group(1)) if match else None


def _extract_amount(text: str, balance: int | None) -> int | None:
    for pattern in (_AMOUNT_AFTER_DEPOSIT_RE, _AMOUNT_BEFORE_DEPOSIT_RE):
        match = pattern.search(text)
        if match:
            value = parse_amount(match.group(1))
            if value and value != balance:
                return value
    # 잔액이 아닌 첫 번째 금액
    for match in _ANY_AMOUNT_RE.finditer(text):
        start = max(match.start() - 4, 0)
        if "잔액" in text[start : match.start()]:
            continue
        value = parse_amount(match.group(1))
        if value and value != balance:
            return value
    return None


def _extract_name_by_heuristic(text: str, amount: int | None, balance: int | None) -> str:
    """금액/시각/기관명을 걷어낸 뒤 남는 토큰 중 이름다운 것을 고른다."""
    cleaned = _ANY_AMOUNT_RE.sub(" ", text)
    cleaned = _DECORATION_RE.sub(" ", cleaned)
    for value in (amount, balance):
        if value is not None:
            cleaned = cleaned.replace(f"{value:,}", " ").replace(str(value), " ")

    best = ""
    for token in cleaned.split():
        token = token.strip()
        if not token or token in _STOPWORDS or _TIME_TOKEN_RE.match(token):
            continue
        stripped = token
        for word in _STOPWORDS:
            stripped = stripped.replace(word, "")
        stripped = stripped.strip()
        if not stripped or stripped.isdigit():
            continue
        if not re.search(r"[가-힣A-Za-z]", stripped):
            continue
        if len(stripped) > len(best):
            best = stripped
    return best


def _extract_name(payload: dict, text: str, amount: int | None, balance: int | None) -> str:
    for key in ("name", "sender", "depositor", "counterparty", "from"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    for pattern in _NAME_PATTERNS:
        match = pattern.search(text)
        if match:
            candidate = match.group("name").strip()
            if candidate and candidate not in _STOPWORDS:
                return candidate

    return _extract_name_by_heuristic(text, amount, balance)


def parse_push_payload(payload: dict) -> ParsedDeposit:
    """알림 포워더 JSON → ParsedDeposit."""
    if not isinstance(payload, dict):
        return ParsedDeposit(ok=False, reason="JSON 객체가 아닙니다")

    text = _collect_text(payload)
    explicit_amount = parse_amount(payload.get("amount"))
    if not text and explicit_amount is None:
        return ParsedDeposit(ok=False, reason="본문과 금액이 모두 비어 있습니다")

    if text and not explicit_amount and not _looks_like_deposit(text):
        if any(hint in text for hint in _NON_DEPOSIT_HINTS):
            return ParsedDeposit(ok=False, reason="입금 알림이 아닙니다 (출금/결제)")
        return ParsedDeposit(ok=False, reason="입금 키워드를 찾지 못했습니다")

    balance = parse_amount(payload.get("balance")) or _extract_balance(text)
    amount = explicit_amount or _extract_amount(text, balance)
    if amount is None or amount <= 0:
        return ParsedDeposit(ok=False, reason="입금 금액을 읽지 못했습니다", balance_after=balance)

    raw_name = _extract_name(payload, text, amount, balance)
    name_part, digits = split_depositor(raw_name)

    occurred_at = (
        parse_datetime(payload.get("occurred_at"))
        or parse_datetime(payload.get("postedAt"))
        or parse_datetime(payload.get("posted_at"))
        or parse_datetime(payload.get("timestamp"))
        or now_kst()
    )

    return ParsedDeposit(
        ok=True,
        raw_name=raw_name,
        name_norm=normalize_name(name_part),
        digit_suffix=digits,
        amount=amount,
        balance_after=balance,
        occurred_at=occurred_at,
    )
