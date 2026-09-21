import type { DepositStatus, PaymentStatus } from '../lib/api'

const PAYMENT_STYLE: Record<PaymentStatus, { label: string; className: string }> = {
  PAID: { label: '납입 완료', className: 'bg-sand-100 text-sand-700 border-sand-300' },
  UNPAID: { label: '미납', className: 'bg-brick-400/12 text-brick-500 border-brick-400/40' },
  UNDERPAID: { label: '부분 입금', className: 'bg-gold-400/18 text-flame-600 border-gold-400/50' },
  OVERPAID: { label: '초과 납입', className: 'bg-cobalt-100 text-cobalt-600 border-cobalt-300' },
  REFUNDED: { label: '환불', className: 'bg-ink-400/12 text-ink-600 border-ink-400/40' },
  WAIVED: { label: '면제', className: 'bg-heart-400/15 text-heart-500 border-heart-400/40' },
}

const DEPOSIT_STYLE: Record<DepositStatus, { label: string; className: string }> = {
  MATCHED: { label: '확인 완료', className: 'bg-sand-100 text-sand-700 border-sand-300' },
  AMBIGUOUS: { label: '확인 필요', className: 'bg-gold-400/18 text-flame-600 border-gold-400/50' },
  UNMATCHED: { label: '미매칭', className: 'bg-brick-400/12 text-brick-500 border-brick-400/40' },
  MINOR: { label: '기타 입금', className: 'bg-cobalt-100 text-cobalt-600 border-cobalt-300' },
  IGNORED: { label: '무관 입금', className: 'bg-ink-400/12 text-ink-500 border-ink-400/40' },
}

// 좁은 화면에서 옆 내용이 길면 배지가 먼저 눌려 글자가 접힌다.
// 알약 안에서 줄이 갈리면 상태가 눈에 안 들어오므로, 배지는 제 폭을 지키고
// 줄어드는 쪽은 옆 본문이 맡는다.
const BASE =
  'inline-flex shrink-0 items-center whitespace-nowrap rounded-full border px-2.5 py-1 text-xs font-bold'

export function PaymentBadge({ status }: { status: PaymentStatus }) {
  const style = PAYMENT_STYLE[status] ?? PAYMENT_STYLE.UNPAID
  return <span className={`${BASE} ${style.className}`}>{style.label}</span>
}

export function DepositBadge({ status }: { status: DepositStatus }) {
  const style = DEPOSIT_STYLE[status] ?? DEPOSIT_STYLE.UNMATCHED
  return <span className={`${BASE} ${style.className}`}>{style.label}</span>
}
