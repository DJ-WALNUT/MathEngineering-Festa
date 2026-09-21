import { useCallback, useEffect, useState } from 'react'

import { PaymentBadge } from '../../components/StatusBadge'
import {
  adminApi,
  type AdminParticipant,
  type AssignmentField,
  type FeeClass,
  type LeaderPreference,
  type PaymentStatus,
} from '../../lib/api'
import { formatDateTime, formatWon } from '../../lib/format'

/**
 * 명단 필터.
 *
 * 납입 상태 · 확정 여부 · 스태프는 서로 다른 축이지만, 실제로 쓸 때는
 * '지금 이 사람들만 보고 싶다' 하나뿐이라 한 줄에 늘어놓고 하나만 고르게 한다.
 */
type ParticipantFilter = {
  status?: string
  confirmed?: boolean | 'pending'
  staff?: boolean
  afterparty?: boolean | 'unpaid'
  leader?: 'want' | 'any'
  resubmitted?: boolean
  overridden?: boolean
}

const FILTERS: { id: string; label: string; params: ParticipantFilter }[] = [
  { id: '', label: '전체', params: {} },
  { id: 'UNPAID', label: '미납', params: { status: 'UNPAID' } },
  { id: 'PAID', label: '납입 완료', params: { status: 'PAID' } },
  { id: 'UNDERPAID', label: '부분 입금', params: { status: 'UNDERPAID' } },
  { id: 'OVERPAID', label: '초과', params: { status: 'OVERPAID' } },
  { id: 'WAIVED', label: '면제', params: { status: 'WAIVED' } },
  { id: 'REFUNDED', label: '환불', params: { status: 'REFUNDED' } },
  { id: 'confirmed', label: '참가 확정', params: { confirmed: true } },
  // 미확정 전체가 아니라 '납입이 끝나 확정만 누르면 되는 사람'.
  // 손볼 대상이 그쪽이고, 미납자까지 섞으면 정작 볼 것이 묻힌다.
  { id: 'pending', label: '확정 대기', params: { confirmed: 'pending' } },
  { id: 'staff', label: '스태프', params: { staff: true } },
  { id: 'afterparty', label: '뒤풀이', params: { afterparty: true } },
  // 뒤풀이비는 별도 안내로 걷는다. 이 필터가 곧 '안내를 보낼 명단'이다.
  { id: 'afterparty-unpaid', label: '뒤풀이비 미납', params: { afterparty: 'unpaid' } },
  // 조를 짤 때 먼저 앉힐 사람. '하고 싶다'만 보고, 모자라면 '상관없다'까지 편다.
  { id: 'leader', label: '조장 희망', params: { leader: 'want' } },
  { id: 'leader-any', label: '조장 가능', params: { leader: 'any' } },
  // 마감 후 한 번 훑을 대상. 폼을 여러 번 낸 사람은 마지막 응답만 남아 있다.
  { id: 'resubmitted', label: '재제출', params: { resubmitted: true } },
  // 입금 내역이 아니라 사람의 판단으로 서 있는 값이라, 정산을 닫기 전에
  // '왜 이렇게 두었는지'를 다시 볼 대상이다. 면제·환불이 여기에 모인다.
  { id: 'overridden', label: '수동 지정', params: { overridden: true } },
]

/**
 * 이름 옆 이름표.
 *
 * 좁은 화면에서는 이름표가 여러 개 붙어 줄이 넘어간다. 줄이 넘어가는 것은
 * 괜찮지만 '수동 지정'처럼 띄어쓰기가 든 이름표가 알약 안에서 갈라지면
 * 지저분해 보이므로, 넘길 때는 이름표 단위로만 넘긴다.
 */
const TAG = 'whitespace-nowrap rounded-full px-2 py-0.5 text-[11px]'

const FEE_CLASS_OPTIONS: { value: FeeClass; label: string }[] = [
  { value: 'member', label: '총학생회비 납부자' },
  { value: 'nonmember', label: '총학생회비 미납부자' },
  { value: 'staff', label: '스태프' },
]

const LEADER_OPTIONS: { value: '' | LeaderPreference; label: string }[] = [
  { value: '', label: '응답 없음' },
  { value: 'want', label: '조장을 하고 싶다' },
  { value: 'ok', label: '조장을 해도 상관없다' },
  { value: 'no', label: '조장을 하고 싶지 않다' },
]

const INTAKE_LABEL: Record<string, string> = {
  earlybird: '얼리버드',
  main: '신청',
  staff: '스태프',
}

const OVERRIDE_OPTIONS: { value: '' | PaymentStatus; label: string }[] = [
  { value: '', label: '자동 (입금 기준)' },
  { value: 'PAID', label: '납입 완료로 강제' },
  { value: 'WAIVED', label: '면제' },
  { value: 'REFUNDED', label: '환불' },
  { value: 'UNPAID', label: '미납으로 강제' },
]

export default function ParticipantsPanel({
  revision,
  onChanged,
}: {
  revision: number
  onChanged: () => void
}) {
  const [query, setQuery] = useState('')
  const [filterId, setFilterId] = useState('')
  const [items, setItems] = useState<AdminParticipant[]>([])
  const [fields, setFields] = useState<AssignmentField[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [showManualForm, setShowManualForm] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const filter = FILTERS.find((item) => item.id === filterId)?.params ?? {}
      const response = await adminApi.participants({ query, ...filter, pageSize: 300 })
      setItems(response.items)
      setTotal(response.pagination.total)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '명단을 불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }, [query, filterId])

  useEffect(() => {
    const timer = setTimeout(load, query ? 250 : 0)
    return () => clearTimeout(timer)
  }, [load, revision])

  // 배정값의 이름표는 항목 정의에 있다. 없으면 키가 그대로 보이므로 함께 받아 둔다.
  useEffect(() => {
    adminApi
      .assignmentFields()
      .then((response) => setFields(response.items.filter((field) => field.isActive)))
      .catch(() => setFields([]))
  }, [revision])

  const patch = async (id: number, body: Record<string, unknown>) => {
    try {
      await adminApi.updateParticipant(id, body)
      onChanged()
    } catch (caught) {
      alert(caught instanceof Error ? caught.message : '수정에 실패했습니다.')
    }
  }

  const awaitingConfirm = items.filter((item) => item.isSettled && !item.isConfirmed).length

  const confirmAll = async () => {
    if (!confirm(`납입이 끝난 미확정자 전원을 참가 확정 처리할까요?`)) return
    try {
      const result = await adminApi.confirmParticipants()
      alert(
        `${result.confirmed}명을 확정했습니다.` +
          (result.skipped ? ` (납입 미완료 ${result.skipped}명 제외)` : ''),
      )
      onChanged()
    } catch (caught) {
      alert(caught instanceof Error ? caught.message : '확정 처리에 실패했습니다.')
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-2">
        {FILTERS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setFilterId(item.id)}
            className={`rounded-full border-2 px-3.5 py-1.5 text-sm font-bold transition ${
              filterId === item.id
                ? 'border-sand-400 bg-sand-100 text-sand-700'
                : 'border-sand-200 bg-white text-ink-500 hover:border-sand-300 hover:text-ink-700'
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        <input
          className="input flex-1 sm:max-w-xs"
          placeholder="이름 · 전화번호 · 학번 · 학과 검색"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <button
          type="button"
          className="btn-ghost"
          onClick={() => setShowManualForm((open) => !open)}
        >
          참가자 수기 등록
        </button>
      </div>

      {showManualForm && (
        <ManualParticipantForm
          onDone={() => {
            setShowManualForm(false)
            onChanged()
          }}
        />
      )}

      {awaitingConfirm > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border-2 border-cobalt-200 bg-cobalt-50 px-4 py-3.5">
          <p className="text-sm font-semibold text-ink-700">
            납입이 끝났는데 아직 확정하지 않은 참가자{' '}
            <strong className="font-black text-cobalt-600">{awaitingConfirm}명</strong>
          </p>
          <button type="button" className="btn-primary shrink-0 px-3.5 py-1.5 text-xs" onClick={confirmAll}>
            전원 참가 확정
          </button>
        </div>
      )}

      {error && <p className="text-sm font-semibold text-brick-500">{error}</p>}
      {loading ? (
        <p className="text-sm text-ink-500">불러오는 중…</p>
      ) : (
        <p className="text-xs font-semibold text-ink-500">{total}명</p>
      )}

      <ul className="space-y-2">
        {items.map((participant) => {
          const expanded = expandedId === participant.id
          // 마이그레이션으로 올라온 옛 행은 값이 비어 있을 수 있다.
          const submissions = participant.submissionCount ?? 1
          return (
            <li key={participant.id} className="card overflow-hidden">
              {/*
                이름표가 여러 줄로 늘어나도 상태 배지는 이름 줄 옆에 붙어 있어야
                어느 사람의 상태인지 한눈에 읽힌다. 가운데 정렬이면 배지만 붕 뜬다.
              */}
              <button
                type="button"
                onClick={() => setExpandedId(expanded ? null : participant.id)}
                className="flex w-full items-start justify-between gap-3 px-4 py-3.5 text-left"
              >
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-black text-ink-900">{participant.name}</span>
                    {participant.isCancelled && (
                      <span className={`${TAG} border border-ink-400/40 bg-ink-400/10 font-semibold text-ink-500`}>
                        취소
                      </span>
                    )}
                    {participant.statusOverride && (
                      <span className={`${TAG} border border-heart-400/40 bg-heart-400/12 font-semibold text-heart-500`}>
                        수동 지정
                      </span>
                    )}
                    {participant.isStaff && (
                      <span className={`${TAG} bg-flame-200 font-black text-flame-600`}>스태프</span>
                    )}
                    {/*
                      뒤풀이 배지는 세 갈래로 갈린다.
                      **'합산 납부'를 따로 세우는 것이 이 배지의 핵심이다** — 뒤풀이비는
                      별도 안내로 걷는데, 안내가 나가기 전에 본 행사비와 한 번에 보낸
                      사람이 이미 있다. 갈라 두지 않으면 그 사람에게 다시 걷으러 간다.
                    */}
                    {participant.joinsAfterparty && (
                      participant.afterpartyPrepaid ? (
                        <span
                          className={`${TAG} bg-heart-100 font-black text-heart-500`}
                          title="본 행사비와 뒤풀이비를 한 번에 보낸 사람입니다. 안내를 보낼 때 빼 주세요."
                        >
                          뒤풀이 · 합산 납부
                        </span>
                      ) : participant.afterpartyStatus === 'PAID' ? (
                        <span className={`${TAG} bg-heart-100 font-black text-heart-500`}>
                          뒤풀이 · 납입
                        </span>
                      ) : (
                        <span
                          className={`${TAG} border border-flame-300 bg-flame-100 font-semibold text-flame-600`}
                          title={`뒤풀이비 ${formatWon(participant.afterpartyFee)} 중 ${formatWon(participant.afterpartyPaid)} 확인됨`}
                        >
                          뒤풀이 · 미납
                        </span>
                      )
                    )}
                    {/* 조 편성 때 이름표만 훑어도 조장감이 보이게. '사양'은 표시하지 않는다. */}
                    {participant.leaderPreference === 'want' && (
                      <span className={`${TAG} bg-gold-300 font-black text-ink-900`}>조장 희망</span>
                    )}
                    {participant.leaderPreference === 'ok' && (
                      <span className={`${TAG} border border-gold-400 font-semibold text-ink-700`}>
                        조장 가능
                      </span>
                    )}
                    {participant.isConfirmed && (
                      <span className={`${TAG} bg-sand-200 font-black text-sand-800`}>확정</span>
                    )}
                    {participant.checkedInAt && (
                      <span className={`${TAG} bg-cobalt-100 font-black text-cobalt-600`}>
                        출석
                      </span>
                    )}
                    {submissions > 1 && (
                      <span
                        className={`${TAG} border border-flame-300 bg-flame-100 font-semibold text-flame-600`}
                        title="폼을 여러 번 제출했습니다. 마지막 응답만 남아 있습니다."
                      >
                        {submissions}회 제출
                      </span>
                    )}
                  </span>
                  <span className="mt-0.5 block truncate text-xs font-semibold text-ink-500 tabular">
                    {participant.phoneMasked} · {participant.department ?? '학과 미기재'} ·{' '}
                    {formatWon(participant.paidAmount)} / {formatWon(participant.expectedAmount)}
                    {participant.joinsAfterparty &&
                      ` (본행사 ${formatWon(participant.baseFee)} + 뒤풀이 ${formatWon(participant.afterpartyFee)})`}
                  </span>
                </span>
                <PaymentBadge status={participant.status} />
              </button>

              {expanded && (
                <div className="space-y-4 border-t border-sand-200 bg-sand-50/40 px-4 py-4">
                  <ProfileBlock participant={participant} onChanged={onChanged} />

                  <ConfirmRow participant={participant} onPatch={patch} />

                  {participant.isConfirmed && fields.length > 0 && (
                    <dl className="grid gap-x-4 gap-y-2 rounded-xl bg-cobalt-50 px-3 py-2.5 text-sm sm:grid-cols-3">
                      {fields.map((field) => (
                        <Field
                          key={field.key}
                          label={field.label}
                          value={participant.assignments[field.key] ?? '미배정'}
                        />
                      ))}
                    </dl>
                  )}

                  {submissions > 1 && (
                    <p className="rounded-xl border-2 border-flame-200 bg-flame-100/60 px-3 py-2.5 text-xs font-semibold text-flame-600">
                      같은 전화번호로 폼을 {submissions}번 제출했습니다. 위 정보는 <strong>가장
                      나중에 도착한 응답</strong>이고 이전 응답은 남아 있지 않습니다. 응답이 엇갈릴
                      수 있으니 지병·알레르기처럼 현장에서 중요한 항목은 원본 스프레드시트에서
                      한 번 확인해 주세요.
                    </p>
                  )}

                  {participant.declaredPaid && participant.status === 'UNPAID' && (
                    <p className="rounded-xl border-2 border-flame-200 bg-flame-100/60 px-3 py-2.5 text-xs font-semibold text-flame-600">
                      본인은 입금했다고 답했으나 은행 내역에서 확인되지 않았습니다. 입금자명이
                      다르거나 아직 반영 전일 수 있습니다.
                    </p>
                  )}

                  <HealthInfo participant={participant} />

                  {participant.allocations.length > 0 && (
                    <div>
                      <p className="text-xs font-bold text-ink-500">
                        연결된 입금 {participant.allocations.length}건
                      </p>
                      <ul className="mt-1.5 space-y-1">
                        {participant.allocations.map((allocation) => (
                          <li key={allocation.id} className="text-xs text-ink-600 tabular">
                            {formatDateTime(allocation.occurredAt)} · {allocation.depositRawName} ·{' '}
                            {formatWon(allocation.amount)}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <div className="grid gap-3 sm:grid-cols-2">
                    <div>
                      <label className="label" htmlFor={`override-${participant.id}`}>
                        납입 상태 강제 지정
                      </label>
                      <select
                        id={`override-${participant.id}`}
                        className="input"
                        value={participant.statusOverride ?? ''}
                        onChange={(event) =>
                          patch(participant.id, { statusOverride: event.target.value || null })
                        }
                      >
                        {OVERRIDE_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div>
                      <label className="label" htmlFor={`fee-${participant.id}`}>
                        요금 구분
                      </label>
                      <select
                        id={`fee-${participant.id}`}
                        className="input"
                        value={participant.feeClass}
                        onChange={(event) =>
                          patch(participant.id, { feeClass: event.target.value as FeeClass })
                        }
                      >
                        {FEE_CLASS_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <p className="mt-1 text-xs text-ink-500 tabular">
                        참가비 {formatWon(participant.expectedAmount)}
                        {participant.isStaff && ' · 입금 내역 탭에서 스태프 금액을 정합니다'}
                      </p>
                    </div>
                  </div>

                  {/*
                    뒤풀이 참가 여부. 폼 응답이 그대로 들어오지만, 현장에서 마음을
                    바꾸는 사람이 반드시 나온다. 켜면 참가비에 뒤풀이비가 얹히고
                    뒤풀이 회차의 출석 대상이 되며, 끄면 그 회차의 출석도 함께 지워진다.
                  */}
                  <div className="rounded-xl border border-heart-400/30 bg-heart-100/40 px-3 py-2.5">
                    <label className="flex items-center gap-2 text-sm font-bold text-ink-800">
                      <input
                        type="checkbox"
                        checked={participant.joinsAfterparty}
                        onChange={(event) =>
                          patch(participant.id, { joinsAfterparty: event.target.checked })
                        }
                      />
                      뒤풀이 참가
                    </label>
                    <p className="mt-1 text-xs leading-relaxed text-ink-500 break-keep">
                      {participant.joinsAfterparty ? (
                        <>
                          뒤풀이비 {formatWon(participant.afterpartyFee)} 중{' '}
                          {formatWon(participant.afterpartyPaid)} 확인됨
                          {participant.afterpartyPrepaid &&
                            ' · 본 행사비와 한 번에 보낸 사람입니다 (다시 걷지 마세요)'}
                        </>
                      ) : (
                        '켜면 참가비에 뒤풀이비가 얹히고 뒤풀이 출석 명단에 들어갑니다.'
                      )}
                    </p>
                  </div>

                  <div className="grid gap-3 sm:grid-cols-2">
                    <div>
                      <label className="label" htmlFor={`leader-${participant.id}`}>
                        조장 지원 (1부 교류전)
                      </label>
                      <select
                        id={`leader-${participant.id}`}
                        className="input"
                        value={participant.leaderPreference ?? ''}
                        onChange={(event) =>
                          patch(participant.id, { leaderPreference: event.target.value || null })
                        }
                      >
                        {LEADER_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <p className="mt-1 text-xs text-ink-500">
                        폼 응답이 그대로 들어옵니다. 현장에서 마음이 바뀌면 여기서 고칩니다.
                      </p>
                    </div>
                    <div>
                      <label className="label" htmlFor={`nickname-${participant.id}`}>
                        닉네임 (솔로파티 · 명찰)
                      </label>
                      <input
                        id={`nickname-${participant.id}`}
                        className="input"
                        defaultValue={participant.nickname ?? ''}
                        maxLength={40}
                        onBlur={(event) => {
                          if (event.target.value.trim() !== (participant.nickname ?? '')) {
                            void patch(participant.id, { nickname: event.target.value.trim() })
                          }
                        }}
                        placeholder="폼에서 적은 닉네임 (자동 저장)"
                      />
                    </div>
                  </div>

                  <OnsitePaymentRow participant={participant} onChanged={onChanged} />

                  <div>
                    <label className="label" htmlFor={`memo-${participant.id}`}>
                      메모
                    </label>
                    <textarea
                      id={`memo-${participant.id}`}
                      className="input min-h-20 resize-y"
                      defaultValue={participant.memo ?? ''}
                      onBlur={(event) => {
                        if (event.target.value !== (participant.memo ?? '')) {
                          void patch(participant.id, { memo: event.target.value })
                        }
                      }}
                      placeholder="특이사항을 적어 두세요 (자동 저장)"
                    />
                  </div>

                  <button
                    type="button"
                    className="btn-ghost text-xs"
                    onClick={() => patch(participant.id, { isCancelled: !participant.isCancelled })}
                  >
                    {participant.isCancelled ? '참가 취소 해제' : '참가 취소 처리'}
                  </button>
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/**
 * 현장 납부.
 *
 * 당일 행사라 미납자가 문 앞에서 내는 일이 반드시 생긴다. 그때 계좌로 다시
 * 보내게 하면 거래내역 파일을 또 내려받아 올릴 때까지 확정이 열리지 않아 줄이
 * 선다. 그래서 **받은 즉시 이 자리에서 입금 1건으로 남긴다.**
 *
 * 거래내역 업로드로 들어온 것과 같은 테이블에 들어가되 출처가 '현장'이라,
 * 정산할 때 계좌로 들어온 돈과 손에 쥔 현금을 갈라 볼 수 있다.
 */
function OnsitePaymentRow({
  participant,
  onChanged,
}: {
  participant: AdminParticipant
  onChanged: () => void
}) {
  const remaining = Math.max(participant.expectedAmount - participant.paidAmount, 0)
  const [open, setOpen] = useState(false)
  const [amount, setAmount] = useState(String(remaining))
  const [method, setMethod] = useState('현금')
  const [busy, setBusy] = useState(false)

  useEffect(() => setAmount(String(remaining)), [remaining])

  if (participant.isCancelled) return null

  const parsed = Number(amount.replace(/[^\d]/g, ''))

  const submit = async () => {
    if (!Number.isFinite(parsed) || parsed <= 0) return
    if (!confirm(`${participant.name} 님에게 ${formatWon(parsed)}을 ${method}으로 받았습니까?`)) {
      return
    }
    setBusy(true)
    try {
      await adminApi.recordOnsitePayment(participant.id, { amount: parsed, method })
      setOpen(false)
      onChanged()
    } catch (caught) {
      alert(caught instanceof Error ? caught.message : '현장 납부를 기록하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <button type="button" className="btn-ghost text-xs" onClick={() => setOpen(true)}>
        현장에서 참가비 받기
        {remaining > 0 && ` · 남은 금액 ${formatWon(remaining)}`}
      </button>
    )
  }

  return (
    <div className="rounded-xl border border-cobalt-200 bg-cobalt-50 px-3 py-3">
      <p className="text-xs font-black text-cobalt-600">현장 납부 기록</p>
      <p className="mt-1 text-xs leading-relaxed text-ink-500 break-keep">
        접수대에서 받은 돈을 입금 1건으로 남깁니다. 계좌 거래내역에는 뜨지 않으므로
        <strong className="text-ink-700"> 실제로 받은 뒤에만</strong> 눌러 주세요.
      </p>

      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <input
          className="input h-9 max-w-28 py-1 text-sm tabular"
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
          inputMode="numeric"
          aria-label="받은 금액"
        />
        <span className="text-sm font-semibold text-ink-500">원</span>
        <select
          className="input h-9 max-w-28 py-1 text-sm"
          value={method}
          onChange={(event) => setMethod(event.target.value)}
          aria-label="받은 방법"
        >
          <option value="현금">현금</option>
          <option value="계좌이체">계좌이체</option>
          <option value="간편송금">간편송금</option>
        </select>
        <button
          type="button"
          className="btn-primary px-3.5 py-1.5 text-xs"
          onClick={submit}
          disabled={busy || !Number.isFinite(parsed) || parsed <= 0}
        >
          {busy ? '기록 중…' : '받았음'}
        </button>
        <button
          type="button"
          className="btn-ghost px-3 py-1.5 text-xs"
          onClick={() => setOpen(false)}
          disabled={busy}
        >
          취소
        </button>
      </div>
    </div>
  )
}

/**
 * 신청 정보와 그 정정.
 *
 * 폼에 잘못 적어 내는 사람이 반드시 나온다 — 학번 칸에 생년월일, 이름 오타,
 * 번호 한 자리 누락. 접수가 끝나면 원본 시트를 고쳐 다시 흘려보낼 수 없으므로
 * 여기서 고친다.
 *
 * 요금 구분 · 접수 회차 · 초상 이용은 여기서 다루지 않는다. 요금 구분은 아래에
 * 전용 드롭다운이 있고, 나머지 둘은 본인이 폼에서 답한 값이라 관리자가 대신
 * 뒤집을 것이 아니다.
 */
function ProfileBlock({
  participant,
  onChanged,
}: {
  participant: AdminParticipant
  onChanged: () => void
}) {
  const [editing, setEditing] = useState(false)

  if (editing) {
    return (
      <ProfileForm
        participant={participant}
        onCancel={() => setEditing(false)}
        onSaved={() => {
          setEditing(false)
          onChanged()
        }}
      />
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-bold text-ink-500">신청 정보</p>
        <button
          type="button"
          className="text-xs font-semibold text-cobalt-600 hover:underline"
          onClick={() => setEditing(true)}
        >
          정보 수정
        </button>
      </div>

      <dl className="mt-2 grid gap-x-4 gap-y-2 text-sm sm:grid-cols-2">
        <Field label="전화번호" value={participant.phone} />
        <Field label="비상 연락처" value={participant.emergencyPhone ?? '-'} />
        <Field label="학번" value={participant.studentId ?? '-'} />
        <Field label="학과" value={participant.department ?? '-'} />
        <Field label="성별" value={participant.gender ?? '-'} />
        <Field
          label="요금 구분"
          value={
            FEE_CLASS_OPTIONS.find((option) => option.value === participant.feeClass)?.label ?? '-'
          }
        />
        <Field label="닉네임" value={participant.nickname ?? '-'} />
        <Field label="태어난 해" value={participant.birthYear ? `${participant.birthYear}년` : '-'} />
        <Field
          label="솔로파티비 안내"
          value={
            participant.joinsAfterparty
              ? participant.afterpartyFeeAcknowledged
                ? '추후 안내 확인함'
                : '확인 안 함 — 안내 시 설명 필요'
              : '-'
          }
        />
        <Field label="접수 회차" value={INTAKE_LABEL[participant.intakeRound ?? ''] ?? '-'} />
        <Field label="신청 시각" value={formatDateTime(participant.submittedAt)} />
        <Field
          label="초상 이용"
          value={participant.portraitConsent ? '동의' : '비동의 — 촬영 주의'}
        />
      </dl>
    </div>
  )
}

/** 바뀐 칸만 보낸다. 손대지 않은 값을 함께 실어 보내면 작업 기록이 잡음으로 찬다. */
function ProfileForm({
  participant,
  onCancel,
  onSaved,
}: {
  participant: AdminParticipant
  onCancel: () => void
  onSaved: () => void
}) {
  const [form, setForm] = useState({
    name: participant.name,
    phone: participant.phone,
    studentId: participant.studentId ?? '',
    department: participant.department ?? '',
    gender: participant.gender ?? '',
    emergencyPhone: participant.emergencyPhone ?? '',
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const set = (key: keyof typeof form) => (event: React.ChangeEvent<HTMLInputElement>) =>
    setForm((current) => ({ ...current, [key]: event.target.value }))

  const digits = (value: string) => value.replace(/\D/g, '')
  // 서버가 숫자만 남겨 보관하므로, 바뀌었는지도 숫자끼리 비교해야 한다.
  // (010-1234-5678 을 01012345678 로 고쳐 쓴 것은 바뀐 것이 아니다)
  const phoneChanged = digits(form.phone) !== participant.phone
  const canSave = form.name.trim().length > 0 && digits(form.phone).length >= 10

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (busy || !canSave) return

    const patch: Record<string, string> = {}
    if (form.name.trim() !== participant.name) patch.name = form.name.trim()
    if (phoneChanged) patch.phone = form.phone
    if (form.studentId.trim() !== (participant.studentId ?? '')) {
      patch.studentId = form.studentId.trim()
    }
    if (form.department.trim() !== (participant.department ?? '')) {
      patch.department = form.department.trim()
    }
    if (form.gender.trim() !== (participant.gender ?? '')) patch.gender = form.gender.trim()
    if (digits(form.emergencyPhone) !== (participant.emergencyPhone ?? '')) {
      patch.emergencyPhone = form.emergencyPhone
    }

    if (Object.keys(patch).length === 0) {
      onCancel()
      return
    }

    setBusy(true)
    setError('')
    try {
      await adminApi.updateParticipant(participant.id, patch)
      onSaved()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '수정에 실패했습니다.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="rounded-2xl border-2 border-cobalt-200 bg-white p-4">
      <p className="text-xs font-black text-ink-700">신청 정보 수정</p>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label className="label" htmlFor={`edit-name-${participant.id}`}>
            이름
          </label>
          <input
            id={`edit-name-${participant.id}`}
            className="input"
            value={form.name}
            onChange={set('name')}
            maxLength={40}
            autoFocus
          />
        </div>
        <div>
          <label className="label" htmlFor={`edit-phone-${participant.id}`}>
            전화번호
          </label>
          <input
            id={`edit-phone-${participant.id}`}
            className="input tabular"
            value={form.phone}
            onChange={set('phone')}
            inputMode="tel"
          />
        </div>
        <div>
          <label className="label" htmlFor={`edit-student-id-${participant.id}`}>
            학번
          </label>
          <input
            id={`edit-student-id-${participant.id}`}
            className="input tabular"
            value={form.studentId}
            onChange={set('studentId')}
            placeholder="20261234"
          />
        </div>
        <div>
          <label className="label" htmlFor={`edit-department-${participant.id}`}>
            학과
          </label>
          <input
            id={`edit-department-${participant.id}`}
            className="input"
            value={form.department}
            onChange={set('department')}
            placeholder="기계공학과"
          />
        </div>
        <div>
          <label className="label" htmlFor={`edit-gender-${participant.id}`}>
            성별
          </label>
          <input
            id={`edit-gender-${participant.id}`}
            className="input"
            value={form.gender}
            onChange={set('gender')}
            placeholder="남 / 여"
          />
        </div>
        <div>
          <label className="label" htmlFor={`edit-emergency-${participant.id}`}>
            비상 연락처
          </label>
          <input
            id={`edit-emergency-${participant.id}`}
            className="input tabular"
            value={form.emergencyPhone}
            onChange={set('emergencyPhone')}
            inputMode="tel"
          />
        </div>
      </div>

      <p className="mt-3 text-xs leading-relaxed text-ink-500">
        셀프 체크인은 <strong className="font-bold text-ink-700">이름 · 학번 · 전화번호 뒷 4자리</strong>로
        본인을 확인합니다. 학번을 생년월일처럼 잘못 적어 낸 사람은 여기서 고쳐 두어야 당일에
        체크인이 됩니다.
      </p>
      {phoneChanged && (
        <p className="mt-1.5 text-xs font-semibold leading-relaxed text-flame-600">
          전화번호는 참가자를 알아보는 기준입니다. 고치면 본인 조회 · 체크인이 새 번호로만 되고,
          이름으로 붙지 못했던 입금이 있으면 저장과 동시에 다시 확인합니다.
        </p>
      )}
      {error && <p className="mt-2 text-sm font-semibold text-brick-500">{error}</p>}

      <div className="mt-3 flex gap-2">
        <button type="submit" className="btn-primary px-4 py-2 text-sm" disabled={busy || !canSave}>
          {busy ? '저장 중…' : '저장'}
        </button>
        <button type="button" className="btn-ghost px-4 py-2 text-sm" onClick={onCancel}>
          취소
        </button>
      </div>
    </form>
  )
}

/**
 * 참가자 수기 등록.
 *
 * 폼을 내지 않은 사람이 반드시 나온다 — 현장 합류, 대리 신청, 폼 응답 유실.
 * 입금 수기 등록과 같은 이유로 명단에도 손으로 넣는 길을 열어 둔다.
 *
 * 전화번호가 자연키다. 나중에 같은 번호로 폼 응답이 도착하면 새 사람이 생기지
 * 않고 이 행이 갱신되므로, 손으로 넣어 둔 것이 중복으로 남지 않는다.
 */
function ManualParticipantForm({ onDone }: { onDone: () => void }) {
  const [form, setForm] = useState({
    name: '',
    phone: '',
    studentId: '',
    department: '',
    gender: '',
    emergencyPhone: '',
    memo: '',
  })
  const [feeClass, setFeeClass] = useState<FeeClass>('nonmember')
  const [joinsAfterparty, setJoinsAfterparty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const set = (key: keyof typeof form) => (event: React.ChangeEvent<HTMLInputElement>) =>
    setForm((current) => ({ ...current, [key]: event.target.value }))

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (busy) return

    setBusy(true)
    setError('')
    try {
      const result = await adminApi.createParticipant({
        name: form.name.trim(),
        phone: form.phone.trim(),
        studentId: form.studentId.trim() || undefined,
        department: form.department.trim() || undefined,
        gender: form.gender.trim() || undefined,
        emergencyPhone: form.emergencyPhone.trim() || undefined,
        memo: form.memo.trim() || undefined,
        feeClass,
        joinsAfterparty,
      })
      // 이 사람 이름으로 이미 들어와 있던 입금이 등록과 동시에 붙기도 한다.
      // 붙었다면 그 사실을 알려 준다 — 다시 입금 탭을 뒤지지 않도록.
      alert(
        `${result.participant.name} 님을 명단에 넣었습니다.` +
          (result.participant.paidAmount > 0
            ? ` 기존 입금 ${formatWon(result.participant.paidAmount)} 이 함께 연결되었습니다.`
            : ''),
      )
      onDone()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '등록에 실패했습니다.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="card space-y-3 p-5">
      <div>
        <p className="text-sm font-black text-ink-800">참가자 수기 등록</p>
        <p className="mt-1 text-xs leading-relaxed text-ink-500">
          폼을 내지 않은 사람을 명단에 넣습니다. 전화번호가 이미 있는 사람이면 등록되지 않아요.
          참가비는 요금 구분에 따라 자동으로 매겨집니다.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="label" htmlFor="new-participant-name">
            이름
          </label>
          <input
            id="new-participant-name"
            className="input"
            value={form.name}
            onChange={set('name')}
            placeholder="홍길동"
            maxLength={40}
            autoFocus
            required
          />
        </div>
        <div>
          <label className="label" htmlFor="new-participant-phone">
            전화번호
          </label>
          <input
            id="new-participant-phone"
            className="input tabular"
            value={form.phone}
            onChange={set('phone')}
            inputMode="tel"
            placeholder="010-1234-5678"
            required
          />
        </div>
        <div>
          <label className="label" htmlFor="new-participant-student-id">
            학번
          </label>
          <input
            id="new-participant-student-id"
            className="input tabular"
            value={form.studentId}
            onChange={set('studentId')}
            placeholder="20261234"
          />
        </div>
        <div>
          <label className="label" htmlFor="new-participant-department">
            학과
          </label>
          <input
            id="new-participant-department"
            className="input"
            value={form.department}
            onChange={set('department')}
            placeholder="기계공학과"
          />
        </div>
        <div>
          <label className="label" htmlFor="new-participant-fee">
            요금 구분
          </label>
          <select
            id="new-participant-fee"
            className="input"
            value={feeClass}
            onChange={(event) => setFeeClass(event.target.value as FeeClass)}
          >
            {FEE_CLASS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="new-participant-gender">
            성별
          </label>
          <input
            id="new-participant-gender"
            className="input"
            value={form.gender}
            onChange={set('gender')}
            placeholder="남 / 여"
          />
        </div>
        <div>
          <label className="label" htmlFor="new-participant-emergency">
            비상 연락처
          </label>
          <input
            id="new-participant-emergency"
            className="input tabular"
            value={form.emergencyPhone}
            onChange={set('emergencyPhone')}
            inputMode="tel"
            placeholder="010-0000-0000"
          />
        </div>
        <div>
          <label className="label" htmlFor="new-participant-memo">
            메모
          </label>
          <input
            id="new-participant-memo"
            className="input"
            value={form.memo}
            onChange={set('memo')}
            placeholder="현장 합류 등"
          />
        </div>
      </div>

      <label className="flex items-center gap-2 text-sm font-bold text-ink-800">
        <input
          type="checkbox"
          checked={joinsAfterparty}
          onChange={(event) => setJoinsAfterparty(event.target.checked)}
        />
        뒤풀이도 참가
        <span className="text-xs font-semibold text-ink-400">
          참가비에 뒤풀이비가 얹힙니다
        </span>
      </label>

      {error && <p className="text-sm font-semibold text-brick-500">{error}</p>}

      <p className="text-xs leading-relaxed text-ink-500">
        셀프 체크인은 이름 · 학번 · 전화번호 뒷자리로 하므로,{' '}
        <strong className="font-bold text-ink-700">학번을 비워 두면 본인이 체크인할 수 없습니다</strong>{' '}
        (현장에서 스태프가 출석 처리하면 됩니다). 지병 · 알레르기 같은 안전 정보는 여기서 받지
        않으니 필요하면 메모에 적어 주세요.
      </p>

      <button
        type="submit"
        className="btn-primary"
        disabled={busy || !form.name.trim() || !form.phone.trim()}
      >
        {busy ? '등록 중…' : '명단에 넣기'}
      </button>
    </form>
  )
}

/**
 * 참가 확정.
 *
 * 납입 완료와 확정은 다른 단계다. 돈이 들어왔다고 자동으로 확정하지 않고,
 * 학생회가 명단을 확인한 뒤 여기서 누른다. 확정된 사람만 배정과 체크인이 열린다.
 */
function ConfirmRow({
  participant,
  onPatch,
}: {
  participant: AdminParticipant
  onPatch: (id: number, body: Record<string, unknown>) => Promise<void>
}) {
  if (participant.isCancelled) return null

  return (
    <div
      className={`flex flex-wrap items-center justify-between gap-3 rounded-xl border-2 px-3.5 py-3 ${
        participant.isConfirmed
          ? 'border-sand-300 bg-sand-50'
          : 'border-sand-200 bg-white'
      }`}
    >
      <div className="min-w-0">
        <p className="text-sm font-black text-ink-900">
          {participant.isConfirmed ? '참가 확정됨' : '참가 미확정'}
        </p>
        <p className="mt-0.5 text-xs text-ink-500 tabular">
          {participant.isConfirmed
            ? `${formatDateTime(participant.confirmedAt)}${
                participant.confirmedBy ? ` · ${participant.confirmedBy}` : ''
              }`
            : participant.isSettled
              ? '납입이 끝나 확정할 수 있습니다.'
              : '납입이 완료되어야 확정할 수 있습니다.'}
          {participant.checkedInAt &&
            ` · 출석 ${formatDateTime(participant.checkedInAt)}`}
        </p>
      </div>

      <div className="flex shrink-0 gap-2">
        <button
          type="button"
          className={participant.isConfirmed ? 'btn-ghost text-xs' : 'btn-primary px-3.5 py-1.5 text-xs'}
          disabled={!participant.isConfirmed && !participant.isSettled}
          onClick={() => onPatch(participant.id, { isConfirmed: !participant.isConfirmed })}
        >
          {participant.isConfirmed ? '확정 해제' : '참가 확정'}
        </button>
        {participant.isConfirmed && (
          <button
            type="button"
            className="btn-ghost text-xs"
            onClick={() => onPatch(participant.id, { isCheckedIn: !participant.checkedInAt })}
          >
            {participant.checkedInAt ? '출석 취소' : '출석 처리'}
          </button>
        )}
      </div>
    </div>
  )
}

/**
 * 건강 정보는 민감정보다. 현장 응급 대응에 필요해 보관하지만,
 * 눈에 띄게 구분해 두어 함부로 다루지 않도록 한다.
 */
function HealthInfo({ participant }: { participant: AdminParticipant }) {
  const hasAllergy = participant.allergy && !/^없|^무$|^none$/i.test(participant.allergy.trim())
  if (!participant.hasHealthIssue && !hasAllergy) return null

  return (
    <div className="rounded-xl border-2 border-brick-400/40 bg-brick-400/8 px-3.5 py-3">
      <p className="text-xs font-black text-brick-500">현장 안전 정보 · 취급 주의</p>

      {participant.hasHealthIssue && (
        <dl className="mt-2 space-y-1.5 text-sm">
          {participant.healthNote && (
            <div className="flex gap-2">
              <dt className="w-20 shrink-0 font-bold text-ink-500">지병</dt>
              <dd className="min-w-0 break-words text-ink-800">{participant.healthNote}</dd>
            </div>
          )}
          {participant.healthAction && (
            <div className="flex gap-2">
              <dt className="w-20 shrink-0 font-bold text-ink-500">조치</dt>
              <dd className="min-w-0 break-words font-semibold text-ink-900">
                {participant.healthAction}
              </dd>
            </div>
          )}
        </dl>
      )}

      {hasAllergy && (
        <div className="mt-2 flex gap-2 text-sm">
          <dt className="w-20 shrink-0 font-bold text-ink-500">알레르기</dt>
          <dd className="min-w-0 break-words text-ink-800">{participant.allergy}</dd>
        </div>
      )}
    </div>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2">
      <dt className="w-24 shrink-0 font-bold text-ink-500">{label}</dt>
      <dd className="min-w-0 break-words font-semibold text-ink-800">{value}</dd>
    </div>
  )
}
