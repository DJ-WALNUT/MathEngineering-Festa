import { useEffect, useState } from 'react'

import { PaymentBadge } from '../../components/StatusBadge'
import { adminApi, type AdminDeposit, type AdminParticipant } from '../../lib/api'
import { formatWon } from '../../lib/format'

/**
 * 입금 1건이 누구 것인지 지정한다.
 *
 * 입금 1건은 참가자 1명의 것이다. 한 사람이 여러 명 몫을 한 번에 보내는 일은
 * 없다고 확인되었으므로, 금액을 쪼개 입력받지 않고 전액을 그 참가자에게 붙인다.
 * (참가자가 여러 번 나눠 내는 것은 입금이 여러 건이므로 각각 지정하면 된다)
 */
export default function AllocationDialog({
  deposit,
  onClose,
  onSaved,
}: {
  deposit: AdminDeposit
  onClose: () => void
  onSaved: () => void
}) {
  const alreadyLinked = deposit.allocations[0]
  const [query, setQuery] = useState(deposit.rawName.replace(/\d+$/, '').trim())
  const [results, setResults] = useState<AdminParticipant[]>([])
  const [selected, setSelected] = useState<AdminParticipant | null>(null)
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    const trimmed = query.trim()
    if (!trimmed) {
      setResults([])
      return
    }
    const timer = setTimeout(() => {
      setSearching(true)
      adminApi
        .participants({ query: trimmed, pageSize: 20 })
        .then((response) => setResults(response.items))
        .catch(() => setResults([]))
        .finally(() => setSearching(false))
    }, 250)
    return () => clearTimeout(timer)
  }, [query])

  const save = async () => {
    if (!selected) return
    setSaving(true)
    setError('')
    try {
      await adminApi.allocate(deposit.id, [
        { participantId: selected.id, amount: deposit.amount },
      ])
      onSaved()
      onClose()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '지정에 실패했습니다.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-ink-900/45 p-0 backdrop-blur-sm sm:items-center sm:p-4">
      <div className="flex max-h-[92dvh] w-full max-w-lg flex-col rounded-t-3xl border-2 border-sand-200 bg-white sm:rounded-3xl">
        <header className="border-b border-sand-200 px-5 py-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-black text-ink-900">이 입금은 누구 것인가요?</h2>
              <p className="mt-1 text-sm text-ink-600">
                <span className="font-bold text-ink-800">
                  {deposit.rawName || '(입금자명 없음)'}
                </span>
                {' · '}
                <span className="tabular font-semibold">{formatWon(deposit.amount)}</span>
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="text-sm font-semibold text-ink-400 hover:text-ink-700"
            >
              닫기
            </button>
          </div>

          {alreadyLinked && (
            <p className="mt-2 rounded-xl bg-sand-50 px-3 py-2 text-xs text-ink-600">
              현재 <strong className="text-ink-800">{alreadyLinked.participantName}</strong> 님에게
              연결되어 있습니다. 다른 사람을 고르면 교체됩니다.
            </p>
          )}
        </header>

        <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
          <div>
            <label htmlFor="alloc-search" className="label">
              참가자 검색 (이름 · 전화번호 · 학번)
            </label>
            <input
              id="alloc-search"
              className="input"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="이름을 입력하세요"
              autoFocus
            />
          </div>

          {searching && <p className="text-xs text-ink-500">검색 중…</p>}
          {!searching && query.trim() && results.length === 0 && (
            <p className="text-sm text-ink-500">검색 결과가 없습니다.</p>
          )}

          <ul className="space-y-1.5">
            {results.map((participant) => {
              const isSelected = selected?.id === participant.id
              const outstanding = participant.expectedAmount - participant.paidAmount
              return (
                <li key={participant.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(isSelected ? null : participant)}
                    aria-pressed={isSelected}
                    className={`flex w-full items-center justify-between gap-3 rounded-2xl border-2 px-3 py-2.5 text-left transition ${
                      isSelected
                        ? 'border-cobalt-400 bg-cobalt-50'
                        : 'border-sand-200 hover:border-sand-300 hover:bg-sand-50'
                    }`}
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-bold text-ink-900">
                        {participant.name}
                        <span className="ml-2 text-xs font-semibold text-ink-500 tabular">
                          {participant.phoneMasked}
                        </span>
                      </span>
                      <span className="block text-xs text-ink-500">
                        {participant.department ?? '학과 미기재'} · 남은 금액{' '}
                        {formatWon(Math.max(outstanding, 0))}
                      </span>
                    </span>
                    <PaymentBadge status={participant.status} />
                  </button>
                </li>
              )
            })}
          </ul>

          {selected && (
            <div className="rounded-2xl border-2 border-cobalt-200 bg-cobalt-50 px-4 py-3">
              <p className="text-sm font-semibold text-ink-800">
                <strong className="font-black">{selected.name}</strong> 님에게{' '}
                <span className="tabular">{formatWon(deposit.amount)}</span> 전액을 연결합니다.
              </p>
              {deposit.amount !== selected.expectedAmount && (
                <p className="mt-1 text-xs text-flame-600">
                  참가비 {formatWon(selected.expectedAmount)} 와 금액이 다릅니다. 연결 후{' '}
                  {deposit.amount < selected.expectedAmount ? '부분 입금' : '초과 납입'} 으로
                  표시됩니다.
                </p>
              )}
            </div>
          )}

          {error && <p className="text-sm font-semibold text-brick-500">{error}</p>}
        </div>

        <footer className="flex gap-2 border-t border-sand-200 px-5 py-4">
          <button type="button" className="btn-ghost flex-1" onClick={onClose}>
            취소
          </button>
          <button
            type="button"
            className="btn-primary flex-1"
            onClick={save}
            disabled={!selected || saving}
          >
            {saving ? '저장 중…' : '이 참가자로 지정'}
          </button>
        </footer>
      </div>
    </div>
  )
}
