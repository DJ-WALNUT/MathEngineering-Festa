"""DB 모델.

참가자 1명이 여러 번에 나눠 낼 수 있어(부분 입금 후 추가 입금) 입금↔참가자는
`Allocation` 테이블로 잇는다. 반대 방향(입금 1건 → 참가자 여러 명)은
실제로 일어나지 않는다고 확인되어, 화면은 '참가자 1명 지정'만 다룬다.
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .extensions import db
from .utils import mask_name, mask_phone, now_kst, to_iso

# --- 상태 상수 ---

PAY_UNPAID = "UNPAID"          # 입금 없음
PAY_PAID = "PAID"              # 정상 납입
PAY_UNDERPAID = "UNDERPAID"    # 부족 납입
PAY_OVERPAID = "OVERPAID"      # 초과 납입
PAY_REFUNDED = "REFUNDED"      # 환불 처리 (관리자 강제)
PAY_WAIVED = "WAIVED"          # 면제 (관리자 강제)

OVERRIDABLE_STATUSES = {PAY_UNPAID, PAY_PAID, PAY_UNDERPAID, PAY_OVERPAID, PAY_REFUNDED, PAY_WAIVED}

# 참가 확정을 눌러도 되는 납입 상태.
# 초과 납입도 낼 돈은 다 낸 것이므로 포함한다. 차액 환불은 별개의 문제다.
SETTLED_STATUSES = {PAY_PAID, PAY_OVERPAID, PAY_WAIVED}

CHECKIN_SELF = "self"
CHECKIN_STAFF = "staff"

# 출석 회차의 기본 두 개. 값은 CheckinSession.key 와 같다.
#
# 이 행사는 하루짜리라 '출석'이 한 번으로 끝나지 않는다. 낮의 본 행사가 있고,
# 그중 일부만 남는 뒤풀이가 따로 있다. 회차를 코드에 박지 않고 데이터로 두는 이유는
# BackEnd/README.md 의 '출석 회차' 절에 적어 두었다.
SESSION_MAIN = "main"
SESSION_AFTERPARTY = "afterparty"

# 접수 회차. 폼(=스프레드시트)마다 하나씩 붙는다.
# 이 중 스태프 폼만 값이 의미를 갖는다: 그 시트로 들어온 사람은 받는 즉시 스태프가 된다.
INTAKE_STAFF = "staff"

# 요금 구분. 총학생회비 납부 여부에 스태프가 하나 더 붙는다.
FEE_MEMBER = "member"
FEE_NON_MEMBER = "nonmember"
FEE_STAFF = "staff"
FEE_CLASSES = {FEE_MEMBER, FEE_NON_MEMBER, FEE_STAFF}

# 1부 교류전 조장 지원 여부. 폼의 세 갈래 답을 그대로 옮긴다.
# 조 편성할 때 '조장 하고 싶다'는 사람을 먼저 앉히기 위한 값이다.
LEADER_WANT = "want"      # 조장을 하고 싶다
LEADER_OK = "ok"          # 조장을 해도 상관없다
LEADER_NO = "no"          # 조장을 하고 싶지 않다
LEADER_PREFERENCES = {LEADER_WANT, LEADER_OK, LEADER_NO}

# 뒤풀이 참가비 납입 상태. 본 행사비와 따로 센다 — 뒤풀이비는 별도 안내로 나중에
# 걷으므로, 아직 안 낸 것이 본 행사의 '미납'으로 번져서는 안 된다.
AFTER_NONE = "NONE"            # 뒤풀이 미참가 → 해당 없음
AFTER_UNPAID = "UNPAID"        # 참가하지만 아직 뒤풀이비가 안 들어옴
AFTER_UNDERPAID = "UNDERPAID"  # 일부만 들어옴
AFTER_PAID = "PAID"            # 뒤풀이비까지 완납

DEP_UNMATCHED = "UNMATCHED"    # 매칭 실패 → 관리자 처리 필요
DEP_AMBIGUOUS = "AMBIGUOUS"    # 후보는 있으나 확신 부족 → 관리자 확인
DEP_MATCHED = "MATCHED"        # 참가자 확인 완료
DEP_IGNORED = "IGNORED"        # MT와 무관한 입금 (관리자가 직접 지정)
# 이름도 안 맞고 금액도 참가비에 한참 못 미치는 소액.
# 버리지 않고 '기타 입금'으로 갈라 두어, 확인 필요 큐가 잡음으로 차는 것만 막는다.
DEP_MINOR = "MINOR"

# 관리자가 손으로 되돌릴 수 있는 상태
REQUEUE_STATUSES = {DEP_UNMATCHED, DEP_AMBIGUOUS, DEP_MINOR}

SRC_PUSH = "push"
SRC_IMPORT = "import"
SRC_MANUAL = "manual"
# 행사 당일 접수대에서 현금·간편송금으로 받은 것. 계좌 거래내역에는 뜨지 않으므로
# 관리자가 직접 넣고, 정산 때 갈라 보아야 하니 출처를 따로 남긴다.
SRC_ONSITE = "onsite"


class Participant(db.Model):
    """구글폼 응답 1건 = 참가자 1명. 정규화된 전화번호를 자연키로 쓴다."""

    __tablename__ = "participants"
    # 럭키드로우 번호와 개인 카드 토큰의 유일성은 컬럼이 아니라 인덱스로 건다. SQLite 의
    # `ALTER TABLE ADD COLUMN` 은 UNIQUE 제약을 붙일 수 없어, 컬럼에 달면
    # 이미 배포된 DB 에 이 필드를 추가할 수 없다. (database.ensure_schema 가 만든다)
    __table_args__ = (
        Index("uq_participants_draw_no", "draw_no", unique=True),
        Index("uq_participants_card_token", "card_token", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    phone_last4: Mapped[str] = mapped_column(String(4), index=True, default="")
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    name_norm: Mapped[str] = mapped_column(String(80), index=True, default="")

    student_id: Mapped[str | None] = mapped_column(String(40), index=True)
    department: Mapped[str | None] = mapped_column(String(80))
    gender: Mapped[str | None] = mapped_column(String(20))
    emergency_phone: Mapped[str | None] = mapped_column(String(20))

    # 현장 안전 정보. 응급 상황에서 스태프가 즉시 봐야 하므로 보관하지만,
    # 건강정보는 민감정보이므로 관리자 인증 뒤에서만 노출한다.
    has_health_issue: Mapped[bool] = mapped_column(Boolean, default=False)
    health_note: Mapped[str | None] = mapped_column(Text)
    health_action: Mapped[str | None] = mapped_column(Text)
    allergy: Mapped[str | None] = mapped_column(Text)
    portrait_consent: Mapped[bool] = mapped_column(Boolean, default=True)

    is_council_member: Mapped[bool] = mapped_column(Boolean, default=False)
    # 운영 스태프. 참가비가 일반 참가자와 다르므로 회비 구분과 함께 요금을 정한다.
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # 뒤풀이 참가 여부. 신청 폼의 문항에서 그대로 들어오고, 관리자 화면에서 고칠 수 있다.
    # 참가비가 본 행사비 위에 얹히고, 뒤풀이 회차의 출석 대상도 이 값으로 갈린다.
    joins_afterparty: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # 폼에서 '솔로파티 비용은 추후 안내'를 확인했다고 답했는가. 뒤풀이비 안내를 보낼 때
    # 이미 알고 있는 사람과 처음 듣는 사람을 가르는 참고값이다.
    afterparty_fee_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- 이번 폼에서 새로 받는 것들 (조 편성 · 명찰 · 솔로파티에 쓴다) ---
    # 1부 교류전 조장 지원 여부 (LEADER_*). 폼에 문항이 없으면 None.
    leader_preference: Mapped[str | None] = mapped_column(String(10), index=True)
    # 솔로파티에서 부를 이름. 명찰에도 실을 수 있다.
    nickname: Mapped[str | None] = mapped_column(String(40))
    # 태어난 해. '2004년' · '2006.0' 같은 표기가 섞여 들어오므로 숫자로 정리해 담는다.
    birth_year: Mapped[int | None] = mapped_column(Integer)

    # 본 행사비 + 뒤풀이비를 합한 총 청구액. 파생값이지만 컬럼으로 두는 이유는
    # 명단을 금액으로 정렬·검색하기 위해서다. 쓰기는 services.recalc_expected 한 곳뿐이다.
    expected_amount: Mapped[int] = mapped_column(Integer, default=0)
    declared_depositor: Mapped[str | None] = mapped_column(String(80))
    # 폼에서 본인이 '입금했다'고 답한 값. 은행 내역과 어긋나면 먼저 확인할 대상이 된다.
    declared_paid: Mapped[bool] = mapped_column(Boolean, default=False)

    # 접수 회차 (얼리버드 / 본모집). 소속에 따라 접수 기간이 나뉜다.
    intake_round: Mapped[str | None] = mapped_column(String(20), index=True)

    # 참가 확정. 납입이 끝난 사람을 관리자가 명시적으로 눌러 확정한 시점이다.
    # 납입 상태에서 자동으로 파생시키지 않는 이유는, 확정 뒤에 환불·취소가 생기거나
    # 입금이 뒤늦게 정정되어도 '언제 확정했는가'는 그대로 남아야 하기 때문이다.
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(40))

    # 현장 배정. 폼이 아니라 관리자 페이지에서 따로 넣는다.
    # 항목 자체가 운영 중에 늘어나므로(팀·자리·조끼…) 값은 assignments_json 이
    # 단일 진실이고, group_no 는 조 단위 집계·CSV 고정 열·인덱스 검색을 위한
    # 사본이다. 쓰기는 assignments.apply_assignments 한 곳에서만 일어난다.
    #
    # 당일 행사라 숙소 호수·버스가 없어 조 하나로 시작한다. 그 밖의 항목이
    # 필요해지면 관리자 화면에서 만들면 되고, 스키마는 그대로다.
    group_no: Mapped[str | None] = mapped_column(String(20), index=True)
    assignments_json: Mapped[str | None] = mapped_column(Text)

    # 본 행사 회차의 출석 사본. 단일 진실은 CheckIn 행이고 이 두 컬럼은 사본이다
    # (쓰기는 attendance.record_checkin 한 곳뿐). 명찰·CSV·대시보드가 회차를
    # 따지지 않고 '왔는가'만 묻기 때문에 남겨 둔다.
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime)
    checked_in_by: Mapped[str | None] = mapped_column(String(20))  # self | staff

    # 럭키드로우 번호. 체크인한 순서대로 1, 2, 3 … 을 주고 화면에는 001 로 보여준다.
    #
    # 한 번 준 번호는 스태프가 출석을 취소해도 회수하지 않는다. 번호를 다시 쓰면
    # 자기 번호를 외운 채 추첨 화면을 보고 있는 사람과 어긋나 버린다.
    # 대신 추첨 후보에서는 빠진다 (draw.eligible_participants).
    draw_no: Mapped[int | None] = mapped_column(Integer)

    # 개인 QR 에 실리는 값. 명찰에 인쇄되고, 본인 확인 페이지(/p/<token>)의 주소다.
    #
    # 참가자 id 를 그대로 쓰지 않는 이유는 1, 2, 3 … 이 눈에 보이면 남의 카드를
    # 열어 보는 장난이 가능하기 때문이다. 무작위 값은 비용이 들지 않는다.
    card_token: Mapped[str | None] = mapped_column(String(16))

    form_row_key: Mapped[str | None] = mapped_column(String(120), index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    submission_count: Mapped[int] = mapped_column(Integer, default=1)
    extra_json: Mapped[str | None] = mapped_column(Text)

    status_override: Mapped[str | None] = mapped_column(String(20))
    memo: Mapped[str | None] = mapped_column(Text)
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst, onupdate=now_kst)

    allocations: Mapped[list["Allocation"]] = relationship(
        back_populates="participant", cascade="all, delete-orphan"
    )
    checkins: Mapped[list["CheckIn"]] = relationship(
        back_populates="participant", cascade="all, delete-orphan"
    )

    # --- 파생 값 ---

    @property
    def paid_amount(self) -> int:
        return sum(alloc.amount for alloc in self.allocations)

    # --- 참가비는 두 겹이다 ---
    #
    # 본 행사비(총학생회비 납부자 / 미납부자 / 스태프)가 아래에 깔리고, 뒤풀이에
    # 가는 사람만 그 위에 뒤풀이비가 얹힌다. 그런데 **뒤풀이비는 별도 안내로 나중에
    # 걷는다.** 두 겹을 한 덩어리로 세면 뒤풀이 신청자 전원이 안내가 나가기도 전에
    # '미납'으로 물들어, 본 행사 확정을 막아 버린다.
    #
    # 그래서 들어온 돈을 **본 행사비부터 채우고** 남는 것을 뒤풀이비로 넘긴다.
    # 납입 상태도 두 개로 갈라 센다 — 확정·배정·출석의 문을 여는 것은 본 행사비
    # 쪽(payment_status)뿐이고, 뒤풀이비는 배지로만 드러난다.

    @property
    def afterparty_fee(self) -> int:
        return current_afterparty_fee() if self.joins_afterparty else 0

    @property
    def base_fee(self) -> int:
        """본 행사 참가비. expected_amount 에서 뒤풀이비를 덜어낸 값이다."""
        return max(self.expected_amount - self.afterparty_fee, 0)

    @property
    def base_paid(self) -> int:
        return min(self.paid_amount, self.base_fee)

    @property
    def afterparty_paid(self) -> int:
        return max(self.paid_amount - self.base_fee, 0)

    @property
    def payment_status(self) -> str:
        """**본 행사비** 기준 납입 상태."""
        if self.status_override:
            return self.status_override
        # 스태프 참가비가 아직 정해지지 않았거나 0원이면 낼 것이 없다.
        # 그대로 두면 명단 내내 '미납'으로 떠 확인 필요 건에 섞인다.
        if self.base_fee <= 0:
            return PAY_WAIVED
        paid = self.paid_amount
        if paid <= 0:
            return PAY_UNPAID
        if self.base_paid < self.base_fee:
            return PAY_UNDERPAID
        # 뒤풀이비까지 합한 총액을 넘겼을 때만 초과다.
        return PAY_OVERPAID if paid > self.expected_amount else PAY_PAID

    @property
    def afterparty_status(self) -> str:
        """뒤풀이비 납입 상태. 참가하지 않으면 해당 없음."""
        if not self.joins_afterparty:
            return AFTER_NONE
        fee = self.afterparty_fee
        if fee <= 0:
            return AFTER_PAID
        got = self.afterparty_paid
        if got <= 0:
            return AFTER_UNPAID
        return AFTER_PAID if got >= fee else AFTER_UNDERPAID

    @property
    def afterparty_prepaid(self) -> bool:
        """뒤풀이비를 본 행사비와 **한 번에** 보낸 사람.

        뒤풀이비는 별도 안내로 나중에 걷는데, 안내가 나가기 전에 이미 합쳐서
        보낸 사람이 있다. 다시 걷으러 가지 않도록 명단에서 갈라 보여 준다.
        입금 **1건**이 총 청구액을 덮었으면 합산 납부로 본다 — 두 번에 나눠 낸
        사람은 안내를 받고 낸 것이므로 여기 해당하지 않는다.
        """
        if not self.joins_afterparty or self.afterparty_fee <= 0:
            return False
        total = self.base_fee + self.afterparty_fee
        return any(alloc.amount >= total for alloc in self.allocations)

    @property
    def fee_class(self) -> str:
        """요금 구분 한 값. 화면의 드롭다운이 이 값 하나만 다룬다."""
        if self.is_staff:
            return FEE_STAFF
        return FEE_MEMBER if self.is_council_member else FEE_NON_MEMBER

    @property
    def is_settled(self) -> bool:
        """참가 확정을 눌러도 되는 상태인가."""
        return not self.is_cancelled and self.payment_status in SETTLED_STATUSES

    @property
    def is_confirmed(self) -> bool:
        """참가 확정 여부. 취소하면 확정 기록이 남아 있어도 확정으로 보지 않는다."""
        return self.confirmed_at is not None and not self.is_cancelled

    @property
    def draw_label(self) -> str | None:
        """화면에 띄우는 세 자리 표기. 001, 042, 137 …"""
        return f"{self.draw_no:03d}" if self.draw_no else None

    @property
    def extra(self) -> dict:
        if not self.extra_json:
            return {}
        try:
            loaded = json.loads(self.extra_json)
            return loaded if isinstance(loaded, dict) else {}
        except (ValueError, TypeError):
            return {}

    @property
    def assignments(self) -> dict:
        """현장 배정값. {필드 key: 값}. 정의는 AssignmentField 에 있다."""
        if not self.assignments_json:
            return {}
        try:
            loaded = json.loads(self.assignments_json)
            return loaded if isinstance(loaded, dict) else {}
        except (ValueError, TypeError):
            return {}

    def to_public_dict(self) -> dict:
        """본인 조회 응답. 대조에 필요한 최소 정보만 노출한다."""
        return {
            "name": mask_name(self.name),
            "isCouncilMember": self.is_council_member,
            "expectedAmount": self.expected_amount,
            "paidAmount": self.paid_amount,
            "remainingAmount": max(self.expected_amount - self.paid_amount, 0),
            "status": self.payment_status,
            # 본 행사비만 따로. 화면이 '본 행사 / 뒤풀이' 두 줄로 나눠 보여준다.
            "baseFee": self.base_fee,
            "basePaid": self.base_paid,
            # 뒤풀이는 신청한 사람에게만 뜬다.
            "joinsAfterparty": self.joins_afterparty,
            "afterpartyFee": self.afterparty_fee,
            "afterpartyPaid": min(self.afterparty_paid, self.afterparty_fee),
            "afterpartyStatus": self.afterparty_status,
            "afterpartyPrepaid": self.afterparty_prepaid,
            "isCancelled": self.is_cancelled,
            # 참가 확정은 납입 완료와 별개다. 돈이 들어왔다고 자동으로 확정되지 않고,
            # 학생회가 명단을 확인한 뒤 눌러야 확정된다. 화면에서 이 둘을 구분해 보여준다.
            "isConfirmed": self.is_confirmed,
            "confirmedAt": to_iso(self.confirmed_at) if self.is_confirmed else None,
            "lastPaidAt": to_iso(
                max((alloc.deposit.occurred_at for alloc in self.allocations if alloc.deposit), default=None)
            ),
            "checkedAt": to_iso(now_kst()),
        }

    def to_admin_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "phone": self.phone,
            "phoneMasked": mask_phone(self.phone),
            "studentId": self.student_id,
            "department": self.department,
            "gender": self.gender,
            "emergencyPhone": self.emergency_phone,
            "hasHealthIssue": self.has_health_issue,
            "healthNote": self.health_note,
            "healthAction": self.health_action,
            "allergy": self.allergy,
            "portraitConsent": self.portrait_consent,
            "isCouncilMember": self.is_council_member,
            "isStaff": self.is_staff,
            "feeClass": self.fee_class,
            "expectedAmount": self.expected_amount,
            "paidAmount": self.paid_amount,
            "status": self.payment_status,
            "baseFee": self.base_fee,
            "basePaid": self.base_paid,
            "joinsAfterparty": self.joins_afterparty,
            "afterpartyFee": self.afterparty_fee,
            "afterpartyPaid": min(self.afterparty_paid, self.afterparty_fee),
            "afterpartyStatus": self.afterparty_status,
            "afterpartyPrepaid": self.afterparty_prepaid,
            "afterpartyFeeAcknowledged": self.afterparty_fee_acknowledged,
            "leaderPreference": self.leader_preference,
            "nickname": self.nickname,
            "birthYear": self.birth_year,
            "statusOverride": self.status_override,
            "declaredDepositor": self.declared_depositor,
            "declaredPaid": self.declared_paid,
            "intakeRound": self.intake_round,
            "isSettled": self.is_settled,
            "isConfirmed": self.is_confirmed,
            "confirmedAt": to_iso(self.confirmed_at),
            "confirmedBy": self.confirmed_by,
            "assignments": self.assignments,
            "groupNo": self.group_no,
            "checkedInAt": to_iso(self.checked_in_at),
            "checkedInBy": self.checked_in_by,
            # 회차별 출석. {회차 key: ISO 시각}. 본 행사 · 뒤풀이가 한 줄에 같이 보인다.
            "checkins": {
                row.session.key: to_iso(row.at) for row in self.checkins if row.session
            },
            "drawNo": self.draw_no,
            "drawLabel": self.draw_label,
            "submittedAt": to_iso(self.submitted_at),
            "submissionCount": self.submission_count,
            "isCancelled": self.is_cancelled,
            "memo": self.memo,
            "extra": self.extra,
            "allocations": [
                {
                    "id": alloc.id,
                    "depositId": alloc.deposit_id,
                    "amount": alloc.amount,
                    "depositRawName": alloc.deposit.raw_name if alloc.deposit else None,
                    "occurredAt": to_iso(alloc.deposit.occurred_at) if alloc.deposit else None,
                }
                for alloc in self.allocations
            ],
        }


class Deposit(db.Model):
    """계좌 입금 1건. 원문(raw_payload)은 항상 보관해 재파싱이 가능하게 한다."""

    __tablename__ = "deposits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int | None] = mapped_column(Integer)

    raw_name: Mapped[str] = mapped_column(String(120), default="")
    name_norm: Mapped[str] = mapped_column(String(80), index=True, default="")
    digit_suffix: Mapped[str] = mapped_column(String(20), default="")

    source: Mapped[str] = mapped_column(String(20), default=SRC_PUSH)
    raw_payload: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(20), default=DEP_UNMATCHED, index=True)
    match_reason: Mapped[str | None] = mapped_column(String(200))
    manual_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    memo: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst, onupdate=now_kst)

    allocations: Mapped[list["Allocation"]] = relationship(
        back_populates="deposit", cascade="all, delete-orphan"
    )

    @property
    def allocated_amount(self) -> int:
        return sum(alloc.amount for alloc in self.allocations)

    @property
    def unallocated_amount(self) -> int:
        return self.amount - self.allocated_amount

    def to_admin_dict(self) -> dict:
        return {
            "id": self.id,
            "occurredAt": to_iso(self.occurred_at),
            "amount": self.amount,
            "balanceAfter": self.balance_after,
            "rawName": self.raw_name,
            "digitSuffix": self.digit_suffix,
            "source": self.source,
            "status": self.status,
            "matchReason": self.match_reason,
            "manualLocked": self.manual_locked,
            "memo": self.memo,
            "allocatedAmount": self.allocated_amount,
            "unallocatedAmount": self.unallocated_amount,
            "rawPayload": self.raw_payload,
            "allocations": [
                {
                    "id": alloc.id,
                    "participantId": alloc.participant_id,
                    "participantName": alloc.participant.name if alloc.participant else None,
                    "participantPhoneMasked": (
                        mask_phone(alloc.participant.phone) if alloc.participant else None
                    ),
                    "amount": alloc.amount,
                }
                for alloc in self.allocations
            ],
        }


class Allocation(db.Model):
    """입금 ↔ 참가자 연결.

    한 참가자가 여러 번 나눠 내는 경우를 담기 위해 별도 테이블로 둔다.
    스키마상 한 입금을 여러 명에게 쪼갤 수도 있지만, 실제로는 쓰이지 않는다.
    """

    __tablename__ = "allocations"
    __table_args__ = (UniqueConstraint("deposit_id", "participant_id", name="uq_alloc_pair"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deposit_id: Mapped[int] = mapped_column(ForeignKey("deposits.id", ondelete="CASCADE"), index=True)
    participant_id: Mapped[int] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE"), index=True
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[str] = mapped_column(String(40), default="auto")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)

    deposit: Mapped[Deposit] = relationship(back_populates="allocations")
    participant: Mapped[Participant] = relationship(back_populates="allocations")


class LuckyDraw(db.Model):
    """럭키드로우 당첨 기록 1건.

    **추첨은 뽑는 순간 여기에 박힌다.** 화면의 슬롯머신은 이미 정해진 결과를
    드러내는 연출일 뿐이고, 무작위로 돌려서 나온 번호를 결과로 삼지 않는다.
    거꾸로 만들면 두 가지가 터진다 — 250명이 체크인한 자리에서 287번이 나오거나,
    "마음에 안 드니 한 번 더" 가 흔적 없이 가능해진다.

    무효 처리(당첨자가 자리에 없는 경우 등)도 행을 지우지 않고 표시만 남긴다.
    누가 언제 무효로 했는지가 그대로 보여야 뒷말이 생기지 않는다.
    """

    __tablename__ = "lucky_draws"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 몇 번째 추첨인가. 무효 처리된 건은 세지 않아 '1등·2등' 순서가 흐트러지지 않는다.
    round_no: Mapped[int] = mapped_column(Integer, default=1)
    # 걸었던 상품. 이름을 그대로 박아 둔다 — 나중에 목록에서 상품을 지우거나 이름을
    # 고쳐도 "그때 무엇을 걸었는가"는 그대로 읽혀야 한다.
    prize: Mapped[str] = mapped_column(String(80), default="")
    # 상품 목록의 어느 항목이었는지. 남은 수량 집계는 이름이 아니라 이 값으로 센다.
    prize_id: Mapped[str | None] = mapped_column(String(20), index=True)

    draw_no: Mapped[int] = mapped_column(Integer, nullable=False)
    participant_id: Mapped[int | None] = mapped_column(
        ForeignKey("participants.id", ondelete="SET NULL"), index=True
    )
    # 뽑을 때 후보가 몇 명이었나. 나중에 "몇 분의 일이었나"를 답할 수 있어야 한다.
    pool_size: Mapped[int] = mapped_column(Integer, default=0)

    drawn_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst, index=True)
    actor: Mapped[str] = mapped_column(String(40), default="admin")

    voided: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    voided_reason: Mapped[str | None] = mapped_column(String(200))

    participant: Mapped[Participant | None] = relationship()

    @property
    def draw_label(self) -> str:
        return f"{self.draw_no:03d}"

    def to_admin_dict(self, group_key: str | None = None) -> dict:
        person = self.participant
        return {
            "id": self.id,
            "roundNo": self.round_no,
            "prize": self.prize,
            "prizeId": self.prize_id,
            "drawNo": self.draw_no,
            "drawLabel": self.draw_label,
            "poolSize": self.pool_size,
            "drawnAt": to_iso(self.drawn_at),
            "actor": self.actor,
            "voided": self.voided,
            "voidedReason": self.voided_reason,
            # 참가자가 지워졌더라도 번호와 회차는 남는다.
            "name": person.name if person else None,
            "department": person.department if person else None,
            "groupValue": (
                person.assignments.get(group_key) if person and group_key else None
            ),
        }


class CheckinSession(db.Model):
    """출석 회차.

    하루짜리 행사인데도 출석이 한 번으로 끝나지 않는다. 낮의 본 행사가 있고,
    신청자 중 일부만 남는 뒤풀이가 저녁에 따로 있다.

    회차를 코드에 두 개 박지 않고 데이터로 두는 이유는 배정 항목과 같다 —
    운영을 시작하면 회차가 늘어난다(사전 리허설, 2부, 뒤풀이 2차…). 그때마다
    스키마를 고치고 재배포하는 대신 **무엇을 세는가 자체를 데이터로 둔다.**

    `main` 만 `is_system` 으로 잠근다. 럭키드로우 번호와 참가자 사본 컬럼
    (`checked_in_at`)이 이 회차 하나를 전제로 하고 있어, 지우면 출석 현황이
    통째로 비어 버린다.
    """

    __tablename__ = "checkin_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # CheckIn 이 가리키는 열쇠. 만든 뒤에는 바꾸지 않는다.
    key: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(60), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0)

    # 셀프 체크인 창구. 기본은 닫힘 — QR 은 행사 며칠 전부터 돌아다니므로
    # 열어 두면 집결 전에 원격으로 체크인해 버리는 사람이 생긴다.
    is_open: Mapped[bool] = mapped_column(Boolean, default=False)

    # 이 회차의 대상이 뒤풀이 신청자뿐인가. 켜 두면 신청하지 않은 사람이 셀프
    # 체크인을 시도했을 때 명단에 없다고 돌려보내고, 현황의 분모도 신청자 수가 된다.
    afterparty_only: Mapped[bool] = mapped_column(Boolean, default=False)

    # 이 회차의 체크인 순서로 럭키드로우 번호를 매기는가. 본 행사에만 켠다.
    # 두 회차에서 각각 번호를 주면 참가자가 번호 두 개를 외워야 한다.
    gives_draw_no: Mapped[bool] = mapped_column(Boolean, default=False)

    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)

    checkins: Mapped[list["CheckIn"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )

    def to_admin_dict(self) -> dict:
        return {
            "id": self.id,
            "key": self.key,
            "label": self.label,
            "position": self.position,
            "isOpen": self.is_open,
            "afterpartyOnly": self.afterparty_only,
            "givesDrawNo": self.gives_draw_no,
            "isSystem": self.is_system,
            "isActive": self.is_active,
        }


class CheckIn(db.Model):
    """어느 회차에 누가 왔는가. 회차 × 참가자 한 쌍에 한 행."""

    __tablename__ = "checkins"
    __table_args__ = (
        UniqueConstraint("session_id", "participant_id", name="uq_checkin_pair"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("checkin_sessions.id", ondelete="CASCADE"), index=True
    )
    participant_id: Mapped[int] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE"), index=True
    )

    at: Mapped[datetime] = mapped_column(DateTime, default=now_kst, index=True)
    # self(본인이 QR 로) | staff(관리자가 명단에서 눌러)
    by: Mapped[str] = mapped_column(String(20), default=CHECKIN_SELF)
    # 손으로 체크한 관리자 이름. 셀프 체크인이면 비어 있다.
    actor: Mapped[str | None] = mapped_column(String(40))

    session: Mapped[CheckinSession] = relationship(back_populates="checkins")
    participant: Mapped[Participant] = relationship(back_populates="checkins")


class AssignmentField(db.Model):
    """현장 배정 항목의 정의.

    당일 행사라 숙소 호수도 버스도 없다. 필요한 것은 **조** 하나뿐이다.
    그래도 운영을 시작하면 항목이 더 필요해진다(자리, 조끼 색, 담당 스태프…).
    그때마다 컬럼을 늘리고 재배포하는 대신 **무엇을 배정하는가 자체를 데이터로
    둔다.** 값은 Participant.assignments_json 에 담기므로 항목이 늘어도 스키마는
    그대로고, 관리자 화면에서 항목과 선택지를 직접 만들 수 있다.

    조만 `is_system` 으로 잠가 둔다. 조 단위 집계와 CSV 고정 열이 이 항목을
    전제로 하고 있어, 실수로 지우면 출석 현황이 통째로 비어 버린다.
    """

    __tablename__ = "assignment_fields"

    KIND_TEXT = "text"
    KIND_CHOICE = "choice"
    KINDS = {KIND_TEXT, KIND_CHOICE}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 값 딕셔너리의 키. 만든 뒤에는 바꾸지 않는다 (바꾸면 기존 값이 미아가 된다).
    key: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(60), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), default=KIND_TEXT)
    # kind 가 choice 일 때 고를 수 있는 값들. '조를 추가한다'는 곧 여기에 한 줄 넣는 것이다.
    options_json: Mapped[str | None] = mapped_column(Text)

    position: Mapped[int] = mapped_column(Integer, default=0)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    # 셀프 체크인 화면에서 참가자에게 보여줄 항목인지. 조는 보여주고,
    # 내부 관리용 항목(예: 담당 스태프)은 꺼 둘 수 있다.
    show_on_checkin: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)

    @property
    def options(self) -> list[str]:
        if not self.options_json:
            return []
        try:
            loaded = json.loads(self.options_json)
        except (ValueError, TypeError):
            return []
        return [str(item) for item in loaded] if isinstance(loaded, list) else []

    def to_admin_dict(self) -> dict:
        return {
            "id": self.id,
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "options": self.options,
            "position": self.position,
            "isSystem": self.is_system,
            "showOnCheckin": self.show_on_checkin,
            "isActive": self.is_active,
        }


class AdminRole(db.Model):
    """관리자 역할군 — 학생회장 · 국장 · 차장 · 국원 …

    권한을 사람마다 따로 매기면 인원이 바뀔 때마다 다시 짜야 한다. 역할에 매기고
    사람을 역할에 넣으면, 국원이 열 명이어도 한 번만 정하면 된다.

    역할군은 **어느 비밀번호로 들어오는지**도 정한다(`tier`). 탭 권한이 화면을
    정리하는 것이라면 등급은 진짜 문이다 — 국원 비밀번호를 아는 사람은 국장단
    계정으로 들어올 수 없다.
    """

    __tablename__ = "admin_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    #: 이 역할이 볼 수 있는 탭 key 목록 (JSON 배열)
    tabs_json: Mapped[str | None] = mapped_column(Text)
    #: 로그인 등급 — 'lead'(최고 관리자·국장단) 또는 'staff'(국원).
    #: NULL 은 '아직 정해지지 않음'이고, 기동할 때 app.admins.ensure_role_tiers() 가 채운다.
    #: (컬럼이 뒤늦게 추가되므로 기존 행은 NULL 로 생긴다. 그것을 이름으로 되살린다.)
    tier: Mapped[str | None] = mapped_column(String(10))
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)

    accounts: Mapped[list["AdminAccount"]] = relationship(back_populates="role")

    @property
    def tabs(self) -> list[str]:
        return _json_list(self.tabs_json)

    def to_admin_dict(self) -> dict:
        from .admins import TIER_STAFF

        return {
            "id": self.id,
            "name": self.name,
            "tabs": self.tabs,
            "tier": self.tier or TIER_STAFF,
            "position": self.position,
            "memberCount": len(self.accounts),
        }


class AdminAccount(db.Model):
    """관리자 한 명.

    **비밀번호는 계정마다 두지 않는다.** 등급마다 하나씩, `.env` 에 둘이 있을 뿐이다
    (최고 관리자·국장단 / 국원). 그 사람이 어느 쪽을 쓰는지는 역할군의 등급이 정하고,
    ID 는 누가 들어왔는지 밝히는 이름표다.

    등급을 나눈 것은 **국원이 알아야 할 비밀번호로 예산·명단까지 열리지 않게** 하기
    위함이고, ID 를 나눈 것은 **누가 무엇을 했는지 남기기** 위함이다. 지금까지는 모든
    조작이 'admin' 한 이름으로 뭉쳐 있어, 몇 달 뒤에 로그를 봐도 누구였는지 알 수 없었다.
    """

    __tablename__ = "admin_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: 로그인 ID. 보통 본인 이름이고, 최고 관리자만 예외적으로 짧은 아이디를 쓴다.
    username: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    #: 화면과 작업 기록에 뜨는 이름
    display_name: Mapped[str] = mapped_column(String(40), nullable=False)

    role_id: Mapped[int | None] = mapped_column(
        ForeignKey("admin_roles.id", ondelete="SET NULL"), index=True
    )
    #: 개인별로 따로 준 탭. 비어 있으면 역할의 권한을 그대로 따른다.
    tabs_json: Mapped[str | None] = mapped_column(Text)

    #: 최고 관리자. 모든 탭이 열리고, 관리자·역할군을 다룰 수 있는 유일한 계정이다.
    is_super: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)

    role: Mapped[AdminRole | None] = relationship(back_populates="accounts")

    @property
    def own_tabs(self) -> list[str]:
        return _json_list(self.tabs_json)

    def to_admin_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "displayName": self.display_name,
            "roleId": self.role_id,
            "roleName": self.role.name if self.role else None,
            "ownTabs": self.own_tabs,
            "isSuper": self.is_super,
            "isActive": self.is_active,
            # 이 사람이 어느 비밀번호로 들어오는지. 역할군에서 정해져 내려온다.
            "tier": tier_of(self),
            "lastLoginAt": to_iso(self.last_login_at),
        }


def tier_of(account: AdminAccount) -> str:
    """계정의 로그인 등급. 순환 import 를 피하려고 여기서 지연 import 한다."""
    from .admins import tier_for

    return tier_for(account)


def _json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        loaded = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return [str(item) for item in loaded] if isinstance(loaded, list) else []


class Setting(db.Model):
    """재배포 없이 운영 중에 바꿔야 하는 값.

    환경변수로 두면 행사 당일 컨테이너를 다시 띄워야 반영되므로, DB 에 두고
    관리자 화면에서 고치게 한다. (체크인 창구의 개폐만은 회차마다 달라야 해서
    여기가 아니라 CheckinSession.is_open 에 있다.)
    """

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst, onupdate=now_kst)


# 체크인 완료 화면에 '내 QR 열기'(개인 카드) 버튼을 보일지.
# 명찰을 나눠 주기 전에는 내려 둔다.
SETTING_CARD_LINK = "checkin.card_link"
# 스태프 참가비. 금액이 늦게 정해지고 바뀔 수 있어 관리자 화면에서 고친다.
SETTING_STAFF_FEE = "fee.staff"
# 뒤풀이 참가비. 본 행사비 위에 얹히고, 총학생회비 납부 여부와 무관하게 같다.
SETTING_AFTERPARTY_FEE = "fee.afterparty"
# 럭키드로우 상품 목록(JSON). 행사 전에 미리 등록해 두고 당일에는 고르기만 한다.
# 별도 테이블을 만들지 않는 이유는 '순서 있는 짧은 목록' 이라 관계를 맺을 것이 없고,
# 진행 중에 통째로 갈아끼우는 편집이 더 자연스럽기 때문이다.
SETTING_DRAW_PRIZES = "draw.prizes"


def get_setting(key: str, default: str = "") -> str:
    row = db.session.get(Setting, key)
    return row.value if row is not None else default


def set_setting(key: str, value: str) -> None:
    row = db.session.get(Setting, key)
    if row is None:
        db.session.add(Setting(key=key, value=value))
    else:
        row.value = value


def staff_fee() -> int:
    """스태프 참가비.

    아직 정해지지 않은 값이라 `.env` 가 아니라 DB 에 둔다. 관리자 화면에서 고치고,
    고치면 스태프 전원의 예상 금액이 함께 따라간다. 0 이면 낼 것이 없는 것으로 본다.
    """
    from flask import current_app

    raw = get_setting(SETTING_STAFF_FEE, "")
    if raw == "":
        return int(current_app.config.get("FEE_STAFF", 0) or 0)
    try:
        return max(int(raw), 0)
    except ValueError:
        return 0


def current_afterparty_fee() -> int:
    """뒤풀이 참가비.

    스태프 참가비와 같은 이유로 DB 에 둔다 — 금액이 바뀌면 재배포 없이 고치고,
    고치는 순간 뒤풀이 신청자 전원의 예상 금액이 함께 따라가야 한다
    (services.recalc_expected_amounts).
    """
    from flask import current_app

    raw = get_setting(SETTING_AFTERPARTY_FEE, "")
    if raw == "":
        return int(current_app.config.get("FEE_AFTERPARTY", 0) or 0)
    try:
        return max(int(raw), 0)
    except ValueError:
        return 0


def is_card_link_visible() -> bool:
    """기본값은 '보임'.

    체크인 창구와 반대다. 창구는 열어 두면 집결 전에 원격으로 체크인해 버리는
    사람이 생기지만, 이 버튼은 보인다고 해서 벌어질 일이 없다 — 본인이 자기
    QR 을 여는 것뿐이다. 그래서 기본은 보임이고, 명찰을 나눠 주기 전이라
    헷갈릴 것 같을 때만 내린다.
    """
    return get_setting(SETTING_CARD_LINK, "1") == "1"


class AuditLog(db.Model):
    """관리자 조작 이력. 수동 처리를 허용하는 만큼 흔적은 반드시 남긴다."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=now_kst, index=True)
    actor: Mapped[str] = mapped_column(String(40), default="admin")
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(30))
    target_id: Mapped[int | None] = mapped_column(Integer)
    detail_json: Mapped[str | None] = mapped_column(Text)

    def to_dict(self) -> dict:
        detail = {}
        if self.detail_json:
            try:
                detail = json.loads(self.detail_json)
            except (ValueError, TypeError):
                detail = {"raw": self.detail_json}
        return {
            "id": self.id,
            "at": to_iso(self.at),
            "actor": self.actor,
            "action": self.action,
            "targetType": self.target_type,
            "targetId": self.target_id,
            "detail": detail,
        }


class ImportRecord(db.Model):
    """거래내역 파일 업로드 이력.

    카카오뱅크 개인 계좌에는 공개 API가 없고, 유심 없는 공기계로는 앱 로그인조차
    불가능하다. 그래서 입금 확인은 '관리자가 거래내역 파일을 올린 시점'까지만
    반영된다. 참가자에게 그 시점을 정직하게 알리기 위한 기록이다.
    """

    __tablename__ = "import_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst, index=True)
    actor: Mapped[str] = mapped_column(String(40), default="admin")
    filename: Mapped[str] = mapped_column(String(200), default="")

    parsed_rows: Mapped[int] = mapped_column(Integer, default=0)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicated_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)

    # 파일 머리말의 조회 범위
    period_from: Mapped[datetime | None] = mapped_column(DateTime)
    period_to: Mapped[datetime | None] = mapped_column(DateTime)
    # 파일에 실제로 담긴 마지막 거래 시각 — '어디까지 확인됐나'의 가장 정확한 답
    latest_transaction_at: Mapped[datetime | None] = mapped_column(DateTime)

    def to_admin_dict(self) -> dict:
        return {
            "id": self.id,
            "importedAt": to_iso(self.imported_at),
            "actor": self.actor,
            "filename": self.filename,
            "parsedRows": self.parsed_rows,
            "createdCount": self.created_count,
            "duplicatedCount": self.duplicated_count,
            "skippedCount": self.skipped_count,
            "periodFrom": to_iso(self.period_from),
            "periodTo": to_iso(self.period_to),
            "latestTransactionAt": to_iso(self.latest_transaction_at),
        }


class UnparsedNotification(db.Model):
    """파싱하지 못한 입금 알림 원문.

    카카오뱅크 알림 문구는 앱 버전에 따라 바뀐다. 읽지 못한 알림을 버리면
    입금 1건이 조용히 증발하므로, 원문을 남겨 두고 규칙을 고친 뒤 재파싱한다.
    설치 초기에 실제 알림 문구를 확인하는 용도로도 쓴다.
    """

    __tablename__ = "unparsed_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    first_received_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)
    last_received_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst, index=True)
    # 같은 문구가 반복 전송되어도 행이 불어나지 않도록 횟수만 센다
    receive_count: Mapped[int] = mapped_column(Integer, default=1)

    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    preview: Mapped[str] = mapped_column(String(400), default="")
    reason: Mapped[str] = mapped_column(String(200), default="")

    resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deposit_id: Mapped[int | None] = mapped_column(Integer)

    @property
    def payload(self) -> dict:
        try:
            loaded = json.loads(self.payload_json)
            return loaded if isinstance(loaded, dict) else {}
        except (ValueError, TypeError):
            return {}

    def to_admin_dict(self) -> dict:
        return {
            "id": self.id,
            "firstReceivedAt": to_iso(self.first_received_at),
            "lastReceivedAt": to_iso(self.last_received_at),
            "receiveCount": self.receive_count,
            "preview": self.preview,
            "reason": self.reason,
            "resolved": self.resolved,
            "depositId": self.deposit_id,
            "payload": self.payload,
        }


class LookupAttempt(db.Model):
    """본인 조회 시도 기록. rate limit 보조 + 이상 접근 추적용."""

    __tablename__ = "lookup_attempts"
    __table_args__ = (Index("ix_lookup_ip_at", "ip", "at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)
    ip: Mapped[str] = mapped_column(String(60), default="")
    name_norm: Mapped[str] = mapped_column(String(80), default="")
    phone_last4: Mapped[str] = mapped_column(String(4), default="")
    success: Mapped[bool] = mapped_column(Boolean, default=False)


def write_audit(actor: str, action: str, target_type: str | None = None,
                target_id: int | None = None, detail: dict | None = None) -> AuditLog:
    entry = AuditLog(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail_json=json.dumps(detail, ensure_ascii=False) if detail else None,
    )
    db.session.add(entry)
    return entry
