/**
 * 작업 기록.
 *
 * 몇 달 뒤에 "이거 누가 왜 이렇게 했지" 를 되짚는 화면이다. 그래서 한 줄에
 * **누가 · 누구를 · 무엇을 · 무엇에서 무엇으로** 가 모두 들어가야 한다.
 *
 * 표시 문구는 백엔드가 만들어 보낸다. 기록은 그 자체로 완결되어야 해서,
 * 나중에 이 화면의 라벨이 바뀌어도 예전 기록은 그때의 표현대로 읽혀야 한다.
 */

import { useEffect, useState } from 'react'

import { adminApi, type AuditChange, type AuditEntry } from '../../lib/api'
import { formatDateTime } from '../../lib/format'

const ACTION_LABEL: Record<string, string> = {
  login: '로그인',
  'participant.update': '참가자 수정',
  'participant.confirm_bulk': '참가 확정 일괄 처리',
  'deposit.create': '입금 수기 등록',
  'deposit.update': '입금 수정',
  'deposit.allocate': '참가자 지정',
  'deposit.clear_allocations': '연결 해제',
  'deposit.import': '거래내역 업로드',
  'assignment_field.create': '배정 항목 추가',
  'assignment_field.update': '배정 항목 수정',
  'assignment_field.delete': '배정 항목 삭제',
  'checkin.window': '체크인 창구',
  'settings.staff_fee': '스태프 참가비 변경',
  'notification.reparse': '알림 다시 해석',
  'notification.dismiss': '알림 치우기',
  rematch: '재매칭',
  'export.participants': '명단 내보내기',
}

/** 이 동작들은 특정 대상이 아니라 전체를 훑는다. 굳이 대상 이름을 찾지 않는다. */
const ACTION_TONE: Record<string, string> = {
  'participant.update': 'bg-cobalt-100 text-cobalt-600',
  'participant.confirm_bulk': 'bg-sand-200 text-sand-800',
  'settings.staff_fee': 'bg-flame-200 text-flame-600',
  'checkin.window': 'bg-flame-200 text-flame-600',
  'deposit.allocate': 'bg-cobalt-100 text-cobalt-600',
  'deposit.update': 'bg-cobalt-100 text-cobalt-600',
}

export default function AuditPanel({ revision }: { revision: number }) {
  const [items, setItems] = useState<AuditEntry[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    adminApi
      .audit(200)
      .then((response) => setItems(response.items))
      .catch((caught) => setError(caught.message ?? '기록을 불러오지 못했습니다.'))
  }, [revision])

  if (error) return <p className="text-sm font-semibold text-brick-500">{error}</p>

  return (
    <div className="space-y-3">
      <p className="text-xs text-ink-500">
        관리자가 수동으로 처리한 내역입니다. 나중에 무엇을 왜 고쳤는지 되짚을 때 사용하세요.
      </p>

      {items.length === 0 && (
        <p className="card p-8 text-center text-sm text-ink-500">아직 기록이 없습니다.</p>
      )}

      <ul className="space-y-2">
        {items.map((entry) => (
          <li key={entry.id} className="card px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
              <span className="flex flex-wrap items-center gap-2">
                <span
                  className={`rounded-full px-2.5 py-0.5 text-[11px] font-black ${
                    ACTION_TONE[entry.action] ?? 'bg-sand-100 text-sand-700'
                  }`}
                >
                  {ACTION_LABEL[entry.action] ?? entry.action}
                </span>
                {entry.detail.target && (
                  <span className="text-sm font-black text-ink-900">{entry.detail.target}</span>
                )}
              </span>
              <span className="text-xs text-ink-400 tabular">
                {formatDateTime(entry.at)} · {entry.actor}
              </span>
            </div>

            <Detail entry={entry} />
          </li>
        ))}
      </ul>
    </div>
  )
}

function Detail({ entry }: { entry: AuditEntry }) {
  const changes = entry.detail.changes

  // 이 형태를 쓰기 전에 쌓인 기록은 그대로 펼쳐 보여준다. 읽히지 않는 것보다 낫다.
  if (!Array.isArray(changes)) {
    if (Object.keys(entry.detail).length === 0) return null
    return (
      <pre className="mt-2 overflow-x-auto rounded-xl bg-sand-50 px-3 py-2 text-[11px] leading-relaxed text-ink-600">
        {JSON.stringify(entry.detail, null, 2)}
      </pre>
    )
  }

  if (changes.length === 0) return null

  return (
    <ul className="mt-2 space-y-1">
      {changes.map((change, index) => (
        <li key={`${change.field ?? change.label}-${index}`} className="text-sm leading-relaxed">
          <ChangeLine change={change} />
        </li>
      ))}
    </ul>
  )
}

function ChangeLine({ change }: { change: AuditChange }) {
  // 전후가 없는 단발성 기록 — '새 입금 12건' 처럼 값 하나만 의미가 있다.
  if (change.from === null) {
    return (
      <>
        <span className="font-bold text-ink-500">{change.label}</span>
        <span className="mx-1.5 text-ink-300">·</span>
        <span className="font-semibold text-ink-800">{change.to}</span>
      </>
    )
  }

  return (
    <>
      <span className="font-bold text-ink-500">{change.label}</span>
      <span className="mx-1.5 text-ink-300">·</span>
      <span className="text-ink-500 line-through decoration-ink-300">{change.from}</span>
      <span className="mx-1.5 font-black text-ink-400">→</span>
      <span className="font-black text-ink-900">{change.to}</span>
    </>
  )
}
