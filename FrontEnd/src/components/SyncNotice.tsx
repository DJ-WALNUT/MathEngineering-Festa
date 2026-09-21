import type { SyncState } from '../lib/api'
import { formatDateTime } from '../lib/format'

/**
 * '입금 확인은 실시간이 아니다'를 알리는 안내.
 *
 * 카카오뱅크 개인 계좌에는 공개 API가 없어 담당자가 거래내역 파일을 올린
 * 시점까지만 반영된다. 이 사실을 숨기면 "돈 냈는데 미납으로 뜬다"는 문의가
 * 쏟아지므로, 조회 화면 맨 위에 반영 시점을 그대로 보여준다.
 */
export default function SyncNotice({ sync }: { sync: SyncState | null }) {
  return (
    <div className="rounded-2xl border-2 border-flame-200 bg-flame-100/50 px-5 py-4">
      <p className="flex items-center gap-2 text-sm font-black text-flame-600">
        <ClockIcon />
        입금 확인은 실시간이 아니에요
      </p>
      <p className="mt-2 text-sm leading-relaxed text-ink-700">
        은행 거래내역을 담당자가 직접 확인해 올리는 방식이라, 방금 입금하셨다면 아직 반영되지 않았을
        수 있어요.
      </p>

      {sync?.hasData ? (
        <dl className="mt-3 space-y-1 text-xs text-ink-600">
          <div className="flex gap-2">
            <dt className="font-bold text-ink-500">확인된 입금</dt>
            <dd className="font-semibold tabular">
              {sync.coverageUntil ? `${formatDateTime(sync.coverageUntil)}까지` : '-'}
            </dd>
          </div>
          <div className="flex gap-2">
            <dt className="font-bold text-ink-500">마지막 반영</dt>
            <dd className="font-semibold tabular">{formatDateTime(sync.lastImportedAt)}</dd>
          </div>
        </dl>
      ) : (
        <p className="mt-3 text-xs font-semibold text-ink-500">
          아직 입금 내역이 한 번도 반영되지 않았어요.
        </p>
      )}
    </div>
  )
}

function ClockIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth={2.5}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
