/**
 * 참가 신청 버튼과 신청 기간 안내.
 *
 * 차수마다 구글 폼이 다르므로 링크는 resolveApplyState 가 고른 것만 쓴다.
 * 마감했거나 폼 링크가 아직 없으면 눌리지 않는 버튼으로 바꿔, 엉뚱한 폼으로
 * 보내는 대신 화면에서 바로 티가 나게 한다.
 */

import { EVENT, type ApplyPhase } from '../data/event'
import { resolveApplyState, type ApplyPhaseStatus } from '../lib/apply'
import { daysUntil, formatDay, formatDeadline } from '../lib/format'

interface ApplyLinkProps {
  className?: string
  /** 링크가 살아 있을 때의 문구. 비우면 '얼리버드 신청하기' 처럼 차수 이름을 붙인다. */
  label?: string
}

export function ApplyLink({ className = 'btn-primary', label }: ApplyLinkProps) {
  const { openPhase, nextPhase, applyUrl } = resolveApplyState()

  if (!openPhase) {
    // 아직 시작 전이면 마감이 아니라 '언제부터'를 알려 줘야 한다.
    return (
      <button type="button" disabled className={className}>
        {nextPhase ? `${formatDay(nextPhase.startsAt)} 신청 시작` : '신청이 마감됐어요'}
      </button>
    )
  }

  if (!applyUrl) {
    return (
      <button type="button" disabled className={className}>
        {openPhase.label} 폼 준비 중
      </button>
    )
  }

  return (
    <a href={applyUrl} target="_blank" rel="noreferrer noopener" className={className}>
      {label ?? `${openPhase.label} 신청하기`}
    </a>
  )
}

/** 상태별 색. 지금 받는 차수만 또렷하게 두고 나머지는 뒤로 물린다. */
const PHASE_STYLE: Record<ApplyPhaseStatus, { row: string; label: string; date: string; badge: string }> = {
  open: {
    row: 'border-ink-900 bg-white shadow-[3px_3px_0_var(--color-ink-900)]',
    label: 'text-ink-900',
    date: 'text-ink-700',
    badge: 'border-2 border-ink-900 bg-cobalt-500 text-white',
  },
  upcoming: {
    row: 'border-ink-900 bg-white/70',
    label: 'text-ink-700',
    date: 'text-ink-500',
    badge: 'border-2 border-ink-900 bg-white text-ink-700',
  },
  closed: {
    row: 'border-ink-300 bg-white/50',
    label: 'text-ink-400',
    date: 'text-ink-400 line-through',
    badge: 'border-2 border-ink-300 bg-sand-100 text-ink-500',
  },
}

function statusLabel(status: ApplyPhaseStatus, phase: ApplyPhase): string {
  if (status === 'closed') return '마감'

  if (status === 'upcoming') {
    const untilStart = daysUntil(phase.startsAt)
    if (untilStart === null) return '예정'
    return untilStart <= 0 ? '곧 시작' : `D-${untilStart}`
  }

  const untilEnd = daysUntil(phase.endsAt)
  if (untilEnd === null) return '신청 중'
  return untilEnd <= 0 ? '오늘 마감' : `신청 중 · D-${untilEnd}`
}

/** 차수별 신청 기간을 한 줄씩 세워 보여 준다. */
export function ApplySchedule({ className }: { className?: string }) {
  const { phases, openPhase, nextPhase, allClosed } = resolveApplyState()

  // 차수가 하나뿐인 행사와 여럿인 행사가 같은 화면을 쓴다. '두 차수' 같은 말은 세지 않는다.
  const note = allClosed
    ? '신청이 마감됐어요. 추가 모집 여부는 학생회 인스타그램으로 안내됩니다.'
    : openPhase
      // 신청 버튼이 이 안내보다 위에만 있는 것은 아니라, '위 버튼'이라 부르지 않는다.
      ? `선착순이에요. 1부 교류전 ${EVENT.capacity}명 · 2부 솔로파티 ${EVENT.afterpartyCapacity}명(교류전 참여자 중). 신청 버튼은 ${openPhase.label} 폼으로 연결돼요.`
      : nextPhase
        ? `${formatDay(nextPhase.startsAt)}부터 ${nextPhase.label}이 시작됩니다. 시작하면 신청 버튼이 열려요.`
        : '신청 기간이 정해지면 여기에 안내됩니다.'

  return (
    <div
      className={`rounded-md border-2 border-ink-900 bg-sand-50 p-4 sm:p-5 ${className ?? ''}`}
    >
      <p className="font-pixel-small text-xs font-bold text-ink-500">신청 기간</p>

      <ul className="mt-3 space-y-2">
        {phases.map(({ phase, status }) => {
          const style = PHASE_STYLE[status]
          return (
            <li
              key={phase.key}
              className={`flex items-center justify-between gap-3 rounded-md border-2 px-3.5 py-2.5 ${style.row}`}
            >
              <div className="min-w-0">
                <p className={`text-sm font-black ${style.label}`}>{phase.label}</p>
                <p className={`mt-0.5 text-xs font-semibold tabular ${style.date}`}>
                  {formatDeadline(phase.startsAt)} ~ {formatDeadline(phase.endsAt)}
                </p>
              </div>
              <span
                className={`font-pixel-small shrink-0 rounded-sm px-2.5 py-1 text-[11px] font-bold tabular ${style.badge}`}
              >
                {statusLabel(status, phase)}
              </span>
            </li>
          )
        })}
      </ul>

      <p className="mt-3 text-xs leading-relaxed text-ink-500">{note}</p>
    </div>
  )
}
