/**
 * '이공공이 2002' 포스터의 장식 요소들.
 *
 * 픽셀 하트 · 픽셀 별 · 게임패드 · 봉투 · 반짝임 · ON AIR 표시.
 * 전부 인라인 SVG 라 외부 요청 없이 어디서든 크기만 바꿔 쓸 수 있다.
 *
 * **픽셀 그림은 격자 위의 네모로만 그린다.** `shape-rendering="crispEdges"` 를 주어
 * 브라우저가 가장자리를 뭉개지 않게 하고, 크기는 격자의 정수배가 아니어도 된다 —
 * 어차피 SVG 라 계단이 그대로 커질 뿐 흐려지지 않는다.
 *
 * 순수 장식이므로 aria-hidden 을 기본값으로 둔다. 행사 이름(Wordmark)만 예외다.
 */

import type { CSSProperties } from 'react'

import { EVENT } from '../data/event'

interface DecorProps {
  className?: string
  style?: CSSProperties
}

/**
 * 행사 이름 — 포스터의 '이공공이 2002'.
 *
 * 지난 행사는 포스터의 글자를 그림으로 잘라 썼지만, 이번 포스터의 글자는 픽셀
 * 글꼴이라 **웹폰트로 그대로 다시 세울 수 있다.** 흰 글자에 검은 픽셀 테두리,
 * 노란 '2002' — 포스터와 같은 구성이다. 그림이 아니라 글자라서 검색되고,
 * 크기를 바꿔도 깨지지 않으며, 파일을 갈아끼울 일이 없다.
 *
 * 테두리는 text-shadow 를 여덟 방향으로 겹쳐 만든다. `-webkit-text-stroke` 는
 * 글자 안쪽까지 파고들어 픽셀 글꼴의 가는 획을 먹어 버린다.
 */
export function Wordmark({ className, compact = false }: { className?: string; compact?: boolean }) {
  return (
    <span
      className={`font-pixel inline-flex flex-wrap items-baseline justify-center gap-x-[0.3em] leading-none ${className ?? ''}`}
      aria-label={`${EVENT.name} ${EVENT.edition}`}
    >
      <span className="wordmark-outline text-white">{EVENT.name}</span>
      {!compact && (
        <span className="wordmark-outline text-gold-400">{EVENT.edition}</span>
      )}
    </span>
  )
}

/** 픽셀 격자를 SVG 네모로 편다. 문자열 한 줄이 한 행이고, 글자가 색이다. */
function pixels(rows: string[], palette: Record<string, string>) {
  const cells: { x: number; y: number; fill: string }[] = []
  rows.forEach((row, y) => {
    Array.from(row).forEach((char, x) => {
      const fill = palette[char]
      if (fill) cells.push({ x, y, fill })
    })
  })
  return cells
}

function PixelArt({
  rows,
  palette,
  className,
  style,
  title,
}: DecorProps & { rows: string[]; palette: Record<string, string>; title?: string }) {
  const width = Math.max(...rows.map((row) => Array.from(row).length))
  const height = rows.length
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      style={style}
      shapeRendering="crispEdges"
      aria-hidden={title ? undefined : true}
      role={title ? 'img' : undefined}
    >
      {title && <title>{title}</title>}
      {pixels(rows, palette).map((cell) => (
        <rect key={`${cell.x}-${cell.y}`} x={cell.x} y={cell.y} width={1} height={1} fill={cell.fill} />
      ))}
    </svg>
  )
}

const INK = '#15110d'

/** 포스터 오른쪽의 빨간 픽셀 하트. 솔로파티(2부)의 표식이기도 하다. */
export function PixelHeart({ className, style }: DecorProps) {
  return (
    <PixelArt
      className={className}
      style={style}
      rows={[
        '..kkk...kkk..',
        '.krrrk.krrrk.',
        'krwrrrkrrrrrk',
        'krrrrrrrrrrrk',
        'krrrrrrrrrrrk',
        '.krrrrrrrrrk.',
        '..krrrrrrrk..',
        '...krrrrrk...',
        '....krrrk....',
        '.....krk.....',
        '......k......',
      ]}
      palette={{ k: INK, r: '#e8304f', w: '#ff9aa8' }}
    />
  )
}

/** 노란 픽셀 별 — 포스터 제목 옆 */
export function PixelStar({ className, style }: DecorProps) {
  return (
    <PixelArt
      className={className}
      style={style}
      rows={[
        '.....k.....',
        '....kyk....',
        '....kyk....',
        'kkkkkyykkkk',
        '.kyyyyyyyk.',
        '..kyyyyyk..',
        '...kyyyk...',
        '..kyykyyk..',
        '.kyk...kyk.',
        'kk.......kk',
      ]}
      palette={{ k: INK, y: '#f5b719' }}
    />
  )
}

/** 게임패드. 포스터 오른쪽 아래의 흰 컨트롤러 — 색 버튼 넷이 슈퍼패미컴이다. */
export function Gamepad({ className, style }: DecorProps) {
  return (
    <PixelArt
      className={className}
      style={style}
      rows={[
        '..kkkkkkkkkkkkkkkkkk..',
        '.kwwwwwwwwwwwwwwwwwwk.',
        'kwwwkwwwwwwwwwwwwwwwwk',
        'kwwwkwwwwwwwwwwwgwwwwk',
        'kwkkkkkwwwwwwwwbwwrwwk',
        'kwwwkwwwwwkkwwwwwywwwk',
        'kwwwkwwwwwkkwwwwwwwwwk',
        'kwwwwwwwwwwwwwwwwwwwwk',
        '.kwwwwwwwwwwwwwwwwwwk.',
        '..kkkkkkkkkkkkkkkkkk..',
      ]}
      palette={{ k: INK, w: '#ffffff', g: '#3aa655', b: '#2b4fd1', r: '#d84a38', y: '#f5b719' }}
    />
  )
}

/** 노란 봉투 — '[초대장]이 도착하였습니다.' */
export function Envelope({ className, style }: DecorProps) {
  return (
    <PixelArt
      className={className}
      style={style}
      rows={[
        'kkkkkkkkkkkkkk',
        'kyyyyyyyyyyyyk',
        'kkyyyyyyyyyykk',
        'kykyyyyyyyykyk',
        'kyykyyyyyykyyk',
        'kyyykyyyykyyyk',
        'kyykyykkyykyyk',
        'kykyyyyyyyykyk',
        'kyyyyyyyyyyyyk',
        'kkkkkkkkkkkkkk',
      ]}
      palette={{ k: INK, y: '#f5b719' }}
    />
  )
}

/** 네 갈래 반짝임 — 포스터 바탕에 흩어진 검은 별 */
export function Sparkle({ className, style }: DecorProps) {
  return (
    <PixelArt
      className={className}
      style={style}
      rows={['...k...', '...k...', '..kkk..', 'kkkkkkk', '..kkk..', '...k...', '...k...']}
      palette={{ k: 'currentColor' }}
    />
  )
}

/** 포스터 왼쪽 위의 'ON AIR' 표시. 접수 중일 때 켠다. */
export function OnAir({ className, label = 'ON AIR' }: { className?: string; label?: string }) {
  return (
    <span
      className={`font-pixel-small inline-flex items-center gap-1.5 rounded-sm border-2 border-ink-900 bg-white px-2 py-0.5 text-xs font-bold text-brick-500 ${className ?? ''}`}
      aria-hidden
    >
      <span className="blink block size-2 rounded-full bg-brick-500" />
      {label}
    </span>
  )
}

/** 히어로에 흩뿌리는 별 · 반짝임 */
export function PixelScatter() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
      {/* 가장자리에만 둔다. 가운데 글자·버튼 위에 얹히면 폰에서 D-day 상자와 겹친다. */}
      <PixelStar className="twinkle absolute -left-1 top-[46%] size-7 opacity-80 sm:left-[3%] sm:size-9" />
      <Sparkle className="twinkle absolute left-[7%] top-[88%] size-3 text-ink-900 [animation-delay:0.6s]" />
      <Sparkle className="twinkle absolute right-[6%] top-[42%] size-4 text-ink-900 [animation-delay:1.1s]" />
      <PixelStar className="twinkle absolute -right-1 top-[86%] size-5 opacity-80 [animation-delay:0.3s] sm:right-[3%] sm:size-6" />
    </div>
  )
}

export function KakaoIcon({ className }: DecorProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden>
      <path d="M12 3C6.5 3 2 6.6 2 11c0 2.8 1.8 5.2 4.6 6.6L5.5 21.5l4.6-3c.6.1 1.2.1 1.9.1 5.5 0 10-3.6 10-8S17.5 3 12 3z" />
    </svg>
  )
}

export function MapPinIcon({ className }: DecorProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth={2.2} aria-hidden>
      <path d="M12 21s-6-5.4-6-11a6 6 0 1 1 12 0c0 5.6-6 11-6 11z" strokeLinejoin="round" />
      <circle cx="12" cy="10" r="2.3" />
    </svg>
  )
}

export function ClockIcon({ className }: DecorProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth={2.2} aria-hidden>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function InstagramIcon({ className }: DecorProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
      <rect x="3" y="3" width="18" height="18" rx="5" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="17.5" cy="6.5" r="1.2" fill="currentColor" stroke="none" />
    </svg>
  )
}
