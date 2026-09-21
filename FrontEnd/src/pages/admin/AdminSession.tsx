/**
 * 관리자 인증 — `/admin` 과 그 하위 화면이 함께 쓴다.
 *
 * 로그인은 **ID + 등급별 비밀번호**다. 비밀번호는 국장단용과 국원용 둘이고, 어느
 * 것을 요구할지는 그 계정의 역할군이 정한다 — 어긋나면 서버가 거절한다.
 *
 * 화면마다 따로 인증을 두면 한쪽만 느슨해진다. 실제로 추첨 화면은 처음에
 * '토큰이 있는가'만 보고 통과시켜, 만료된 토큰으로도 화면이 열린 뒤 API 호출에서야
 * 튕겼다. 인증을 한 곳에 모아 **모든 관리자 화면이 같은 검사를 거치게** 한다.
 *
 * 검사는 두 단계다.
 *
 *   1. `sessionStorage` 에 토큰이 있는가 (없으면 바로 로그인)
 *   2. 그 토큰이 서버에서 아직 유효한가 (`GET /api/admin/session`)
 *
 * 토큰을 `sessionStorage` 에 두므로 **탭마다 따로다.** 강당 노트북에서 추첨 화면을
 * 새로 열면 비밀번호를 다시 묻는데, 이건 불편이 아니라 의도다 — 관리자 화면을 띄워
 * 둔 기기를 두고 자리를 비워도 다른 탭으로 명단이 새지 않는다.
 */

import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { PixelStar } from '../../components/Decorations'
import { EVENT } from '../../data/event'
import { ApiError, adminApi, getAdminToken, type AdminSessionInfo } from '../../lib/api'

/** 마지막으로 로그인한 ID. 자기 이름을 매번 다시 치게 할 이유가 없다. */
const LAST_ID_KEY = 'mt.admin.lastId'

export type SessionStatus = 'checking' | 'in' | 'out'

/**
 * 지금 로그인한 사람.
 *
 * 누구인지(이름)와 무엇을 볼 수 있는지(탭)를 **서버에서 매번 받아 온다.** 토큰에
 * 박아 두면 최고 관리자가 권한을 바꿔도 상대가 로그아웃할 때까지 그대로다.
 */
export function useAdminSession(): {
  status: SessionStatus
  session: AdminSessionInfo | null
  signIn: (session: AdminSessionInfo) => void
} {
  const [status, setStatus] = useState<SessionStatus>('checking')
  const [session, setSession] = useState<AdminSessionInfo | null>(null)

  useEffect(() => {
    if (!getAdminToken()) {
      setStatus('out')
      return
    }
    let alive = true
    adminApi
      .checkSession()
      .then((info) => {
        if (!alive) return
        setSession(info)
        setStatus('in')
      })
      .catch(() => alive && setStatus('out'))
    return () => {
      alive = false
    }
  }, [])

  const signIn = useCallback((info: AdminSessionInfo) => {
    setSession(info)
    setStatus('in')
  }, [])

  return { status, session, signIn }
}

/**
 * 로그인 화면.
 *
 * `tone` 으로 밝은 관리자 화면과 어두운 추첨 화면 양쪽에 맞춘다. 추첨은 프로젝터를
 * 연결한 뒤 로그인하는 일이 많아, 흰 화면이 한 번 번쩍이면 그것부터 관객에게 보인다.
 */
export function AdminLogin({
  onSuccess,
  tone = 'light',
  title,
  subtitle,
}: {
  onSuccess: (session: AdminSessionInfo) => void
  tone?: 'light' | 'dark'
  title?: string
  subtitle?: string
}) {
  // 마지막으로 들어온 ID 를 기억해 둔다. 자기 이름을 매번 다시 치게 할 이유가 없다.
  const [username, setUsername] = useState(() => localStorage.getItem(LAST_ID_KEY) ?? '')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!username.trim() || !password || busy) return

    setBusy(true)
    setError('')
    try {
      const session = await adminApi.login(username.trim(), password)
      localStorage.setItem(LAST_ID_KEY, username.trim())
      onSuccess(session)
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.status === 429
            ? '로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요.'
            : caught.message
          : '로그인에 실패했습니다.',
      )
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  if (tone === 'dark') {
    return (
      <div className="grid min-h-dvh place-items-center bg-[#10161c] px-4 text-white">
        <form onSubmit={submit} className="w-full max-w-sm space-y-4">
          <div className="text-center">
            <p className="text-sm font-bold tracking-[0.3em] text-flame-300/80">LUCKY DRAW</p>
            <h1 className="mt-2 text-lg font-black">{title ?? '추첨 화면'}</h1>
            <p className="mt-1.5 text-sm text-white/45">
              {subtitle ?? '본인 이름과 본인 등급의 비밀번호를 입력해 주세요.'}
            </p>
          </div>

          <input
            className="w-full rounded-xl border border-white/15 bg-white/8 px-4 py-3 text-base text-white placeholder:text-white/35 focus:border-flame-300 focus:outline-none"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="이름 (로그인 ID)"
            autoComplete="username"
            autoFocus={!username}
          />

          <input
            type="password"
            className="w-full rounded-xl border border-white/15 bg-white/8 px-4 py-3 text-base text-white placeholder:text-white/35 focus:border-flame-300 focus:outline-none"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="비밀번호"
            autoComplete="current-password"
            autoFocus={Boolean(username)}
          />

          {error && <p className="text-sm font-semibold text-brick-400">{error}</p>}

          <button
            type="submit"
            className="w-full rounded-full bg-flame-300 py-3 text-sm font-black text-[#10161c] transition hover:bg-flame-200 disabled:opacity-40"
            disabled={!username.trim() || !password || busy}
          >
            {busy ? '확인 중…' : '들어가기'}
          </button>

          <Link to="/admin" className="block text-center text-xs text-white/40 hover:text-white/70">
            관리자 화면으로
          </Link>
        </form>
      </div>
    )
  }

  return (
    <div className="grid min-h-dvh place-items-center bg-gradient-to-b from-sand-100 to-cream px-4">
      <form onSubmit={submit} className="card w-full max-w-sm space-y-4 p-7">
        <div className="text-center">
          <PixelStar className="mx-auto size-10 text-sand-300" />
          <h1 className="mt-3 text-lg font-black text-ink-900">{title ?? `${EVENT.name} 관리자`}</h1>
          <p className="mt-1.5 text-sm text-ink-500">
            {subtitle ?? '본인 이름과 본인 등급의 비밀번호를 입력해 주세요.'}
          </p>
        </div>

        <div>
          <label htmlFor="admin-username" className="label">
            로그인 ID
          </label>
          <input
            id="admin-username"
            className="input"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="본인 이름"
            autoComplete="username"
            autoFocus={!username}
          />
          <p className="mt-1 text-xs text-ink-400">
            작업 기록에 이 이름이 남습니다. 계정이 없다면 학생회장에게 요청해 주세요.
          </p>
        </div>

        <div>
          <label htmlFor="password" className="label">
            비밀번호
          </label>
          <input
            id="password"
            type="password"
            className="input"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            autoFocus={Boolean(username)}
          />
          <p className="mt-1 text-xs text-ink-400">
            비밀번호는 등급마다 다릅니다 — 국장단과 국원이 서로 다른 것을 씁니다.
          </p>
        </div>

        {error && <p className="text-sm font-semibold text-brick-500">{error}</p>}

        <button
          type="submit"
          className="btn-primary w-full py-3"
          disabled={!username.trim() || !password || busy}
        >
          {busy ? '확인 중…' : '로그인'}
        </button>

        <Link to="/" className="block text-center text-xs text-ink-500 hover:text-ink-700">
          사이트로 돌아가기
        </Link>
      </form>
    </div>
  )
}

/** 세션을 확인하는 동안 잠깐 뜨는 화면. */
export function SessionChecking({ tone = 'light' }: { tone?: 'light' | 'dark' }) {
  return (
    <div
      className={`grid min-h-dvh place-items-center text-sm ${
        tone === 'dark' ? 'bg-[#10161c] text-white/45' : 'text-ink-500'
      }`}
    >
      확인 중…
    </div>
  )
}
