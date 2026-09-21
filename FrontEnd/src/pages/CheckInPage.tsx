/**
 * 셀프 체크인.
 *
 * 행사장 입구에 붙인 QR 을 찍으면 열리는 화면이다. 줄이 밀리는 자리이므로
 * 입력은 세 칸으로 끝내고, 성공하면 스태프가 한눈에 볼 수 있도록
 * 이름과 조를 크게 띄운다. (명찰 · 간식 배부의 근거가 되는 화면이다)
 *
 * **QR 은 하나이고 자리는 여럿이다.** 낮의 본 행사와 저녁의 뒤풀이가 같은 QR 을
 * 쓰고, 지금 열려 있는 회차에 찍힌다(관리자 > 출석에서 연다). 그래서 화면이
 * 어느 자리에 찍혔는지 말해 주지 않으면 참가자는 자기가 어디에 찍힌 것인지 모른다.
 *
 * 한 번 체크인하면 **그 화면이 기기에 남는다.** 모바일 크롬은 탭을 오래 놔두면
 * 돌아왔을 때 알아서 새로고침해 버리는데, 그때마다 학번과 전화번호를 다시 묻는다면
 * 조를 확인하려는 사람이 매번 입력을 반복해야 한다. 되돌리려면 상단의
 * '다시 입력하기'를 누른다 (기기를 빌려준 경우 등).
 *
 * 남은 화면은 저절로 최신 배정을 따라가지만 간격 제한이 걸려 있어, 방금 바뀐 조를
 * 지금 보려면 브라우저 새로고침으로는 부족하다. 그래서 화면 안에 '새로고침'을 둔다.
 */

import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { PixelStar, PixelHeart } from '../components/Decorations'
import ContactChannels from '../components/ContactChannels'
import { EVENT } from '../data/event'
import {
  ApiError,
  fetchCheckInState,
  submitCheckIn,
  type CheckInResponse,
} from '../lib/api'
import { formatDateTime } from '../lib/format'

type ViewState =
  | { kind: 'form' }
  | { kind: 'sending' }
  | { kind: 'done'; result: CheckInResponse }
  | { kind: 'error'; message: string }

type CheckInParticipant = NonNullable<CheckInResponse['participant']>
type Credentials = { name: string; studentId: string; phoneLast4: string }
/** '새로고침'을 누른 결과. 눌렀는데 아무 반응도 없으면 눌린 줄을 모른다. */
type RefreshNote = { ok: boolean; text: string }

/**
 * 체크인 결과 보관.
 *
 * sessionStorage 는 탭이 정리되면 함께 사라져 여기서는 쓸모가 없다.
 * 본인 기기에 본인 정보를 두는 것이라 localStorage 를 쓴다.
 */
const STORAGE_KEY = 'festa.checkin'
/** 하루 일정을 넉넉히 덮는다. 행사가 끝나면 알아서 비워진다. */
const KEEP_MS = 24 * 60 * 60 * 1000
/**
 * 다시 열었을 때 **조용히** 최신 배정을 받아오는 간격.
 *
 * 조가 현장에서 바뀌는 일이 있어 캐시만 믿으면 옛 조를 스태프에게 보여주게 된다.
 * 다만 행사장에서는 수백 명이 같은 IP 를 타므로, 새로고침할 때마다 부르면
 * rate limit 을 헛되이 먹는다. 그래서 마지막으로 받은 지 1분이 지났을 때만 부른다.
 *
 * 이 간격은 화면의 '새로고침' 버튼에는 걸지 않는다. 직접 누른 것은
 * "지금 바뀐 걸 보고 싶다"는 뜻이라, 방금 받아온 뒤라도 한 번 더 부른다.
 */
const REFRESH_AFTER_MS = 60 * 1000

interface StoredCheckIn {
  savedAt: number
  credentials: Credentials
  participant: CheckInParticipant
}

/** 저장소는 시크릿 모드나 용량 초과로 던질 수 있다. 실패해도 화면은 살아야 한다. */
function loadStored(): StoredCheckIn | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as StoredCheckIn
    if (!parsed?.participant?.name || Date.now() - parsed.savedAt > KEEP_MS) {
      localStorage.removeItem(STORAGE_KEY)
      return null
    }
    return parsed
  } catch {
    return null
  }
}

function saveStored(credentials: Credentials, participant: CheckInParticipant): void {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ savedAt: Date.now(), credentials, participant } satisfies StoredCheckIn),
    )
  } catch {
    // 저장하지 못해도 이번 화면은 그대로 보인다. 새로고침 시 다시 입력하면 된다.
  }
}

function clearStored(): void {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    // 무시
  }
}

function doneView(participant: CheckInParticipant, alreadyCheckedIn: boolean): ViewState {
  return {
    kind: 'done',
    result: { ok: true, reason: 'ok', alreadyCheckedIn, participant },
  }
}

export default function CheckInPage() {
  const [name, setName] = useState('')
  const [studentId, setStudentId] = useState('')
  const [last4, setLast4] = useState('')
  // 새로고침되어도 이미 체크인한 사람은 입력 화면으로 돌아가지 않는다.
  const [view, setView] = useState<ViewState>(() => {
    const stored = loadStored()
    return stored ? doneView(stored.participant, true) : { kind: 'form' }
  })
  const [windowOpen, setWindowOpen] = useState<boolean | null>(null)
  // '내 QR 열기'를 보일지. 관리자가 언제든 내릴 수 있어 저장본이 아니라 서버를 본다.
  // 서버에 못 물어봤으면 보이지 않는 쪽으로 둔다 — 없어서 문의하는 것이,
  // 있는데 안 되는 것보다 낫다.
  const [cardLink, setCardLink] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [refreshNote, setRefreshNote] = useState<RefreshNote | null>(null)

  // 닫혀 있으면 입력을 다 시킨 뒤에 튕기는 대신 미리 알려 준다.
  useEffect(() => {
    fetchCheckInState()
      .then((state) => {
        setWindowOpen(state.open)
        setCardLink(state.cardLink)
      })
      .catch(() => setWindowOpen(null))
  }, [])

  /**
   * 보관해 둔 화면을 최신 배정으로 맞춘다.
   *
   * `manual` 이면 사람이 '새로고침'을 누른 것이다. 이때는 간격 제한을 넘기고,
   * 결과(맞췄는지 · 왜 못 받아왔는지)를 반드시 화면에 남긴다. 조용히 실패하면
   * 누른 사람은 "바뀐 게 없다"고 읽어 버리는데, 사실은 못 받아온 것이라
   * 옛 조를 그대로 스태프에게 보여 주게 된다.
   *
   * 자동 갱신은 반대로 아무 말도 하지 않는다. 실패해도(창구가 닫혔거나 통신이
   * 끊겼거나) 보관된 화면은 그대로 둔다.
   */
  const refresh = useCallback(async (manual: boolean) => {
    const stored = loadStored()
    if (!stored) return
    if (!manual && Date.now() - stored.savedAt < REFRESH_AFTER_MS) return

    if (manual) {
      setRefreshing(true)
      setRefreshNote(null)
    }
    try {
      const result = await submitCheckIn(stored.credentials)
      if (result.ok && result.participant) {
        saveStored(stored.credentials, result.participant)
        setView(doneView(result.participant, true))
        if (manual) setRefreshNote({ ok: true, text: '최신 정보로 맞췄어요.' })
      } else if (manual) {
        setRefreshNote({
          ok: false,
          text: result.message || '지금은 정보를 받아올 수 없어요. 스태프에게 문의해 주세요.',
        })
      }
    } catch (error) {
      if (manual) {
        setRefreshNote({
          ok: false,
          text:
            error instanceof ApiError && error.status === 429
              ? '요청이 너무 잦습니다. 잠시 뒤 다시 눌러 주세요.'
              : '정보를 받아오지 못했어요. 잠시 뒤 다시 눌러 주세요.',
        })
      }
    } finally {
      if (manual) setRefreshing(false)
    }
  }, [])

  // 페이지를 여는 순간만 보면, 화면을 켜 둔 채로는 영영 갱신되지 않는다.
  // 홈으로 나갔다 돌아오거나 탭을 다시 볼 때도 확인한다 — 관리자가 조나 표시 항목을
  // 바꾸는 일이 현장에서 실제로 일어나기 때문이다.
  useEffect(() => {
    void refresh(false)

    const onVisible = () => {
      if (document.visibilityState === 'visible') void refresh(false)
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [refresh])

  const reset = () => {
    clearStored()
    setName('')
    setStudentId('')
    setLast4('')
    setRefreshNote(null)
    setView({ kind: 'form' })
  }

  const canSubmit =
    name.trim().length >= 2 &&
    studentId.trim().length >= 4 &&
    last4.length === 4 &&
    view.kind !== 'sending'

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (!canSubmit) return

    setView({ kind: 'sending' })
    const credentials = { name: name.trim(), studentId: studentId.trim(), phoneLast4: last4 }
    try {
      const result = await submitCheckIn(credentials)
      setView({ kind: 'done', result })
      if (result.ok && result.participant) saveStored(credentials, result.participant)
      if (result.reason === 'closed') setWindowOpen(false)
    } catch (error) {
      setView({
        kind: 'error',
        message:
          error instanceof ApiError
            ? error.status === 429
              ? '시도가 너무 많습니다. 잠시 후 다시 시도하거나 스태프에게 문의해 주세요.'
              : error.message
            : '체크인에 실패했습니다. 스태프에게 문의해 주세요.',
      })
    }
  }

  if (view.kind === 'done' && view.result.ok && view.result.participant) {
    return (
      <SuccessCard
        participant={view.result.participant}
        already={view.result.alreadyCheckedIn === true}
        onReset={reset}
        onRefresh={() => void refresh(true)}
        refreshing={refreshing}
        note={refreshNote}
        cardLink={cardLink}
      />
    )
  }

  return (
    <div className="mx-auto max-w-md space-y-6">
      <header className="text-center">
        <PixelStar className="mx-auto size-10 text-sand-300" />
        <h1 className="mt-3 text-2xl font-black text-ink-900 sm:text-3xl">셀프 체크인</h1>
        <p className="mt-2 text-sm leading-relaxed text-ink-600">
          {EVENT.name}에 오신 것을 환영합니다!<br />
          미리 체크인 한 뒤 스태프에게 보여주세요.
        </p>
      </header>

      {windowOpen === false && (
        <div className="rounded-2xl border-2 border-flame-200 bg-flame-100/70 px-5 py-4">
          <p className="text-sm font-black text-flame-600">아직 체크인이 열리지 않았어요</p>
          <p className="mt-1.5 text-sm leading-relaxed text-ink-700">
            체크인 시작 이후 화면을 새로고침하여 체크인 해주세요.
          </p>
        </div>
      )}

      {view.kind === 'done' && !view.result.ok && <FailureCard result={view.result} />}
      {view.kind === 'error' && (
        <div className="card border-brick-400/40 bg-brick-400/8 p-5 text-sm font-semibold text-brick-500">
          {view.message}
        </div>
      )}

      <form onSubmit={handleSubmit} className="card space-y-4 p-6">
        <div>
          <label htmlFor="checkin-name" className="label">
            이름
          </label>
          <input
            id="checkin-name"
            className="input"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="홍길동"
            autoComplete="name"
            maxLength={20}
          />
        </div>

        <div>
          <label htmlFor="checkin-student-id" className="label">
            학번
          </label>
          <input
            id="checkin-student-id"
            className="input tabular"
            value={studentId}
            onChange={(event) => setStudentId(event.target.value)}
            placeholder="20261234"
            inputMode="numeric"
            maxLength={20}
          />
        </div>

        <div>
          <label htmlFor="checkin-last4" className="label">
            전화번호 뒤 4자리
          </label>
          <input
            id="checkin-last4"
            className="input tabular"
            value={last4}
            onChange={(event) => setLast4(event.target.value.replace(/\D/g, '').slice(0, 4))}
            placeholder="5678"
            inputMode="numeric"
            maxLength={4}
          />
          <p className="mt-1.5 text-xs text-ink-500">
            구글폼에 적은 전화번호의 마지막 네 자리를 입력해주세요.
          </p>
        </div>

        <button type="submit" className="btn-primary w-full py-3.5" disabled={!canSubmit}>
          {view.kind === 'sending' ? '확인 중…' : '체크인하기'}
        </button>
      </form>

      <p className="text-center text-xs leading-relaxed text-ink-400">
        참가가 확정된 분만 체크인할 수 있어요.<br />
        체크인에 이상이 있거나 문의가 필요하면 근처 스태프에게 말씀해 주세요.
      </p>
    </div>
  )
}

/**
 * 체크인 완료 화면.
 *
 * 스태프가 멀리서도 조를 확인해야 하므로 조를 가장 크게 둔다.
 * 이미 체크인한 사람이 다시 열어도 같은 화면이 나와야 명찰을 받을 수 있다.
 *
 * 럭키드로우 번호는 조 바로 아래에 금색 띠로 둔다. 조는 **접수처에서 스태프가**
 * 보는 값이고 번호는 **몇 시간 뒤 본인이** 찾는 값이라 쓰임이 갈리므로, 색을
 * 아예 달리해 한 화면에서 헷갈리지 않게 한다. (추첨 화면도 같은 금색이다)
 *
 * 조가 바뀌었다는 말을 듣고 브라우저를 새로고침해도 갱신 간격에 걸려 그대로일 수
 * 있어, 간격을 넘기는 '새로고침' 버튼을 화면 안에 둔다.
 */
function SuccessCard({
  participant,
  already,
  onReset,
  onRefresh,
  refreshing,
  note,
  cardLink,
}: {
  participant: CheckInParticipant
  already: boolean
  onReset: () => void
  onRefresh: () => void
  refreshing: boolean
  note: RefreshNote | null
  /** '내 QR 열기'를 보일지 (관리자 > 명찰에서 정한다) */
  cardLink: boolean
}) {
  const filled = participant.assignments.filter((item) => item.value)
  const [primary, ...rest] = filled
  // 기기에 저장된 옛 화면에는 이 값이 없다. 조용히 갱신되므로 없으면 안내만 띄운다.
  const drawLabel = participant.drawLabel ?? null

  return (
    <div className="mx-auto max-w-md space-y-5">
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          className="btn-ghost px-3.5 py-1.5 text-xs"
          onClick={onRefresh}
          disabled={refreshing}
        >
          {refreshing ? '받아오는 중…' : '새로고침'}
        </button>
        <button type="button" className="btn-ghost px-3.5 py-1.5 text-xs" onClick={onReset}>
          다시 입력하기
        </button>
      </div>

      {note && (
        <p
          className={`text-center text-xs font-bold ${
            note.ok ? 'text-sand-700' : 'text-brick-500'
          }`}
        >
          {note.text}
        </p>
      )}

      <div className="card overflow-hidden text-center">
        <div className="border-b-2 border-sand-200 bg-sand-100 px-6 py-6">
          <PixelHeart className="mx-auto size-9 text-sand-500" />
          {/*
            어느 자리에 찍혔는지. 같은 QR 로 본 행사와 뒤풀이에 각각 찍히므로,
            이 한 줄이 없으면 참가자는 자기가 어디에 찍힌 것인지 알 수 없다.
          */}
          <p className="mt-2 text-[11px] font-black tracking-[0.2em] text-sand-600">
            {participant.sessionLabel}
          </p>
          <p className="mt-1 text-sm font-bold text-sand-700">
            {already ? '이미 체크인하셨어요' : '체크인 완료!'}
          </p>
          <p className="mt-1 text-3xl font-black text-ink-900">{participant.name}</p>
        </div>

        {primary ? (
          <div className="px-6 py-7">
            <p className="text-xs font-bold tracking-wide text-ink-500">{primary.label}</p>
            <p className="mt-1 text-5xl font-black text-cobalt-600">{primary.value}</p>
          </div>
        ) : (
          <div className="px-6 py-7">
            <p className="text-sm font-semibold text-ink-500">
              아직 배정 정보가 없어요. 스태프에게 문의해 주세요.
            </p>
          </div>
        )}

        {/* 아래 요소가 각자 위쪽 선을 갖고 있어 여기서는 윗선만 그린다. */}
        <div className="border-t-2 border-flame-200 bg-flame-100/70 px-6 py-5">
          <p className="text-xs font-black tracking-wide text-flame-600">럭키드로우 번호</p>
          {drawLabel ? (
            <>
              <p className="mt-0.5 text-5xl font-black tabular text-flame-600">{drawLabel}</p>
              <p className="mt-2 text-xs leading-relaxed text-ink-600">
                추첨 때 화면에서 이 번호를 찾으세요. 당첨되면 이 화면을 스태프에게 보여 주시면
                됩니다.
              </p>
            </>
          ) : (
            <p className="mt-1 text-sm font-semibold leading-relaxed text-ink-600">
              번호를 받아오는 중입니다. 잠시 뒤 위의 &lsquo;새로고침&rsquo;을 눌러 주세요.
            </p>
          )}
        </div>

        {rest.length > 0 && (
          <dl className="grid grid-cols-2 divide-x divide-sand-100 border-t border-sand-100">
            {rest.map((item) => (
              <div key={item.key} className="px-4 py-3.5">
                <dt className="text-xs font-bold text-ink-500">{item.label}</dt>
                <dd className="mt-0.5 text-lg font-black text-ink-900">{item.value}</dd>
              </div>
            ))}
          </dl>
        )}

        <p className="border-t border-sand-100 bg-sand-50 px-6 py-3 text-xs text-ink-500 tabular">
          {formatDateTime(participant.checkedInAt)} 체크인
        </p>
      </div>

      <p className="text-center text-sm font-bold text-ink-700">
        이 화면을 스태프에게 보여 주세요.
      </p>

      {/*
        개인 카드. 명찰을 받으면 거기에도 같은 QR 이 인쇄되어 있으니, 이 링크는
        명찰을 두고 왔거나 아직 받지 못했을 때의 길이다.

        보일지 말지는 관리자가 정한다(관리자 > 명찰). 이 화면은 기기에 저장되어
        새로고침해도 그대로 열리므로, 저장본이 아니라 **지금의 설정**을 따라야
        나중에 내렸을 때 이미 체크인한 사람의 화면에서도 사라진다.
      */}
      {participant.token && cardLink && (
        <Link
          to={`/p/${participant.token}`}
          className="btn-ghost block w-full py-3 text-center text-sm"
        >
          내 QR 열기
        </Link>
      )}
      <p className="text-center text-xs leading-relaxed text-ink-400">
        이 화면은 이 기기에 저장돼 새로고침해도 그대로 열려요. 조가 바뀌었다면 위의
        &lsquo;새로고침&rsquo;을, 다른 사람이 체크인하려면 &lsquo;다시 입력하기&rsquo;를
        눌러 주세요.
      </p>
    </div>
  )
}

const FAIL_GUIDE: Record<string, string> = {
  closed: '시각이 되면 스태프가 체크인을 열어 줍니다. 잠시만 기다려 주세요.',
  not_in_session:
    '지금 열려 있는 자리의 참가 명단에 없습니다. 솔로파티라면 신청하지 않으신 것일 수 있어요. 합류하고 싶으시면 스태프에게 말씀해 주세요.',
  not_found:
    '이름 · 학번 · 전화번호 뒤 4자리가 신청서와 모두 같아야 해요. 다시 확인해 주시고, 그래도 안 되면 스태프에게 말씀해 주세요.',
  not_confirmed:
    '참가비 납입 확인이 끝나야 체크인할 수 있어요. 스태프에게 말씀하시면 현장에서 처리해 드립니다.',
  cancelled: '참가 취소로 처리된 신청이에요. 착오가 있다면 스태프에게 문의해 주세요.',
}

function FailureCard({ result }: { result: CheckInResponse }) {
  return (
    <div className="card border-flame-200 bg-flame-100/50 p-5">
      <p className="text-base font-black text-ink-900">{result.message}</p>
      <p className="mt-2 text-sm leading-relaxed text-ink-700">
        {FAIL_GUIDE[result.reason] ?? '스태프에게 문의해 주세요.'}
      </p>
      {result.reason !== 'closed' && (
        <div className="mt-4">
          <ContactChannels compact />
        </div>
      )}
    </div>
  )
}
