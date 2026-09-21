/**
 * 행사 기본 정보.
 *
 * ⚠️ 확정되지 않은 값은 TODO 로 표시해 두었다. **이 파일만 고치면 사이트 전체에
 *    반영된다** — 홈 · 타임테이블 · 납입 확인 · 관리자 헤더가 모두 여기를 읽는다.
 *
 * 참가비만은 예외다. 화면에 적는 숫자는 여기 있지만, **실제로 얼마를 청구할지는
 * 백엔드가 정한다**(BackEnd/.env 의 FEE_*). 두 곳을 반드시 같은 값으로 맞춘다.
 */

/**
 * 문의 창구.
 *
 * 개인 전화번호 대신 학생회 상시 채널로 안내한다.
 * 담당자가 바뀌어도 고칠 필요가 없고, 개인 번호가 공개되지도 않는다.
 */
export interface ContactChannel {
  kind: 'kakao' | 'instagram'
  label: string
  handle: string
  url: string
}

/**
 * 신청 차수.
 *
 * 배열에 적은 순서대로 진행되며, startsAt ~ endsAt 사이에 있는 차수만 신청을 받는다.
 * 지금 열린 차수를 고르는 일은 lib/apply.ts 가 맡는다.
 */
export interface ApplyPhase {
  key: string
  /** 화면에 그대로 노출되는 차수 이름 */
  label: string
  /** 이 차수의 신청 시작 시각 (한국 시간) */
  startsAt: string
  /** 이 차수의 마감 시각 (한국 시간). 이 시각까지 아래 폼으로 받는다. */
  endsAt: string
  /** 차수별 구글 폼 링크. 비워 두면 신청 버튼이 '준비 중'으로 잠긴다. */
  formUrl: string
}

export const EVENT = {
  /** 포스터의 큰 글자. 워드마크는 name + edition 을 픽셀 글꼴로 세운다 ('이공공이 2002'). */
  name: '이공공이',
  /** 포스터 말풍선 문구 */
  tagline: '교류전에서는 피터지게🔥, 솔로파티에서는 달달하게💕',
  title: '이과대 × 공과대 교류전',
  organization: '제7대 이과대학 학생회 [E:ON] × 제4대 공과대학 학생회 [여정]',
  /** 워드마크의 노란 숫자. 행사 컨셉(2002년으로 리턴)이라 연도가 아니다. */
  edition: '2002',

  // 당일 행사라 시작과 끝이 같은 날이다. 집합 14:30 · 2부 종료 22:00.
  startsAt: '2026-10-24T14:30:00+09:00',
  endsAt: '2026-10-24T22:00:00+09:00',
  dateLabel: '2026년 10월 24일 (토)',

  // 장소 안내 페이지(지도·길찾기)는 이번 행사에 없다 — 한 곳에서 당일에 끝나
  // 도면과 길찾기가 쓰이지 않는다. 홈에 한 줄로만 적는다.
  venueName: '컨퍼런스홀 (K336)',
  venueAddress: '',
  venueMapUrl: '',

  departure: {
    place: '컨퍼런스홀 (K336)',
    time: '10월 24일(토) 14시 30분',
    note: '집합 시간에 맞춰 입구 QR 로 출석 체크인을 받습니다.',
  },

  /**
   * 홈 초대장의 타임라인. 세부 순서는 타임테이블(data/timetable.ts)이 맡고,
   * 여기는 포스터에 적힌 큰 틀만 둔다.
   */
  program: [
    {
      label: '1부 교류전',
      time: '14:30 ~ 18:30',
      note: '2002년대 배경 야유회 · 무한상사. 이과대와 공과대가 만나는 본 행사.',
    },
    {
      label: '2부 솔로파티',
      time: '18:30 ~ 22:00',
      note: '교류전 참여 인원 중 50명. 참가비는 별도 안내로 따로 받습니다.',
    },
  ],

  /** 선착순 정원. 1부 교류전 100명 · 2부 솔로파티 50명 (교류전 참여자 중). */
  capacity: 100,
  afterpartyCapacity: 50,

  /**
   * 참가비는 두 겹이다.
   *
   * 본 행사비가 아래에 깔리고(총학생회비 납부 여부로 갈린다), **뒤풀이에 가는
   * 사람만** 그 위에 뒤풀이비가 얹힌다. 뒤풀이비는 별도 안내로 나중에 걷으므로
   * 아직 안 낸 것이 본 행사의 '미납'이 되지 않는다.
   *
   * ⚠️ BackEnd/.env 의 FEE_COUNCIL_MEMBER · FEE_NON_MEMBER · FEE_AFTERPARTY 와
   *    같은 값이어야 한다. 여기는 화면에 적는 숫자일 뿐이다.
   */
  fees: {
    councilMember: 5_000,
    nonMember: 7_000,
    afterparty: 10_000,
  },

  /**
   * 2부 솔로파티 — 코드에서는 'afterparty' 로 부른다.
   * 참가자에게 보이는 이름은 여기 label 하나로 정한다. 관리자 화면은 '뒤풀이'라고
   * 부르는데, 운영진 사이의 말이라 참가자 화면과 달라도 상관없다.
   */
  afterparty: {
    label: '2부 솔로파티',
    note: '솔로파티 참가비는 별도 안내를 통해 따로 납입합니다. 본 행사 참가비와 함께 보내 주셨다면 다시 내지 않으셔도 됩니다.',
  },

  account: {
    // TODO: 실제 계좌로 교체
    bank: '카카오뱅크',
    number: '3333-35-9105913',
    holder: '(최원서)',
    /** 신청 폼의 안내와 반드시 같은 문구를 유지할 것 (매칭 규칙의 근거) */
    depositNameRule: '성명 + 전화번호 뒷자리 (예: 김공대0711)',
  },

  applyPhases: [
    {
      key: 'main',
      label: '선착순',
      startsAt: '2026-09-22T00:00:00+09:00',
      endsAt: '2026-09-25T17:59:59+09:00',
      // TODO: 구글 폼 링크로 교체. 비워 두면 신청 버튼이 '준비 중'으로 잠긴다.
      formUrl: 'https://forms.gle/mn6hesfnBZpVnpBx5',
    },
  ] as ApplyPhase[],

  contacts: [
    {
      kind: 'instagram',
      label: '이과대학 학생회',
      handle: '@cuk_ns',
      url: 'https://www.instagram.com/cuk_ns',
    },
    {
      kind: 'instagram',
      label: '공과대학 학생회',
      handle: '@cuk.engineering',
      url: 'https://www.instagram.com/cuk.engineering',
    },
  ] as ContactChannel[],

  packingList: [
    '학생증 또는 신분증',
    '2002년 감성 복장 (야유회 · 무한상사 컨셉이면 더 좋아요)',
    '웰컴키트를 담아 갈 가방',
  ],

  notices: [
    '참가비 납입이 확인되어야 최종 참가가 확정됩니다.',
    '입금자명은 반드시 「성명 + 전화번호 뒷자리」 형식으로 보내 주세요. 다르면 자동 확인이 되지 않습니다.',
    '2부 솔로파티는 교류전 참여 인원 중 50명만 받습니다. 참가비는 별도 안내를 통해 납입하며, 본 행사 참가비와 함께 보내신 분은 다시 내지 않으셔도 됩니다.',
    '입금 이후에는 어떠한 사유로도 환불이 불가하오니 신중하게 입금해 주세요.',
    '문의는 이과대 · 공과대 학생회 인스타그램 DM으로 남겨 주세요.',
  ],
} as const

/**
 * 헤더 · 푸터에 걸리는 메뉴.
 *
 * 타임테이블(/schedule) 은 화면을 다 만들어 두었고 주소로 들어가면 열리지만,
 * 요강이 확정될 때까지 메뉴에는 걸지 않는다. 아래 한 줄을 되살리면 공개된다.
 */
export const NAV_LINKS = [
  { to: '/', label: '홈' },
  // { to: '/schedule', label: '타임테이블' },
  { to: '/payment', label: '납입 확인' },
] as const

/**
 * 홈에 거는 카드 뉴스. `public/poster/` 의 그림이고, 순서대로 넘겨 본다.
 * 새 카드가 나오면 파일을 넣고 여기 한 줄을 더한다.
 */
export const POSTER_CARDS = [
  { src: '/poster/phone.webp', alt: '나랑 이공대 교류전 갈 사람? 그때 그 시절로' },
  { src: '/poster/card-1.webp', alt: '초대장 — 2026년 10월 24일 토요일, 컨퍼런스홀(K336)' },
  { src: '/poster/card-2.webp', alt: '본 행사 컨셉 — 2002년대 배경 야유회, 무한상사. 타임라인' },
  { src: '/poster/card-3.webp', alt: '참가자 자격과 참가비' },
  { src: '/poster/card-4.webp', alt: '신청 방법 — 9월 21일부터 25일까지 선착순' },
  { src: '/poster/card-5.webp', alt: '웰컴키트가 준비되어 있다고? 문의사항' },
] as const
