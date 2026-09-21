import { useEffect, useState } from 'react'

import { adminApi, type Summary } from '../../lib/api'
import { formatDateTime, formatWon } from '../../lib/format'

const STATUS_LABEL: Record<string, string> = {
  PAID: '납입 완료',
  UNPAID: '미납',
  UNDERPAID: '부분 입금',
  OVERPAID: '초과 납입',
  REFUNDED: '환불',
  WAIVED: '면제',
}

const DEPOSIT_LABEL: Record<string, string> = {
  MATCHED: '확인 완료',
  AMBIGUOUS: '판단 보류',
  UNMATCHED: '미매칭',
  MINOR: '기타 입금',
  IGNORED: '무관',
}

/**
 * 대시보드.
 *
 * **읽는 화면이다.** 다른 탭으로 건너뛰는 버튼과 다른 탭에서 할 일(거래내역
 * 업로드 · 재매칭 · 스태프 참가비)은 각자의 탭으로 옮겼다. 관리자마다 열리는
 * 탭이 다르므로, 여기에 남겨 두면 권한이 없는 화면으로 가는 버튼이 보인다.
 */
export default function SummaryPanel({ revision }: { revision: number }) {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    adminApi
      .summary()
      .then(setSummary)
      .catch((caught) => setError(caught.message ?? '요약을 불러오지 못했습니다.'))
  }, [revision])

  if (error) return <p className="text-sm font-semibold text-brick-500">{error}</p>
  if (!summary) return <p className="text-sm text-ink-500">불러오는 중…</p>

  const { participants, amounts, deposits, afterparty } = summary

  return (
    <div className="space-y-6">
      <div
        className={`card p-5 ${
          summary.sync.hasData ? '' : 'border-flame-300 bg-flame-100/50'
        }`}
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-sm font-black text-ink-800">입금 반영 현황</p>
            {summary.sync.hasData ? (
              <>
                <p className="mt-1.5 text-sm text-ink-600 tabular">
                  {summary.sync.coverageUntil
                    ? `${formatDateTime(summary.sync.coverageUntil)}까지의 입금이 확인된 상태`
                    : '반영 범위를 알 수 없음'}
                </p>
                <p className="mt-0.5 text-xs text-ink-500 tabular">
                  마지막 업로드 {formatDateTime(summary.sync.lastImportedAt)}
                  {summary.sync.lastFilename && ` · ${summary.sync.lastFilename}`}
                </p>
              </>
            ) : (
              <p className="mt-1.5 text-sm font-semibold text-flame-600">
                아직 거래내역 파일을 한 번도 올리지 않았습니다. 참가자 화면에는 모두 미납으로
                표시됩니다.
              </p>
            )}
          </div>
        </div>
      </div>

      {deposits.unparsedCount > 0 && (
        <div className="card border-brick-400/50 bg-brick-400/8 p-5">
          <p className="text-sm font-black text-brick-500">
            해석하지 못한 알림 {deposits.unparsedCount}건
          </p>
          <p className="mt-1 text-xs text-ink-600">
            &lsquo;읽지 못한 알림&rsquo; 탭에서 원문을 확인하고 파싱 규칙을 맞춰 주세요. 원문은
            보관되어 있어 되살릴 수 있습니다.
          </p>
        </div>
      )}

      {deposits.needsReview > 0 && (
        <div className="card border-flame-300 bg-flame-100/60 p-5">
          <p className="text-sm font-black text-flame-600">
            확인이 필요한 입금 {deposits.needsReview}건이 있습니다
          </p>
          <p className="mt-1 text-xs text-ink-600">
            &lsquo;입금 내역&rsquo; 탭에서 미매칭 · 확인 필요 건을 처리해 주세요.
          </p>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <StatCard
          label="신청 인원"
          value={`${participants.active}명`}
          sub={`취소 ${participants.cancelled}명`}
        />
        <StatCard
          label="납입 완료"
          value={`${participants.byStatus.PAID ?? 0}명`}
          sub={`납입률 ${participants.paidRate}%`}
          accent
        />
        <StatCard
          label="참가 확정"
          value={`${participants.confirmed}명`}
          sub={
            participants.awaitingConfirm > 0
              ? `확정 대기 ${participants.awaitingConfirm}명`
              : `출석 ${participants.checkedIn}명`
          }
          accent={participants.awaitingConfirm === 0}
        />
        <StatCard
          label="수납 금액"
          value={formatWon(amounts.collectedTotal)}
          sub={`목표 ${formatWon(amounts.expectedTotal)}`}
        />
        <StatCard
          label="미확인 입금"
          value={formatWon(amounts.unallocatedTotal)}
          sub={`최근 입금 ${formatDateTime(deposits.lastDepositAt)}`}
        />
      </div>

      {participants.awaitingConfirm > 0 && (
        <div className="card border-cobalt-200 bg-cobalt-50 p-5">
          <p className="text-sm font-black text-cobalt-600">
            납입이 끝났는데 확정하지 않은 참가자 {participants.awaitingConfirm}명
          </p>
          <p className="mt-1 text-xs leading-relaxed text-ink-600">
            &lsquo;참가자&rsquo; 탭에서 확정하면 조 배정과 셀프 체크인이 열립니다. 참가자 본인
            화면에도 &lsquo;확정 대기 중&rsquo;으로 보이는 상태입니다.
          </p>
        </div>
      )}

      <div className="card p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-black text-ink-800">납입 진행률</h2>
          <span className="text-sm font-black text-sand-600 tabular">{participants.paidRate}%</span>
        </div>
        <div className="mt-3 h-3 overflow-hidden rounded-full bg-sand-100">
          <div
            className="h-full rounded-full bg-sand-400 transition-all"
            style={{ width: `${Math.min(participants.paidRate, 100)}%` }}
          />
        </div>

        <ul className="mt-5 grid gap-2 sm:grid-cols-3">
          {Object.entries(participants.byStatus).map(([status, count]) => (
            <li
              key={status}
              className="flex items-center justify-between rounded-xl border border-sand-200 bg-sand-50/50 px-3 py-2 text-sm"
            >
              <span className="font-semibold text-ink-600">{STATUS_LABEL[status] ?? status}</span>
              <span className="font-black text-ink-900 tabular">{count}명</span>
            </li>
          ))}
        </ul>
      </div>

      {/*
        뒤풀이는 참가비도 출석도 본 행사와 따로 센다.
        **뒤풀이비는 별도 안내로 걷으므로 '아직 안 낸 사람'이 곧 안내 대상이다.**
        신청자가 없으면 이 카드 자체를 띄우지 않는다 — 0으로 가득한 칸은 읽을 것이 없다.
      */}
      {afterparty.joining > 0 && (
        <div className="card p-5">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-sm font-black text-ink-800">뒤풀이</h2>
            <span className="text-xs font-semibold text-ink-500 tabular">
              1인 {formatWon(afterparty.fee)}
            </span>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-ink-500 break-keep">
            뒤풀이비는 본 행사비와 따로 셉니다. 아직 안 냈다고 해서 본 행사 참가가 막히지
            않고, 대신 <strong className="text-ink-700">별도 안내를 보낼 명단</strong>이 됩니다.
          </p>

          <ul className="mt-3 grid gap-2 sm:grid-cols-4">
            <FeeStat label="신청" value={`${afterparty.joining}명`} />
            <FeeStat label="납입 완료" value={`${afterparty.paid}명`} tone="text-sand-700" />
            <FeeStat label="안내 대상" value={`${afterparty.unpaid}명`} tone="text-flame-600" />
            <FeeStat label="합산 납부" value={`${afterparty.prepaid}명`} tone="text-heart-500" />
          </ul>

          <p className="mt-3 text-sm font-semibold text-ink-600 tabular">
            수납 {formatWon(afterparty.collectedTotal)} / {formatWon(afterparty.expectedTotal)}
          </p>
          {afterparty.prepaid > 0 && (
            <p className="mt-1 text-[11px] leading-relaxed text-ink-400 break-keep">
              &lsquo;합산 납부&rsquo;는 안내가 나가기 전에 본 행사비와 뒤풀이비를 한 번에 보낸
              사람입니다. 참가자 탭에 배지로 붙어 있으니 안내를 보낼 때 빼 주세요.
            </p>
          )}
        </div>
      )}

      <div className="card p-5">
        <h2 className="text-sm font-black text-ink-800">입금 처리 현황</h2>
        {deposits.minorThreshold > 0 && (
          <p className="mt-1 text-xs text-ink-500">
            이름이 맞지 않으면서 {formatWon(deposits.minorThreshold)} 미만인 입금은 &lsquo;기타
            입금&rsquo;으로 분리됩니다. 지워지지 않으니 언제든 다시 볼 수 있습니다.
          </p>
        )}
        <ul className="mt-3 grid gap-2 sm:grid-cols-5">
          {(['MATCHED', 'AMBIGUOUS', 'UNMATCHED', 'MINOR', 'IGNORED'] as const).map((status) => (
            <li
              key={status}
              className="flex items-center justify-between rounded-xl border border-sand-200 bg-sand-50/50 px-3 py-2 text-sm"
            >
              <span className="font-semibold text-ink-600">{DEPOSIT_LABEL[status]}</span>
              <span className="font-black text-ink-900 tabular">
                {deposits.byStatus[status] ?? 0}
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-ghost"
          onClick={() => adminApi.downloadParticipantsCsv().catch((caught) => alert(caught.message))}
        >
          참가자 명단 CSV 내려받기
        </button>
      </div>

      <p className="text-xs text-ink-400">기준 시각 · {formatDateTime(summary.generatedAt)}</p>
    </div>
  )
}

function FeeStat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <li className="rounded-xl border border-sand-200 bg-sand-50/50 px-3 py-2">
      <p className="text-[11px] font-bold text-ink-500">{label}</p>
      <p className={`mt-0.5 text-lg font-black tabular ${tone ?? 'text-ink-900'}`}>{value}</p>
    </li>
  )
}

function StatCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string
  value: string
  sub?: string
  accent?: boolean
}) {
  return (
    <div className="card p-4">
      <p className="text-xs font-bold text-ink-500">{label}</p>
      <p
        className={`mt-1.5 text-2xl font-black tabular ${accent ? 'text-sand-600' : 'text-ink-900'}`}
      >
        {value}
      </p>
      {sub && <p className="mt-1 text-xs text-ink-500">{sub}</p>}
    </div>
  )
}
