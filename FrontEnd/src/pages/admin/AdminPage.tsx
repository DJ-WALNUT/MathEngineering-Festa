import { Suspense, lazy, useCallback, useState } from 'react'
import { Link } from 'react-router-dom'

import { EVENT } from '../../data/event'
import { adminApi } from '../../lib/api'
import { AdminLogin, SessionChecking, useAdminSession } from './AdminSession'
import AdminsPanel from './AdminsPanel'
import AssignmentsPanel from './AssignmentsPanel'
import AttendancePanel from './AttendancePanel'
import AuditPanel from './AuditPanel'
import BadgesPanel from './BadgesPanel'
import DepositsPanel from './DepositsPanel'
import ImportsPanel from './ImportsPanel'
import ParticipantsPanel from './ParticipantsPanel'
import SummaryPanel from './SummaryPanel'

/**
 * 업무 분장표는 스태프 개인별 일정이 통째로 들어 있어 다른 패널 전부를 합친 것만큼
 * 무겁다. 이 탭을 열 때만 따로 받아 오게 떼어 둔다.
 *
 * 이번 행사는 **양식이 통째로 바뀐다.** 새 양식을 받기 전까지 화면은 '준비 중'으로
 * 두고, 받는 대로 data/staffDuties.ts 를 다시 만들어 이 패널을 채운다.
 */
const DutyPanel = lazy(() => import('./DutyPanel'))

type Tab =
  | 'duty'
  | 'summary'
  | 'imports'
  | 'deposits'
  | 'participants'
  | 'assignments'
  | 'badges'
  | 'attendance'
  | 'audit'
  | 'admins'

/**
 * 탭 목록.
 *
 * **무엇을 볼 수 있는지는 서버가 정한다**(관리자 계정의 권한). 여기 있는 것은
 * 순서와 이름표, 그리고 어떤 패널을 그릴지의 짝뿐이다.
 *
 * '내 업무'만 예외로 누구에게나 열린다(ALWAYS_TABS). 남의 것이 아니라 **로그인한
 * 본인의 업무 분장**을 보여 주는 화면이라 권한으로 가를 것이 없고, 국원이 관리자
 * 화면에 들어오는 이유가 대개 이것이기 때문이다.
 */
const TABS: { id: Tab; label: string }[] = [
  { id: 'duty', label: '내 업무' },
  { id: 'summary', label: '대시보드' },
  { id: 'imports', label: '거래내역 업로드' },
  { id: 'deposits', label: '입금 내역' },
  { id: 'participants', label: '참가자' },
  { id: 'assignments', label: '배정' },
  { id: 'badges', label: '명찰' },
  { id: 'attendance', label: '출석' },
  { id: 'audit', label: '작업 기록' },
  { id: 'admins', label: '관리자' },
]

/** 서버의 권한 목록과 무관하게 늘 열리는 탭. */
const ALWAYS_TABS: Tab[] = ['duty']

export default function AdminPage() {
  const { status, session, signIn } = useAdminSession()
  const [tab, setTab] = useState<Tab>('summary')
  /** 한 패널의 변경(참가자 지정 등)이 다른 패널에도 반영되도록 하는 갱신 신호 */
  const [revision, setRevision] = useState(0)
  /** 로그아웃하면 세션 훅을 다시 태우기 위해 화면을 통째로 갈아끼운다. */
  const [signedOut, setSignedOut] = useState(false)

  const refreshAll = useCallback(() => setRevision((value) => value + 1), [])

  if (status === 'checking') return <SessionChecking />
  if (status === 'out' || signedOut || !session) {
    return (
      <AdminLogin
        onSuccess={(info) => {
          setSignedOut(false)
          // 대시보드를 못 보는 사람(국원)이 관리자 화면에 들어오는 이유는 대개 본인 업무다.
          setTab(info.tabs.includes('summary') ? 'summary' : 'duty')
          signIn(info)
        }}
      />
    )
  }

  // 볼 수 있는 탭만 그린다. 서버가 사람마다 정해 주므로 여기서 판단할 것이 없다.
  const visibleTabs = TABS.filter(
    (item) => ALWAYS_TABS.includes(item.id) || session.tabs.includes(item.id),
  )
  const current = visibleTabs.some((item) => item.id === tab) ? tab : visibleTabs[0]?.id

  return (
    <div className="min-h-dvh">
      <div className="halftone h-2 w-full" aria-hidden />

      <header className="sticky top-0 z-30 border-b border-sand-200 bg-cream/92 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <div className="flex min-w-0 items-baseline gap-2">
            <h1 className="truncate text-base font-black text-ink-900">
              {EVENT.name} 관리자
            </h1>
            {/* 지금 누구로 들어와 있는지. 작업 기록에 남는 이름과 같은 값이다. */}
            <span className="shrink-0 whitespace-nowrap rounded-full bg-sand-100 px-2.5 py-0.5 text-[11px] font-black text-sand-700">
              {session.actor}
              {session.roleName && ` · ${session.roleName}`}
              {session.isSuper && ' · 최고'}
            </span>
            <Link
              to="/"
              className="hidden shrink-0 text-xs font-semibold text-ink-500 hover:text-ink-700 sm:inline"
            >
              사이트 보기
            </Link>
          </div>
          <button
            type="button"
            className="btn-ghost px-3.5 py-1.5 text-xs"
            onClick={() => {
              adminApi.logout()
              setSignedOut(true)
            }}
          >
            로그아웃
          </button>
        </div>

        <nav className="mx-auto flex max-w-6xl gap-1 overflow-x-auto px-4 pb-2">
          {visibleTabs.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              className={`whitespace-nowrap rounded-full px-3.5 py-2 text-sm font-bold transition ${
                current === item.id
                  ? 'bg-sand-200 text-sand-800'
                  : 'text-ink-500 hover:bg-sand-100 hover:text-ink-700'
              }`}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6 break-keep">
        {current === 'duty' && (
          <Suspense fallback={<p className="text-sm text-ink-500">불러오는 중…</p>}>
            <DutyPanel actor={session.actor} username={session.username} />
          </Suspense>
        )}
        {current === 'summary' && <SummaryPanel revision={revision} />}
        {current === 'imports' && <ImportsPanel revision={revision} onChanged={refreshAll} />}
        {current === 'deposits' && <DepositsPanel revision={revision} onChanged={refreshAll} />}
        {current === 'participants' && (
          <ParticipantsPanel revision={revision} onChanged={refreshAll} />
        )}
        {current === 'assignments' && (
          <AssignmentsPanel revision={revision} onChanged={refreshAll} />
        )}
        {current === 'badges' && <BadgesPanel revision={revision} />}
        {current === 'attendance' && <AttendancePanel revision={revision} onChanged={refreshAll} />}
        {current === 'audit' && <AuditPanel revision={revision} />}
        {current === 'admins' && <AdminsPanel revision={revision} onChanged={refreshAll} />}
        {current === undefined && (
          <p className="card p-8 text-center text-sm text-ink-500">
            열람 권한이 있는 탭이 없습니다. 학생회장에게 권한을 요청해 주세요.
          </p>
        )}
      </main>
    </div>
  )
}
