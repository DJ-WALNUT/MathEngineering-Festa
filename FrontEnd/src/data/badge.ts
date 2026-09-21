/**
 * 명찰 서식 — **디자인 원본(`명찰 최종본.psd`)에서 그대로 옮겨 온 값.**
 *
 * 좌표와 크기는 전부 **PSD 픽셀**이다. 아트보드 한 장이 1240 × 1754 px, 300dpi 이므로
 * 실물은 A6(105 × 148.5mm)이고 A4 한 장에 정확히 네 장이 떨어진다. 화면과 인쇄는
 * 이 캔버스를 그대로 담은 SVG 를 mm 크기로 늘려 그린다 — 그래서 어떤 배율로 뽑아도
 * 글자가 시안에서 밀리지 않는다.
 *
 * 배경은 `public/badge/` 의 PNG 세 장이다. PSD 병합본에서 **사람마다 달라지는 것만
 * 지우고** 구운 것이라, 로고 · STAFF/GUEST 띠 · 일정표처럼 효과가 잔뜩 걸린 것들은
 * 시안과 픽셀 단위로 같다. 지운 자리에 이 파일이 적어 둔 좌표대로 글자와 QR 을 얹는다.
 *
 * 사람마다 달라지는 것은 앞면 셋뿐이다 — 학과 · 이름 · 조. 그리고 참가자 앞면
 * 오른쪽 아래의 개인 QR(외출 태그). **스태프 앞면에는 QR 이 없다**(시안대로).
 * 뒷면은 스태프 · 참가자가 같고, QR 세 개도 모두에게 같은 고정 주소다.
 *
 * 아직 없는 것 (에디터가 맡을 몫)
 *   · 요소를 끌어 놓아 위치 · 크기 · 정렬을 잡는 화면
 *   · 배경과 글꼴 업로드 (지금은 public/ 에 두고 경로를 적는다)
 */

/**
 * 이 서식이 **이번 행사의 시안과 맞는가.**
 *
 * 지금은 `false` 다 — 아래 좌표 · 글꼴 · 배경 PNG 는 모두 지난 행사(공들이)의
 * 시안에서 옮겨 온 것이고, 이번 행사는 디자인과 글꼴이 통째로 바뀐다.
 *
 * false 인 동안 관리자 > 명찰 탭은 '준비 중'을 띄우고 인쇄를 막는다. **빈 화면이
 * 아니라 막는 것**이 중요하다 — 그리는 코드는 멀쩡해서 누르면 옛 디자인이 150장
 * 그대로 나오고, 그것이 인쇄소로 넘어가면 되돌릴 수 없다.
 *
 * 새 시안을 받으면 할 일은 세 가지다.
 *
 *   1. `public/badge/` 의 배경 PNG 세 장을 새 시안에서 구운 것으로 교체
 *      (`scripts/build-badge-background.py` 가 PSD 에서 만든다)
 *   2. `public/fonts/` 에 새 글꼴을 넣고 아래 BADGE_FONTS 의 family · src 를 교체
 *   3. 아래 좌표를 새 PSD 의 값으로 맞춘 뒤 이 값을 true 로
 *
 * 마지막에 **한 장만 시험 인쇄해** 케이스에 넣어 보고 QR 이 폰으로 읽히는지 본다.
 */
export const BADGE_READY = false

/** 디자인 캔버스. 아래 좌표는 전부 이 안의 픽셀이다. */
export const BADGE_CANVAS = { width: 1240, height: 1754, dpi: 300 } as const

/** PSD 픽셀 → mm (300dpi) */
export const pxToMm = (px: number): number => (px * 25.4) / BADGE_CANVAS.dpi

export interface BadgeFont {
  /** CSS font-family 이름 */
  family: string
  /** `public/fonts/…` 에 넣고 `/fonts/…` 로 적는다. null 이면 시스템 글꼴로 그린다. */
  src: string | null
  weight: number
}

/** 한 줄짜리 글자. PSD 의 기준점(가운데 x · 베이스라인 y)을 그대로 쓴다. */
export interface BadgeText {
  /** 가운데 정렬 기준 x */
  x: number
  /** 베이스라인 y */
  baseline: number
  /** 글자 크기 (px) */
  size: number
  /** 자간. PSD Tracking 값 그대로이고 단위는 1/1000 em 이다. */
  tracking: number
  font: 'display' | 'body'
  /** 이보다 넓어지면 이 폭에 맞춰 눌러 그린다. 긴 이름 · 긴 학과명 때문에 필요하다. */
  maxWidth: number
}

export interface BadgeQr {
  key: string
  /** QR 받침(하늘색 사각형) 왼쪽 위 */
  x: number
  y: number
  /** 받침 한 변 */
  size: number
  /** 받침 안쪽으로 이만큼 띄워 QR 을 그린다. 이 여백이 조용한 구역의 일부가 된다. */
  inset: number
  /** QR 그림 안에 넣을 여백 (모듈 수). 0 이면 받침과 흰 칸이 그 몫을 대신한다. */
  margin: number
  /**
   * 담을 주소.
   *   · `fixed`    — 모두에게 같다. QR 도 한 번만 만든다.
   *   · `personal` — 사람마다 다른 개인 카드(`/p/<token>`). 외출 태그의 열쇠다.
   */
  kind: 'fixed' | 'personal'
  url?: string
  /** 오류정정 등급. 고정 주소는 작게 들어가므로 L 로 모듈을 키운다. */
  ecc: 'L' | 'M' | 'Q' | 'H'
}

export interface BadgeLayout {
  /**
   * QR 에 쓸 사이트 주소.
   *
   * **비워 두지 않는다.** 여기를 null 로 두면 인쇄한 브라우저의 주소(미리보기 도메인 ·
   * localhost)가 그대로 150장에 박힌다. 배포 도메인이 바뀌면 여기를 고친다.
   */
  siteOrigin: string
  /** 명찰 한 장 (mm). 캔버스 그대로면 A6. */
  card: { widthMm: number; heightMm: number }
  /**
   * 인쇄 용지.
   *
   * **한 페이지에 한 장씩**, 용지가 곧 명찰 크기다. A4 에 넷씩 모아 두면 재단선을
   * 맞춰 자르는 일이 생기는데, 페이지를 명찰 크기로 잡으면 인쇄기가 알아서 낱장으로
   * 떨궈 준다.
   *
   * `safeMarginMm` 은 **집이나 사무실 프린터로 뽑을 때만** 쓴다. 그런 프린터는 종이
   * 가장자리 4~5mm 를 못 찍어 명찰 바깥쪽이 잘려 나가므로, 이 값을 주면 그만큼
   * 여백을 두고 축소해 뽑는다. 인쇄소에 맡길 때는 0 이 맞다.
   */
  sheet: { safeMarginMm: number }
  fonts: { display: BadgeFont; body: BadgeFont }
  front: {
    background: { staff: string; guest: string }
    /** 이름 · 학과 · 조 글자색 (시안 실측) */
    color: string
    department: BadgeText
    name: BadgeText
    group: BadgeText
    /** 개인 QR. 참가자 앞면에만 있다. */
    qr: BadgeQr
    /** 스태프 앞면에도 개인 QR 을 넣을지. 시안에는 없다. */
    qrOnStaff: boolean
  }
  back: {
    background: string
    qrs: BadgeQr[]
  }
}

export const BADGE_LAYOUT: BadgeLayout = {
  siteOrigin: 'https://mt.cukeng.kr',

  card: { widthMm: 105, heightMm: 148.5 },
  sheet: { safeMarginMm: 0 },

  fonts: {
    display: { family: 'GmarketSansBold', src: '/fonts/GmarketSansBold.woff2', weight: 700 },
    body: { family: 'GmarketSansMedium', src: '/fonts/GmarketSansMedium.woff2', weight: 500 },
  },

  front: {
    background: { staff: '/badge/front-staff.png', guest: '/badge/front-guest.png' },
    color: '#414F5C',

    department: { x: 616.93, baseline: 670.49, size: 50, tracking: -20, font: 'body', maxWidth: 900 },
    name: { x: 620.74, baseline: 957.44, size: 250, tracking: -30, font: 'display', maxWidth: 980 },
    group: { x: 616.93, baseline: 1101.49, size: 50, tracking: -20, font: 'body', maxWidth: 400 },

    // 시안의 하늘색 사각형 자리 그대로. 토큰 주소가 31자라 29모듈이 되고, 여백까지
    // 31모듈이 132px 안에 들어가 모듈 하나가 0.36mm — 어두운 복도에서도 잘 읽힌다.
    qr: { key: 'personal', x: 1072, y: 1589, size: 146, inset: 7, margin: 1, kind: 'personal', ecc: 'Q' },
    qrOnStaff: false,
  },

  back: {
    background: '/badge/back.png',
    // 주소는 시안에 박혀 있던 QR 을 읽어 낸 것 그대로다.
    //
    // **더 키울 수 없다.** QR 은 사방에 4모듈치 밝은 여백(조용한 구역)이 있어야 읽히는데,
    // 흰 칸 높이가 84px 뿐이라 그 여백까지 세면 64px 가 상한이다. 여기서 더 키우면
    // 모듈은 커지지만 여백이 깎여 오히려 안 읽힌다 — 칸 밖은 어두운 들판 그림이다.
    // 시안의 60px 에서 64px 로 올리고 오류정정을 L 로 낮춰 모듈을 0.20 → 0.22mm 로 벌었다.
    // 이보다 크게 하려면 주소를 17자 이내로 줄여 25모듈을 21모듈로 떨어뜨려야 한다.
    qrs: [
      { key: 'venue', x: 377, y: 1571, size: 76, inset: 6, margin: 0, kind: 'fixed', ecc: 'L',
        url: 'https://mt.cukeng.kr/venue' },
      { key: 'checkin', x: 685, y: 1571, size: 76, inset: 6, margin: 0, kind: 'fixed', ecc: 'L',
        url: 'https://mt.cukeng.kr/checkin' },
      // 이것만 주소가 길어 29모듈(0.19mm)이다. 대문자로 적으면 QR 이 영숫자 모드로
      // 들어가 25모듈(0.22mm)로 떨어진다 — 주소는 대소문자를 가리지 않으므로 그대로 열린다.
      { key: 'instagram', x: 993, y: 1571, size: 76, inset: 6, margin: 0, kind: 'fixed', ecc: 'L',
        url: 'https://www.instagram.com/cuk.engineering/' },
    ],
  },
}
