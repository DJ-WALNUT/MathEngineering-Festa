/**
 * 럭키드로우 추첨 화면 (`/admin/draw`).
 *
 * 프로젝터에 띄우는 전체 화면이다. **관리자 하위 경로**이고 인증도 관리자와 같은
 * 것을 쓴다(`pages/admin/AdminSession.tsx`) — 주소를 알아냈다고 열리지 않는다.
 * 관리자 헤더·탭을 쓰지 않는 이유는 네비게이션과 표가 함께 보이면 연출이 죽기
 * 때문이고, 별도 화면인 이유는 추첨을 흔히 강당의 다른 기기에서 띄우기 때문이다.
 *
 * ─────────────────────────────────────────────────────────────
 * 연출 — 자릿수를 하나씩 잠그며 후보를 좁힌다
 *
 *   247명  →  1__ 100명  →  13_ 10명  →  137 1명
 *
 * 릴이 멈출 때마다 **화면 아래 번호판에서 탈락한 번호가 실제로 꺼진다.** 자기 번호를
 * 벽에서 찾아 둔 사람은 백의 자리가 잠기는 순간 살았는지 죽었는지 바로 안다.
 * 탈락이 한꺼번에 일어나므로 탄식도 한꺼번에 나온다.
 *
 * **멈추는 건 진행자다.** 릴은 시작하면 계속 돌고, 진행자가 신호를 줘야 선다.
 * 타이머로 알아서 멈추면 "지금이다" 하는 순간을 진행자가 잡을 수 없다.
 *
 *   Enter · Space · → · PageDown   한 번이면 왼쪽부터 차례로 (기본)
 *   A / S / D                      백 / 십 / 일의 자리만 바로
 *
 * 기본을 '한 번에 끝까지'로 둔 이유는 진행자가 대개 마이크를 들고 있기 때문이다.
 * 자리마다 키를 찾아 누르게 하면 정작 관객을 못 본다. 자리를 끊어 보고 싶을 때만
 * A/S/D 로 끼어들면 되고, 그때 예약되어 있던 신호는 이미 선 자리라 그냥 흘러간다.
 *
 * 키는 `event.code` 로 읽으므로 한/영 상태와 무관하다. 무대에서 한글 자판인 채로
 * A 를 눌러 'ㅁ' 이 들어오는 상황이 실제로 생긴다.
 *
 * **결과가 정해진 자리에서는 뜸을 들이지 않는다.** 80명이 체크인했다면 번호는
 * 001~080 이고 백의 자리는 어차피 0 이다. 후보 전원이 같은 숫자를 쓰는 자리는
 * 처음부터 확정으로 띄우고, 실제로 갈리는 자리에만 시간을 쓴다.
 *
 * ─────────────────────────────────────────────────────────────
 * 결과는 연출로 정하지 않는다
 *
 * 번호는 서버가 **뽑는 순간** 고르고 그 자리에서 DB 에 박는다. 이 화면이 하는 일은
 * 이미 정해진 번호를 자릿수별로 드러내는 것뿐이다. 무작위로 릴을 돌려 나온 값을
 * 결과로 삼으면 250명이 체크인한 자리에서 287번이 나온다.
 */

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from 'react'
import { Link } from 'react-router-dom'

import {
  adminApi,
  type DrawPrize,
  type DrawRecord,
  type DrawState,
  type DrawTile,
} from '../lib/api'
import { formatDateTime } from '../lib/format'
import { AdminLogin, SessionChecking, useAdminSession } from './admin/AdminSession'

// --- 연출 타이밍 -----------------------------------------------------------

/** 멈추라는 신호를 받고 실제로 서기까지. 슬롯이 힘없이 서지 않을 만큼은 끌어야 한다. */
const DECEL_MS = 1600
/** 마지막 자리가 선 뒤 당첨자를 띄우기까지의 뜸. */
const REVEAL_DELAY_MS = 700
/** 차례로 멈출 때 한 자리와 다음 자리 사이. 감속(DECEL_MS)이 끝나고 잠깐 서 있는 틈이 남는다. */
const STOP_GAP_MS = 2600
/** 자동 정지를 켰을 때 시작하고 첫 자리가 서기까지. */
const AUTO_FIRST_MS = 2600

/** 띠에 0~9 를 몇 벌 이어 붙일지. 회전 중 위치(최대 10칸) + 감속 2바퀴를 덮어야 한다. */
const STRIP_CELLS = 50
/** 멈출 때 몇 바퀴 더 돌고 설 것인가. */
const DECEL_LOOPS = 2

const DIGITS = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']

/** 자리별 직접 정지 키. 백·십·일 순서로 왼손 홈포지션에 놓았다. */
const POSITION_KEYS = ['KeyA', 'KeyS', 'KeyD']
const NEXT_KEYS = ['Enter', 'NumpadEnter', 'Space', 'ArrowRight', 'PageDown']

const OUT_LABEL: Record<string, string> = {
  not_checked_in: '출석 취소',
  cancelled: '참가 취소',
  staff: '스태프 제외',
  already_won: '이미 당첨',
  not_in_session: '이 자리에 없음',
}

type Phase =
  | { kind: 'idle' }
  | { kind: 'drawing' }
  | { kind: 'rolling'; draw: DrawRecord }
  | { kind: 'won'; draw: DrawRecord }

/** 이번 판의 고정 정보. 키 입력 핸들러가 오래된 값을 붙잡지 않도록 ref 에 둔다. */
type Roll = {
  draw: DrawRecord
  /** 뜸을 들이는 자리 (왼쪽부터) */
  stages: number[]
}

/**
 * 자릿수별로 후보들이 쓰는 숫자를 모은다.
 *
 * 어떤 자리에서 후보 전원이 같은 숫자를 쓰면 그 자리는 승부와 무관하다.
 */
function digitSpread(tiles: DrawTile[], digits: number): Set<string>[] {
  const eligible = tiles.filter((tile) => tile.eligible)
  return Array.from(
    { length: digits },
    (_, index) => new Set(eligible.map((tile) => tile.label[index])),
  )
}

/** 뜸을 들일 자리. 후보가 갈리는 자리만 고르고, 하나도 없으면 마지막 자리를 쓴다. */
function stagedPositions(spread: Set<string>[]): number[] {
  const staged = spread
    .map((values, index) => (values.size > 1 ? index : -1))
    .filter((index) => index >= 0)
  return staged.length > 0 ? staged : [spread.length - 1]
}

export default function DrawPage() {
  const { status, signIn } = useAdminSession()

  if (status === 'checking') return <SessionChecking tone="dark" />
  if (status === 'out') return <AdminLogin tone="dark" onSuccess={signIn} />
  return <DrawStage />
}

// ---------------------------------------------------------------------------
// 무대
// ---------------------------------------------------------------------------

function DrawStage() {
  const [state, setState] = useState<DrawState | null>(null)
  const [error, setError] = useState('')
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' })

  const [prizeId, setPrizeId] = useState('')
  const [excludeStaff, setExcludeStaff] = useState(false)
  const [allowRepeat, setAllowRepeat] = useState(false)
  /**
   * 후보를 좁힐 출석 회차. 빈 문자열이면 번호를 받은 사람 전체가 후보다.
   *
   * 번호는 본 행사 체크인 순서로만 준다 — 회차마다 새로 매기면 참가자가 번호를
   * 두 개 외워야 한다. 대신 뒤풀이 자리에서 뽑을 때 **그 자리에 남은 사람으로
   * 후보를 좁힌다.** 낮에만 왔던 사람의 번호는 처음부터 꺼져 있다.
   */
  const [poolSession, setPoolSession] = useState('')
  const [autoStop, setAutoStop] = useState(false)
  const [muted, setMuted] = useState(false)
  const [panelOpen, setPanelOpen] = useState(true)

  /**
   * 연출에 쓰는 번호판.
   *
   * 조회할 때마다 갈아치우지 않는다. 추첨이 시작되면 서버가 준 '뽑기 전' 판으로
   * 고정한다 — 도중에 누가 체크인해서 번호가 늘어나면 탈락 연출과 남은 후보 수가
   * 어긋난다.
   */
  const [board, setBoard] = useState<DrawTile[]>([])
  /** 값이 드러난 자리. 릴이 실제로 선 순간에 늘어난다 (누른 순간이 아니다). */
  const [revealed, setRevealed] = useState<number[]>([])
  /** 이미 '멈춰' 신호를 보낸 자리. 아직 서는 중이어도 버튼에서는 빠져야 한다. */
  const [commandedList, setCommandedList] = useState<number[]>([])
  /** 차례로 멈추기가 돌고 있는가 (화면 표시용). 판정은 아래 ref 로 한다. */
  const [sequencing, setSequencing] = useState(false)

  const reels = useRef<(ReelHandle | null)[]>([])
  const timers = useRef<number[]>([])
  const audio = useRef<AudioContext | null>(null)
  const roll = useRef<Roll | null>(null)
  // 키 입력은 렌더 사이에 들어오므로 판정은 ref 로 한다. 같은 키를 연타해도
  // 한 번만 먹어야 하고, state 갱신을 기다리는 사이에 두 번 들어오면 안 된다.
  const commanded = useRef<Set<number>>(new Set())
  const revealedRef = useRef<number[]>([])
  const sequencingRef = useRef(false)
  const phaseRef = useRef<Phase>(phase)

  const clearTimers = () => {
    timers.current.forEach((id) => window.clearTimeout(id))
    timers.current = []
  }
  const later = (fn: () => void, ms: number) => {
    timers.current.push(window.setTimeout(fn, ms))
  }

  useEffect(() => clearTimers, [])
  useEffect(() => {
    phaseRef.current = phase
  }, [phase])

  const load = useCallback(async () => {
    try {
      const next = await adminApi.drawState({ excludeStaff, allowRepeat, poolSession })
      setState(next)
      // 돌고 있는 중에는 판을 건드리지 않는다.
      if (phaseRef.current.kind === 'idle') setBoard(next.pool)
      setError('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '추첨 정보를 불러오지 못했습니다.')
    }
  }, [excludeStaff, allowRepeat, poolSession])

  useEffect(() => {
    void load()
  }, [load])

  /** 대기 중에는 새로 체크인한 사람이 판에 붙어야 한다. */
  useEffect(() => {
    if (phase.kind !== 'idle') return
    const timer = window.setInterval(() => void load(), 10_000)
    return () => window.clearInterval(timer)
  }, [phase.kind, load])

  // --- 소리 -----------------------------------------------------------------
  // 파일을 싣지 않고 오실레이터로 만든다. 첫 소리가 버튼 클릭 뒤에 나므로
  // 브라우저의 자동재생 정책에도 걸리지 않는다.
  const beep = useCallback(
    (frequency: number, duration = 0.09, gain = 0.16) => {
      if (muted) return
      try {
        audio.current ??= new AudioContext()
        const context = audio.current
        void context.resume()

        const osc = context.createOscillator()
        const volume = context.createGain()
        osc.type = 'triangle'
        osc.frequency.value = frequency
        volume.gain.setValueAtTime(gain, context.currentTime)
        volume.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + duration)
        osc.connect(volume).connect(context.destination)
        osc.start()
        osc.stop(context.currentTime + duration)
      } catch {
        // 소리는 있으면 좋은 것이다. 안 나도 추첨은 굴러가야 한다.
      }
    },
    [muted],
  )

  const fanfare = useCallback(() => {
    // 도-미-솔-도. 올라가는 화음이면 무슨 일이 일어났는지 설명이 필요 없다.
    ;[523, 659, 784, 1047].forEach((note, index) => {
      window.setTimeout(() => beep(note, 0.34, 0.2), index * 130)
    })
  }, [beep])

  // --- 파생값 ---------------------------------------------------------------

  const digits = state?.digits ?? 3
  const spread = useMemo(() => digitSpread(board, digits), [board, digits])
  const stages = useMemo(() => stagedPositions(spread), [spread])
  const prizes = state?.prizes ?? []
  const prize = prizes.find((item) => item.id === prizeId) ?? null

  const target = phase.kind === 'rolling' || phase.kind === 'won' ? phase.draw.drawLabel : null

  /** 처음부터 확정으로 띄우는 자리 — 후보 전원이 같은 숫자를 쓰는 자리다. */
  const constantAt = useCallback(
    (index: number) => {
      if (stages.includes(index)) return null
      const values = spread[index]
      return values && values.size === 1 ? Number([...values][0]) : null
    },
    [spread, stages],
  )

  /** 지금 화면에서 값이 드러난 자리 전체 (확정 자리 + 세워진 자리). */
  const shown = useMemo(() => {
    const opened = new Set<number>()
    for (let index = 0; index < digits; index += 1) {
      if (!stages.includes(index)) opened.add(index)
    }
    revealed.forEach((index) => opened.add(index))
    return opened
  }, [digits, stages, revealed])

  const survivors = useMemo(
    () =>
      board.filter(
        (tile) =>
          tile.eligible &&
          (target === null || [...shown].every((index) => tile.label[index] === target[index])),
      ),
    [board, shown, target],
  )

  const idleEligible = state?.counts.eligible ?? 0
  const remaining = phase.kind === 'idle' ? idleEligible : survivors.length
  // 아직 '멈춰' 신호를 보내지 않은 자리. 서는 중인 자리는 이미 빠져 있어야
  // 진행자가 같은 자리를 두 번 누르려 하지 않는다.
  const pendingStages = stages.filter((index) => !commandedList.includes(index))

  // --- 대기 중 릴 모습 ------------------------------------------------------
  // 갈리지 않는 자리는 대기 화면에서도 그 숫자를 보여 준다. '0 ? ?' 로 서 있으면
  // 관객이 시작 전에 이미 자기 번호의 운명을 반쯤 안다.
  useEffect(() => {
    if (phase.kind !== 'idle') return
    for (let index = 0; index < digits; index += 1) {
      const fixed = constantAt(index)
      if (fixed === null) reels.current[index]?.clear()
      else reels.current[index]?.place(fixed)
    }
  }, [phase.kind, digits, constantAt])

  // --- 정지 ----------------------------------------------------------------

  const stopAt = useCallback(
    (position: number) => {
      const current = roll.current
      if (phaseRef.current.kind !== 'rolling' || current === null) return
      if (!current.stages.includes(position)) return
      if (commanded.current.has(position)) return

      commanded.current.add(position)
      setCommandedList((prev) => [...prev, position])
      const digit = Number(current.draw.drawLabel[position])
      reels.current[position]?.stop(digit)

      // 번호판이 꺼지는 건 **릴이 실제로 선 순간**이어야 한다. 키를 누른 순간
      // 꺼지면 아직 돌고 있는 숫자를 화면이 먼저 알아버린 꼴이 된다.
      later(() => {
        beep(440 + current.stages.indexOf(position) * 180, 0.13, 0.22)
        if (revealedRef.current.includes(position)) return

        revealedRef.current = [...revealedRef.current, position]
        setRevealed(revealedRef.current)

        if (revealedRef.current.length === current.stages.length) {
          later(() => {
            setPhase({ kind: 'won', draw: current.draw })
            fanfare()
            void load()
          }, REVEAL_DELAY_MS)
        }
      }, DECEL_MS)
    },
    [beep, fanfare, load],
  )

  /**
   * 남은 자리를 **왼쪽부터 차례로** 세운다.
   *
   * 한 번 누르면 끝까지 굴러간다. 진행자는 대개 마이크를 들고 있어서, 자리마다
   * 키를 찾아 누르게 하면 정작 관객을 못 본다. 중간에 A/S/D 로 끼어들면 그 자리는
   * 바로 서고, 예약되어 있던 신호는 이미 선 자리라 그냥 흘러간다.
   */
  const stopSequence = useCallback(() => {
    const current = roll.current
    if (phaseRef.current.kind !== 'rolling' || current === null) return
    if (sequencingRef.current) return // 연타해도 리듬이 빨라지지 않는다

    const pending = current.stages.filter((position) => !commanded.current.has(position))
    if (pending.length === 0) return

    sequencingRef.current = true
    setSequencing(true)
    pending.forEach((position, order) => {
      if (order === 0) stopAt(position)
      else later(() => stopAt(position), STOP_GAP_MS * order)
    })
  }, [stopAt])

  // 키보드. event.code 로 읽어 한/영 상태와 무관하게 동작한다.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const node = event.target as HTMLElement | null
      if (node && (node.tagName === 'INPUT' || node.tagName === 'TEXTAREA' || node.isContentEditable)) {
        return
      }
      if (phaseRef.current.kind !== 'rolling') return

      if (NEXT_KEYS.includes(event.code)) {
        event.preventDefault()
        stopSequence()
        return
      }
      const position = POSITION_KEYS.indexOf(event.code)
      if (position >= 0) {
        event.preventDefault()
        stopAt(position)
      }
    }

    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [stopSequence, stopAt])

  // --- 추첨 ----------------------------------------------------------------

  const start = async () => {
    if (phase.kind === 'drawing' || phase.kind === 'rolling') return

    clearTimers()
    commanded.current = new Set()
    revealedRef.current = []
    sequencingRef.current = false
    setCommandedList([])
    setSequencing(false)
    setRevealed([])
    setPhase({ kind: 'drawing' })
    beep(320, 0.06, 0.1) // 눌렸다는 응답 + AudioContext 깨우기

    let result: Awaited<ReturnType<typeof adminApi.createDraw>>
    try {
      result = await adminApi.createDraw({
        prizeId: prizeId || undefined,
        excludeStaff,
        allowRepeat,
        poolSession: poolSession || null,
      })
    } catch (caught) {
      setPhase({ kind: 'idle' })
      setError(caught instanceof Error ? caught.message : '추첨에 실패했습니다.')
      void load()
      return
    }

    setError('')
    setBoard(result.state.pool)

    // 무대 수는 이번 판에서 직접 구한다. 위에서 setBoard 한 값이 useMemo 에
    // 반영되기 전이므로 렌더용 값(stages)을 그대로 쓸 수 없다.
    const rollSpread = digitSpread(result.state.pool, result.state.digits)
    const rollStages = stagedPositions(rollSpread)
    roll.current = { draw: result.draw, stages: rollStages }

    for (let index = 0; index < result.state.digits; index += 1) {
      if (rollStages.includes(index)) reels.current[index]?.spin()
      else {
        const values = rollSpread[index]
        reels.current[index]?.place(values && values.size === 1 ? Number([...values][0]) : 0)
      }
    }

    setPhase({ kind: 'rolling', draw: result.draw })

    if (autoStop) {
      sequencingRef.current = true
      setSequencing(true)
      rollStages.forEach((position, order) => {
        later(() => stopAt(position), AUTO_FIRST_MS + STOP_GAP_MS * order)
      })
    }
  }

  const reset = () => {
    clearTimers()
    roll.current = null
    commanded.current = new Set()
    revealedRef.current = []
    sequencingRef.current = false
    setCommandedList([])
    setSequencing(false)
    setRevealed([])
    setPhase({ kind: 'idle' })
    void load()
  }

  const voidWinner = async (record: DrawRecord) => {
    const reason = window.prompt(
      `${record.roundNo}회 · ${record.drawLabel}번 당첨을 무효로 돌립니다.\n사유를 적어 주세요 (기록에 남습니다).`,
      '자리에 없음',
    )
    if (reason === null) return
    try {
      clearTimers()
      const result = await adminApi.voidDraw(record.id, reason)
      roll.current = null
      commanded.current = new Set()
      setRevealed([])
      setPhase({ kind: 'idle' })
      setState(result.state)
      setBoard(result.state.pool)
    } catch (caught) {
      alert(caught instanceof Error ? caught.message : '무효 처리에 실패했습니다.')
    }
  }

  /**
   * 시연 흔적 지우기.
   *
   * 무효 처리로는 안 된다 — 무효는 '이런 일이 있었고 취소했다'를 남기는 것이라,
   * 시연 기록이 이력에 그대로 쌓인 채 본 추첨이 시작된다.
   */
  const clearHistory = async () => {
    const count = state?.history.length ?? 0
    if (count === 0) return
    if (
      !confirm(
        `당첨 기록 ${count}건을 전부 지웁니다.\n\n` +
          '되돌릴 수 없습니다. 상품 수량과 후보가 처음 상태로 돌아가고,\n' +
          '체크인 번호는 그대로 유지됩니다.\n' +
          '(지운 사실은 관리자 > 작업 기록에 남습니다)',
      )
    ) {
      return
    }

    try {
      clearTimers()
      const result = await adminApi.clearDraws()
      roll.current = null
      commanded.current = new Set()
      revealedRef.current = []
      sequencingRef.current = false
      setCommandedList([])
      setSequencing(false)
      setRevealed([])
      setPhase({ kind: 'idle' })
      setState(result.state)
      setBoard(result.state.pool)
      setPrizeId('')
    } catch (caught) {
      alert(caught instanceof Error ? caught.message : '기록을 지우지 못했습니다.')
    }
  }

  const savePrizes = async (items: { id?: string; label: string; count: number }[]) => {
    const result = await adminApi.setDrawPrizes(items)
    setState(result.state)
    // 고르고 있던 상품이 사라졌으면 선택을 비운다.
    if (prizeId && !result.state.prizes.some((item) => item.id === prizeId)) setPrizeId('')
    return result.state.prizes
  }

  const busy = phase.kind === 'drawing' || phase.kind === 'rolling'

  return (
    <div className="min-h-dvh bg-[#10161c] text-white">
      {phase.kind === 'won' && <Confetti />}

      <ControlPanel
        open={panelOpen}
        onClose={() => setPanelOpen(false)}
        onOpen={() => setPanelOpen(true)}
        state={state}
        busy={busy}
        excludeStaff={excludeStaff}
        onExcludeStaff={setExcludeStaff}
        allowRepeat={allowRepeat}
        onAllowRepeat={setAllowRepeat}
        poolSession={poolSession}
        onPoolSession={setPoolSession}
        autoStop={autoStop}
        onAutoStop={setAutoStop}
        muted={muted}
        onMuted={setMuted}
        onSavePrizes={savePrizes}
        onVoid={voidWinner}
        onClearHistory={clearHistory}
      />

      {/*
        무대는 조작판을 여닫아도 **한 픽셀도 움직이지 않는다.** 조작판이 위에서
        밀고 들어오면 슬롯이 아래로 내려갔다 올라와 연출이 흔들린다. 그래서
        조작판은 왼쪽에 겹쳐 뜨는 판으로 두고, 무대는 늘 같은 자리에 있게 한다.
      */}
      <main className="mx-auto flex max-w-6xl flex-col items-center px-4 pb-16 pt-14">
        <p className="text-sm font-bold tracking-[0.3em] text-flame-300/80">LUCKY DRAW</p>
        <h1 className="mt-2 text-center text-2xl font-black sm:text-3xl">
          {phase.kind === 'won' || phase.kind === 'rolling'
            ? phase.draw.prize || `${phase.draw.roundNo}회차 추첨`
            : prize?.label || `${state?.nextRoundNo ?? 1}회차 추첨`}
        </h1>

        <div
          className="mt-8 flex gap-3 sm:gap-4"
          style={{ '--reel-cell': 'clamp(5.5rem, 17vw, 11rem)' } as React.CSSProperties}
        >
          {Array.from({ length: digits }, (_, index) => (
            <Reel
              key={index}
              ref={(handle) => {
                reels.current[index] = handle
              }}
              locked={shown.has(index)}
              staged={stages.includes(index)}
              hint={index < POSITION_KEYS.length ? ['A', 'S', 'D'][index] : null}
              showHint={phase.kind === 'rolling' && pendingStages.includes(index)}
            />
          ))}
        </div>

        <RemainingCounter
          remaining={remaining}
          total={board.length || idleEligible}
          phase={phase}
          revealedStages={revealed.length}
          stageCount={stages.length}
        />

        {phase.kind === 'rolling' ? (
          <KeyHints
            pending={pendingStages}
            sequencing={sequencing}
            onStopAll={stopSequence}
            onStopAt={stopAt}
          />
        ) : phase.kind === 'won' ? (
          <WinnerCard draw={phase.draw} onAgain={reset} onVoid={() => voidWinner(phase.draw)} />
        ) : (
          <PrizePicker
            prizes={prizes}
            selected={prizeId}
            onSelect={setPrizeId}
            onStart={start}
            busy={busy}
            canDraw={(state?.counts.eligible ?? 0) > 0}
            error={error}
            hint={
              (state?.counts.issued ?? 0) === 0
                ? '아직 발급된 번호가 없습니다. 번호는 참가자가 체크인하는 순서대로 001 부터 붙습니다.'
                : null
            }
          />
        )}

        {board.length > 0 && (
          <NumberBoard
            board={board}
            target={target}
            shown={shown}
            winner={phase.kind === 'won' ? target : null}
          />
        )}
      </main>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 릴
// ---------------------------------------------------------------------------

type ReelHandle = {
  /** 계속 돈다. 멈추라는 신호가 올 때까지. */
  spin: () => void
  /** 지금 위치에서 목표 숫자까지 감속해 선다. */
  stop: (digit: number) => void
  /** 즉시 그 숫자에 놓는다 (승부와 무관한 자리). */
  place: (digit: number) => void
  /** 물음표 상태로 되돌린다. */
  clear: () => void
}

/**
 * 숫자 릴 한 벌.
 *
 * 움직임은 React 가 아니라 이 컴포넌트가 DOM 을 직접 몬다. 돌 때는 CSS keyframe 으로
 * 등속 회전하고, 멈추라는 신호가 오면 **그 순간의 transform 을 읽어** 거기서부터
 * 목표 숫자까지 감속 transition 을 이어 붙인다. keyframe 을 그냥 걷어내면 위치가
 * 0 으로 튀어 릴이 순간이동한 것처럼 보인다.
 */
const Reel = forwardRef<
  ReelHandle,
  {
    locked: boolean
    staged: boolean
    hint: string | null
    showHint: boolean
  }
>(function Reel({ locked, staged, hint, showHint }, ref) {
  const stripRef = useRef<HTMLDivElement>(null)
  const [empty, setEmpty] = useState(true)

  /** 한 칸의 높이(px). `--reel-cell` 이 clamp() 라서 계산이 아니라 측정으로 얻는다. */
  const cellHeight = () => {
    const strip = stripRef.current
    if (!strip) return 0
    return strip.getBoundingClientRect().height / STRIP_CELLS
  }

  /** 지금 화면에 보이는 위치(px). 회전 중에도 정확하다. */
  const currentY = () => {
    const strip = stripRef.current
    if (!strip) return 0
    const transform = getComputedStyle(strip).transform
    if (!transform || transform === 'none') return 0
    return new DOMMatrixReadOnly(transform).m42
  }

  const freeze = (y: number) => {
    const strip = stripRef.current
    if (!strip) return
    strip.classList.remove('reel-rolling')
    strip.style.transition = 'none'
    strip.style.transform = `translateY(${y}px)`
    // 리플로우를 한 번 강제해야 다음 줄의 transition 이 '이 위치에서' 시작한다.
    void strip.offsetHeight
  }

  useImperativeHandle(ref, () => ({
    spin() {
      const strip = stripRef.current
      if (!strip) return
      setEmpty(false)
      freeze(0)
      strip.style.transform = ''
      strip.classList.add('reel-rolling')
    },

    stop(digit: number) {
      const strip = stripRef.current
      if (!strip) return
      const cell = cellHeight()
      if (cell <= 0) return

      const y = currentY()
      freeze(y)

      // 지금 지나고 있는 칸의 다음 칸부터 세어, 몇 바퀴 더 돌고 목표 숫자에 선다.
      const passed = Math.ceil(-y / cell)
      let landing = passed + DECEL_LOOPS * 10
      landing += ((digit - (landing % 10)) + 10) % 10

      strip.style.transition = `transform ${DECEL_MS}ms cubic-bezier(0.16, 0.72, 0.02, 1)`
      strip.style.transform = `translateY(${-landing * cell}px)`
    },

    place(digit: number) {
      setEmpty(false)
      freeze(-digit * cellHeight())
    },

    clear() {
      setEmpty(true)
      freeze(0)
    },
  }))

  return (
    <div
      className={`reel-window border-2 ${
        locked
          ? 'border-flame-400 bg-gradient-to-b from-flame-100 to-flame-200 text-[#10161c] shadow-[0_0_40px_-6px_rgba(208,165,101,0.75)]'
          : 'border-white/12 bg-white/6 text-white'
      } ${locked && staged ? 'reel-clunk' : ''}`}
    >
      <div ref={stripRef} className="reel-strip">
        {Array.from({ length: STRIP_CELLS }, (_, cell) => (
          <div
            key={cell}
            className="reel-cell text-center text-[clamp(3.4rem,11vw,7rem)] font-black tabular"
          >
            {DIGITS[cell % 10]}
          </div>
        ))}
      </div>

      {/* 아직 아무것도 정해지지 않은 자리는 물음표로 덮는다. */}
      {empty && (
        <div className="absolute inset-0 grid place-items-center bg-[#10161c]">
          <span className="text-[clamp(3rem,9vw,6rem)] font-black text-white/22">?</span>
        </div>
      )}

      {/* 창 위아래 그늘 — 띠가 통 안에서 돌아가는 것처럼 보이게 한다. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-gradient-to-b from-black/35 via-transparent to-black/35"
      />

      {/* 어느 키가 이 자리를 세우는지. 진행자만 보면 되므로 작고 흐리게. */}
      {showHint && hint && (
        <span className="pointer-events-none absolute bottom-1.5 right-2 rounded bg-black/45 px-1.5 py-0.5 text-[11px] font-black text-white/55">
          {hint}
        </span>
      )}
    </div>
  )
})

// ---------------------------------------------------------------------------
// 남은 후보 수
// ---------------------------------------------------------------------------

function RemainingCounter({
  remaining,
  total,
  phase,
  revealedStages,
  stageCount,
}: {
  remaining: number
  total: number
  phase: Phase
  revealedStages: number
  stageCount: number
}) {
  const caption = (() => {
    if (phase.kind === 'idle') return '추첨 후보'
    if (phase.kind === 'drawing') return '뽑는 중…'
    if (phase.kind === 'won') return '당첨'
    if (revealedStages === 0) return '전원 생존'
    if (revealedStages < stageCount) return `${revealedStages}자리 확정 — 남은 후보`
    return '당첨'
  })()

  return (
    <div className="mt-7 text-center">
      <p className="text-xs font-bold tracking-[0.2em] text-white/45">{caption}</p>
      <p className="mt-1 flex items-baseline justify-center gap-2">
        <span
          key={remaining}
          className="winner-pop text-5xl font-black tabular text-flame-300 sm:text-6xl"
        >
          {remaining}
        </span>
        <span className="text-lg font-bold text-white/35 tabular">/ {total}명</span>
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 상품 고르기 · 시작
// ---------------------------------------------------------------------------

/**
 * 이번 회차에 무엇을 걸지 고르는 자리.
 *
 * 슬롯 바로 아래에 둔다. 진행자가 조작판을 열지 않고도 '고르고 → 돌린다'가
 * 한 동선에서 끝나야 한다.
 */
function PrizePicker({
  prizes,
  selected,
  onSelect,
  onStart,
  busy,
  canDraw,
  error,
  hint,
}: {
  prizes: DrawPrize[]
  selected: string
  onSelect: (id: string) => void
  onStart: () => void
  busy: boolean
  canDraw: boolean
  error: string
  hint: string | null
}) {
  const available = prizes.filter((prize) => prize.remaining > 0)

  return (
    <div className="mt-8 w-full max-w-3xl text-center">
      {error && (
        <p className="mb-4 rounded-xl border border-brick-400/40 bg-brick-400/12 px-3.5 py-2.5 text-sm font-semibold text-brick-400">
          {error}
        </p>
      )}

      {prizes.length > 0 && (
        <>
          <p className="text-xs font-bold tracking-[0.2em] text-white/40">이번에 걸 상품</p>
          <div className="mt-2.5 flex flex-wrap justify-center gap-2">
            {prizes.map((prize) => {
              const gone = prize.remaining <= 0
              const active = selected === prize.id
              return (
                <button
                  key={prize.id}
                  type="button"
                  disabled={gone || busy}
                  onClick={() => onSelect(active ? '' : prize.id)}
                  className={`rounded-full border-2 px-4 py-2 text-sm font-bold transition ${
                    active
                      ? 'border-flame-300 bg-flame-300 text-[#10161c]'
                      : gone
                        ? 'cursor-not-allowed border-white/8 text-white/25 line-through'
                        : 'border-white/15 text-white/75 hover:border-flame-300/60 hover:text-white'
                  }`}
                >
                  {prize.label}
                  <span className="ml-2 text-xs font-black tabular">
                    {gone ? '소진' : `${prize.remaining}/${prize.count}`}
                  </span>
                </button>
              )
            })}
          </div>
          {available.length === 0 && (
            <p className="mt-2.5 text-xs font-semibold text-flame-200/80">
              등록된 상품이 모두 나갔습니다. 조작판에서 상품을 더 등록하거나, 상품 없이 뽑을 수
              있습니다.
            </p>
          )}
        </>
      )}

      <button
        type="button"
        onClick={onStart}
        disabled={busy || !canDraw}
        className="mt-5 rounded-full bg-flame-300 px-10 py-3.5 text-base font-black text-[#10161c] transition hover:bg-flame-200 disabled:cursor-not-allowed disabled:opacity-35"
      >
        {busy ? '추첨 중…' : '추첨 시작'}
      </button>

      <p className="mt-3 text-xs text-white/35">
        {hint ??
          (selected
            ? '시작하면 릴이 계속 돕니다. Enter 나 Space 를 누르면 차례로 멈춰요.'
            : '상품을 고르지 않고 돌려도 됩니다. 결과는 그대로 기록됩니다.')}
      </p>
    </div>
  )
}

/**
 * 돌고 있는 동안의 안내.
 *
 * 진행자는 대개 마이크를 들고 있다. 그래서 기본 동작은 **한 번 눌러 끝까지**이고,
 * 자리를 끊어 보고 싶을 때만 A/S/D 로 끼어든다.
 * 키를 못 쓰는 상황(터치 화면 등)을 위해 같은 동작의 버튼도 함께 둔다.
 */
function KeyHints({
  pending,
  sequencing,
  onStopAll,
  onStopAt,
}: {
  pending: number[]
  sequencing: boolean
  onStopAll: () => void
  onStopAt: (position: number) => void
}) {
  const names = ['백의 자리', '십의 자리', '일의 자리']

  return (
    <div className="mt-8 w-full max-w-3xl text-center">
      <button
        type="button"
        onClick={onStopAll}
        disabled={sequencing}
        className="rounded-full bg-flame-300 px-10 py-3.5 text-base font-black text-[#10161c] transition hover:bg-flame-200 disabled:opacity-35"
      >
        {sequencing ? '차례로 멈추는 중…' : '멈추기'}
      </button>

      <p className="mt-3 text-xs font-semibold text-white/45">
        <kbd className="rounded bg-white/10 px-1.5 py-0.5">Enter</kbd>{' '}
        <kbd className="rounded bg-white/10 px-1.5 py-0.5">Space</kbd> 한 번이면 왼쪽부터 차례로
        멈춥니다 · <kbd className="rounded bg-white/10 px-1.5 py-0.5">A</kbd>{' '}
        <kbd className="rounded bg-white/10 px-1.5 py-0.5">S</kbd>{' '}
        <kbd className="rounded bg-white/10 px-1.5 py-0.5">D</kbd> 로 그 자리만 먼저 세울 수 있어요
      </p>

      {pending.length > 0 && (
        <div className="mt-3 flex flex-wrap justify-center gap-2">
          {pending.map((position) => (
            <button
              key={position}
              type="button"
              onClick={() => onStopAt(position)}
              className="rounded-full border border-white/15 px-3.5 py-1.5 text-xs font-bold text-white/70 hover:bg-white/8"
            >
              {['A', 'S', 'D'][position] ?? position + 1} ·{' '}
              {names[position] ?? `${position + 1}번째`} 바로
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 번호판
// ---------------------------------------------------------------------------

/**
 * 발급된 번호 전체를 벽처럼 깔아 둔다.
 *
 * 이 판이 연출의 핵심이다. 참가자는 시작 전에 자기 번호를 벽에서 찾아 두고,
 * 자릿수가 잠길 때마다 자기 타일이 꺼지는지를 본다. 화면 어딘가에 자기 것이
 * 있다는 사실만으로 남의 추첨이 자기 추첨이 된다.
 */
function NumberBoard({
  board,
  target,
  shown,
  winner,
}: {
  board: DrawTile[]
  target: string | null
  shown: Set<number>
  winner: string | null
}) {
  const positions = [...shown]

  return (
    <section className="mt-12 w-full">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xs font-bold tracking-[0.2em] text-white/45">번호판</h2>
        <p className="text-[11px] font-semibold text-white/30">
          체크인 순서대로 발급된 번호 {board.length}개
        </p>
      </div>

      <ul
        className="grid gap-1.5"
        style={{
          gridTemplateColumns: `repeat(auto-fill, minmax(${
            board.length > 220 ? '2.6rem' : '3.1rem'
          }, 1fr))`,
        }}
      >
        {board.map((tile) => {
          const isWinner = winner === tile.label
          const alive =
            tile.eligible &&
            (target === null || positions.every((index) => tile.label[index] === target[index]))

          return (
            <li
              key={tile.no}
              title={tile.out ? OUT_LABEL[tile.out] : undefined}
              className={[
                'grid place-items-center rounded-lg py-1.5 text-sm font-black tabular transition-colors duration-500',
                isWinner
                  ? 'bg-flame-300 text-[#10161c] shadow-[0_0_28px_-2px_rgba(226,196,140,0.9)] ring-2 ring-flame-100'
                  : alive
                    ? 'bg-sand-500/22 text-sand-200 ring-1 ring-sand-400/35'
                    : tile.eligible
                      ? 'tile-out bg-white/4 text-white/18'
                      : 'bg-white/4 text-white/14 line-through decoration-white/25',
              ].join(' ')}
            >
              {tile.label}
            </li>
          )
        })}
      </ul>

      <p className="mt-3 text-[11px] leading-relaxed text-white/30">
        취소선이 그어진 번호는 후보에서 빠진 것입니다 (출석 취소 · 참가 취소 · 이미 당첨).
        취소선 없는 회색은 이번 자릿수에서 탈락한 번호입니다.
      </p>
    </section>
  )
}

// ---------------------------------------------------------------------------
// 당첨자
// ---------------------------------------------------------------------------

/** 상품과 사람을 한 카드에서 함께 보여 준다. 시상은 둘이 짝지어야 성립한다. */
function WinnerCard({
  draw,
  onAgain,
  onVoid,
}: {
  draw: DrawRecord
  onAgain: () => void
  onVoid: () => void
}) {
  const facts = [
    draw.department && { label: '학과', value: draw.department },
    draw.groupValue && { label: '조', value: draw.groupValue },
  ].filter(Boolean) as { label: string; value: string }[]

  return (
    <div className="winner-pop mt-8 w-full max-w-xl rounded-3xl border-2 border-flame-400/60 bg-gradient-to-b from-flame-400/22 to-transparent px-6 py-7 text-center">
      <p className="text-xs font-bold tracking-[0.25em] text-flame-300">{draw.roundNo}회차 당첨</p>

      {draw.prize && (
        <p className="mt-2 inline-block rounded-full bg-flame-300 px-4 py-1.5 text-lg font-black text-[#10161c]">
          {draw.prize}
        </p>
      )}

      <p className="mt-4 text-6xl font-black tabular text-flame-200 sm:text-7xl">
        {draw.drawLabel}
      </p>
      <p className="mt-3 text-3xl font-black sm:text-4xl">{draw.name ?? '(기록 없음)'}</p>

      {facts.length > 0 && (
        <dl className="mt-3 flex flex-wrap justify-center gap-x-6 gap-y-1">
          {facts.map((fact) => (
            <div key={fact.label} className="flex items-baseline gap-1.5">
              <dt className="text-xs font-bold text-white/40">{fact.label}</dt>
              <dd className="text-base font-black text-white/85">{fact.value}</dd>
            </div>
          ))}
        </dl>
      )}

      <p className="mt-5 text-xs text-white/40 tabular">
        후보 {draw.poolSize}명 중 1명 · {formatDateTime(draw.drawnAt)}
      </p>
      <p className="mt-2 text-sm font-bold text-flame-200">
        체크인 화면의 번호를 스태프에게 보여 주세요.
      </p>

      <div className="mt-6 flex flex-wrap justify-center gap-2">
        <button
          type="button"
          onClick={onAgain}
          className="rounded-full bg-flame-300 px-7 py-2.5 text-sm font-black text-[#10161c] transition hover:bg-flame-200"
        >
          다음 추첨
        </button>
        <button
          type="button"
          onClick={onVoid}
          className="rounded-full border border-white/15 px-4 py-2.5 text-sm font-bold text-white/60 hover:bg-white/8"
        >
          자리에 없음 — 무효 처리
        </button>
      </div>
    </div>
  )
}

/** 꽃가루. 라이브러리를 싣지 않고 조각 몇 십 개를 떨어뜨린다. */
function Confetti() {
  const pieces = useMemo(
    () =>
      Array.from({ length: 90 }, (_, index) => ({
        id: index,
        left: Math.random() * 100,
        drift: `${(Math.random() - 0.5) * 40}vw`,
        spin: `${Math.random() * 1080 - 540}deg`,
        duration: 2.6 + Math.random() * 2.4,
        delay: Math.random() * 1.2,
        color: ['#f0dcb6', '#95c572', '#72a6d9', '#f5cc63', '#f08a7e'][index % 5],
      })),
    [],
  )

  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 z-40 overflow-hidden">
      {pieces.map((piece) => (
        <span
          key={piece.id}
          className="confetti-piece"
          style={
            {
              left: `${piece.left}%`,
              backgroundColor: piece.color,
              animationDuration: `${piece.duration}s`,
              animationDelay: `${piece.delay}s`,
              '--drift': piece.drift,
              '--spin': piece.spin,
            } as React.CSSProperties
          }
        />
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 조작판 (왼쪽 서랍)
// ---------------------------------------------------------------------------

/**
 * 진행자가 쓰는 부분.
 *
 * **무대를 밀어내지 않도록 왼쪽에 겹쳐 뜬다.** 위에서 밀고 들어오는 방식이면
 * 여닫을 때마다 슬롯이 아래로 내려갔다 올라와 연출이 흔들린다.
 */
function ControlPanel({
  open,
  onClose,
  onOpen,
  state,
  busy,
  excludeStaff,
  onExcludeStaff,
  allowRepeat,
  onAllowRepeat,
  poolSession,
  onPoolSession,
  autoStop,
  onAutoStop,
  muted,
  onMuted,
  onSavePrizes,
  onVoid,
  onClearHistory,
}: {
  open: boolean
  onClose: () => void
  onOpen: () => void
  state: DrawState | null
  busy: boolean
  excludeStaff: boolean
  onExcludeStaff: (value: boolean) => void
  allowRepeat: boolean
  onAllowRepeat: (value: boolean) => void
  poolSession: string
  onPoolSession: (value: string) => void
  autoStop: boolean
  onAutoStop: (value: boolean) => void
  muted: boolean
  onMuted: (value: boolean) => void
  onSavePrizes: (items: { id?: string; label: string; count: number }[]) => Promise<DrawPrize[]>
  onVoid: (record: DrawRecord) => void
  onClearHistory: () => void
}) {
  const history = state?.history ?? []

  // 서랍은 Esc 로도 닫는다. 진행자가 무대를 보며 손만 뻗어 닫을 수 있어야 한다.
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.code === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  return (
    <>
      {/* 무대 위에 겹쳐 두는 얇은 띠. 열기 버튼은 서랍에 가리므로 닫혀 있을 때만 띄우고,
          닫기 버튼은 서랍 안(아래 header)에 둔다. */}
      <div className="pointer-events-none fixed inset-x-0 top-0 z-20 flex items-start justify-between px-3 py-3">
        {open ? (
          <span />
        ) : (
          <button
            type="button"
            onClick={onOpen}
            className="pointer-events-auto rounded-full border border-white/15 bg-black/45 px-3.5 py-1.5 text-xs font-bold text-white/70 backdrop-blur hover:bg-black/70"
          >
            조작판
          </button>
        )}
        <span className="pointer-events-none rounded-full bg-black/35 px-3 py-1.5 text-xs font-semibold text-white/45 tabular backdrop-blur">
          후보 {state?.counts.eligible ?? 0} · 발급 {state?.counts.issued ?? 0} · 당첨{' '}
          {state?.counts.won ?? 0}
        </span>
      </div>

      <aside
        className={`fixed inset-y-0 left-0 z-30 flex w-[21rem] max-w-[88vw] flex-col border-r border-white/10 bg-[#0b1015]/97 backdrop-blur transition-transform duration-300 ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
        aria-hidden={!open}
      >
        <header className="flex shrink-0 items-center justify-between border-b border-white/10 px-4 py-3">
          <h2 className="text-sm font-black text-white/80">조작판</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full border border-white/15 px-3 py-1.5 text-xs font-bold text-white/65 hover:bg-white/10"
          >
            닫기 <span className="text-white/35">Esc</span>
          </button>
        </header>

        <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-4 pb-10 pt-5">
          <PrizeEditor prizes={state?.prizes ?? []} onSave={onSavePrizes} />

          <section>
            <h2 className="text-xs font-bold tracking-[0.2em] text-white/45">추첨 조건</h2>
            <div className="mt-2.5 space-y-2">
              <Toggle
                label="스태프 제외"
                checked={excludeStaff}
                onChange={onExcludeStaff}
                disabled={busy}
              />
              <Toggle
                label="중복 당첨 허용"
                checked={allowRepeat}
                onChange={onAllowRepeat}
                disabled={busy}
              />
              <Toggle
                label="키 없이 자동으로 멈춤"
                checked={autoStop}
                onChange={onAutoStop}
                disabled={busy}
                note="켜면 시작과 동시에 알아서 차례로 섭니다."
              />
              <Toggle label="소리 끄기" checked={muted} onChange={onMuted} />
            </div>

            {/*
              어느 자리에서 뽑는가. 번호는 본 행사 체크인 순서로만 주지만, 뒤풀이
              자리에서 낮에만 왔던 사람이 뽑히면 상품을 줄 사람이 없다. 자리를
              고르면 그 자리에 출석한 사람으로 후보가 좁혀지고, 나머지 번호는
              번호판에서 처음부터 꺼진 채로 보인다.
            */}
            <label className="mt-3 block">
              <span className="text-[11px] font-bold text-white/45">후보 범위</span>
              <select
                value={poolSession}
                onChange={(event) => onPoolSession(event.target.value)}
                disabled={busy}
                className="mt-1 w-full rounded-xl border border-white/15 bg-black/40 px-3 py-2 text-sm font-semibold text-white/85 disabled:opacity-40"
              >
                <option value="">번호를 받은 사람 전체</option>
                {(state?.sessions ?? []).map((session) => (
                  <option key={session.key} value={session.key}>
                    {session.label}에 출석한 사람만
                  </option>
                ))}
              </select>
              {poolSession && (
                <span className="mt-1 block text-[11px] leading-relaxed text-white/40 tabular">
                  그 자리에 {state?.counts.present ?? 0}명 출석 · 후보{' '}
                  {state?.counts.eligible ?? 0}명
                </span>
              )}
            </label>
          </section>

          {(state?.counts.issued ?? 0) === 0 && (
            <p className="rounded-xl border border-flame-400/40 bg-flame-400/12 px-3.5 py-2.5 text-xs font-semibold leading-relaxed text-flame-200">
              아직 번호를 받은 사람이 없습니다. 번호는 본 행사 체크인 때 발급되므로,
              관리자 &gt; 출석에서 체크인을 먼저 열어 주세요.
            </p>
          )}

          <section>
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-bold tracking-[0.2em] text-white/45">
                당첨 이력 {history.length > 0 && `(${history.length})`}
              </h2>
              {history.length > 0 && (
                <button
                  type="button"
                  onClick={onClearHistory}
                  disabled={busy}
                  title="시연으로 돌려 본 기록을 지우고 처음 상태로 되돌립니다"
                  className="rounded-full border border-brick-400/40 px-2.5 py-1 text-[11px] font-bold text-brick-400/85 hover:bg-brick-400/12 disabled:opacity-35"
                >
                  전체 삭제
                </button>
              )}
            </div>
            {history.length === 0 ? (
              <p className="mt-2 text-xs text-white/30">아직 추첨하지 않았습니다.</p>
            ) : (
              <ul className="mt-2.5 space-y-1.5">
                {history.map((record) => (
                  <li
                    key={record.id}
                    className="rounded-xl border border-white/10 px-3 py-2 text-xs"
                  >
                    <div className="flex items-baseline gap-2">
                      <span className="font-black tabular text-flame-300">{record.drawLabel}</span>
                      <span
                        className={`font-bold ${record.voided ? 'text-white/30 line-through' : ''}`}
                      >
                        {record.name ?? '(기록 없음)'}
                      </span>
                    </div>
                    <p className="mt-0.5 text-white/40">
                      {record.prize || `${record.roundNo}회차`}
                      {record.groupValue && ` · ${record.groupValue}`}
                    </p>
                    {record.voided ? (
                      <p className="mt-1 text-white/30">무효 — {record.voidedReason}</p>
                    ) : (
                      <button
                        type="button"
                        onClick={() => onVoid(record)}
                        className="mt-1.5 rounded-full border border-white/15 px-2.5 py-1 font-bold text-white/55 hover:bg-white/8"
                      >
                        무효 처리
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <Link
            to="/admin"
            className="block rounded-full border border-white/15 py-2 text-center text-xs font-bold text-white/60 hover:bg-white/8"
          >
            관리자 화면으로
          </Link>
        </div>
      </aside>
    </>
  )
}

type PrizeDraft = { id?: string; label: string; count: number }

/**
 * 상품 등록.
 *
 * 행사 전에 한 번에 넣어 두는 자리다. 당일에는 무대 아래에서 고르기만 한다.
 */
function PrizeEditor({
  prizes,
  onSave,
}: {
  prizes: DrawPrize[]
  onSave: (items: PrizeDraft[]) => Promise<DrawPrize[]>
}) {
  const [draft, setDraft] = useState<PrizeDraft[] | null>(null)
  const [busy, setBusy] = useState(false)

  const rows: PrizeDraft[] =
    draft ?? prizes.map((prize) => ({ id: prize.id, label: prize.label, count: prize.count }))
  const dirty = draft !== null

  const update = (index: number, patch: Partial<PrizeDraft>) => {
    setDraft(rows.map((row, position) => (position === index ? { ...row, ...patch } : row)))
  }

  const save = async () => {
    setBusy(true)
    try {
      await onSave(rows.filter((row) => row.label.trim()))
      setDraft(null)
    } catch (caught) {
      alert(caught instanceof Error ? caught.message : '상품을 저장하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-bold tracking-[0.2em] text-white/45">상품</h2>
        <button
          type="button"
          onClick={() => setDraft([...rows, { label: '', count: 1 }])}
          className="rounded-full border border-white/15 px-2.5 py-1 text-[11px] font-bold text-white/60 hover:bg-white/8"
        >
          + 추가
        </button>
      </div>

      {rows.length === 0 ? (
        <p className="mt-2 text-xs leading-relaxed text-white/30">
          미리 등록해 두면 추첨할 때 고르기만 하면 됩니다. 남은 수량도 알아서 셉니다.
        </p>
      ) : (
        <ul className="mt-2.5 space-y-1.5">
          {rows.map((row, index) => {
            const saved = prizes.find((prize) => prize.id === row.id)
            return (
              <li key={row.id ?? `new-${index}`} className="flex items-center gap-1.5">
                <input
                  className="min-w-0 flex-1 rounded-lg border border-white/15 bg-white/8 px-2.5 py-1.5 text-sm font-semibold text-white placeholder:text-white/30 focus:border-flame-300 focus:outline-none"
                  placeholder="상품 이름"
                  value={row.label}
                  maxLength={40}
                  onChange={(event) => update(index, { label: event.target.value })}
                />
                <input
                  type="number"
                  min={1}
                  max={999}
                  className="w-14 rounded-lg border border-white/15 bg-white/8 px-2 py-1.5 text-center text-sm font-bold tabular text-white focus:border-flame-300 focus:outline-none"
                  value={row.count}
                  onChange={(event) =>
                    update(index, { count: Math.max(1, Number(event.target.value) || 1) })
                  }
                />
                <button
                  type="button"
                  title={saved && saved.drawn > 0 ? `${saved.drawn}개 나감` : '지우기'}
                  onClick={() => setDraft(rows.filter((_, position) => position !== index))}
                  className="shrink-0 rounded-lg border border-white/12 px-2 py-1.5 text-xs font-bold text-white/45 hover:bg-white/8"
                >
                  ×
                </button>
              </li>
            )
          })}
        </ul>
      )}

      {dirty && (
        <div className="mt-2.5 flex gap-2">
          <button
            type="button"
            onClick={save}
            disabled={busy}
            className="flex-1 rounded-full bg-flame-300 py-1.5 text-xs font-black text-[#10161c] hover:bg-flame-200 disabled:opacity-40"
          >
            {busy ? '저장 중…' : '상품 저장'}
          </button>
          <button
            type="button"
            onClick={() => setDraft(null)}
            className="rounded-full border border-white/15 px-3 py-1.5 text-xs font-bold text-white/55 hover:bg-white/8"
          >
            되돌리기
          </button>
        </div>
      )}

      {prizes.some((prize) => prize.drawn > 0) && (
        <p className="mt-2 text-[11px] leading-relaxed text-white/30">
          이미 나간 상품을 목록에서 지워도 당첨 기록은 남습니다.
        </p>
      )}
    </section>
  )
}

function Toggle({
  label,
  checked,
  onChange,
  disabled,
  note,
}: {
  label: string
  checked: boolean
  onChange: (value: boolean) => void
  disabled?: boolean
  note?: string
}) {
  return (
    <label className={`block ${disabled ? 'text-white/25' : 'text-white/65'}`}>
      <span className="flex items-center gap-2 text-xs font-semibold">
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
        />
        {label}
      </span>
      {note && <span className="ml-6 block text-[11px] text-white/30">{note}</span>}
    </label>
  )
}
