import { useState } from 'react'

import { PixelStar } from '../components/Decorations'
import { CATEGORY_STYLE, TIMETABLE, type MealMenu, type TimetableSession } from '../data/timetable'

export default function SchedulePage() {
  const [activeDayId, setActiveDayId] = useState(TIMETABLE[0]?.id ?? '')
  const activeDay = TIMETABLE.find((day) => day.id === activeDayId) ?? TIMETABLE[0]
  const hasSessions = TIMETABLE.some((day) => day.sessions.length > 0)

  /*
   * 요강이 확정되기 전에는 '준비 중'을 띄운다.
   *
   * 빈 타임라인을 그리면 '순서가 없는 행사'처럼 읽힌다. 아직 정해지지 않았다는
   * 말과 언제 올라오는지를 대신 보여 준다. 채우는 자리는 data/timetable.ts 다.
   */
  if (!hasSessions) {
    return (
      <div className="card p-10 text-center">
        <PixelStar className="mx-auto size-10 text-sand-300" />
        <h1 className="mt-3 text-xl font-black text-ink-900">타임테이블은 준비 중입니다</h1>
        <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-ink-600 break-keep">
          행사 요강이 확정되는 대로 이 자리에 올라옵니다. 확정되면 학생회 채널로도 함께
          공지드릴게요.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-black text-ink-900 sm:text-3xl">타임테이블</h1>
        <p className="mt-2 text-sm leading-relaxed text-ink-600">
          현장 상황에 따라 시간이 조정될 수 있어요. 변경되면 공지드릴게요.
        </p>
      </header>

      {/* 날짜 묶음이 하나뿐인 당일 행사에서는 고를 것이 없어 탭을 띄우지 않는다. */}
      <div className={`flex gap-2 ${TIMETABLE.length > 1 ? '' : 'hidden'}`}>
        {TIMETABLE.map((day) => (
          <button
            key={day.id}
            type="button"
            onClick={() => setActiveDayId(day.id)}
            className={`flex-1 rounded-2xl border-2 px-4 py-3 text-left transition sm:flex-none sm:px-6 ${
              day.id === activeDay?.id
                ? 'border-sand-400 bg-sand-100'
                : 'border-sand-200 bg-white hover:border-sand-300'
            }`}
          >
            <span
              className={`block text-sm font-black ${
                day.id === activeDay?.id ? 'text-sand-700' : 'text-ink-600'
              }`}
            >
              {day.label}
            </span>
            <span className="mt-0.5 block text-xs font-semibold text-ink-500">{day.dateLabel}</span>
          </button>
        ))}
      </div>

      {activeDay && (
        <ol className="relative space-y-3 border-l-2 border-dashed border-sand-300 pl-6">
          {activeDay.sessions.map((session, index) => (
            <SessionRow key={`${session.start}-${index}`} session={session} />
          ))}
        </ol>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-sand-200 pt-5">
        <PixelStar className="size-5 text-sand-300" />
        {Object.entries(CATEGORY_STYLE).map(([key, style]) => (
          <span
            key={key}
            className={`rounded-full border px-2.5 py-1 text-xs font-bold ${style.className}`}
          >
            {style.label}
          </span>
        ))}
      </div>
    </div>
  )
}

function SessionRow({ session }: { session: TimetableSession }) {
  const style = CATEGORY_STYLE[session.category]
  // 식단표는 항목이 많아 펼쳐두면 타임테이블이 밀린다. 기본은 접어둔다.
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <li className="relative">
      <span className="absolute -left-[1.95rem] top-5 size-3 rounded-full bg-sand-400 ring-4 ring-cream" />
      <div className="card p-4 sm:p-5">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <span className="text-sm font-black text-cobalt-500 tabular">
            {session.start}
            {session.end ? ` – ${session.end}` : ''}
          </span>
          <span className={`rounded-full border px-2 py-0.5 text-[11px] font-bold ${style.className}`}>
            {style.label}
          </span>
          {session.required && (
            <span className="rounded-full border border-brick-400/40 bg-brick-400/12 px-2 py-0.5 text-[11px] font-bold text-brick-500">
              필참
            </span>
          )}
        </div>

        <p className="mt-2 text-base font-bold text-ink-900">{session.title}</p>
        {session.place && <p className="mt-1 text-sm font-semibold text-ink-600">{session.place}</p>}
        {session.description && (
          <p className="mt-2 text-sm leading-relaxed text-ink-500">{session.description}</p>
        )}

        {session.menu && (
          <div className="mt-3 border-t border-dashed border-sand-200 pt-3">
            <button
              type="button"
              onClick={() => setMenuOpen((open) => !open)}
              aria-expanded={menuOpen}
              className="flex w-full items-center justify-between gap-2 text-sm font-bold text-sand-700"
            >
              <span>식단표 · {session.menu.label}</span>
              <span
                className={`text-xs text-sand-600 transition-transform ${
                  menuOpen ? 'rotate-180' : ''
                }`}
                aria-hidden
              >
                ▼
              </span>
            </button>

            {menuOpen && <MenuTable menu={session.menu} />}
          </div>
        )}
      </div>
    </li>
  )
}

function MenuTable({ menu }: { menu: MealMenu }) {
  return (
    <div className="mt-3 space-y-2.5 rounded-2xl bg-sand-50 p-3.5">
      {menu.groups.map((group) => (
        <div key={group.label} className="sm:flex sm:gap-3">
          <p className="text-xs font-black text-sand-700 sm:w-20 sm:shrink-0 sm:pt-0.5">
            {group.label}
          </p>
          <ul className="mt-1 flex flex-wrap gap-x-2 gap-y-1 sm:mt-0">
            {group.items.map((item) => (
              <li
                key={item}
                className="rounded-full border border-sand-200 bg-white px-2.5 py-1 text-xs font-semibold text-ink-700"
              >
                {item}
              </li>
            ))}
          </ul>
        </div>
      ))}
      <p className="pt-0.5 text-[11px] font-semibold text-ink-400">
        급식소 사정에 따라 일부 메뉴가 바뀔 수 있어요.
      </p>
    </div>
  )
}
