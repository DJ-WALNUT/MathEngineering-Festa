/**
 * 지금 신청을 받는 차수를 고른다.
 *
 * 얼리버드와 본모집은 참가비가 같고 구글 폼만 다르기 때문에,
 * 화면마다 링크를 적어 두면 차수가 넘어갈 때 한 군데씩 빠뜨리게 된다.
 * 링크를 고르는 규칙은 여기 한 곳에만 둔다.
 */

import { EVENT, type ApplyPhase } from '../data/event'

export type ApplyPhaseStatus = 'closed' | 'open' | 'upcoming'

export interface ApplyPhaseState {
  phase: ApplyPhase
  status: ApplyPhaseStatus
}

export interface ApplyState {
  phases: ApplyPhaseState[]
  /** 지금 신청을 받는 차수. 시작 전이거나 전부 마감이면 null */
  openPhase: ApplyPhase | null
  /** 아직 시작하지 않은 차수 중 가장 먼저 열리는 것 */
  nextPhase: ApplyPhase | null
  /** 열린 차수의 폼 주소. 아직 링크를 안 넣었으면 null */
  applyUrl: string | null
  allClosed: boolean
}

/** 잘못 적어 둔 날짜 때문에 신청이 통째로 막히지 않도록, 못 읽으면 null 로 넘긴다. */
function toTime(iso: string): number | null {
  const time = new Date(iso).getTime()
  return Number.isNaN(time) ? null : time
}

/**
 * startsAt ~ endsAt 사이에 있는 차수만 신청을 받는다.
 * 시작 전이면 예정, 마감 시각이 지났으면 마감이다.
 */
export function resolveApplyState(now: Date = new Date()): ApplyState {
  const time = now.getTime()

  const phases = EVENT.applyPhases.map((phase): ApplyPhaseState => {
    const startsAt = toTime(phase.startsAt)
    const endsAt = toTime(phase.endsAt)
    if (endsAt !== null && endsAt < time) return { phase, status: 'closed' }
    if (startsAt !== null && startsAt > time) return { phase, status: 'upcoming' }
    return { phase, status: 'open' }
  })

  const openPhase = phases.find((state) => state.status === 'open')?.phase ?? null
  const nextPhase = phases.find((state) => state.status === 'upcoming')?.phase ?? null

  return {
    phases,
    openPhase,
    nextPhase,
    applyUrl: openPhase?.formUrl ? openPhase.formUrl : null,
    allClosed: phases.length > 0 && phases.every((state) => state.status === 'closed'),
  }
}
