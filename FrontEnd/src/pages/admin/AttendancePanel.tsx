/**
 * 출석 현황.
 *
 * 분모는 신청자가 아니라 **참가 확정자**다. 확정되지 않은 사람은 체크인 자체가
 * 막혀 있어서, 전체 신청자를 분모로 잡으면 출석률이 영원히 100%에 닿지 않는다.
 *
 * ## 회차
 *
 * 하루짜리 행사인데도 출석이 한 번으로 끝나지 않는다 — 낮의 **본 행사**와, 신청자
 * 중 일부만 남는 저녁의 **뒤풀이**. 두 자리는 인원도 여닫는 시각도 다르므로 화면
 * 맨 위에서 회차를 고르고, 아래 전부가 그 회차의 이야기가 된다.
 *
 * 들어오는 길도 둘이다. 인원이 많은 본 행사는 참가자가 QR 로 직접 찍고, 인원이
 * 적고 자리가 어수선한 뒤풀이는 **명단에서 이름을 찾아 누른다.** 수동 체크는
 * 창구가 닫혀 있어도 되고, 실제로 뒤풀이는 창구를 열지 않고 이쪽만 쓰게 된다.
 *
 * 현장에서 스태프가 보는 화면이므로 자동 새로고침을 기본으로 켜 둔다.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import QRCode from 'qrcode'

import {
  adminApi,
  type Attendance,
  type AttendanceRow,
  type CheckinSession,
  type DrawState,
} from '../../lib/api'
import { formatDateTime } from '../../lib/format'

const REFRESH_MS = 15_000

/** 명단 한 사람이 검색어에 걸리는지. 전화번호는 하이픈을 지우고 숫자만 비교한다. */
function matches(row: AttendanceRow, needle: string) {
  const digits = needle.replace(/\D/g, '')
  return (
    row.name.toLowerCase().includes(needle) ||
    (row.department ?? '').toLowerCase().includes(needle) ||
    (row.groupValue ?? '').toLowerCase().includes(needle) ||
    (row.studentId ?? '').includes(needle) ||
    (row.drawLabel ?? '').includes(needle) ||
    (digits.length > 0 && row.phone.replace(/\D/g, '').includes(digits))
  )
}

export default function AttendancePanel({
  revision,
  onChanged,
}: {
  revision: number
  onChanged: () => void
}) {
  const [data, setData] = useState<Attendance | null>(null)
  /** 지금 보고 있는 회차. 비어 있으면 서버가 본 행사를 준다. */
  const [session, setSession] = useState('')
  const [groupBy, setGroupBy] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [tab, setTab] = useState<'notCheckedIn' | 'checkedIn'>('notCheckedIn')
  const [query, setQuery] = useState('')

  const rows = (tab === 'notCheckedIn' ? data?.notCheckedIn : data?.checkedIn) ?? []
  const others = (tab === 'notCheckedIn' ? data?.checkedIn : data?.notCheckedIn) ?? []
  const needle = query.trim().toLowerCase()
  const visible = needle ? rows.filter((row) => matches(row, needle)) : rows
  const otherTabHits = needle ? others.filter((row) => matches(row, needle)).length : 0

  const load = useCallback(async () => {
    try {
      setData(await adminApi.attendance(session || undefined, groupBy || undefined))
      setError('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '출석 현황을 불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }, [session, groupBy])

  useEffect(() => {
    void load()
  }, [load, revision])

  useEffect(() => {
    if (!autoRefresh) return
    const timer = setInterval(() => void load(), REFRESH_MS)
    return () => clearInterval(timer)
  }, [autoRefresh, load])

  const toggleWindow = async (open: boolean) => {
    if (!data) return
    try {
      await adminApi.setCheckInWindow(open, data.session.key)
      await load()
    } catch (caught) {
      alert(caught instanceof Error ? caught.message : '체크인 상태를 바꾸지 못했습니다.')
    }
  }

  /**
   * 명단에서 눌러 출석을 남기거나 지운다.
   *
   * **창구가 닫혀 있어도 된다** — 사람이 직접 확인하고 누르는 것이기 때문이다.
   * 뒤풀이는 대개 이 길만 쓴다.
   */
  const setCheckedIn = async (row: AttendanceRow, checkedIn: boolean) => {
    if (!data) return
    try {
      await adminApi.markAttendance(data.session.key, row.id, checkedIn)
      await load()
      onChanged()
    } catch (caught) {
      alert(caught instanceof Error ? caught.message : '출석 처리에 실패했습니다.')
    }
  }

  if (loading) return <p className="text-sm text-ink-500">불러오는 중…</p>
  if (error) return <p className="text-sm font-semibold text-brick-500">{error}</p>
  if (!data) return null

  const { overall } = data

  return (
    <div className="space-y-5">
      <SessionTabs
        sessions={data.sessions}
        current={data.session}
        onSelect={(key) => {
          setSession(key)
          setQuery('')
          setTab('notCheckedIn')
        }}
        onChanged={() => void load()}
      />

      <CheckInWindowCard session={data.session} onToggle={toggleWindow} />

      <section className="card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-black text-ink-900">전체 출석률</h2>
          <label className="flex items-center gap-1.5 text-xs font-semibold text-ink-500">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(event) => setAutoRefresh(event.target.checked)}
            />
            15초마다 자동 새로고침
          </label>
        </div>

        <div className="mt-3 flex items-baseline gap-2">
          <span className="text-4xl font-black tabular text-sand-700">{overall.rate}%</span>
          <span className="text-sm font-semibold text-ink-500 tabular">
            {overall.checkedIn} / {overall.confirmed}명
          </span>
        </div>
        <div className="mt-2 h-2.5 overflow-hidden rounded-full bg-sand-100">
          <div
            className="h-full rounded-full bg-sand-500 transition-[width]"
            style={{ width: `${Math.min(overall.rate, 100)}%` }}
          />
        </div>

        <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="도착" value={overall.checkedIn} tone="text-sand-700" />
          <Stat label="미도착" value={overall.notCheckedIn} tone="text-flame-600" />
          <Stat label="참가 확정" value={overall.confirmed} />
          <Stat label="신청자" value={overall.applicants} tone="text-ink-500" />
        </dl>

        {data.session.afterpartyOnly && (
          <p className="mt-3 text-[11px] leading-relaxed text-ink-400 break-keep">
            이 회차의 분모는 <strong className="text-ink-600">뒤풀이를 신청한 확정자</strong>입니다.
            신청하지 않은 사람은 명단에도 나오지 않고 체크인도 되지 않습니다 — 현장에서
            합류하기로 했다면 참가자 탭에서 뒤풀이 참가로 먼저 바꿔 주세요.
          </p>
        )}

        {overall.confirmed === 0 && (
          <p className="mt-4 rounded-xl border-2 border-flame-200 bg-flame-100/60 px-4 py-3 text-xs font-semibold text-flame-600">
            {data.session.afterpartyOnly
              ? '뒤풀이를 신청한 확정자가 아직 없습니다. 참가자 탭에서 확인해 주세요.'
              : '참가 확정자가 아직 없습니다. 참가자 탭에서 납입 완료자를 확정해야 체크인이 열립니다.'}
          </p>
        )}
      </section>

      <section className="card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-black text-ink-900">
            {data.groupBy.label ?? '조'}별 출석 현황
          </h2>
          <select
            className="input h-9 max-w-36 py-1 text-sm"
            value={groupBy || (data.groupBy.key ?? '')}
            onChange={(event) => setGroupBy(event.target.value)}
          >
            {data.fields.map((field) => (
              <option key={field.key} value={field.key}>
                {field.label} 기준
              </option>
            ))}
          </select>
        </div>

        {data.groups.length === 0 ? (
          <p className="mt-4 text-sm text-ink-500">아직 배정된 인원이 없습니다.</p>
        ) : (
          <ul className="mt-4 space-y-2">
            {data.groups.map((group) => (
              <li key={group.label} className="flex items-center gap-3">
                <span className="w-16 shrink-0 truncate text-sm font-black text-ink-800">
                  {group.label}
                </span>
                <span className="h-2.5 flex-1 overflow-hidden rounded-full bg-sand-100">
                  <span
                    className="block h-full rounded-full bg-cobalt-500"
                    style={{ width: `${Math.min(group.rate, 100)}%` }}
                  />
                </span>
                <span className="w-24 shrink-0 text-right text-xs font-bold tabular text-ink-600">
                  {group.checkedIn}/{group.confirmed} · {group.rate}%
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card overflow-hidden">
        <div className="flex gap-1 border-b border-sand-200 px-4 pt-3">
          <TabButton
            active={tab === 'notCheckedIn'}
            onClick={() => setTab('notCheckedIn')}
            label={`미도착 ${data.notCheckedIn.length}`}
          />
          <TabButton
            active={tab === 'checkedIn'}
            onClick={() => setTab('checkedIn')}
            label={`도착 ${data.checkedIn.length}`}
          />
        </div>

        <div className="flex flex-wrap items-center gap-2 px-4 py-3">
          <input
            className="input flex-1 sm:max-w-xs"
            placeholder="이름 · 전화번호 · 학과 · 조 · 번호 검색"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          {needle && (
            <span className="text-xs font-semibold text-ink-500 tabular">
              {visible.length}명 / {rows.length}명
            </span>
          )}
        </div>

        {/* 150명이 한 화면에 늘어지면 아래 카드들이 스크롤 밖으로 밀려난다. */}
        <ul className="max-h-[26rem] divide-y divide-sand-100 overflow-y-auto">
          {visible.map((row) => (
            <li key={row.id} className="flex items-center justify-between gap-3 px-4 py-3">
              <div className="min-w-0">
                <p className="flex items-center gap-2">
                  {/* 접수처에서 "내 번호가 뭐냐"는 질문이 반드시 나온다. */}
                  {row.drawLabel && (
                    <span className="rounded-md bg-flame-100 px-1.5 py-0.5 text-[11px] font-black tabular text-flame-600">
                      {row.drawLabel}
                    </span>
                  )}
                  <span className="text-sm font-black text-ink-900">{row.name}</span>
                  {row.groupValue && (
                    <span className="rounded-full bg-cobalt-50 px-2 py-0.5 text-[11px] font-bold text-cobalt-600">
                      {row.groupValue}
                    </span>
                  )}
                  {row.checkedInBy === 'staff' && (
                    <span className="rounded-full border border-heart-400/40 px-2 py-0.5 text-[11px] font-semibold text-heart-500">
                      스태프 처리
                    </span>
                  )}
                  {/*
                    본 행사 명단에서 '이 사람이 저녁에도 남는가'를 바로 보기 위한 것이다.
                    뒤풀이비가 아직 안 들어왔으면 그 자리에서 받아야 하므로 함께 띄운다.
                  */}
                  {!data.session.afterpartyOnly && row.joinsAfterparty && (
                    <span
                      className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${
                        row.afterpartyStatus === 'PAID'
                          ? 'bg-heart-100 text-heart-500'
                          : 'border border-flame-300 text-flame-600'
                      }`}
                    >
                      뒤풀이
                      {row.afterpartyStatus !== 'PAID' && ' · 미납'}
                    </span>
                  )}
                </p>
                <p className="mt-0.5 truncate text-xs font-semibold text-ink-500 tabular">
                  {row.phone}
                  {row.checkedInAt && ` · ${formatDateTime(row.checkedInAt)}`}
                </p>
              </div>

              <button
                type="button"
                className="btn-ghost shrink-0 px-3 py-1.5 text-xs"
                onClick={() => setCheckedIn(row, tab === 'notCheckedIn')}
              >
                {tab === 'notCheckedIn' ? '출석 처리' : '출석 취소'}
              </button>
            </li>
          ))}
          {visible.length === 0 && (
            <li className="px-4 py-8 text-center text-sm text-ink-500">
              {!needle ? (
                tab === 'notCheckedIn' ? (
                  '모두 도착했습니다.'
                ) : (
                  '아직 도착한 사람이 없습니다.'
                )
              ) : (
                <>
                  검색 결과가 없습니다.
                  {/* 접수처에서는 "이 사람 왜 없냐"가 곧 "반대쪽 탭에 있다"인 경우가 많다. */}
                  {otherTabHits > 0 && (
                    <button
                      type="button"
                      className="mt-2 block w-full text-xs font-bold text-cobalt-600 hover:underline"
                      onClick={() => setTab(tab === 'notCheckedIn' ? 'checkedIn' : 'notCheckedIn')}
                    >
                      {tab === 'notCheckedIn' ? '도착' : '미도착'} 목록에 {otherTabHits}명
                      있습니다 — 그쪽 보기
                    </button>
                  )}
                </>
              )}
            </li>
          )}
        </ul>
      </section>

      <LuckyDrawCard revision={revision} />

      <CheckInQrCard />
    </div>
  )
}

/**
 * 럭키드로우 안내.
 *
 * 추첨 자체는 별도 화면(/draw)에서 한다. 여기서는 '번호가 몇 개 나왔는지'만
 * 보여주고 넘긴다 — 번호가 체크인에서 발급되므로 이 탭이 자연스러운 입구다.
 */
function LuckyDrawCard({ revision }: { revision: number }) {
  const [state, setState] = useState<DrawState | null>(null)

  useEffect(() => {
    adminApi
      .drawState()
      .then(setState)
      .catch(() => setState(null))
  }, [revision])

  const counts = state?.counts
  const winners = (state?.history ?? []).filter((record) => !record.voided).slice(0, 3)

  return (
    <section className="card p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-black text-ink-900">럭키드로우</h2>
          <p className="mt-1 text-xs leading-relaxed text-ink-500">
            번호는 <strong>본 행사</strong> 체크인 순서대로 001 부터 자동 발급됩니다.
            뒤풀이에서 뽑을 때도 같은 번호를 쓰되, 추첨 화면에서 후보 범위를 뒤풀이로
            좁히면 그 자리에 남은 사람만 후보가 됩니다.
          </p>
        </div>
        <Link to="/admin/draw" className="btn-primary shrink-0 px-4 py-2 text-xs">
          추첨 화면 열기
        </Link>
      </div>

      <dl className="mt-4 grid grid-cols-3 gap-3">
        <Stat label="발급된 번호" value={counts?.issued ?? 0} />
        <Stat label="추첨 후보" value={counts?.eligible ?? 0} tone="text-sand-700" />
        <Stat label="당첨" value={counts?.won ?? 0} tone="text-flame-600" />
      </dl>

      {winners.length > 0 && (
        <ul className="mt-3 space-y-1">
          {winners.map((record) => (
            <li key={record.id} className="text-xs font-semibold text-ink-600 tabular">
              <span className="font-black text-flame-600">{record.drawLabel}</span>{' '}
              {record.name ?? '(기록 없음)'} — {record.prize || `${record.roundNo}회차`}
            </li>
          ))}
        </ul>
      )}

      <p className="mt-3 text-[11px] leading-relaxed text-ink-400">
        다른 기기(강당 노트북 등)에서 진행하려면 그 기기의 브라우저로{' '}
        <code>/admin/draw</code> 에 접속해 관리자 비밀번호를 넣으면 됩니다.
        상품은 그 화면의 조작판에서 미리 등록해 두세요.
      </p>
    </section>
  )
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="rounded-xl bg-sand-50 px-3 py-2.5">
      <dt className="text-[11px] font-bold text-ink-500">{label}</dt>
      <dd className={`mt-0.5 text-xl font-black tabular ${tone ?? 'text-ink-900'}`}>{value}</dd>
    </div>
  )
}

function TabButton({
  active,
  onClick,
  label,
}: {
  active: boolean
  onClick: () => void
  label: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-t-lg px-3.5 py-2 text-sm font-bold transition ${
        active ? 'bg-sand-100 text-sand-800' : 'text-ink-500 hover:text-ink-700'
      }`}
    >
      {label}
    </button>
  )
}

/**
 * 체크인 창구 스위치.
 *
 * QR 인쇄물은 행사 며칠 전부터 돌아다니므로 기본은 닫힘이다.
 * 열어 두면 집결 전에 원격으로 출석 처리해 버리는 사람이 생긴다.
 */
function CheckInWindowCard({
  session,
  onToggle,
}: {
  session: CheckinSession
  onToggle: (open: boolean) => void
}) {
  const open = session.isOpen
  return (
    <section
      className={`card flex flex-wrap items-center justify-between gap-3 p-5 ${
        open ? 'border-sand-300 bg-sand-50' : 'border-flame-200 bg-flame-100/50'
      }`}
    >
      <div>
        <p className="text-sm font-black text-ink-900">
          {session.label} 셀프 체크인 {open ? '열림' : '닫힘'}
        </p>
        <p className="mt-1 text-xs leading-relaxed text-ink-600 break-keep">
          {open
            ? `QR 을 찍은 참가자가 지금 ${session.label}에 직접 출석 처리할 수 있습니다.`
            : '시각이 되면 열어 주세요. 닫혀 있으면 QR 을 찍어도 체크인되지 않습니다. 아래 명단에서 직접 누르는 것은 닫혀 있어도 됩니다.'}
        </p>
        {/*
          참가자는 회차를 고르지 않는다 — 같은 입구 QR 로 들어와 '지금 열린' 자리에
          찍힌다. 그래서 하나를 열면 나머지는 서버가 닫는다. 이 사실을 말해 두지 않으면
          두 자리를 동시에 열어 두려다 조용히 하나가 닫힌 것을 나중에 발견하게 된다.
        */}
        {!open && (
          <p className="mt-1 text-[11px] text-ink-400">
            열면 다른 회차의 창구는 자동으로 닫힙니다. 참가자는 같은 QR 로 들어와 지금 열린
            자리에 찍히기 때문입니다.
          </p>
        )}
      </div>
      <button
        type="button"
        className={open ? 'btn-ghost shrink-0' : 'btn-primary shrink-0'}
        onClick={() => onToggle(!open)}
      >
        {open ? '체크인 닫기' : '체크인 열기'}
      </button>
    </section>
  )
}

/**
 * 회차 고르기 + 회차 관리.
 *
 * 회차는 코드가 아니라 데이터다(BackEnd/app/attendance.py). 현장에서 '2부도 따로
 * 세자'가 나와도 여기서 하나 만들면 되고, 재배포가 필요하지 않다.
 */
function SessionTabs({
  sessions,
  current,
  onSelect,
  onChanged,
}: {
  sessions: CheckinSession[]
  current: CheckinSession
  onSelect: (key: string) => void
  onChanged: () => void
}) {
  const [adding, setAdding] = useState(false)
  const [label, setLabel] = useState('')
  const [afterpartyOnly, setAfterpartyOnly] = useState(false)
  const [busy, setBusy] = useState(false)

  const create = async () => {
    const name = label.trim()
    if (!name) return
    setBusy(true)
    try {
      const created = await adminApi.createCheckinSession({ label: name, afterpartyOnly })
      setAdding(false)
      setLabel('')
      setAfterpartyOnly(false)
      onSelect(created.key)
      onChanged()
    } catch (caught) {
      alert(caught instanceof Error ? caught.message : '회차를 만들지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (current.isSystem) return
    if (!confirm(`'${current.label}' 회차를 지울까요? 이 회차의 출석 기록도 함께 사라집니다.`)) {
      return
    }
    setBusy(true)
    try {
      try {
        await adminApi.deleteCheckinSession(current.id)
      } catch (caught) {
        // 이미 출석 기록이 있는 회차는 한 번 더 묻는다.
        const message = caught instanceof Error ? caught.message : ''
        if (!message || !confirm(`${message}\n그래도 지울까요?`)) throw caught
        await adminApi.deleteCheckinSession(current.id, true)
      }
      onSelect('')
      onChanged()
    } catch (caught) {
      if (caught instanceof Error) alert(caught.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card p-4">
      <div className="flex flex-wrap items-center gap-2">
        {sessions.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => onSelect(item.key)}
            className={`rounded-full px-3.5 py-1.5 text-sm font-bold transition ${
              item.key === current.key
                ? 'bg-sand-200 text-sand-800'
                : 'text-ink-500 hover:bg-sand-100 hover:text-ink-700'
            }`}
          >
            {item.label}
            {item.isOpen && <span className="ml-1.5 text-[11px] text-sand-700">● 열림</span>}
          </button>
        ))}

        <span className="flex-1" />

        {!current.isSystem && (
          <button
            type="button"
            className="text-xs font-semibold text-ink-400 hover:text-brick-500 disabled:opacity-40"
            onClick={remove}
            disabled={busy}
          >
            이 회차 삭제
          </button>
        )}
        <button
          type="button"
          className="btn-ghost px-3 py-1.5 text-xs"
          onClick={() => setAdding((value) => !value)}
        >
          {adding ? '취소' : '회차 추가'}
        </button>
      </div>

      {adding && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-sand-100 pt-3">
          <input
            className="input h-9 flex-1 py-1 text-sm sm:max-w-48"
            placeholder="회차 이름 (예: 2부)"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
          />
          <label className="flex items-center gap-1.5 text-xs font-semibold text-ink-500">
            <input
              type="checkbox"
              checked={afterpartyOnly}
              onChange={(event) => setAfterpartyOnly(event.target.checked)}
            />
            뒤풀이 신청자만
          </label>
          <button
            type="button"
            className="btn-primary px-3.5 py-1.5 text-xs"
            onClick={create}
            disabled={busy || !label.trim()}
          >
            만들기
          </button>
        </div>
      )}
    </section>
  )
}

/**
 * 집결지에 붙일 QR.
 *
 * 인쇄는 관리자 화면 전체를 건드리지 않도록 새 창에 최소한의 문서를 띄워 처리한다.
 */
function CheckInQrCard() {
  const [dataUrl, setDataUrl] = useState('')
  const urlRef = useRef('')

  useEffect(() => {
    const url = `${window.location.origin}/checkin`
    urlRef.current = url
    QRCode.toDataURL(url, { width: 640, margin: 1, errorCorrectionLevel: 'M' })
      .then(setDataUrl)
      .catch(() => setDataUrl(''))
  }, [])

  const print = () => {
    if (!dataUrl) return
    const popup = window.open('', '_blank', 'width=720,height=900')
    if (!popup) {
      alert('팝업이 차단되었습니다. 이미지를 직접 저장해 인쇄해 주세요.')
      return
    }
    popup.document.write(`
      <!doctype html>
      <html lang="ko"><head><meta charset="utf-8" /><title>출석 체크인 QR</title>
      <style>
        body { font-family: system-ui, sans-serif; text-align: center; padding: 48px 24px; }
        h1 { font-size: 40px; margin: 0 0 8px; }
        p { font-size: 20px; color: #444; margin: 0 0 32px; }
        img { width: 460px; max-width: 90%; }
        code { display: block; margin-top: 24px; font-size: 18px; color: #666; }
      </style></head>
      <body>
        <h1>출석 체크인</h1>
        <p>휴대폰 카메라로 QR 을 찍어 주세요</p>
        <img src="${dataUrl}" alt="체크인 QR" />
        <code>${urlRef.current}</code>
      </body></html>
    `)
    popup.document.close()
    popup.focus()
    popup.print()
  }

  return (
    <section className="card p-5">
      <h2 className="text-sm font-black text-ink-900">체크인 QR</h2>
      <p className="mt-1 text-xs leading-relaxed text-ink-500">
        행사장 입구에 붙여 두세요. 찍으면 <strong>지금 열어 둔 회차</strong>의 셀프 체크인
        화면이 열립니다. QR 은 회차마다 다르지 않으므로 한 번만 인쇄하면 됩니다.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-4">
        {dataUrl ? (
          <img
            src={dataUrl}
            alt="체크인 QR"
            className="size-36 rounded-xl border-2 border-sand-200 bg-white p-1.5"
          />
        ) : (
          <div className="grid size-36 place-items-center rounded-xl bg-sand-50 text-xs text-ink-400">
            QR 생성 중…
          </div>
        )}

        <div className="min-w-0 space-y-2">
          <p className="break-all text-xs font-semibold text-ink-600 tabular">
            {urlRef.current}
          </p>
          <button type="button" className="btn-ghost px-3.5 py-1.5 text-xs" onClick={print}>
            인쇄용으로 열기
          </button>
        </div>
      </div>
    </section>
  )
}
