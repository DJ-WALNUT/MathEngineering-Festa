"""입금 ↔ 참가자 매칭 엔진.

전제: **입금 1건은 참가자 1명의 것이다.** 한 사람이 여러 명 몫을 한 번에 보내는
일은 없다고 확인되었다. 그래서 금액 조합을 역산해 합산 입금을 추측하지 않는다.
(반대 방향, 즉 한 참가자가 여러 번에 나눠 내는 것은 가능하다)

입금자명 규칙("이름+전화뒷4자리")이 지켜지지 않는 것을 전제로 4단계 폴백을 둔다.

  1) 이름 + 전화 뒷4자리 일치, 후보 유일     → 자동 연결 (확신 높음)
  2) 이름 일치, 후보 유일 + 금액이 미납액과 동일 → 자동 연결
  3) 이름은 맞으나 동명이인 다수 / 금액 불일치   → AMBIGUOUS (관리자 확인)
  4) 이름 매칭 실패                          → UNMATCHED (관리자 확인)

자동 연결은 절대 관리자의 수동 처리를 덮어쓰지 않는다(manual_locked).

## 금액이 하나가 아니다

참가비가 본 행사비 + 뒤풀이비 두 겹이고, **뒤풀이비는 별도 안내로 나중에 걷는다.**
그래서 뒤풀이 신청자가 지금 보낼 법한 금액이 하나가 아니다 — 본 행사비만
(안내 전), 뒤풀이비만 (안내 후), 또는 둘을 합쳐서. 2단계에서 '미납액과 정확히
같은가'만 보면 셋 중 둘이 금액 불일치로 떨어져 확인 필요 큐에 쌓인다.
`plausible_amounts` 가 이 셋을 모두 인정한다.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from flask import current_app

from .extensions import db
from .models import (
    DEP_AMBIGUOUS,
    DEP_IGNORED,
    DEP_MATCHED,
    DEP_MINOR,
    DEP_UNMATCHED,
    Allocation,
    Deposit,
    Participant,
)
from .utils import normalize_name, split_depositor


def fingerprint_for(
    occurred_at: datetime,
    amount: int,
    balance_after: int | None,
    raw_name: str,
) -> str:
    """중복 제거 지문.

    푸시 알림과 엑셀 업로드가 같은 입금을 각각 넣게 되므로 반드시 필요하다.
    거래 후 잔액이 있으면 그것이 원장에서 거의 유일한 지문 역할을 하고,
    두 경로 간 타임스탬프가 몇 초~몇 분 어긋날 수 있어 날짜까지만 사용한다.
    잔액이 없으면 분 단위 시각 + 입금자명으로 대체한다.
    """
    if balance_after is not None:
        key = f"bal|{occurred_at.date().isoformat()}|{amount}|{balance_after}"
    else:
        key = (
            f"nam|{occurred_at.strftime('%Y-%m-%dT%H:%M')}|{amount}|"
            f"{normalize_name(raw_name)}"
        )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def outstanding_amount(participant: Participant) -> int:
    """아직 채워지지 않은 총 금액. 초과 납입 시 음수."""
    return participant.expected_amount - participant.paid_amount


def plausible_amounts(participant: Participant) -> set[int]:
    """이 사람이 지금 보낼 법한 금액들.

    뒤풀이 신청자는 본 행사비만 먼저 낼 수도, 뒤풀이비만 따로 낼 수도, 둘을
    합쳐 한 번에 낼 수도 있다. 셋 다 정상이므로 셋 다 매칭 신호로 인정한다.
    뒤풀이에 가지 않는 사람은 어차피 한 값으로 모인다.
    """
    amounts: set[int] = set()

    total_left = outstanding_amount(participant)
    if total_left > 0:
        amounts.add(total_left)

    base_left = participant.base_fee - participant.base_paid
    if base_left > 0:
        amounts.add(base_left)

    fee = participant.afterparty_fee
    after_left = fee - min(participant.afterparty_paid, fee)
    if after_left > 0:
        amounts.add(after_left)

    return amounts


def _clear_auto_allocations(deposit: Deposit) -> None:
    for alloc in list(deposit.allocations):
        if alloc.created_by == "auto":
            deposit.allocations.remove(alloc)
            db.session.delete(alloc)


def _allocate(deposit: Deposit, participant: Participant, reason: str) -> None:
    db.session.add(
        Allocation(
            deposit=deposit,
            participant=participant,
            amount=deposit.amount,
            created_by="auto",
        )
    )
    deposit.status = DEP_MATCHED
    deposit.match_reason = reason


def _unresolved(deposit: Deposit, status: str, reason: str) -> None:
    deposit.status = status
    deposit.match_reason = reason


def _no_name_match(deposit: Deposit, reason: str) -> None:
    """이름이 전혀 매칭되지 않은 입금의 최종 처리.

    참가비에 한참 못 미치는 소액은 '기타 입금'으로 갈라 둔다.
    계좌를 참가비 전용으로 쓰지 않으면 이런 잡음이 확인 필요 큐를 덮어버려,
    정작 봐야 할 건이 묻히기 때문이다. 버리는 것이 아니라 분류일 뿐이다.

    이름이 하나라도 맞은 건은 금액이 작아도 여기로 오지 않는다.
    (부분 납입일 수 있으므로 반드시 사람이 봐야 한다)
    """
    threshold = current_app.config.get("MINOR_DEPOSIT_THRESHOLD", 0)
    if threshold and deposit.amount < threshold:
        _unresolved(
            deposit,
            DEP_MINOR,
            f"참가비와 무관해 보이는 소액 입금 ({threshold:,}원 미만) · {reason}",
        )
    else:
        _unresolved(deposit, DEP_UNMATCHED, reason)


def match_deposit(deposit: Deposit) -> str:
    """입금 1건을 매칭하고 최종 status 를 돌려준다.

    호출자가 db.session.commit() 을 책임진다.
    """
    if deposit.manual_locked or deposit.status == DEP_IGNORED:
        return deposit.status
    if not current_app.config.get("AUTO_MATCH_ENABLED", True):
        _unresolved(deposit, DEP_UNMATCHED, "자동 매칭 비활성화")
        return deposit.status

    _clear_auto_allocations(deposit)
    db.session.flush()

    if not deposit.name_norm:
        _no_name_match(deposit, "입금자명을 읽지 못했습니다")
        return deposit.status

    candidates: list[Participant] = (
        db.session.query(Participant)
        .filter(Participant.name_norm == deposit.name_norm)
        .filter(Participant.is_cancelled.is_(False))
        .all()
    )

    if not candidates:
        _no_name_match(deposit, "일치하는 신청자 없음")
        return deposit.status

    # --- 1단계: 이름 + 전화 뒷4자리 ---
    last4 = deposit.digit_suffix[-4:] if len(deposit.digit_suffix) >= 4 else ""
    if last4:
        exact = [c for c in candidates if c.phone_last4 == last4]
        if len(exact) == 1:
            target = exact[0]
            if outstanding_amount(target) <= 0:
                _unresolved(
                    deposit,
                    DEP_AMBIGUOUS,
                    "이름+연락처는 일치하나 이미 납입이 완료된 참가자입니다",
                )
            else:
                _allocate(deposit, target, "이름+전화 뒷4자리 일치")
            return deposit.status
        if len(exact) > 1:
            _unresolved(deposit, DEP_AMBIGUOUS, f"이름+뒷4자리가 같은 신청자 {len(exact)}명")
            return deposit.status
        # 뒷자리가 학번 등 다른 숫자일 수 있으므로 이름 매칭으로 계속 진행한다.

    # --- 2~3단계: 이름 기반 ---
    open_candidates = [c for c in candidates if outstanding_amount(c) > 0]
    if not open_candidates:
        _unresolved(deposit, DEP_AMBIGUOUS, "동명 신청자가 모두 납입 완료 상태입니다")
        return deposit.status

    amount_fit = [c for c in open_candidates if deposit.amount in plausible_amounts(c)]
    if len(amount_fit) == 1:
        _allocate(deposit, amount_fit[0], "이름 일치 + 금액 일치")
        return deposit.status

    if len(amount_fit) > 1:
        _unresolved(
            deposit,
            DEP_AMBIGUOUS,
            f"이름과 금액이 모두 같은 신청자 {len(amount_fit)}명 — 확인 필요",
        )
        return deposit.status

    # --- 4단계: 금액이 맞지 않음 ---
    if len(open_candidates) == 1:
        target = open_candidates[0]
        # 참가비가 두 겹이라 '예상 금액'이 하나가 아니다. 총 미납액만 적어 두면
        # 뒤풀이 신청자에게 "17,000원을 안 냈다"고 읽혀, 본 행사비는 다 낸 사람에게
        # 관리자가 전액을 다시 걷으러 간다. 인정되는 금액을 전부 적는다.
        expected = " · ".join(f"{amount:,}원" for amount in sorted(plausible_amounts(target)))
        _unresolved(
            deposit,
            DEP_AMBIGUOUS,
            f"이름은 일치하나 금액 불일치 (예상 {expected or '없음'} / 입금 {deposit.amount:,}원)",
        )
    else:
        _unresolved(
            deposit,
            DEP_AMBIGUOUS,
            f"동명 신청자 {len(open_candidates)}명 중 금액으로 특정 불가",
        )
    return deposit.status


def rematch_deposits(only_unresolved: bool = True) -> dict:
    """전체(또는 미해결) 입금을 재매칭한다.

    - 신규 폼 응답이 들어온 뒤 기존 미매칭 건을 다시 태울 때
    - 파싱 규칙을 고친 뒤 일괄 재처리할 때
    """
    query = db.session.query(Deposit).filter(Deposit.manual_locked.is_(False))
    query = query.filter(Deposit.status != DEP_IGNORED)
    if only_unresolved:
        # 기타 입금도 다시 태운다. 늦게 신청서를 낸 사람이 소액을 먼저 보냈을 수 있다.
        query = query.filter(Deposit.status.in_([DEP_UNMATCHED, DEP_AMBIGUOUS, DEP_MINOR]))

    counts = {DEP_MATCHED: 0, DEP_AMBIGUOUS: 0, DEP_UNMATCHED: 0, DEP_MINOR: 0}
    # 오래된 입금부터 처리해 부분 입금의 선후 관계가 뒤집히지 않게 한다.
    for deposit in query.order_by(Deposit.occurred_at.asc(), Deposit.id.asc()).all():
        status = match_deposit(deposit)
        counts[status] = counts.get(status, 0) + 1
    db.session.commit()
    return {"processed": sum(counts.values()), "byStatus": counts}
