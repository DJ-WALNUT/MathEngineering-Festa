/**
 * 내 업무 — 스태프 업무 분장.
 *
 * **준비 중이다.** 이번 행사는 스태프 개인별 일정 양식이 통째로 바뀐다. 양식을
 * 받기 전에 예전 표를 그대로 띄우면 실제 운영과 어긋난 시각이 화면에 서 있게 되고,
 * 그것을 보고 움직인 사람이 생긴다. 그래서 **빈 화면 대신 '아직 없다'고 말한다.**
 *
 * 양식을 받으면 되살릴 자리는 두 곳이다.
 *
 *   1. `scripts/build-staff-duties.py` 로 엑셀 → `src/data/staffDuties.ts` 생성
 *   2. 이 파일을 그 데이터를 읽는 화면으로 교체
 *      (로그인한 이름으로 자기 줄만 남기고, 지금 시각의 순서를 맨 위에 세운다)
 *
 * 그때까지 이 탭은 누구에게나 열려 있다(AdminPage 의 ALWAYS_TABS). 국원이 관리자
 * 화면에 들어오는 이유가 대개 이것이라, 탭 자체를 숨기면 '내 것이 어디 갔나'가 된다.
 */

interface Props {
  actor: string
  username: string
}

export default function DutyPanel({ actor }: Props) {
  return (
    <section className="card p-8 text-center">
      <p className="text-2xl" aria-hidden>
        🗓️
      </p>
      <h2 className="mt-3 text-lg font-black text-ink-900">업무 분장표는 준비 중입니다</h2>
      <p className="mt-2 text-sm leading-relaxed text-ink-500 break-keep">
        {actor} 님의 개인 일정은 요강이 확정되면 이 자리에 올라옵니다.
        <br />
        올라오기 전까지는 학생회 공지 채널의 안내를 따라 주세요.
      </p>
    </section>
  )
}
