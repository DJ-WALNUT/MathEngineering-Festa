import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'

import { EVENT, NAV_LINKS } from '../data/event'
import ContactChannels from './ContactChannels'
import { PixelHeart, PixelStar, Wordmark } from './Decorations'

export default function Layout() {
  const [menuOpen, setMenuOpen] = useState(false)
  const location = useLocation()

  /**
   * 페이지를 옮기면 맨 위에서 시작한다.
   *
   * 브라우저는 같은 문서 안의 이동으로 보아 스크롤 위치를 그대로 물려주는데,
   * 홈 중간에서 '납입 확인'을 누르면 그 페이지의 중간부터 보여 무슨 화면인지
   * 알 수 없다. 문서 안 앵커(#)로 가는 경우만 브라우저에 맡긴다.
   */
  useEffect(() => {
    if (location.hash) return
    window.scrollTo({ top: 0, behavior: 'instant' })
  }, [location.pathname, location.hash])

  return (
    <div className="halftone-light flex min-h-dvh flex-col">
      {/* 포스터 위쪽의 만국기 */}
      <div className="bunting w-full border-b-2 border-ink-900" aria-hidden />

      <header className="sticky top-0 z-40 border-b-2 border-ink-900 bg-cream/95 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-2.5">
          <Link to="/" className="flex items-center gap-2.5" onClick={() => setMenuOpen(false)}>
            <span className="grid size-9 place-items-center rounded-md border-2 border-ink-900 bg-brick-500 shadow-[2px_2px_0_var(--color-ink-900)]">
              <PixelHeart className="size-6" />
            </span>
            <span className="leading-tight">
              {/* 헤더는 픽셀 글자 한 줄. 히어로의 큰 워드마크와 같은 글꼴이라 한 식구로 읽힌다. */}
              <span className="font-pixel block text-lg text-ink-900">
                {EVENT.name} <span className="text-flame-500">{EVENT.edition}</span>
              </span>
              <span className="block text-[11px] font-semibold text-ink-500">{EVENT.title}</span>
            </span>
          </Link>

          <nav className="hidden gap-1 sm:flex">
            {NAV_LINKS.map((link) => (
              <NavItem key={link.to} to={link.to} label={link.label} />
            ))}
          </nav>

          <button
            type="button"
            className="rounded-md border-2 border-ink-900 bg-white p-2 text-ink-800 shadow-[2px_2px_0_var(--color-ink-900)] sm:hidden"
            aria-label={menuOpen ? '메뉴 닫기' : '메뉴 열기'}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
          >
            {menuOpen ? <CloseIcon /> : <MenuIcon />}
          </button>
        </div>

        {menuOpen && (
          <nav className="border-t-2 border-ink-900 bg-white px-4 py-2 sm:hidden">
            {NAV_LINKS.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                end={link.to === '/'}
                onClick={() => setMenuOpen(false)}
                className={({ isActive }) =>
                  `font-pixel block rounded-md px-3 py-2.5 text-base ${
                    isActive ? 'bg-cobalt-500 text-white' : 'text-ink-700'
                  }`
                }
              >
                {isActiveArrow(link.label)}
              </NavLink>
            ))}
          </nav>
        )}
      </header>

      <main key={location.pathname} className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 sm:py-12 break-keep">
        <Outlet />
      </main>

      <footer className="halftone relative mt-8 overflow-hidden border-t-2 border-ink-900 text-white">
        <PixelStar className="pointer-events-none absolute -left-3 top-6 size-16 opacity-70 sm:size-20" />
        <PixelHeart className="pointer-events-none absolute -right-4 -bottom-3 size-24 opacity-80 sm:size-32" />

        <div className="relative mx-auto max-w-5xl px-4 py-10 text-center">
          <Wordmark className="text-4xl sm:text-5xl" />
          <p className="mt-3 text-sm font-semibold text-white/85">
            {EVENT.title} · {EVENT.dateLabel}
          </p>
          <div className="mx-auto mt-5 max-w-sm sm:max-w-none">
            <ContactChannels compact />
          </div>
          <p className="mt-5 text-sm">
            <Link
              to="/payment"
              className="font-pixel-small text-gold-300 underline underline-offset-4 hover:text-gold-400"
            >
              참가비 납입 확인하기 →
            </Link>
          </p>
        </div>

        <div className="relative border-t-2 border-ink-900 bg-ink-900 py-3">
          <p className="mx-auto max-w-5xl px-4 text-center text-xs font-bold leading-relaxed text-white/75 break-keep">
            {EVENT.organization}
          </p>
        </div>
      </footer>
    </div>
  )
}

/** 피처폰 메뉴처럼 앞에 '>' 를 붙인다. */
function isActiveArrow(label: string) {
  return `> ${label}`
}

function NavItem({ to, label }: { to: string; label: string }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        `font-pixel rounded-md border-2 px-3.5 py-1.5 text-base transition ${
          isActive
            ? 'border-ink-900 bg-cobalt-500 text-white shadow-[2px_2px_0_var(--color-ink-900)]'
            : 'border-transparent text-ink-600 hover:border-ink-900 hover:bg-white'
        }`
      }
    >
      {label}
    </NavLink>
  )
}

function MenuIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth={2.5}>
      <path d="M4 7h16M4 12h16M4 17h16" strokeLinecap="square" />
    </svg>
  )
}

function CloseIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth={2.5}>
      <path d="M6 6l12 12M18 6L6 18" strokeLinecap="square" />
    </svg>
  )
}
