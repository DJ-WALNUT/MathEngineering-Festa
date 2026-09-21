/**
 * 타임테이블. 변경이 거의 없으므로 프론트에 하드코딩한다.
 *
 * category 는 배지 색상만 결정한다.
 */

export type SessionCategory = 'move' | 'meal' | 'program' | 'rest' | 'free' | 'notice'

/** 식단표 한 묶음. 식판에 담기는 순서(샐러드 → 메인 → 국·밥 → 반찬)대로 적는다. */
export interface MenuGroup {
  label: string
  items: string[]
}

export interface MealMenu {
  /** 화면에 띄우는 이름. '1일차 석식' 처럼 급식소 표기를 그대로 쓴다. */
  label: string
  groups: MenuGroup[]
}

export interface TimetableSession {
  start: string
  end?: string
  title: string
  place?: string
  description?: string
  category: SessionCategory
  /** 반드시 참석해야 하는 순서 */
  required?: boolean
  /** 식사 순서에만 붙는다. 급식소가 준 식단표를 그대로 옮긴다. */
  menu?: MealMenu
}

export interface TimetableDay {
  id: string
  label: string
  dateLabel: string
  sessions: TimetableSession[]
}

export const CATEGORY_STYLE: Record<SessionCategory, { label: string; className: string }> = {
  move: { label: '이동', className: 'bg-cobalt-100 text-cobalt-600 border-cobalt-300' },
  meal: { label: '식사', className: 'bg-sand-100 text-sand-700 border-sand-300' },
  program: { label: '프로그램', className: 'bg-flame-100 text-flame-600 border-flame-300' },
  rest: { label: '휴식', className: 'bg-heart-400/15 text-heart-500 border-heart-400/40' },
  free: { label: '자유', className: 'bg-ink-400/12 text-ink-600 border-ink-400/35' },
  notice: { label: '공지', className: 'bg-brick-400/12 text-brick-500 border-brick-400/40' },
}

/**
 * 타임테이블 — **아직 비어 있다.**
 *
 * 요강이 확정되면 여기에 순서를 채운다. 비어 있는 동안 /schedule 은 '준비 중'을
 * 띄우고, 메뉴에도 걸리지 않는다(data/event.ts 의 NAV_LINKS). 채운 뒤 그 줄의
 * 주석을 풀면 그대로 공개된다.
 *
 * 채우는 법 — 한 순서가 한 줄이다.
 *
 *     { start: '13:00', end: '14:00', title: '개회식', place: '강당', category: 'program' },
 *
 * `required: true` 를 주면 '필참' 표시가 붙고, 식사에는 `menu` 로 식단표를 달 수 있다.
 * 당일 행사라 날짜 묶음은 하나면 충분하지만, 배열이라 늘릴 수도 있다.
 */
export const TIMETABLE: TimetableDay[] = [
  {
    id: 'day1',
    label: '행사 당일',
    dateLabel: '10월 24일 (토)',
    // 포스터에 적힌 큰 틀만 먼저 넣어 두었다. 세부 순서(무한상사 · 야유회 프로그램)가
    // 확정되면 사이사이에 끼워 넣고, event.ts 의 NAV_LINKS 에서 타임테이블 줄을 되살린다.
    sessions: [
      {
        start: '14:30',
        title: '참여자 집합 · 출석 체크인',
        place: '컨퍼런스홀 (K336)',
        description: '입구 QR 을 찍고 이름 · 학번 · 전화 뒷자리로 체크인합니다. 럭키드로우 번호가 이때 발급돼요.',
        category: 'notice',
        required: true,
      },
      {
        start: '14:30',
        end: '18:30',
        title: '1부 교류전',
        place: '컨퍼런스홀 (K336)',
        description: '2002년대 배경 야유회 · 무한상사. 이과대와 공과대가 만나는 본 행사.',
        category: 'program',
        required: true,
      },
      {
        start: '18:30',
        end: '22:00',
        title: '2부 솔로파티',
        place: '컨퍼런스홀 (K336)',
        description: '교류전 참여 인원 중 50명. 참가비는 별도 안내로 따로 받습니다.',
        category: 'program',
      },
    ],
  },
]
