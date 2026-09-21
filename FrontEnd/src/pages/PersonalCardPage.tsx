/**
 * 개인 카드 (`/p/:token`).
 *
 * 명찰의 QR 이 가리키는 화면이다. 자기 조와 럭키드로우 번호, 그리고 지금까지
 * 어느 자리에 출석했는지를 확인한다. 명찰을 두고 왔거나 아직 받지 못한 사람은
 * 이 화면을 띄워 스태프에게 내민다.
 *
 * 그래서 QR 을 화면에서 가장 크게 둔다. 사람이 몰린 자리에서 열었을 때
 * 스크롤하지 않고 바로 내밀 수 있어야 한다.
 *
 * **여기서 새로 드러나는 정보는 없다.** 이름 · 학과 · 조는 명찰 앞면에 이미
 * 인쇄되어 있고, 이 주소는 그 명찰을 든 사람만 안다. 전화번호 · 건강 정보 ·
 * 납입 내역처럼 명찰에 없는 것은 서버가 아예 내려주지 않는다.
 */

import { useEffect, useState, type ComponentType } from 'react'
import { Link, useParams } from 'react-router-dom'
import QRCode from 'qrcode'

import { ClockIcon, PixelStar, InstagramIcon, MapPinIcon } from '../components/Decorations'
import { EVENT } from '../data/event'
import { fetchPersonalCard, type PersonalCard } from '../lib/api'
import { formatDateTime } from '../lib/format'

/**
 * 살아 있는 화면임을 보이는 띠.
 *
 * QR 은 사진으로 찍히면 그만이다. 캡처본을 남의 폰에서 띄워도 스캐너는 똑같이
 * 읽는다 — 그래서 **사람이 1초 만에 가를 수 있는 표시**를 둔다.
 *
 *   · 글자가 흐른다 — 스크린샷은 멈춰 있다
 *   · 시계가 초 단위로 바뀐다 — 캡처본은 찍힌 시각에 멈춰 있다
 *   · 이름이 함께 흐른다 — 남의 화면을 빌려 오면 이름이 다르다
 *
 * 세 가지 모두 스태프가 화면을 자세히 볼 필요 없이 눈에 걸리는 것들이다.
 * 이것으로 위조를 '막지는' 못한다. 다만 캡처본을 그대로 들이미는 가장 쉬운
 * 길을 닫는다.
 */
function LiveTicker({ name }: { name: string }) {
  const [clock, setClock] = useState(() => nowText())

  useEffect(() => {
    const timer = setInterval(() => setClock(nowText()), 1000)
    return () => clearInterval(timer)
  }, [])

  // 같은 내용을 두 벌 이어 붙여야 이음매 없이 돈다 (index.css 의 ticker-slide).
  const line = `${EVENT.name} · ${name} · ${clock}`
  return (
    <div
      className="sticky top-0 z-10 overflow-hidden border-b-2 border-sand-300 bg-ink-900 py-1.5"
      // 눈으로 보는 표시다. 화면 낭독기에는 이름·시각이 이미 본문에 있다.
      aria-hidden
    >
      <div className="ticker-track">
        {[0, 1].map((copy) => (
          <span key={copy} className="flex shrink-0">
            {[0, 1, 2].map((index) => (
              <span
                key={index}
                className="whitespace-nowrap px-6 text-sm font-black tracking-wide text-cream tabular"
              >
                {line}
              </span>
            ))}
          </span>
        ))}
      </div>
    </div>
  )
}

/**
 * 안내 화면으로 가는 줄.
 *
 * 명찰 뒷면의 QR 세 개가 인쇄되지 않은 채로 나왔다. 그래서 그 QR 들이 데려다주려던
 * 곳으로 **이 화면에서** 갈 수 있어야 한다 — 참가자가 실제로 손에 든 화면은 여기뿐이다.
 *
 * 문 앞에서 내미는 QR 이 이 화면의 주인이므로, 안내 줄은 QR 을 밀어내지 않는 아래쪽에
 * 두되 글자 링크로 흘리지는 않는다. 아이콘 · 제목 · 한 줄 설명을 갖춘 줄로 세워
 * 급할 때도 누를 곳이 바로 보이게 한다.
 */
function GuideLinks() {
  const instagram = EVENT.contacts.find((channel) => channel.kind === 'instagram')

  return (
    <nav className="card divide-y divide-sand-100 overflow-hidden" aria-label="안내">
      <GuideLink to="/venue" Icon={MapPinIcon} title="지도 보러가기" note="건물 · 층별 도면과 길찾기" />
      <GuideLink to="/schedule" Icon={ClockIcon} title="타임테이블 보러가기" note="시간별 일정 한눈에" />
      {instagram && (
        <GuideLink
          href={instagram.url}
          Icon={InstagramIcon}
          title="공과대학 인스타"
          note={instagram.handle}
        />
      )}
    </nav>
  )
}

/**
 * 안내 줄 한 칸.
 *
 * `to` 면 앱 안에서 넘어가고 `href` 면 새 탭으로 나간다 — 둘의 생김새는 같게 두고
 * 밖으로 나가는 줄에만 화살표 방향을 달리해 눌렀을 때 무슨 일이 일어날지 미리 알린다.
 */
function GuideLink({
  to,
  href,
  Icon,
  title,
  note,
}: {
  to?: string
  href?: string
  Icon: ComponentType<{ className?: string }>
  title: string
  note: string
}) {
  const inner = (
    <>
      <span className="grid size-10 shrink-0 place-items-center rounded-2xl bg-sand-50 text-sand-700">
        <Icon className="size-5" />
      </span>
      <span className="min-w-0 flex-1 text-left">
        <span className="block text-sm font-black text-ink-900">{title}</span>
        <span className="block truncate text-xs font-semibold text-ink-500">{note}</span>
      </span>
      <span aria-hidden className="text-base font-black text-sand-400">
        {href ? '↗' : '›'}
      </span>
    </>
  )

  const className =
    'flex w-full items-center gap-3 px-4 py-3 transition hover:bg-sand-50 active:bg-sand-100'

  return href ? (
    <a href={href} target="_blank" rel="noreferrer noopener" className={className}>
      {inner}
    </a>
  ) : (
    <Link to={to ?? '/'} className={className}>
      {inner}
    </Link>
  )
}

function nowText(): string {
  return new Date().toLocaleTimeString('ko-KR', { hour12: false })
}

export default function PersonalCardPage() {
  const { token = '' } = useParams()
  const [card, setCard] = useState<PersonalCard | null>(null)
  const [qr, setQr] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    fetchPersonalCard(token)
      .then(setCard)
      .catch(() => setError('확인할 수 없는 QR 입니다. 스태프에게 문의해 주세요.'))
  }, [token])

  useEffect(() => {
    // 명찰과 같은 값을 담는다 — 스태프의 스캐너는 둘을 구분하지 않는다.
    QRCode.toDataURL(`${window.location.origin}/p/${token}`, {
      width: 720,
      margin: 1,
      errorCorrectionLevel: 'M',
    })
      .then(setQr)
      .catch(() => setQr(''))
  }, [token])

  if (error) {
    return (
      <div className="grid min-h-dvh place-items-center bg-cream px-6 text-center">
        <div>
          <PixelStar className="mx-auto size-10 text-sand-300" />
          <p className="mt-3 text-sm font-semibold text-ink-700">{error}</p>
          <Link to="/" className="mt-4 inline-block text-xs font-semibold text-cobalt-600">
            {EVENT.name} 홈으로
          </Link>
        </div>
      </div>
    )
  }

  if (!card) {
    return <div className="grid min-h-dvh place-items-center text-sm text-ink-500">불러오는 중…</div>
  }

  const filled = card.assignments.filter((item) => item.value)

  return (
    <div className="min-h-dvh bg-gradient-to-b from-sand-100 to-cream pb-6">
      <LiveTicker name={card.name} />

      <div className="mx-auto w-full max-w-sm space-y-4 px-4 pt-4">
        <header className="text-center">
          <p className="text-xs font-bold tracking-[0.25em] text-sand-700">{EVENT.name}</p>
          <h1 className="mt-1 text-2xl font-black text-ink-900">{card.name}</h1>
          <p className="mt-0.5 text-sm font-semibold text-ink-500">
            {card.department ?? '학과 미기재'}
          </p>
        </header>

        {/* 문 앞에서 내미는 화면이다. QR 이 가장 크고 가장 위에 있어야 한다. */}
        <div className="card p-5 text-center">
          {qr ? (
            <img src={qr} alt="개인 QR" className="mx-auto aspect-square w-full max-w-64" />
          ) : (
            <div className="mx-auto grid aspect-square w-full max-w-64 place-items-center text-sm text-ink-400">
              QR 생성 중…
            </div>
          )}
          <p className="mt-2 text-xs leading-relaxed text-ink-500">
            확인이 필요할 때 스태프에게 이 화면을 보여 주세요.
          </p>
          <p className="mt-1 text-[11px] font-bold tracking-[0.2em] text-ink-400">{card.token}</p>
        </div>

        {/*
          회차별 출석. 낮의 본 행사와 저녁의 뒤풀이가 따로 세어지므로, 본인이
          어느 자리까지 찍혔는지 한눈에 보여 준다. 뒤풀이에 오면서 "내가 찍혔나"를
          묻는 사람이 반드시 나온다.
        */}
        {card.checkins.length > 0 && (
          <div className="card p-4">
            <ul className="space-y-1.5">
              {card.checkins.map((item) => (
                <li key={item.key} className="flex items-baseline justify-between gap-3">
                  <span className="text-sm font-black text-ink-900">{item.label}</span>
                  <span className="text-xs text-ink-500 tabular">
                    {formatDateTime(item.at)} 확인
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {(filled.length > 0 || card.drawLabel) && (
          <div className="card p-5">
            <dl className="grid grid-cols-2 gap-3 text-center">
              {filled.map((item) => (
                <div key={item.key} className="rounded-2xl bg-sand-50 px-3 py-2.5">
                  <dt className="text-[11px] font-bold text-ink-500">{item.label}</dt>
                  <dd className="mt-0.5 text-lg font-black text-ink-900">{item.value}</dd>
                </div>
              ))}
              {card.drawLabel && (
                <div className="rounded-2xl bg-flame-100 px-3 py-2.5">
                  <dt className="text-[11px] font-bold text-flame-600">럭키드로우 번호</dt>
                  <dd className="mt-0.5 text-lg font-black tabular text-flame-600">
                    {card.drawLabel}
                  </dd>
                </div>
              )}
            </dl>
          </div>
        )}

        <GuideLinks />

        <p className="text-center text-xs text-ink-400">
          {card.checkins.length === 0 && '아직 체크인 전입니다.'}
          {card.joinsAfterparty && card.checkins.length > 0 && `${EVENT.afterparty.label} 신청자입니다.`}
        </p>
      </div>
    </div>
  )
}
