import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

import { DepositBadge } from '../../components/StatusBadge'
import { adminApi, type AdminDeposit, type ImportResult, type Summary } from '../../lib/api'
import { formatDateTime, formatWon } from '../../lib/format'
import AllocationDialog from './AllocationDialog'

const FILTERS = [
  { id: 'REVIEW', label: '확인 필요' },
  { id: '', label: '전체' },
  { id: 'MATCHED', label: '확인 완료' },
  { id: 'UNMATCHED', label: '미매칭' },
  { id: 'AMBIGUOUS', label: '판단 보류' },
  { id: 'MINOR', label: '기타 입금' },
  { id: 'IGNORED', label: '무관' },
] as const

const SOURCE_LABEL: Record<string, string> = {
  push: '알림',
  import: '엑셀',
  // 행사 당일 접수대에서 받은 것. 계좌를 거치지 않아 거래내역에는 뜨지 않는다.
  onsite: '현장',
  manual: '수기',
}

export default function DepositsPanel({
  revision,
  onChanged,
}: {
  revision: number
  onChanged: () => void
}) {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [filter, setFilter] = useState<string>('REVIEW')
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<AdminDeposit[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [dialogDeposit, setDialogDeposit] = useState<AdminDeposit | null>(null)
  const [showManualForm, setShowManualForm] = useState(false)
  const [importResult, setImportResult] = useState<ImportResult | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const response = await adminApi.deposits({ status: filter, query, pageSize: 200 })
      setItems(response.items)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '입금 내역을 불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }, [filter, query])

  useEffect(() => {
    const timer = setTimeout(load, query ? 250 : 0)
    return () => clearTimeout(timer)
  }, [load, revision])

  // 스태프 참가비는 이 탭에서 고친다. 금액을 다루는 화면이 한곳에 모여 있어야
  // 관리자마다 다른 탭이 열려도 '돈은 여기'가 흐트러지지 않는다.
  useEffect(() => {
    adminApi
      .summary()
      .then(setSummary)
      .catch(() => setSummary(null))
  }, [revision])

  const handleImport = async (file: File) => {
    setImportResult(null)
    try {
      const result = await adminApi.importStatement(file)
      setImportResult(result)
      onChanged()
    } catch (caught) {
      alert(caught instanceof Error ? caught.message : '업로드에 실패했습니다.')
    } finally {
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  const act = async (action: () => Promise<unknown>) => {
    try {
      await action()
      onChanged()
    } catch (caught) {
      alert(caught instanceof Error ? caught.message : '처리에 실패했습니다.')
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-2">
        {FILTERS.map((item) => (
          <button
            key={item.label}
            type="button"
            onClick={() => setFilter(item.id)}
            className={`rounded-full border-2 px-3.5 py-1.5 text-sm font-bold transition ${
              filter === item.id
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
          placeholder="입금자명 또는 금액 검색"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <input
          ref={fileInput}
          type="file"
          accept=".xlsx,.xlsm,.csv"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) void handleImport(file)
          }}
        />
        <button type="button" className="btn-ghost" onClick={() => fileInput.current?.click()}>
          거래내역 업로드
        </button>
        <button type="button" className="btn-ghost" onClick={() => setShowManualForm((open) => !open)}>
          입금 수기 등록
        </button>
      </div>

      {importResult && <ImportSummary result={importResult} onClose={() => setImportResult(null)} />}
      {showManualForm && (
        <ManualDepositForm
          onDone={() => {
            setShowManualForm(false)
            onChanged()
          }}
        />
      )}

      {filter === 'MINOR' && (
        <div className="card border-cobalt-200 bg-cobalt-50 p-5">
          <p className="text-sm font-black text-cobalt-600">기타 입금</p>
          <p className="mt-1.5 text-xs leading-relaxed text-ink-600">
            이름이 신청자와 맞지 않으면서 참가비에 한참 못 미치는 소액입니다. 확인 필요 큐가
            잡음으로 차는 것을 막으려고 갈라 두었을 뿐, 지워지지 않았습니다. 참가비가 맞다면{' '}
            <strong className="text-ink-800">참가자 지정</strong>을, 확인 필요 큐로 되돌리려면{' '}
            <strong className="text-ink-800">다시 검토</strong>를 눌러 주세요.
          </p>
        </div>
      )}

      {error && <p className="text-sm font-semibold text-brick-500">{error}</p>}
      {loading && <p className="text-sm text-ink-500">불러오는 중…</p>}
      {!loading && items.length === 0 && (
        <p className="card p-8 text-center text-sm text-ink-500">해당하는 입금 내역이 없습니다.</p>
      )}

      <ul className="space-y-2.5">
        {items.map((deposit) => (
          <li key={deposit.id} className="card p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-base font-black text-ink-900">
                    {deposit.rawName || '(입금자명 없음)'}
                  </span>
                  <DepositBadge status={deposit.status} />
                  <span className="rounded-full border border-sand-200 bg-sand-50 px-2 py-0.5 text-[11px] font-semibold text-ink-500">
                    {SOURCE_LABEL[deposit.source] ?? deposit.source}
                  </span>
                  {deposit.manualLocked && (
                    <span className="rounded-full border border-heart-400/40 bg-heart-400/12 px-2 py-0.5 text-[11px] font-semibold text-heart-500">
                      수동 고정
                    </span>
                  )}
                </div>
                <p className="mt-1.5 text-sm font-semibold text-ink-600 tabular">
                  {formatWon(deposit.amount)} · {formatDateTime(deposit.occurredAt)}
                  {deposit.balanceAfter !== null && ` · 잔액 ${formatWon(deposit.balanceAfter)}`}
                </p>
                {deposit.matchReason && (
                  <p className="mt-1 text-xs leading-relaxed text-ink-500">{deposit.matchReason}</p>
                )}
                {deposit.allocations.length > 0 && (
                  <ul className="mt-2 flex flex-wrap gap-1.5">
                    {deposit.allocations.map((allocation) => (
                      <li
                        key={allocation.id}
                        className="rounded-full border border-sand-300 bg-sand-100 px-2.5 py-1 text-xs font-semibold text-sand-700"
                      >
                        {allocation.participantName} · {formatWon(allocation.amount)}
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="flex shrink-0 flex-wrap gap-1.5">
                <button
                  type="button"
                  className="btn-ghost px-3 py-1.5 text-xs"
                  onClick={() => setDialogDeposit(deposit)}
                >
                  참가자 지정
                </button>
                {deposit.allocations.length > 0 && (
                  <button
                    type="button"
                    className="btn-ghost px-3 py-1.5 text-xs"
                    onClick={() => act(() => adminApi.clearAllocations(deposit.id))}
                  >
                    연결 해제
                  </button>
                )}
                {deposit.status === 'MINOR' && (
                  <button
                    type="button"
                    className="btn-ghost px-3 py-1.5 text-xs"
                    onClick={() => act(() => adminApi.updateDeposit(deposit.id, { status: 'UNMATCHED' }))}
                  >
                    다시 검토
                  </button>
                )}
                {deposit.status !== 'IGNORED' ? (
                  <button
                    type="button"
                    className="btn-ghost px-3 py-1.5 text-xs"
                    onClick={() => {
                      if (confirm('이 입금을 행사와 무관한 건으로 처리할까요?')) {
                        void act(() => adminApi.updateDeposit(deposit.id, { status: 'IGNORED' }))
                      }
                    }}
                  >
                    무관 처리
                  </button>
                ) : (
                  <button
                    type="button"
                    className="btn-ghost px-3 py-1.5 text-xs"
                    onClick={() => act(() => adminApi.updateDeposit(deposit.id, { status: 'UNMATCHED' }))}
                  >
                    되돌리기
                  </button>
                )}
                <button
                  type="button"
                  className="btn-ghost px-3 py-1.5 text-xs"
                  onClick={() => {
                    const next = prompt('입금자명을 수정합니다', deposit.rawName)
                    if (next !== null && next !== deposit.rawName) {
                      void act(() => adminApi.updateDeposit(deposit.id, { rawName: next }))
                    }
                  }}
                >
                  이름 수정
                </button>
              </div>
            </div>
          </li>
        ))}
      </ul>

      {summary && (
        <div className="grid gap-4 lg:grid-cols-2">
          <FeeCard
            title="스태프 참가비"
            amount={summary.fees.staff}
            onSave={adminApi.setStaffFee}
            onChanged={onChanged}
            note={
              <>
                참가자 탭에서 요금 구분을 &lsquo;스태프&rsquo;로 바꾼 사람에게 적용됩니다.
                금액을 고치면{' '}
                <strong className="text-ink-700">
                  스태프 {summary.fees.staffCount}명 전원
                </strong>
                의 참가비가 함께 바뀝니다. 0원이면 낼 것이 없는 것으로 보아 면제로 처리됩니다.
              </>
            }
          />
          <FeeCard
            title="뒤풀이 참가비"
            amount={summary.fees.afterparty}
            onSave={adminApi.setAfterpartyFee}
            onChanged={onChanged}
            note={
              <>
                본 행사비 <strong className="text-ink-700">위에 얹히는</strong> 금액입니다.
                총학생회비 납부 여부와 무관하게 같고, 고치면{' '}
                <strong className="text-ink-700">
                  뒤풀이 신청자 {summary.afterparty.joining}명 전원
                </strong>
                의 청구액이 함께 바뀝니다. 이미 들어온 입금은 건드리지 않습니다.
              </>
            }
          />
        </div>
      )}

      {dialogDeposit && (
        <AllocationDialog
          deposit={dialogDeposit}
          onClose={() => setDialogDeposit(null)}
          onSaved={onChanged}
        />
      )}
    </div>
  )
}

/**
 * 화면에서 고치는 참가비 — 스태프 · 뒤풀이.
 *
 * 총학생회비 납부/미납부 금액과 달리 이 둘은 늦게 정해지고 바뀌므로 `.env` 가
 * 아니라 화면에서 고친다. 고치면 **해당하는 사람 전원의 예상 금액이 함께
 * 따라간다** — 한 명씩 다시 손보게 두면 금액이 섞인 채로 남아 수납 집계가 어긋난다.
 */
function FeeCard({
  title,
  note,
  amount,
  onSave,
  onChanged,
}: {
  title: string
  note: ReactNode
  amount: number
  onSave: (value: number) => Promise<{ amount: number; applied: number }>
  onChanged: () => void
}) {
  const [draft, setDraft] = useState(String(amount))
  const [busy, setBusy] = useState(false)

  // 다른 화면에서 바뀌었을 때 입력칸도 따라오게 한다.
  useEffect(() => setDraft(String(amount)), [amount])

  const parsed = Number(draft.replace(/[^\d]/g, ''))
  const dirty = Number.isFinite(parsed) && parsed !== amount

  const save = async () => {
    setBusy(true)
    try {
      const result = await onSave(parsed)
      alert(`${title}를 ${formatWon(result.amount)}으로 정했습니다. (${result.applied}명 반영)`)
      onChanged()
    } catch (caught) {
      alert(caught instanceof Error ? caught.message : '금액을 저장하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card p-5">
      <h2 className="text-sm font-black text-ink-800">{title}</h2>
      <p className="mt-1 text-xs leading-relaxed text-ink-500 break-keep">{note}</p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <input
          className="input h-10 max-w-36 py-1.5 text-sm tabular"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          inputMode="numeric"
          aria-label={title}
        />
        <span className="text-sm font-semibold text-ink-500">원</span>
        <button
          type="button"
          className="btn-primary px-3.5 py-1.5 text-xs"
          onClick={save}
          disabled={!dirty || busy}
        >
          {busy ? '저장 중…' : '저장'}
        </button>
        {!dirty && <span className="text-xs text-ink-400">현재 {formatWon(amount)}</span>}
      </div>
    </div>
  )
}

function ImportSummary({ result, onClose }: { result: ImportResult; onClose: () => void }) {
  return (
    <div className="card border-cobalt-200 bg-cobalt-50 p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-black text-cobalt-600">{result.filename} 업로드 완료</p>
          <p className="mt-1.5 text-sm font-semibold text-ink-700 tabular">
            신규 {result.created}건 · 중복 {result.duplicated}건 · 건너뜀 {result.skippedCount}건
          </p>
          {result.decrypted && (
            <p className="mt-1 text-xs text-ink-500">비밀번호가 걸린 파일을 열어서 읽었습니다.</p>
          )}
          <p className="mt-1 text-xs text-ink-500">재매칭 {result.rematch.processed}건 처리됨</p>
          {result.skipped.length > 0 && (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs font-semibold text-ink-500">
                건너뛴 행 보기
              </summary>
              <ul className="mt-1.5 max-h-40 space-y-0.5 overflow-y-auto text-xs text-ink-500">
                {result.skipped.map((item) => (
                  <li key={item.row}>
                    {item.row}행 · {item.reason}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-sm font-semibold text-ink-400 hover:text-ink-700"
        >
          닫기
        </button>
      </div>
    </div>
  )
}

function ManualDepositForm({ onDone }: { onDone: () => void }) {
  const [rawName, setRawName] = useState('')
  const [amount, setAmount] = useState('')
  const [occurredAt, setOccurredAt] = useState('')
  const [memo, setMemo] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    const parsedAmount = Number(amount.replace(/,/g, ''))
    if (!parsedAmount || parsedAmount <= 0) {
      alert('금액을 확인해 주세요.')
      return
    }

    setBusy(true)
    try {
      const result = await adminApi.createDeposit({
        rawName: rawName.trim(),
        amount: parsedAmount,
        occurredAt: occurredAt || undefined,
        memo: memo || undefined,
      })
      if (!result.created) alert('이미 등록된 입금과 동일해 새로 추가되지 않았습니다.')
      setRawName('')
      setAmount('')
      setMemo('')
      onDone()
    } catch (caught) {
      alert(caught instanceof Error ? caught.message : '등록에 실패했습니다.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="card space-y-3 p-5">
      <p className="text-sm font-black text-ink-800">입금 수기 등록</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="label" htmlFor="manual-name">
            입금자명
          </label>
          <input
            id="manual-name"
            className="input"
            value={rawName}
            onChange={(event) => setRawName(event.target.value)}
            placeholder="홍길동5678"
          />
        </div>
        <div>
          <label className="label" htmlFor="manual-amount">
            금액
          </label>
          <input
            id="manual-amount"
            className="input tabular"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            inputMode="numeric"
            placeholder="45000"
          />
        </div>
        <div>
          <label className="label" htmlFor="manual-at">
            입금 일시 (비우면 현재 시각)
          </label>
          <input
            id="manual-at"
            type="datetime-local"
            className="input"
            value={occurredAt}
            onChange={(event) => setOccurredAt(event.target.value)}
          />
        </div>
        <div>
          <label className="label" htmlFor="manual-memo">
            메모
          </label>
          <input
            id="manual-memo"
            className="input"
            value={memo}
            onChange={(event) => setMemo(event.target.value)}
            placeholder="현금 수령 등"
          />
        </div>
      </div>
      <button type="submit" className="btn-primary" disabled={busy}>
        {busy ? '등록 중…' : '등록'}
      </button>
    </form>
  )
}
