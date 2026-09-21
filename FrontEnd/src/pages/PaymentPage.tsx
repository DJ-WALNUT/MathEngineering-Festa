import { useEffect, useState, type FormEvent } from 'react'

import { ApplyLink, ApplySchedule } from '../components/Apply'
import ContactChannels from '../components/ContactChannels'
import { PixelStar } from '../components/Decorations'
import { PaymentBadge } from '../components/StatusBadge'
import SyncNotice from '../components/SyncNotice'
import { EVENT } from '../data/event'
import {
  ApiError,
  fetchSyncStatus,
  lookupStatus,
  type PublicParticipant,
  type SyncState,
} from '../lib/api'
import { formatDateTime, formatPhoneInput, formatWon } from '../lib/format'

type ViewState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'found'; participant: PublicParticipant }
  | { kind: 'notFound'; message: string }
  | { kind: 'error'; message: string }

export default function PaymentPage() {
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [view, setView] = useState<ViewState>({ kind: 'idle' })
  const [sync, setSync] = useState<SyncState | null>(null)
  // 조회 전에는 펼쳐 두어 전제조건을 읽히게 하고, 한 번 조회하면 접어 결과에 자리를 내준다.
  const [noticeOpen, setNoticeOpen] = useState(true)

  // 조회 전에도 '언제까지 반영됐는지'를 먼저 보여준다.
  useEffect(() => {
    fetchSyncStatus()
      .then(setSync)
      .catch(() => setSync(null))
  }, [])

  const canSubmit =
    name.trim().length >= 2 && phone.replace(/\D/g, '').length >= 10 && view.kind !== 'loading'

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (!canSubmit) return

    setView({ kind: 'loading' })
    setNoticeOpen(false)
    try {
      const result = await lookupStatus(name.trim(), phone)
      if (result.sync) setSync(result.sync)
      if (result.found && result.participant) {
        setView({ kind: 'found', participant: result.participant })
      } else {
        setView({
          kind: 'notFound',
          message: result.message ?? '일치하는 신청 내역을 찾지 못했어요.',
        })
      }
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.status === 429
            ? '조회 시도가 너무 많아요. 10분 후에 다시 시도해 주세요.'
            : error.message
          : '알 수 없는 오류가 발생했어요.'
      setView({ kind: 'error', message })
    }
  }

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <header className="text-center">
        <PixelStar className="mx-auto size-10 text-sand-300" />
        <h1 className="mt-3 text-2xl font-black text-ink-900 sm:text-3xl">참가비 납입 확인</h1>
        <p className="mt-2 text-sm leading-relaxed text-ink-600">
          신청할 때 적은 이름과 전화번호로 <strong className="text-ink-800">본인의</strong> 납입
          상태만 확인할 수 있어요.
        </p>
      </header>

      <SyncNotice sync={sync} />

      <form onSubmit={handleSubmit} className="card space-y-4 p-6">
        <div>
          <label htmlFor="name" className="label">
            이름
          </label>
          <input
            id="name"
            className="input"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="홍길동"
            autoComplete="name"
            maxLength={20}
          />
        </div>

        <div>
          <label htmlFor="phone" className="label">
            전화번호
          </label>
          <input
            id="phone"
            className="input tabular"
            value={phone}
            onChange={(event) => setPhone(formatPhoneInput(event.target.value))}
            placeholder="010-1234-5678"
            inputMode="numeric"
            autoComplete="tel"
          />
          <p className="mt-1.5 text-xs text-ink-500">신청서에 적은 번호를 그대로 입력해 주세요.</p>
        </div>

        <button type="submit" className="btn-primary w-full py-3.5" disabled={!canSubmit}>
          {view.kind === 'loading' ? '조회 중…' : '납입 상태 확인'}
        </button>
      </form>

      <FormRequiredNotice open={noticeOpen} onToggle={() => setNoticeOpen((value) => !value)} />

      {view.kind === 'found' && <ResultCard participant={view.participant} sync={sync} />}
      {view.kind === 'notFound' && <NotFoundCard message={view.message} />}
      {view.kind === 'error' && (
        <div className="card border-brick-400/40 bg-brick-400/8 p-5 text-sm font-semibold text-brick-500">
          {view.message}
        </div>
      )}

      <p className="text-center text-xs leading-relaxed text-ink-400">
        입력한 정보는 본인 확인 용도로만 쓰이고 저장되지 않아요. 다른 사람의 납입 내역은 조회할 수
        없습니다.
      </p>
    </div>
  )
}

/**
 * 조회의 전제조건 안내.
 *
 * 조회는 신청 폼 응답을 기준으로 동작한다. 입금만 하고 폼을 쓰지 않은 사람은
 * 납입 여부와 무관하게 아무것도 조회되지 않는다. 이걸 미리 알리지 않으면
 * "돈 냈는데 조회가 안 된다"는 문의가 그대로 쌓인다.
 *
 * 버튼에 '참가 신청서 작성하기' 라고만 적으면 접수 기간 내내 한 가지 모집만
 * 하는 것처럼 읽힌다. 차수 이름을 그대로 버튼에 띄우고 기간표를 함께 두어,
 * 지금 열린 것이 얼리버드인지 본모집인지 화면에서 바로 드러나게 한다.
 *
 * 조회를 한 번 하고 나면 제목만 남기고 접힌다. 읽을 이유가 사라진 안내가
 * 결과 카드를 화면 밖으로 밀어내지 않도록. 제목을 누르면 다시 펼쳐진다.
 */
function FormRequiredNotice({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <div className="rounded-2xl border-2 border-cobalt-200 bg-cobalt-50 px-5 py-4">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls="form-required-detail"
        className="flex w-full items-center gap-2 text-left text-sm font-black text-cobalt-600"
      >
        <InfoIcon />
        <span className="min-w-0 flex-1">신청 폼을 제출한 분만 조회할 수 있어요</span>
        <Chevron open={open} />
      </button>

      {/* 높이를 모르는 내용을 접기 위해 grid 행 크기를 0fr ↔ 1fr 로 바꾼다.
          max-height 로 흉내내면 값을 넘길 때 잘리거나 여백이 남는다. */}
      <div
        id="form-required-detail"
        className={`grid transition-[grid-template-rows] duration-300 ease-out ${
          open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
        }`}
      >
        <div className="overflow-hidden">
          <p className="mt-2 text-sm leading-relaxed text-ink-700">
            입금 여부와 관계없이, <strong className="text-ink-900">신청 폼을 작성하지 않으면 조회
            결과가 나오지 않습니다.</strong> 입금만 하신 경우에도 참가가 확정되지 않으니 신청 폼을
            먼저 제출해 주세요.
          </p>
          <ApplyLink className="btn-ghost mt-3 px-3.5 py-1.5 text-xs" />
          <ApplySchedule className="mt-3 bg-white/70" />
        </div>
      </div>
    </div>
  )
}

function InfoIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-4 shrink-0" fill="none" stroke="currentColor" strokeWidth={2.5}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5" strokeLinecap="round" />
      <circle cx="12" cy="7.6" r="0.9" fill="currentColor" stroke="none" />
    </svg>
  )
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden
      className={`size-4 shrink-0 transition-transform duration-300 ${open ? '' : '-rotate-90'}`}
      fill="none"
      stroke="currentColor"
      strokeWidth={2.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="m6 9 6 6 6-6" />
    </svg>
  )
}

function ResultCard({
  participant,
  sync,
}: {
  participant: PublicParticipant
  sync: SyncState | null
}) {
  const isSettled = participant.status === 'PAID' || participant.status === 'WAIVED'
  const isConfirmed = participant.isConfirmed

  return (
    <div className="card overflow-hidden">
      <div
        className={`border-b-2 px-6 py-5 ${
          isConfirmed
            ? 'border-sand-200 bg-sand-100'
            : 'border-flame-200 bg-flame-100/70'
        }`}
      >
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold text-ink-600">
              {participant.name} 님 ·{' '}
              {participant.isCouncilMember ? '총학생회비 납부자' : '총학생회비 미납부자'}
            </p>
            <p className="mt-1 text-xl font-black text-ink-900">
              {isConfirmed
                ? '참가가 확정됐어요!'
                : isSettled
                  ? '납입 확인 완료 · 확정 대기 중'
                  : '아직 납입이 완료되지 않았어요'}
            </p>
          </div>
          <PaymentBadge status={participant.status} />
        </div>
      </div>

      <dl className="divide-y divide-sand-100">
        {/*
          참가비가 두 겹이라 한 줄로 합쳐 보이면 읽는 사람이 계산을 해야 한다.
          뒤풀이에 가지 않는 사람에게는 겹이 하나뿐이므로 예전처럼 한 줄로 둔다.
        */}
        {participant.joinsAfterparty ? (
          <>
            <Row label="본 행사 참가비" value={formatWon(participant.baseFee)} />
            <Row label={`${EVENT.afterparty.label} 참가비`} value={formatWon(participant.afterpartyFee)} />
            <Row label="합계" value={formatWon(participant.expectedAmount)} />
          </>
        ) : (
          <Row label="참가비" value={formatWon(participant.expectedAmount)} />
        )}
        <Row label="확인된 입금액" value={formatWon(participant.paidAmount)} />
        {participant.remainingAmount > 0 && (
          <Row
            label="남은 금액"
            value={formatWon(participant.remainingAmount)}
            highlight="text-flame-600"
          />
        )}
        {participant.lastPaidAt && (
          <Row label="최근 입금 확인" value={formatDateTime(participant.lastPaidAt)} />
        )}
        <Row
          label="참가 확정"
          value={
            isConfirmed && participant.confirmedAt
              ? formatDateTime(participant.confirmedAt)
              : isConfirmed
                ? '확정'
                : '대기 중'
          }
          highlight={isConfirmed ? 'text-sand-700' : 'text-flame-600'}
        />
      </dl>

      {participant.joinsAfterparty && !participant.isCancelled && (
        <AfterpartyGuide participant={participant} />
      )}

      {participant.isCancelled && (
        <p className="border-t border-sand-100 bg-sand-50 px-6 py-4 text-sm text-ink-600">
          참가 취소로 처리된 신청이에요. 착오가 있다면 아래 연락처로 알려 주세요.
        </p>
      )}

      {isConfirmed && !participant.isCancelled && <ConfirmedGuide />}
      {isSettled && !isConfirmed && !participant.isCancelled && <AwaitingConfirmGuide />}
      {!isSettled && !participant.isCancelled && <UnpaidGuide sync={sync} />}
    </div>
  )
}

/**
 * 뒤풀이비 안내.
 *
 * 뒤풀이비는 **별도 안내를 통해 나중에 걷는다.** 그래서 본 행사 참가비를 다 낸
 * 사람이 이 화면에서 '남은 금액'을 보고 "입금이 안 들어갔나" 하고 문의하게 된다.
 * 그 오해를 여기서 먼저 막는다 — 아직 안 냈어도 **본 행사 참가에는 지장이 없다.**
 *
 * 반대로 안내가 나가기 전에 이미 합쳐서 보낸 사람에게는 '다시 내지 않아도 된다'고
 * 분명히 말해 준다. 그 사람들이 안내 문자를 받고 한 번 더 보내는 것이 가장 흔한 사고다.
 */
function AfterpartyGuide({ participant }: { participant: PublicParticipant }) {
  const settled = participant.afterpartyStatus === 'PAID'
  return (
    <div
      className={`border-t px-6 py-5 ${
        settled ? 'border-sand-100 bg-sand-50' : 'border-flame-200 bg-flame-100/50'
      }`}
    >
      <p className={`text-sm font-black ${settled ? 'text-sand-700' : 'text-flame-600'}`}>
        {settled
          ? `${EVENT.afterparty.label} 참가비도 확인됐어요`
          : `${EVENT.afterparty.label} 참가비는 아직 확인되지 않았어요`}
      </p>
      <p className="mt-2 text-sm leading-relaxed text-ink-600 break-keep">
        {settled ? (
          participant.afterpartyPrepaid ? (
            <>
              본 행사 참가비와 <strong className="text-ink-800">함께 보내 주셔서</strong> 솔로파티
              참가비까지 납입이 끝났습니다. 별도 안내를 받으시더라도 다시 내지 않으셔도 됩니다.
            </>
          ) : (
            `${EVENT.afterparty.label} 참가비 납입이 확인되었습니다.`
          )
        ) : (
          <>
            {EVENT.afterparty.label} 참가비 {formatWon(participant.afterpartyFee)} 은 별도 안내를 통해 따로 받습니다.
            아직 내지 않으셨어도 <strong className="text-ink-800">본 행사 참가에는 지장이 없어요.</strong>
            {' '}안내를 받으신 뒤에 보내 주세요.
          </>
        )}
      </p>
    </div>
  )
}

/**
 * 확정 대기 안내.
 *
 * 납입이 확인됐는데도 '확정'이 아니면 참가자는 무언가 잘못된 줄 안다.
 * 확정이 사람 손을 거치는 별도 단계라는 것을 여기서 분명히 말해 둔다.
 */
function AwaitingConfirmGuide() {
  return (
    <div className="border-t border-sand-100 bg-sand-50 px-6 py-5">
      <p className="text-sm font-black text-ink-800">입금은 확인됐어요</p>
      <p className="mt-2 text-sm leading-relaxed text-ink-600">
        학생회가 명단을 확인한 뒤 참가를 확정합니다. 확정되면 이 화면에 바로 표시되니 조금만
        기다려 주세요. 오래 걸린다면 아래 채널로 문의해 주세요.
      </p>
      <div className="mt-3">
        <ContactChannels compact />
      </div>
    </div>
  )
}

function ConfirmedGuide() {
  return (
    <div className="border-t border-sand-100 bg-sand-50 px-6 py-5">
      <p className="text-sm font-black text-sand-700">참가가 확정됐습니다</p>
      <p className="mt-2 text-sm leading-relaxed text-ink-600 break-keep">
        조 배정은 행사 전에 안내되고, 당일 행사장 입구에 붙은 QR 로 직접 출석 체크인하면
        조 번호와 럭키드로우 번호를 확인할 수 있어요.
      </p>
    </div>
  )
}

function Row({ label, value, highlight }: { label: string; value: string; highlight?: string }) {
  return (
    <div className="flex items-center justify-between px-6 py-3.5">
      <dt className="text-sm font-semibold text-ink-600">{label}</dt>
      <dd className={`text-base font-black tabular ${highlight ?? 'text-ink-900'}`}>{value}</dd>
    </div>
  )
}

function UnpaidGuide({ sync }: { sync: SyncState | null }) {
  return (
    <div className="border-t border-sand-100 bg-sand-50 px-6 py-5">
      <div className="rounded-2xl border-2 border-flame-200 bg-flame-100/60 px-4 py-3">
        <p className="text-sm font-black text-flame-600">이미 입금하셨나요?</p>
        <p className="mt-1.5 text-sm leading-relaxed text-ink-700">
          {sync?.coverageUntil
            ? `현재 ${formatDateTime(sync.coverageUntil)}까지의 입금만 확인된 상태예요.`
            : '아직 입금 내역이 반영되지 않은 상태예요.'}{' '}
          그 이후에 보내셨다면 아직 반영되지 않은 것이니 조금 기다려 주세요.
        </p>
      </div>

      <p className="mt-4 text-sm font-black text-ink-800">아직 입금하지 않으셨다면</p>
      <p className="mt-2 text-sm leading-relaxed text-ink-600">
        {EVENT.account.bank} <span className="tabular font-bold">{EVENT.account.number}</span> (
        {EVENT.account.holder})
        <br />
        입금자명 · {EVENT.account.depositNameRule}
      </p>
      <p className="mt-4 text-xs leading-relaxed text-ink-500">
        반영된 시점 이전에 입금했는데도 미납으로 나온다면, 입금자명이 신청자 이름과 다를 수 있어요.
        아래 채널로 <strong className="text-ink-700">입금하신 이름과 날짜</strong>를 알려 주세요.
      </p>
      <div className="mt-3">
        <ContactChannels compact />
      </div>
    </div>
  )
}

function NotFoundCard({ message }: { message: string }) {
  return (
    <div className="card p-6">
      <p className="text-base font-black text-ink-900">{message}</p>

      <div className="mt-4 rounded-2xl border-2 border-cobalt-200 bg-cobalt-50 px-4 py-3.5">
        <p className="text-sm font-black text-cobalt-600">혹시 신청 폼을 작성하셨나요?</p>
        <p className="mt-1.5 text-sm leading-relaxed text-ink-700">
          이 조회는 <strong className="text-ink-900">신청 폼 제출 내역</strong>을 기준으로 합니다.
          입금을 마치셨더라도 폼을 작성하지 않으셨다면 조회되지 않고, 참가도 확정되지 않아요.
        </p>
        <ApplyLink className="btn-primary mt-3" />
        <ApplySchedule className="mt-3 bg-white/70" />
      </div>

      <p className="mt-5 text-sm font-bold text-ink-700">이미 신청하셨다면</p>
      <ul className="mt-2 space-y-2 text-sm leading-relaxed text-ink-600">
        <li>· 이름과 전화번호가 신청서에 적은 것과 같은지 확인해 주세요.</li>
        <li>· 전화번호를 다르게 적으셨다면 그 번호로 조회해 보세요.</li>
        <li>· 신청 직후에는 반영까지 잠시 걸릴 수 있어요.</li>
      </ul>

      <div className="mt-4">
        <ContactChannels compact />
      </div>
    </div>
  )
}
