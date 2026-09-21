/**
 * 명찰 인쇄.
 *
 * 150명분을 손으로 만들 수는 없다. 명단을 그대로 읽어 **한 페이지에 한 장씩** 앞면을
 * 죽 늘어놓고 인쇄용 창을 연다. 용지가 곧 명찰 크기(A6)라 재단선을 맞춰 자를 일이 없다.
 *
 * **그리는 방식** — 명찰 한 장은 `1240 × 1754` 좌표계를 그대로 쓰는 SVG 다. 배경은
 * 디자인 원본(PSD)에서 사람마다 달라지는 것만 지우고 구운 PNG 를 통째로 깔고, 그
 * 위에 시안이 적어 둔 자리(`src/data/badge.ts`)로 글자와 QR 만 얹는다. 좌표가 전부
 * 원본 픽셀이라 A6 로 뽑든 더 작게 뽑든 시안에서 밀리지 않고, 로고나 STAFF 띠처럼
 * 효과가 잔뜩 걸린 것들은 애초에 그리지 않으니 어긋날 일이 없다.
 *
 * 앞면은 스태프 · 참가자가 다르다(띠와 개인 QR). **뒷면은 모두에게 똑같아서 사람 수만큼
 * 찍지 않는다** — 같은 그림이 150번 반복될 뿐이므로 한 장만 따로 뽑아 인쇄소에 준다.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import QRCode from 'qrcode'

import {
  BADGE_CANVAS,
  BADGE_LAYOUT,
  BADGE_READY,
  type BadgeLayout,
  type BadgeQr,
  type BadgeText,
} from '../../data/badge'
import { EVENT } from '../../data/event'
import { adminApi, type RosterEntry } from '../../lib/api'

/** 사람마다 다른 QR 과 모두에게 같은 QR 을 나눠 담는다. */
type QrBundle = { fixed: Record<string, string>; personal: Record<number, string> }

const EMPTY_QR: QrBundle = { fixed: {}, personal: {} }

export default function BadgesPanel({ revision }: { revision: number }) {
  const layout = BADGE_LAYOUT
  const [items, setItems] = useState<RosterEntry[]>([])
  const [qr, setQr] = useState<QrBundle>(EMPTY_QR)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const fontsReady = useBadgeFonts(layout)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const response = await adminApi.roster()
      setItems(response.items)
      setQr(await buildQrCodes(response.items, layout))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '명단을 불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }, [layout])

  useEffect(() => {
    void load()
  }, [load, revision])

  const print = (side: 'front' | 'back') => {
    setBusy(true)
    try {
      const popup = window.open('', '_blank', 'width=900,height=1200')
      if (!popup) {
        alert('팝업이 막혀 있습니다. 이 사이트의 팝업을 허용해 주세요.')
        return
      }
      popup.document.write(printableHtml(items, qr, layout, side))
      popup.document.close()
      popup.focus()
    } finally {
      setBusy(false)
    }
  }

  const staffCount = items.filter((person) => person.isStaff).length

  /*
   * 새 시안을 받기 전에는 인쇄를 막는다.
   *
   * 여기서 중요한 것은 **빈 화면이 아니라 막는 것**이다. 그리는 코드는 멀쩡해서
   * 누르면 지난 행사의 디자인이 그대로 150장 나오고, 그것이 인쇄소로 넘어가면
   * 되돌릴 수 없다. 되살리는 방법은 data/badge.ts 의 BADGE_READY 주석에 적어 두었다.
   */
  if (!BADGE_READY) {
    return (
      <div className="space-y-5">
        <section className="card p-8 text-center">
          <p className="text-2xl" aria-hidden>
            🪪
          </p>
          <h2 className="mt-3 text-lg font-black text-ink-900">명찰은 준비 중입니다</h2>
          <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-ink-500 break-keep">
            이번 행사의 명찰 디자인과 글꼴이 아직 나오지 않았습니다. 인쇄 기능은 그대로
            살아 있지만, 지난 행사의 서식이 그대로 찍혀 나가는 것을 막기 위해 잠가 두었습니다.
            <br />
            시안을 받으면{' '}
            <code className="rounded bg-sand-50 px-1 font-bold">src/data/badge.ts</code> 의
            좌표 · 글꼴 · 배경을 교체하고{' '}
            <code className="rounded bg-sand-50 px-1 font-bold">BADGE_READY</code> 를 켜면
            이 화면이 인쇄 화면으로 돌아옵니다.
          </p>
        </section>

        <section className="card p-5">
          <h2 className="text-sm font-black text-ink-900">지금도 준비할 수 있는 것</h2>
          <p className="mt-1 text-xs leading-relaxed text-ink-500 break-keep">
            참가가 확정된 <strong className="text-ink-700">{items.length}명</strong>
            (스태프 {staffCount}명)에게 개인 QR 주소는 이미 발급되어 있습니다. 디자인이
            나오는 대로 명단을 다시 받을 필요 없이 바로 인쇄할 수 있습니다.
          </p>
          {error && <p className="mt-3 text-sm font-semibold text-brick-500">{error}</p>}
        </section>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <section className="card p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-black text-ink-900">명찰 인쇄</h2>
            <p className="mt-1 text-xs leading-relaxed text-ink-500">
              참가가 확정된 {items.length}명(스태프 {staffCount}명) ·{' '}
              <strong className="text-ink-700">한 페이지에 한 장씩</strong> 여백 없이 냅니다.
            </p>
          </div>
          <div className="flex shrink-0 gap-2">
            <button
              type="button"
              className="btn-secondary px-3 py-2 text-sm"
              disabled={loading || busy || items.length === 0}
              onClick={() => print('back')}
            >
              뒷면 1장
            </button>
            <button
              type="button"
              className="btn-primary px-4 py-2 text-sm"
              disabled={loading || busy || items.length === 0}
              onClick={() => print('front')}
            >
              {loading ? '준비 중…' : `앞면 ${items.length}장 인쇄`}
            </button>
          </div>
        </div>

        {error && <p className="mt-3 text-sm font-semibold text-brick-500">{error}</p>}

        <dl className="mt-4 grid gap-2 text-xs sm:grid-cols-2">
          <Row label="명찰 크기" value={`${layout.card.widthMm} × ${layout.card.heightMm} mm (A6)`} />
          <Row label="글꼴" value={`${layout.fonts.display.family} · ${layout.fonts.body.family}`} />
          <Row label="앞면" value="스태프 · 참가자 따로 (띠와 개인 QR이 다름)" />
          <Row label="QR 주소" value={layout.siteOrigin} />
        </dl>

        <p className="mt-4 rounded-xl bg-flame-100/60 px-4 py-3 text-xs leading-relaxed text-ink-600">
          <strong className="font-black text-flame-600">인쇄 설정</strong> — 용지는{' '}
          <strong className="text-ink-800">A6(105 × 148.5mm)</strong>, 배율은{' '}
          <strong className="text-ink-800">100%(실제 크기)</strong>, 여백은{' '}
          <strong className="text-ink-800">없음</strong>. &lsquo;페이지에 맞춤&rsquo;으로 두면
          A6 가 아닌 크기로 나와 케이스에 안 들어갑니다. 뒷면은 모두에게 똑같아서 사람 수만큼
          찍지 않습니다 — <strong className="text-ink-800">뒷면 1장</strong>으로 한 장만 뽑아
          인쇄소에 맡기세요. 가장자리를 못 찍는 프린터라면{' '}
          <code className="rounded bg-white px-1 font-bold">badge.ts</code> 의{' '}
          <code className="rounded bg-white px-1 font-bold">safeMarginMm</code> 을 5 정도로 주고
          뽑은 뒤 재단하세요.
        </p>
      </section>

      <section className="card p-5">
        <h2 className="text-sm font-black text-ink-900">미리보기</h2>
        <p className="mt-1 text-xs text-ink-500">
          {fontsReady ? '실제 인쇄본과 같은 서식입니다.' : '글꼴을 불러오는 중…'}
        </p>

        {items[0] ? (
          <div className="mt-4 flex flex-wrap gap-4">
            <Preview label="앞면" person={items[0]} qr={qr} layout={layout} side="front" ready={fontsReady} />
            {items.find((person) => person.isStaff !== items[0].isStaff) && (
              <Preview
                label={items[0].isStaff ? '앞면 (참가자)' : '앞면 (스태프)'}
                person={items.find((person) => person.isStaff !== items[0].isStaff)!}
                qr={qr}
                layout={layout}
                side="front"
                ready={fontsReady}
              />
            )}
            <Preview label="뒷면" person={items[0]} qr={qr} layout={layout} side="back" ready={fontsReady} />
          </div>
        ) : (
          <p className="mt-4 rounded-xl bg-sand-50 px-4 py-6 text-center text-sm text-ink-500">
            {loading ? '불러오는 중…' : '참가가 확정된 사람이 없습니다.'}
          </p>
        )}
      </section>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2">
      <dt className="w-20 shrink-0 font-bold text-ink-500">{label}</dt>
      <dd className="min-w-0 break-words font-semibold text-ink-800">{value}</dd>
    </div>
  )
}

/** 화면 미리보기. 인쇄본과 같은 SVG 를 폭만 줄여 그린다. */
function Preview({
  label,
  person,
  qr,
  layout,
  side,
  ready,
}: {
  label: string
  person: RosterEntry
  qr: QrBundle
  layout: BadgeLayout
  side: 'front' | 'back'
  ready: boolean
}) {
  // `ready` 는 본문에서 쓰지 않지만 의존성에 둔다 — 글꼴이 올라온 뒤 다시 그려야
  // 긴 이름을 눌러 그릴 폭이 제대로 잡힌다.
  const svg = useMemo(() => badgeSvg(person, side, qr, layout, 200), [person, side, qr, layout, ready])
  return (
    <figure className="m-0">
      <div
        className="overflow-hidden rounded-xl border-2 border-sand-200 bg-white"
        dangerouslySetInnerHTML={{ __html: svg }}
      />
      <figcaption className="mt-1.5 text-center text-xs font-bold text-ink-500">{label}</figcaption>
    </figure>
  )
}

// ---------------------------------------------------------------------------
// 글꼴
// ---------------------------------------------------------------------------

/**
 * 명찰 글꼴을 이 화면에서도 띄운다.
 *
 * 미리보기 때문만이 아니다. 긴 이름을 폭에 맞춰 눌러 그리려면 **글자가 얼마나 넓은지
 * 재야 하고**, 재려면 이 문서에 글꼴이 올라와 있어야 한다. 인쇄 창은 이 문서가
 * 계산해 준 폭을 그대로 받아 쓴다.
 */
function useBadgeFonts(layout: BadgeLayout): boolean {
  const [ready, setReady] = useState(false)

  useEffect(() => {
    const fonts = [layout.fonts.display, layout.fonts.body].filter((font) => font.src)
    if (fonts.length === 0) {
      setReady(true)
      return
    }

    const style = document.createElement('style')
    style.textContent = fonts.map(fontFace).join('')
    document.head.appendChild(style)

    let alive = true
    void Promise.all(fonts.map((font) => document.fonts.load(`${font.weight} 100px "${font.family}"`)))
      .catch(() => undefined)
      .then(() => {
        if (alive) setReady(true)
      })

    return () => {
      alive = false
      style.remove()
    }
  }, [layout])

  return ready
}

const fontFace = (font: { family: string; src: string | null; weight: number }) =>
  `@font-face{font-family:'${font.family}';src:url('${assetUrl(font.src!)}') format('woff2');` +
  `font-weight:${font.weight};font-style:normal;font-display:block;}`

/**
 * 인쇄 창은 `about:blank` 이라 상대 경로가 통하지 않는다. 배경 · 글꼴은 지금 이
 * 사이트에서 받아야 하므로 **주소를 절대 경로로 바꿔 둔다.**
 * (QR 에 담기는 주소는 이것과 무관하다 — 그쪽은 `layout.siteOrigin` 이다.)
 */
function assetUrl(path: string): string {
  return new URL(path, window.location.origin).href
}

// ---------------------------------------------------------------------------
// QR
// ---------------------------------------------------------------------------

async function buildQrCodes(items: RosterEntry[], layout: BadgeLayout): Promise<QrBundle> {
  const fixed: Record<string, string> = {}
  const personal: Record<number, string> = {}

  for (const spec of layout.back.qrs) {
    // 고정 주소는 모두에게 같다. 150번 만들 이유가 없다.
    if (spec.kind === 'fixed' && spec.url) fixed[spec.key] = await qrDataUrl(spec.url, spec)
  }

  const front = layout.front.qr
  if (front.kind === 'personal') {
    for (const person of items) {
      if (!person.token) continue
      if (person.isStaff && !layout.front.qrOnStaff) continue
      personal[person.id] = await qrDataUrl(`${layout.siteOrigin}/p/${person.token}`, front)
    }
  } else if (front.url) {
    fixed[front.key] = await qrDataUrl(front.url, front)
  }

  return { fixed, personal }
}

/**
 * QR 을 **벡터로** 만든다.
 *
 * 뒷면 QR 은 모듈 하나가 0.2mm 남짓이라, 래스터로 만들어 늘리면 그 경계가 뭉개져
 * 읽히지 않는다. SVG 로 만들면 인쇄기 해상도 그대로 찍힌다.
 */
async function qrDataUrl(text: string, spec: BadgeQr): Promise<string> {
  const svg = await QRCode.toString(text, {
    type: 'svg',
    margin: spec.margin,
    errorCorrectionLevel: spec.ecc,
    color: { dark: '#000000ff', light: '#ffffffff' },
  })
  return `data:image/svg+xml;base64,${btoa(svg)}`
}

// ---------------------------------------------------------------------------
// 명찰 한 장
// ---------------------------------------------------------------------------

function escape(value: string | null | undefined): string {
  return String(value ?? '').replace(/[&<>"]/g, (char) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[char] ?? char,
  )
}

/** 글자 폭을 재는 캔버스 하나를 돌려 쓴다. */
let ruler: CanvasRenderingContext2D | null = null

/**
 * 시안은 세 글자 이름에 맞춰 잡혀 있다. 네 글자 · 다섯 글자가 오면 이름칸을 넘으므로
 * **넘칠 때만** 그 폭에 맞춰 눌러 그린다(`textLength`). 줄이지 않고 두면 글자가
 * 명찰 밖으로 튀어나간다.
 */
function squeeze(text: string, spec: BadgeText, layout: BadgeLayout): string {
  if (!text) return ''
  ruler ??= document.createElement('canvas').getContext('2d')
  if (!ruler) return ''

  const family = layout.fonts[spec.font].family
  const spacing = (spec.size * spec.tracking) / 1000
  ruler.font = `${spec.size}px "${family}"`
  // 자간까지 반영해야 실제 폭이 나온다. 못 다루는 브라우저에서는 손으로 더한다.
  const withSpacing = 'letterSpacing' in ruler
  if (withSpacing) (ruler as unknown as { letterSpacing: string }).letterSpacing = `${spacing}px`
  const width =
    ruler.measureText(text).width + (withSpacing ? 0 : spacing * Math.max(0, text.length - 1))
  if (withSpacing) (ruler as unknown as { letterSpacing: string }).letterSpacing = '0px'

  return width > spec.maxWidth
    ? ` textLength="${spec.maxWidth}" lengthAdjust="spacingAndGlyphs"`
    : ''
}

function textNode(value: string | null | undefined, spec: BadgeText, layout: BadgeLayout): string {
  const text = String(value ?? '').trim()
  if (!text) return ''
  const family = layout.fonts[spec.font].family
  return (
    `<text x="${spec.x}" y="${spec.baseline}" font-family="${family}" font-size="${spec.size}"` +
    ` letter-spacing="${(spec.size * spec.tracking) / 1000}"${squeeze(text, spec, layout)}>` +
    `${escape(text)}</text>`
  )
}

function qrNode(spec: BadgeQr, href: string | undefined): string {
  if (!href) return ''
  const size = spec.size - spec.inset * 2
  return (
    `<image href="${href}" x="${spec.x + spec.inset}" y="${spec.y + spec.inset}"` +
    ` width="${size}" height="${size}" preserveAspectRatio="none" />`
  )
}

/**
 * 명찰 한 장. `widthPx` 를 주면 화면 미리보기 크기로, 안 주면 실제 인쇄 크기(mm)로 낸다.
 */
function badgeSvg(
  person: RosterEntry,
  side: 'front' | 'back',
  qr: QrBundle,
  layout: BadgeLayout,
  widthPx?: number,
): string {
  const { width, height } = BADGE_CANVAS
  const size = widthPx
    ? `width="${widthPx}" height="${(widthPx * height) / width}"`
    : `width="${layout.card.widthMm}mm" height="${layout.card.heightMm}mm"`

  let body: string
  if (side === 'front') {
    const front = layout.front
    const background = person.isStaff ? front.background.staff : front.background.guest
    const showQr = !person.isStaff || front.qrOnStaff
    body =
      `<image href="${assetUrl(background)}" x="0" y="0" width="${width}" height="${height}" />` +
      `<g fill="${front.color}" text-anchor="middle">` +
      textNode(person.department, front.department, layout) +
      textNode(person.name, front.name, layout) +
      textNode(person.groupValue, front.group, layout) +
      `</g>` +
      (showQr ? qrNode(front.qr, qr.personal[person.id]) : '')
  } else {
    body =
      `<image href="${assetUrl(layout.back.background)}" x="0" y="0" width="${width}" height="${height}" />` +
      layout.back.qrs.map((spec) => qrNode(spec, qr.fixed[spec.key])).join('')
  }

  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" ${size}` +
    ` class="badge" shape-rendering="geometricPrecision">${body}</svg>`
  )
}

// ---------------------------------------------------------------------------
// 인쇄용 문서
// ---------------------------------------------------------------------------

/**
 * 인쇄용 문서 한 벌.
 *
 * **한 페이지에 한 장씩** 낸다. 용지를 명찰 크기로 잡아 두면 인쇄기가 알아서 낱장으로
 * 떨궈 주고, 재단선을 맞춰 자를 일이 없다.
 *
 * 뒷면은 여기 섞지 않는다. 뒷면은 **모두에게 똑같아서**, 사람 수만큼 찍어 내면 같은
 * 그림이 150번 반복될 뿐이다. 필요하면 `단면: 'back'` 으로 한 장만 뽑아 인쇄소에 준다.
 */
function printableHtml(
  items: RosterEntry[],
  qr: QrBundle,
  layout: BadgeLayout,
  side: 'front' | 'back',
): string {
  const { widthMm, heightMm } = layout.card
  const safe = layout.sheet.safeMarginMm

  // 가장자리를 못 찍는 프린터를 위한 축소. 0 이면 아무 일도 하지 않는다.
  const scale = safe > 0 ? Math.min((widthMm - safe * 2) / widthMm, (heightMm - safe * 2) / heightMm) : 1
  const shift =
    scale < 1
      ? `transform:translate(${((widthMm * (1 - scale)) / 2).toFixed(3)}mm,` +
        `${((heightMm * (1 - scale)) / 2).toFixed(3)}mm) scale(${scale.toFixed(5)});transform-origin:0 0;`
      : ''

  // 뒷면은 사람과 무관하다. 첫 사람으로 한 장만 그린다.
  const people = side === 'back' ? items.slice(0, 1) : items
  const pages = people
    .map((person) => `<section class="sheet">${badgeSvg(person, side, qr, layout)}</section>`)
    .join('')

  const fonts = [layout.fonts.display, layout.fonts.body].filter((font) => font.src).map(fontFace).join('')
  const title = side === 'back' ? '뒷면 1장' : `앞면 ${people.length}장`

  return `<!doctype html><html lang="ko"><head><meta charset="utf-8" />
<title>${escape(EVENT.name)} 명찰 — ${title}</title>
<style>
  ${fonts}
  @page { size: ${widthMm}mm ${heightMm}mm; margin: 0; }
  * { box-sizing: border-box; }
  body { margin: 0; }
  .sheet {
    width: ${widthMm}mm; height: ${heightMm}mm; overflow: hidden; ${shift}
    page-break-after: always; break-after: page;
  }
  .sheet:last-child { page-break-after: auto; break-after: auto; }
  .badge { display: block; }
  @media screen {
    body { background: #f3f1ec; padding: 8px 0; }
    .sheet { margin: 0 auto 12px; background: #fff; box-shadow: 0 2px 12px rgba(0,0,0,.12); }
  }
</style></head>
<body onload="document.fonts.ready.then(function(){window.print()})">${pages}</body></html>`
}
