export function formatWon(amount: number | null | undefined): string {
  if (amount === null || amount === undefined) return '-'
  return `${amount.toLocaleString('ko-KR')}원`
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '-'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return new Intl.DateTimeFormat('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

/**
 * 신청 일정에 쓰는 날짜 표기.
 * 한국 시간 기준 일정이라 보는 사람의 시간대와 무관하게 KST 로 고정한다.
 */
function formatKst(iso: string, withTime: boolean): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul',
    month: 'long',
    day: 'numeric',
    weekday: 'short',
    ...(withTime ? { hour: '2-digit' as const, minute: '2-digit' as const, hour12: false } : {}),
  })
    .format(date)
    .replace(' (', '(')
}

/** '7월 27일(월)' — 신청 시작일처럼 시각이 중요하지 않을 때 */
export function formatDay(iso: string): string {
  return formatKst(iso, false)
}

/** '8월 2일(일) 23:59' — 마감처럼 시각까지 못 박아야 할 때 */
export function formatDeadline(iso: string): string {
  return formatKst(iso, true)
}

/** 입력 중인 전화번호를 010-1234-5678 꼴로 다듬는다. */
export function formatPhoneInput(value: string): string {
  const digits = value.replace(/\D/g, '').slice(0, 11)
  if (digits.length <= 3) return digits
  if (digits.length <= 7) return `${digits.slice(0, 3)}-${digits.slice(3)}`
  return `${digits.slice(0, 3)}-${digits.slice(3, 7)}-${digits.slice(7)}`
}

export function daysUntil(iso: string): number | null {
  const target = new Date(iso)
  if (Number.isNaN(target.getTime())) return null
  const today = new Date()
  const startOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  const startOfTarget = new Date(target.getFullYear(), target.getMonth(), target.getDate())
  return Math.round((startOfTarget.getTime() - startOfToday.getTime()) / 86_400_000)
}
