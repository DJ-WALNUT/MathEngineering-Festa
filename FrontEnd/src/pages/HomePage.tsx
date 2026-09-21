import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { ApplyLink, ApplySchedule } from '../components/Apply'
import ContactChannels from '../components/ContactChannels'
import {
  Envelope,
  Gamepad,
  OnAir,
  PixelHeart,
  PixelScatter,
  PixelStar,
  Wordmark,
} from '../components/Decorations'
import { EVENT, POSTER_CARDS } from '../data/event'
import { resolveApplyState } from '../lib/apply'
import { daysUntil, formatWon } from '../lib/format'

export default function HomePage() {
  return (
    <div className="space-y-10">
      <Hero />

      <Invitation />

      <FeeSection />

      <PosterGallery />

      <section className="grid gap-4 sm:grid-cols-2">
        <ListCard title="챙겨올 것" items={EVENT.packingList} dot="bg-cobalt-500" />
        <ListCard title="꼭 확인해 주세요" items={EVENT.notices} dot="bg-brick-500" />
      </section>

      <Window title="문의사항">
        <div className="p-5">
          <p className="text-sm leading-relaxed text-ink-600">
            참가비 · 일정 관련 문의는 두 학생회 인스타그램 DM 으로 남겨 주세요.
          </p>
          <div className="mt-4">
            <ContactChannels />
          </div>
        </div>
      </Window>
    </div>
  )
}

/**
 * 히어로 — 포스터 배너를 그대로 건다.
 *
 * 포스터의 글자·망점·만국기를 CSS 로 흉내 내는 대신 **배너 그림 자체**를 쓴다.
 * 인쇄물과 화면이 어긋날 일이 없고, 새 포스터가 나오면 `public/poster/banner.webp`
 * 한 장만 바꾸면 된다. 그림은 검은 픽셀 테두리의 창 안에 넣어 아래 카드들과
 * 한 식구로 보이게 한다.
 *
 * 배너는 2.6:1 이라 폰에서는 납작하다. 그래서 큰 글자(워드마크)와 버튼은 그림
 * 안이 아니라 **그림 아래 크림 종이 위**에 둔다 — 그림 위에 얹으면 폰에서 서로 겹친다.
 */
function Hero() {
  const remaining = daysUntil(EVENT.startsAt)
  const { openPhase } = resolveApplyState()

  return (
    <section className="card relative overflow-hidden">
      <PixelScatter />

      <div className="relative border-b-2 border-ink-900">
        <img
          src="/poster/banner.webp"
          alt={`${EVENT.name} ${EVENT.edition} 포스터`}
          className="block w-full"
          width={2000}
          height={769}
          fetchPriority="high"
        />
        {openPhase && <OnAir className="absolute left-3 top-3" label="접수 중" />}
      </div>

      <div className="relative px-5 pb-8 pt-7 text-center sm:px-8 sm:pb-10 sm:pt-9">
        <p className="speech-bubble mb-6 max-w-full text-xs sm:text-sm">{EVENT.tagline}</p>

        <h1>
          <Wordmark className="text-5xl sm:text-7xl" />
        </h1>

        <p className="mt-5 text-base font-bold text-ink-800 sm:text-lg">{EVENT.title}</p>
        <p className="mt-1.5 text-sm leading-relaxed text-ink-600">
          <span className="mark font-bold">{EVENT.dateLabel}</span>
          <br />
          {EVENT.venueName}
        </p>

        {remaining !== null && (
          <p className="font-pixel mt-6 inline-flex items-center gap-2 rounded-md border-2 border-ink-900 bg-white px-4 py-2 shadow-[3px_3px_0_var(--color-ink-900)]">
            {remaining > 0 ? (
              <>
                <span className="text-sm text-ink-600">교류전까지</span>
                <span className="text-2xl text-cobalt-500 tabular">D-{remaining}</span>
              </>
            ) : remaining === 0 ? (
              <span className="text-xl text-brick-500">오늘이에요!</span>
            ) : (
              <span className="text-sm text-ink-500">즐거웠던 {EVENT.name}, 다음에 또 만나요</span>
            )}
          </p>
        )}

        {/*
          첫 화면에서 할 일은 '신청'이다. 아래 참가비 섹션과 같은 버튼을 그대로 올려
          두고(차수·마감 상태도 함께 따라온다), 납입 확인은 한 걸음 뒤로 물린다.
          두 버튼은 피처폰의 [메뉴] · [답장] 한 쌍이라 크기와 그림자를 맞춘다.
        */}
        <div className="mt-8 flex flex-wrap justify-center gap-3">
          <ApplyLink />
          <Link to="/payment" className="btn-secondary">
            참가비 납입 확인
          </Link>
        </div>
      </div>
    </section>
  )
}

/**
 * 초대장 — 포스터의 브라우저 창을 그대로 옮긴 요강.
 *
 * 언제 · 어디서 · 1부 / 2부. 포스터에서 노란 형광펜으로 그은 것을 여기서도 긋는다.
 */
function Invitation() {
  return (
    <Window title={`${EVENT.name} 초대장`} icon={<Envelope className="size-5" />}>
      <div className="grid gap-0 sm:grid-cols-[1.2fr_1fr]">
        <div className="border-b-2 border-ink-900 p-5 sm:border-b-0 sm:border-r-2 sm:p-6">
          <p className="font-pixel text-lg text-ink-900">하이루 칭구들아~</p>
          <p className="mt-2 text-sm leading-relaxed text-ink-700">
            이과대 × 공과대 교류전에 놀러와! 2002년으로 리턴-♡ 그 시절의 추억 속으로
            함께 가지 않을래?
          </p>

          <dl className="mt-5 space-y-3 text-sm">
            <InviteRow label="언제">
              <span className="mark font-bold">{EVENT.dateLabel}</span>
            </InviteRow>
            <InviteRow label="어디서">
              <span className="mark font-bold">{EVENT.venueName}</span>
            </InviteRow>
            <InviteRow label="집합">
              <span className="font-bold text-ink-900">{EVENT.departure.time}</span>
              <span className="block text-xs text-ink-500">{EVENT.departure.note}</span>
            </InviteRow>
          </dl>
        </div>

        <div className="p-5 sm:p-6">
          <p className="font-pixel-small text-xs font-bold text-ink-500">행사 타임라인</p>
          <ol className="mt-3 space-y-3">
            {EVENT.program.map((part, index) => (
              <li
                key={part.label}
                className={`rounded-md border-2 border-ink-900 px-4 py-3 ${
                  index === 0 ? 'bg-cobalt-50' : 'bg-heart-100'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <p className="font-pixel text-base text-ink-900">
                    {index === 0 ? (
                      <Gamepad className="mr-1.5 inline-block h-4 w-auto align-[-2px]" />
                    ) : (
                      <PixelHeart className="heartbeat mr-1.5 inline-block size-4 align-[-2px]" />
                    )}
                    {part.label}
                  </p>
                  <span className="font-pixel-small shrink-0 text-xs text-ink-600 tabular">
                    {part.time}
                  </span>
                </div>
                <p className="mt-1 text-xs leading-relaxed text-ink-600">{part.note}</p>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </Window>
  )
}

function InviteRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-3">
      <dt className="font-pixel-small w-14 shrink-0 pt-0.5 text-xs font-bold text-ink-500">
        {label}
      </dt>
      <dd className="min-w-0 leading-relaxed text-ink-800">{children}</dd>
    </div>
  )
}

/**
 * 인스타그램에 올라간 카드 뉴스. 왼쪽에서 오른쪽으로 넘겨 본다.
 *
 * 폰에서는 한 장씩 스냅되고, 넓은 화면에서는 몇 장이 나란히 보인다.
 * 그림 파일은 `public/poster/` 에 있고 목록은 data/event.ts 의 POSTER_CARDS 다.
 */
function PosterGallery() {
  return (
    <section>
      <div className="mb-3 flex items-center gap-2">
        <Envelope className="size-6" />
        <h2 className="font-pixel text-lg text-ink-900">[초대장]이 도착하였습니다.</h2>
      </div>
      <ul className="-mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-3 [scrollbar-width:thin]">
        {POSTER_CARDS.map((card) => (
          <li
            key={card.src}
            className="w-[82%] shrink-0 snap-center sm:w-[46%] lg:w-[31%]"
          >
            <img
              src={card.src}
              alt={card.alt}
              loading="lazy"
              width={1200}
              height={1200}
              className="card block w-full"
            />
          </li>
        ))}
      </ul>
    </section>
  )
}

/** 브라우저 창 모양의 카드. 제목줄에 동그라미 셋과 제목이 붙는다. */
function Window({
  title,
  icon,
  children,
}: {
  title: string
  icon?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="card overflow-hidden">
      <div className="window-bar">
        <span className="window-dots">
          <span />
          <span />
          <span />
        </span>
        <span className="font-pixel flex min-w-0 flex-1 items-center justify-center gap-2 truncate text-base">
          {icon}
          &lt;&lt; {title} &gt;&gt;
        </span>
      </div>
      {children}
    </section>
  )
}

function ListCard({ title, items, dot }: { title: string; items: readonly string[]; dot: string }) {
  return (
    <div className="card p-6">
      <h2 className="font-pixel text-lg text-ink-900">{title}</h2>
      <ul className="mt-4 space-y-2.5">
        {items.map((item) => (
          <li key={item} className="flex gap-2.5 text-sm leading-relaxed text-ink-700">
            <span className={`mt-2 size-1.5 shrink-0 ${dot}`} />
            {item}
          </li>
        ))}
      </ul>
    </div>
  )
}

function FeeSection() {
  const [copied, setCopied] = useState(false)

  // 은행 앱은 '은행명 계좌번호' 를 붙여 넣으면 은행까지 함께 알아본다.
  // 번호만 주면 은행을 손으로 다시 고르게 되고, 하이픈이 남아 있으면 그것대로 걸린다.
  const accountText = `${EVENT.account.bank} ${EVENT.account.number.replace(/-/g, '')}`

  const copyAccount = async () => {
    try {
      await navigator.clipboard.writeText(accountText)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  return (
    <Window title="참가비 · 신청">
      <div className="relative overflow-hidden p-5 sm:p-7">
        <PixelStar className="pointer-events-none absolute -right-4 -top-4 size-24 opacity-15" />

        <div className="relative grid gap-3 sm:grid-cols-2">
          <div className="rounded-md border-2 border-ink-900 bg-cobalt-50 p-5 shadow-[3px_3px_0_var(--color-ink-900)]">
            <p className="font-pixel-small text-sm font-bold text-cobalt-600">총학생회비 납부자</p>
            <p className="font-pixel mt-2 text-3xl text-ink-900 tabular">
              {formatWon(EVENT.fees.councilMember)}
            </p>
          </div>
          <div className="rounded-md border-2 border-ink-900 bg-sand-50 p-5 shadow-[3px_3px_0_var(--color-ink-900)]">
            <p className="font-pixel-small text-sm font-bold text-ink-600">총학생회비 미납부자</p>
            <p className="font-pixel mt-2 text-3xl text-ink-900 tabular">
              {formatWon(EVENT.fees.nonMember)}
            </p>
          </div>
        </div>

        {/*
          솔로파티비는 위 두 칸과 **나란히 두지 않는다.** 나란히 두면 셋 중 하나를
          고르는 것처럼 읽히는데, 실제로는 위 금액 **위에 얹히는** 금액이다.
          걷는 시점도 다르다 — 본 행사비는 지금 이 계좌로, 솔로파티비는 나중에
          별도 안내로 받는다. 말해 두지 않으면 "얼마를 보내야 하냐"는 문의가 그대로 온다.
        */}
        <div className="relative mt-4 rounded-md border-2 border-ink-900 bg-heart-100 p-5">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <p className="font-pixel-small text-sm font-bold text-heart-500">
              <PixelHeart className="heartbeat mr-1 inline-block size-4 align-[-2px]" />+{' '}
              {EVENT.afterparty.label} 참가 시
            </p>
            <p className="font-pixel text-2xl text-ink-900 tabular">
              {formatWon(EVENT.fees.afterparty)}
            </p>
            <p className="text-xs font-semibold text-ink-500">총학생회비 납부 여부와 무관</p>
          </div>
          <p className="mt-2 text-sm leading-relaxed text-ink-700 break-keep">{EVENT.afterparty.note}</p>
        </div>

        {/* 금액 다음, 계좌 앞. 순서가 곧 할 일의 순서다. */}
        <div className="relative mt-4 rounded-md border-2 border-ink-900 bg-gold-300 p-5 sm:flex sm:items-center sm:justify-between sm:gap-5">
          <div className="min-w-0">
            <p className="font-pixel text-lg text-ink-900">먼저 신청서를 작성해 주세요</p>
            <p className="mt-1 text-sm leading-relaxed text-ink-700">
              선착순이에요. 신청서를 낸 뒤 아래 계좌로 참가비를 입금하면 끝!
            </p>
          </div>
          <ApplyLink className="btn-primary mt-4 w-full shrink-0 px-7 py-3.5 text-base sm:mt-0 sm:w-auto" />
        </div>

        <div className="relative mt-4 rounded-md border-2 border-ink-900 bg-white p-5">
          <p className="font-pixel-small text-xs font-bold text-ink-500">입금 계좌</p>
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2">
            <span className="font-pixel text-lg text-ink-900 tabular">
              {EVENT.account.bank} {EVENT.account.number}
            </span>
            <span className="text-sm font-semibold text-ink-600">{EVENT.account.holder}</span>
            <button type="button" onClick={copyAccount} className="btn-ghost px-3.5 py-1.5 text-xs">
              {copied ? '복사됐어요' : '계좌번호 복사'}
            </button>
          </div>

          <div className="mt-4 rounded-md border-2 border-ink-900 bg-flame-100 px-4 py-3">
            <p className="font-pixel-small text-sm font-bold text-flame-600">입금자명은 반드시 이렇게</p>
            <p className="mt-1 text-sm font-semibold text-ink-900">{EVENT.account.depositNameRule}</p>
            <p className="mt-2 text-xs leading-relaxed text-ink-600">
              입금자명이 다르면 자동 확인이 되지 않아 직접 대조해야 해요. 가족 명의로 입금하는
              경우에도 입금자명은 규칙대로 적어 주세요.
            </p>
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t-2 border-dashed border-ink-300 pt-4">
            <p className="text-xs leading-relaxed text-ink-600">
              입금을 마치셨나요? 반영까지는 시간이 조금 걸릴 수 있어요.
            </p>
            <Link to="/payment" className="btn-ghost shrink-0 px-4 py-2 text-xs">
              내 납입 확인
            </Link>
          </div>
        </div>

        <ApplySchedule className="relative mt-4" />
      </div>
    </Window>
  )
}
