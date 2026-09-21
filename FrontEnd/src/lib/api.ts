/** 백엔드 API 클라이언트. */

const RAW_BASE = import.meta.env.VITE_API_BASE_URL ?? ''
// 개발 중 빈 값이면 vite 프록시(/api)를 그대로 탄다.
const API_BASE = RAW_BASE.replace(/\/+$/, '')

const TOKEN_KEY = 'mt.admin.token'

export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

export function getAdminToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY)
}

export function setAdminToken(token: string | null): void {
  if (token) sessionStorage.setItem(TOKEN_KEY, token)
  else sessionStorage.removeItem(TOKEN_KEY)
}

interface RequestOptions {
  method?: string
  body?: unknown
  auth?: boolean
  formData?: FormData
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, auth = false, formData } = options
  const headers: Record<string, string> = {}

  if (auth) {
    const token = getAdminToken()
    if (!token) throw new ApiError(401, 'unauthorized', '로그인이 필요합니다.')
    headers.Authorization = `Bearer ${token}`
  }
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  let response: Response
  try {
    response = await fetch(`${API_BASE}/api${path}`, {
      method,
      headers,
      body: formData ?? (body !== undefined ? JSON.stringify(body) : undefined),
    })
  } catch {
    throw new ApiError(0, 'network_error', '서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.')
  }

  if (response.status === 204) return undefined as T

  const contentType = response.headers.get('content-type') ?? ''
  if (!contentType.includes('application/json')) {
    if (!response.ok) {
      throw new ApiError(response.status, 'unexpected_response', '서버 응답을 처리하지 못했습니다.')
    }
    return (await response.text()) as T
  }

  const payload = await response.json()
  if (!response.ok) {
    if (response.status === 401 && auth) setAdminToken(null)
    throw new ApiError(
      response.status,
      payload?.error ?? 'error',
      payload?.message ?? '요청을 처리하지 못했습니다.',
    )
  }
  return payload as T
}

// --------------------------------------------------------------------------
// 공개
// --------------------------------------------------------------------------

export type PaymentStatus =
  | 'UNPAID'
  | 'PAID'
  | 'UNDERPAID'
  | 'OVERPAID'
  | 'REFUNDED'
  | 'WAIVED'

/**
 * 뒤풀이비 납입 상태. 본 행사비와 따로 센다.
 *
 * 뒤풀이비는 별도 안내로 나중에 걷으므로, 아직 안 낸 것이 본 행사의 '미납'으로
 * 번져서는 안 된다. 'NONE' 은 뒤풀이에 가지 않는 사람이다.
 */
export type AfterpartyStatus = 'NONE' | 'UNPAID' | 'UNDERPAID' | 'PAID'

export interface PublicParticipant {
  name: string
  isCouncilMember: boolean
  expectedAmount: number
  paidAmount: number
  remainingAmount: number
  status: PaymentStatus
  /** 본 행사 참가비. status 는 이 금액을 기준으로 판정된다. */
  baseFee: number
  basePaid: number
  joinsAfterparty: boolean
  afterpartyFee: number
  afterpartyPaid: number
  afterpartyStatus: AfterpartyStatus
  /** 본 행사비와 뒤풀이비를 한 번에 보낸 사람 */
  afterpartyPrepaid: boolean
  isCancelled: boolean
  /** 납입 완료와 별개다. 학생회가 명단을 확인하고 눌러야 확정된다. */
  isConfirmed: boolean
  confirmedAt: string | null
  lastPaidAt: string | null
  checkedAt: string
}

/**
 * 입금 반영 시점.
 *
 * 카카오뱅크 개인 계좌에는 공개 API가 없어 실시간 연동이 불가능하다.
 * 담당자가 거래내역 파일을 올린 시점까지만 반영되므로 화면에 그대로 알린다.
 */
export interface SyncState {
  hasData: boolean
  /** 담당자가 마지막으로 파일을 올린 시각 */
  lastImportedAt: string | null
  /** 그 파일에 담긴 마지막 거래 시각 — 실제로 어디까지 확인됐는지 */
  coverageUntil: string | null
}

export interface StatusResponse {
  found: boolean
  message?: string
  participant?: PublicParticipant
  sync: SyncState
}

export function lookupStatus(name: string, phone: string): Promise<StatusResponse> {
  return request<StatusResponse>('/status', { method: 'POST', body: { name, phone } })
}

export function fetchSyncStatus(): Promise<SyncState> {
  return request<SyncState>('/sync-status')
}

// --------------------------------------------------------------------------
// 셀프 체크인
// --------------------------------------------------------------------------

export type CheckInReason =
  | 'ok'
  | 'closed'
  | 'not_found'
  | 'cancelled'
  | 'not_confirmed'
  /** 뒤풀이처럼 대상이 좁은 회차에 신청하지 않은 사람이 왔을 때 */
  | 'not_in_session'
  | 'invalid_input'

export interface CheckInAssignment {
  key: string
  label: string
  value: string | null
}

export interface CheckInResponse {
  ok: boolean
  reason: CheckInReason
  message?: string
  alreadyCheckedIn?: boolean
  participant?: {
    name: string
    /**
     * 어느 자리에 찍혔는지. 본 행사와 뒤풀이가 같은 QR 을 쓰므로, 화면이
     * 말해 주지 않으면 참가자는 자기가 어디에 찍힌 것인지 알 수 없다.
     */
    sessionKey: string
    sessionLabel: string
    checkedInAt: string | null
    /** 럭키드로우 번호. 본 행사 체크인 순서대로 붙는다. 발급에 실패하면 null. */
    drawNo: number | null
    /** 같은 번호의 세 자리 표기 — 001, 042, 137 */
    drawLabel: string | null
    /** 개인 카드(/p/<token>) 주소. 명찰을 두고 왔을 때 자기 정보를 여는 길이다. */
    token: string | null
    assignments: CheckInAssignment[]
  }
}

export function submitCheckIn(payload: {
  name: string
  studentId: string
  phoneLast4: string
}): Promise<CheckInResponse> {
  return request<CheckInResponse>('/checkin', { method: 'POST', body: payload })
}

export interface CheckInState {
  open: boolean
  /** 지금 열려 있는 회차. 화면이 '본 행사 체크인' / '뒤풀이 체크인' 으로 갈린다. */
  sessionKey: string | null
  sessionLabel: string | null
  /**
   * 체크인 완료 화면에 '내 QR 열기' 버튼을 보일지.
   *
   * 저장해 둔 완료 화면이 아니라 **매번 이 응답**을 보고 결정한다. 저장본에
   * 박아 두면 관리자가 나중에 내려도 이미 체크인한 사람의 화면에는 남는다.
   */
  cardLink: boolean
}

export function fetchCheckInState(): Promise<CheckInState> {
  return request('/checkin/state')
}

// --------------------------------------------------------------------------
// 개인 카드 (명찰 QR 이 가리키는 화면)
// --------------------------------------------------------------------------

/**
 * 명찰의 QR 을 찍으면 열리는 화면의 내용.
 *
 * 명찰에 이미 인쇄된 것(이름 · 학과 · 조)과 출석 기록만 담는다. 이 주소는
 * 명찰을 손에 든 사람이면 누구나 열 수 있으므로, 명찰에 없는 것은 담기지 않는다.
 */
export interface PersonalCard {
  found: boolean
  token: string
  name: string
  department: string | null
  checkedInAt: string | null
  drawLabel: string | null
  joinsAfterparty: boolean
  assignments: CheckInAssignment[]
  /** 회차별 출석 기록 — 본 행사 · 뒤풀이 */
  checkins: { key: string; label: string; at: string }[]
}

export function fetchPersonalCard(token: string): Promise<PersonalCard> {
  return request(`/p/${encodeURIComponent(token)}`)
}

// --------------------------------------------------------------------------
// 관리자
// --------------------------------------------------------------------------

export type DepositStatus = 'UNMATCHED' | 'AMBIGUOUS' | 'MATCHED' | 'IGNORED' | 'MINOR'

/** 요금 구분. 총학생회비 납부 여부에 스태프가 하나 더 붙는다. */
export type FeeClass = 'member' | 'nonmember' | 'staff'

/** 조장 지원 여부 — 하고 싶다 / 해도 상관없다 / 하고 싶지 않다 */
export type LeaderPreference = 'want' | 'ok' | 'no'

export interface AdminAllocation {
  id: number
  depositId?: number
  participantId?: number
  participantName?: string | null
  participantPhoneMasked?: string | null
  amount: number
  depositRawName?: string | null
  occurredAt?: string | null
}

export interface AdminParticipant {
  id: number
  name: string
  phone: string
  phoneMasked: string
  studentId: string | null
  department: string | null
  gender: string | null
  emergencyPhone: string | null
  /** 민감정보(건강) — 현장 응급 대응용. 관리자만 볼 수 있다. */
  hasHealthIssue: boolean
  healthNote: string | null
  healthAction: string | null
  allergy: string | null
  portraitConsent: boolean
  intakeRound: string | null
  /** 폼에서 본인이 '입금했다'고 답한 값. 은행 내역과 다를 수 있다. */
  declaredPaid: boolean
  /** 참가 확정을 눌러도 되는 상태인가 (납입 완료·면제·초과 납입) */
  isSettled: boolean
  isConfirmed: boolean
  confirmedAt: string | null
  confirmedBy: string | null
  /** 배정값. 키는 AssignmentField.key */
  assignments: Record<string, string>
  groupNo: string | null
  /** 본 행사 회차의 출석 사본. 회차별 기록은 checkins 에 있다. */
  checkedInAt: string | null
  checkedInBy: string | null
  /** 회차별 출석. {회차 key: ISO 시각} */
  checkins: Record<string, string>
  /** 럭키드로우 번호. 체크인한 순서대로 붙고, 출석을 취소해도 회수하지 않는다. */
  drawNo: number | null
  drawLabel: string | null
  isCouncilMember: boolean
  isStaff: boolean
  /** 요금 구분 한 값 — 화면의 드롭다운은 이것만 다룬다. */
  feeClass: FeeClass
  /** 총 청구액 = 본 행사비 + (뒤풀이에 가면) 뒤풀이비 */
  expectedAmount: number
  paidAmount: number
  /** **본 행사비** 기준 납입 상태. 확정·배정·출석의 문을 여는 것은 이 값이다. */
  status: PaymentStatus
  baseFee: number
  basePaid: number
  joinsAfterparty: boolean
  afterpartyFee: number
  afterpartyPaid: number
  afterpartyStatus: AfterpartyStatus
  /** 안내가 나가기 전에 본 행사비와 한 번에 보낸 사람 — 배지가 붙는다 */
  afterpartyPrepaid: boolean
  /** 폼에서 '솔로파티 비용은 추후 안내'를 확인했다고 답했는가 */
  afterpartyFeeAcknowledged: boolean
  /** 1부 교류전 조장 지원 여부. 폼에 문항이 없으면 null. */
  leaderPreference: LeaderPreference | null
  /** 솔로파티에서 부를 이름. 명찰에 실을 수 있다. */
  nickname: string | null
  birthYear: number | null
  statusOverride: PaymentStatus | null
  declaredDepositor: string | null
  submittedAt: string | null
  /** 같은 전화번호로 폼을 제출한 횟수. 옛 스키마에서 올라온 행은 비어 있다. */
  submissionCount: number | null
  isCancelled: boolean
  memo: string | null
  extra: Record<string, unknown>
  allocations: AdminAllocation[]
}

export interface AdminDeposit {
  id: number
  occurredAt: string
  amount: number
  balanceAfter: number | null
  rawName: string
  digitSuffix: string
  source: string
  status: DepositStatus
  matchReason: string | null
  manualLocked: boolean
  memo: string | null
  allocatedAmount: number
  unallocatedAmount: number
  rawPayload: string | null
  allocations: AdminAllocation[]
}

export interface Pagination {
  page: number
  pageSize: number
  total: number
  totalPages: number
}

/** 배정 항목의 정의. 조 하나로 시작하고 관리자 화면에서 늘릴 수 있다. */
export interface AssignmentField {
  id: number
  key: string
  label: string
  kind: 'text' | 'choice'
  options: string[]
  position: number
  /** 조 — 지우거나 끌 수 없다 */
  isSystem: boolean
  showOnCheckin: boolean
  isActive: boolean
}

/**
 * 출석 회차.
 *
 * 하루짜리 행사인데도 출석이 한 번으로 끝나지 않는다 — 낮의 본 행사와, 신청자
 * 중 일부만 남는 저녁의 뒤풀이. 회차를 코드에 박지 않고 데이터로 두어, 자리가
 * 하나 더 생겨도 화면에서 만들면 되게 한다.
 */
export interface CheckinSession {
  id: number
  key: string
  label: string
  position: number
  /** 셀프 체크인 창구가 열려 있는지. 한 번에 하나만 열린다. */
  isOpen: boolean
  /** 뒤풀이 신청자만 대상인 회차인지. 현황의 분모도 그만큼 좁아진다. */
  afterpartyOnly: boolean
  /** 이 회차의 체크인 순서로 럭키드로우 번호를 매기는지. 본 행사에만 켠다. */
  givesDrawNo: boolean
  isSystem: boolean
  isActive: boolean
}

export interface AttendanceRow {
  id: number
  name: string
  phone: string
  department: string | null
  studentId: string | null
  groupValue: string | null
  checkedInAt: string | null
  checkedInBy: string | null
  joinsAfterparty: boolean
  afterpartyStatus: AfterpartyStatus
  /** 럭키드로우 번호. 현장에서 "내 번호가 뭐냐"는 질문에 답하는 값이다. */
  drawLabel: string | null
}

export interface AttendanceGroup {
  value: string | null
  label: string
  confirmed: number
  checkedIn: number
  notCheckedIn: number
  rate: number
}

export interface Attendance {
  /** 지금 보고 있는 회차 */
  session: CheckinSession
  /** 고를 수 있는 회차 전부 */
  sessions: CheckinSession[]
  open: boolean
  overall: {
    applicants: number
    confirmed: number
    checkedIn: number
    notCheckedIn: number
    rate: number
  }
  groupBy: { key: string | null; label: string | null }
  fields: { key: string; label: string }[]
  groups: AttendanceGroup[]
  checkedIn: AttendanceRow[]
  notCheckedIn: AttendanceRow[]
  generatedAt: string
}

// --------------------------------------------------------------------------
// 럭키드로우
// --------------------------------------------------------------------------

/** 후보에서 빠진 이유. 번호 타일을 어떻게 흐릴지 결정한다. */
export type DrawOutReason =
  | 'not_checked_in'
  | 'cancelled'
  | 'staff'
  | 'already_won'
  /** 번호는 받았지만 지금 추첨하는 자리(뒤풀이 등)에 오지 않은 사람 */
  | 'not_in_session'

/**
 * 번호 판의 타일 하나.
 *
 * **번호만 담는다.** 이 화면은 스크린에 띄우는 것이라, 이름을 함께 내리면
 * 명단이 그대로 공개되는 셈이 된다.
 */
export interface DrawTile {
  no: number
  label: string
  eligible: boolean
  out: DrawOutReason | null
}

/**
 * 미리 등록해 두는 상품.
 *
 * 진행자가 회차마다 이름을 타이핑하면 '1등 에어팟'과 '1등에어팟'이 섞여
 * 남은 수량 집계가 어긋난다. 행사 전에 목록으로 넣어 두고 당일에는 고르기만 한다.
 */
export interface DrawPrize {
  id: string
  label: string
  /** 준비한 개수 */
  count: number
  /** 이미 나간 개수 (무효 처리된 건은 세지 않는다) */
  drawn: number
  remaining: number
}

export interface DrawRecord {
  id: number
  roundNo: number
  prize: string
  /** 상품 목록의 어느 항목이었는지. 직접 입력했거나 상품 없이 뽑았으면 null. */
  prizeId: string | null
  drawNo: number
  drawLabel: string
  poolSize: number
  drawnAt: string
  actor: string
  voided: boolean
  voidedReason: string | null
  /** 당첨자를 부르기 위한 정보. 참가자 기록이 지워졌으면 null. */
  name: string | null
  department: string | null
  groupValue: string | null
}

export interface DrawState {
  /** 슬롯 자릿수. 기본 3 (001~999) */
  digits: number
  prizes: DrawPrize[]
  counts: {
    issued: number
    eligible: number
    checkedIn: number
    staff: number
    won: number
    /** 후보를 좁힌 회차에 실제로 출석한 인원. 좁히지 않았으면 null. */
    present: number | null
  }
  options: {
    excludeStaff: boolean
    allowRepeat: boolean
    /** 후보를 이 회차의 출석자로 좁힌다. 비우면 번호를 받은 사람 전체. */
    poolSession: string | null
  }
  sessions: CheckinSession[]
  nextRoundNo: number
  pool: DrawTile[]
  history: DrawRecord[]
}

export interface DrawOptions {
  excludeStaff?: boolean
  allowRepeat?: boolean
  poolSession?: string | null
}

export interface Summary {
  participants: {
    total: number
    active: number
    cancelled: number
    byStatus: Partial<Record<PaymentStatus, number>>
    paidRate: number
    /** 납입이 끝나 확정을 눌러도 되는 인원 */
    settled: number
    confirmed: number
    /** 납입은 끝났는데 아직 확정하지 않은 인원 */
    awaitingConfirm: number
    checkedIn: number
  }
  amounts: {
    expectedTotal: number
    collectedTotal: number
    depositedTotal: number
    unallocatedTotal: number
  }
  deposits: {
    byStatus: Partial<Record<DepositStatus, number>>
    needsReview: number
    /** 이름도 안 맞고 참가비에 한참 못 미치는 소액 — 확인 필요에서 분리된 건수 */
    minorCount: number
    minorThreshold: number
    lastDepositAt: string | null
    unparsedCount: number
  }
  /**
   * 뒤풀이는 참가비도 출석도 본 행사와 따로 센다.
   * 뒤풀이비는 별도 안내로 걷으므로 `unpaid` 가 곧 안내 대상이다.
   */
  afterparty: {
    fee: number
    joining: number
    paid: number
    unpaid: number
    /** 안내 전에 본 행사비와 한 번에 보낸 사람 — 다시 걷으러 가지 않는다 */
    prepaid: number
    expectedTotal: number
    collectedTotal: number
  }
  fees: {
    councilMember: number
    nonMember: number
    /** 스태프·뒤풀이 금액만 화면에서 고칠 수 있다 (늦게 정해지고 바뀌는 값이라) */
    staff: number
    staffCount: number
    afterparty: number
  }
  sync: SyncState & { lastFilename: string | null; pushIngestEnabled: boolean }
  generatedAt: string
}

export interface ImportRecord {
  id: number
  importedAt: string
  actor: string
  filename: string
  parsedRows: number
  createdCount: number
  duplicatedCount: number
  skippedCount: number
  periodFrom: string | null
  periodTo: string | null
  latestTransactionAt: string | null
}

/**
 * 변경 한 줄. 무엇을 · 무엇에서 · 무엇으로.
 *
 * 표시 문구는 백엔드가 만들어 보낸다. 로그는 그 자체로 완결된 기록이어야 해서,
 * 나중에 화면의 라벨이 바뀌어도 예전 기록은 그때의 표현대로 읽혀야 한다.
 */
export interface AuditChange {
  /** 전후가 없는 단발성 기록이면 null (예: '재매칭 12건') */
  field: string | null
  label: string
  from: string | null
  to: string | null
}

export interface AuditEntry {
  id: number
  at: string
  actor: string
  action: string
  targetType: string | null
  targetId: number | null
  /** 예전 기록은 이 형태가 아닐 수 있어 원본도 함께 남긴다. */
  detail: { target?: string; changes?: AuditChange[] } & Record<string, unknown>
}

export interface ImportResult {
  filename: string
  /** 비밀번호가 걸린 파일을 서버가 풀어서 읽었는지 */
  decrypted: boolean
  headerRow: number | null
  parsedRows: number
  created: number
  duplicated: number
  skipped: { row: number; reason: string }[]
  skippedCount: number
  periodFrom: string | null
  periodTo: string | null
  latestTransactionAt: string | null
  rematch: { processed: number; byStatus: Record<string, number> }
}

/**
 * 채워 온 배정 엑셀을 반영한 결과.
 *
 * 빈 칸은 건드리지 않으므로 `unchanged` 는 '아직 안 짠 사람'이 아니라
 * '적어 온 값이 이미 그대로였던 사람'이다.
 */
export interface AssignmentImportResult {
  filename: string
  /** 값이 하나라도 적혀 있던 행 수 */
  rows: number
  updated: number
  unchanged: number
  changedValues: number
  /** 파일에서 알아본 배정 항목. 열 이름을 고쳤다면 여기서 빠진다. */
  fields: string[]
  skipped: { row: number; reason: string }[]
  skippedCount: number
}

// --------------------------------------------------------------------------
// 개인 QR · 명찰 명단
// --------------------------------------------------------------------------

/** 명찰 인쇄가 쓰는 개인별 기본 정보. */
export interface RosterEntry {
  id: number
  /** 개인 QR 에 실리는 값. 명찰에 인쇄되고 개인 카드(/p/<token>)의 주소가 된다. */
  token: string | null
  name: string
  department: string | null
  studentId: string | null
  /** 명찰 앞면이 STAFF 로 나갈지 GUEST 로 나갈지 가르는 값 */
  isStaff: boolean
  groupValue: string | null
  joinsAfterparty: boolean
  /** 솔로파티에서 부를 이름. 명찰에 실을지는 인쇄 화면이 정한다. */
  nickname: string | null
  drawLabel: string | null
}

export interface RosterView {
  items: RosterEntry[]
  /** 이 요청에서 새로 발급된 토큰 수 */
  issued: number
  /** 체크인 완료 화면에 '내 QR 열기' 버튼이 보이는 중인지 */
  cardLinkVisible: boolean
  generatedAt: string
}

/** 파싱하지 못한 알림 원문 — 실제 카카오뱅크 문구를 확인하는 창구 */
export interface UnparsedNotification {
  id: number
  firstReceivedAt: string
  lastReceivedAt: string
  receiveCount: number
  preview: string
  reason: string
  resolved: boolean
  depositId: number | null
  payload: Record<string, unknown>
}

// --------------------------------------------------------------------------
// 관리자 계정 · 역할군 · 탭 권한
// --------------------------------------------------------------------------

/** 관리자 화면의 탭 하나. 목록과 이름표는 서버가 단일 진실이다. */
export interface AdminTab {
  key: string
  label: string
}

/**
 * 로그인 등급 — 어느 비밀번호로 들어오는지.
 *
 * 'lead' 는 최고 관리자·국장단, 'staff' 는 국원이다. 탭 권한이 화면을 정리하는
 * 것이라면 등급은 진짜 문이다 — 국원 비밀번호로는 국장단 계정이 열리지 않는다.
 */
export type AdminTier = 'lead' | 'staff'

export interface AdminTierInfo {
  key: AdminTier
  label: string
  envKey: string
}

/** 지금 로그인한 사람이 누구이고 무엇을 볼 수 있는지. */
export interface AdminSessionInfo {
  authenticated: boolean
  /** 작업 기록에 남는 이름 */
  actor: string
  username: string
  isSuper: boolean
  roleName: string | null
  /** 이 사람이 쓰는 비밀번호의 등급 */
  tier: AdminTier
  tierLabel: string
  /** 이 사람에게 열리는 탭 key */
  tabs: string[]
  tabLabels: AdminTab[]
}

export interface AdminAccount {
  id: number
  username: string
  displayName: string
  roleId: number | null
  roleName: string | null
  /** 개인별로 따로 준 탭. 비어 있으면 역할군을 따른다. */
  ownTabs: string[]
  /** 실제로 열리는 탭 (개인 지정 또는 역할군의 결과) */
  tabs: string[]
  isSuper: boolean
  isActive: boolean
  /** 이 사람이 쓰는 비밀번호의 등급. 역할군에서 정해져 내려온다. */
  tier: AdminTier
  lastLoginAt: string | null
}

export interface AdminRole {
  id: number
  name: string
  tabs: string[]
  /** 이 역할군의 사람들이 쓰는 비밀번호 */
  tier: AdminTier
  position: number
  memberCount: number
}

export const adminApi = {
  /**
   * 로그인.
   *
   * 비밀번호는 **등급마다 하나**다 (최고 관리자·국장단 / 국원). 어느 것을 요구할지는
   * 그 계정의 역할군이 정하고, 서버가 등급이 어긋난 로그인을 거절한다. ID 는 누가
   * 들어왔는지 밝히는 이름표라, 같은 등급 안에서는 남의 ID 로도 들어올 수 있다 —
   * 그 층의 목적은 차단이 아니라 작업 기록에 사람 이름을 남기는 것이다.
   */
  async login(username: string, password: string): Promise<AdminSessionInfo> {
    const result = await request<{ token: string } & AdminSessionInfo>('/admin/login', {
      method: 'POST',
      body: { username, password },
    })
    setAdminToken(result.token)
    return result
  },

  logout(): void {
    setAdminToken(null)
  },

  checkSession(): Promise<AdminSessionInfo> {
    return request('/admin/session', { auth: true })
  },

  /** 관리자·역할군 목록. 최고 관리자만 부를 수 있다. */
  admins(): Promise<{
    accounts: AdminAccount[]
    roles: AdminRole[]
    tabs: AdminTab[]
    tiers: AdminTierInfo[]
    /** 국원용 비밀번호가 .env 에 실제로 들어가 있는지 */
    tiersSeparated: boolean
    superUsername: string
  }> {
    return request('/admin/admins', { auth: true })
  },

  createAdmin(payload: {
    username: string
    displayName?: string
    roleId?: number | null
    tabs?: string[]
  }): Promise<AdminAccount> {
    return request('/admin/admins', { method: 'POST', body: payload, auth: true })
  },

  updateAdmin(id: number, patch: Record<string, unknown>): Promise<AdminAccount> {
    return request(`/admin/admins/${id}`, { method: 'PATCH', body: patch, auth: true })
  },

  deleteAdmin(id: number): Promise<{ ok: boolean }> {
    return request(`/admin/admins/${id}`, { method: 'DELETE', auth: true })
  },

  createRole(payload: { name: string; tabs?: string[]; tier?: AdminTier }): Promise<AdminRole> {
    return request('/admin/roles', { method: 'POST', body: payload, auth: true })
  },

  updateRole(id: number, patch: Record<string, unknown>): Promise<AdminRole> {
    return request(`/admin/roles/${id}`, { method: 'PATCH', body: patch, auth: true })
  },

  deleteRole(id: number): Promise<{ ok: boolean }> {
    return request(`/admin/roles/${id}`, { method: 'DELETE', auth: true })
  },

  summary(): Promise<Summary> {
    return request('/admin/summary', { auth: true })
  },

  participants(params: {
    query?: string
    status?: string
    page?: number
    pageSize?: number
    includeCancelled?: boolean
    /** true/false 는 확정 여부, 'pending' 은 '납입 완료 + 미확정' 만 */
    confirmed?: boolean | 'pending'
    staff?: boolean
    /**
     * true/false 는 뒤풀이 참가 여부, 'unpaid' 는 '뒤풀이 신청 + 뒤풀이비 미완납'.
     * 뒤풀이비는 별도 안내로 걷으므로 'unpaid' 가 곧 안내를 보낼 명단이다.
     */
    afterparty?: boolean | 'unpaid'
    /** 'want' 는 조장 희망자만, 'any' 는 희망 + 상관없음 */
    leader?: 'want' | 'any'
    /** 이 배정 항목의 값이 아직 없는 사람만 */
    unassigned?: string
    /** 폼을 두 번 이상 낸 사람만 */
    resubmitted?: boolean
    /** 관리자가 납입 상태를 손으로 지정해 둔 사람만 */
    overridden?: boolean
  }): Promise<{ items: AdminParticipant[]; pagination: Pagination }> {
    const search = new URLSearchParams()
    if (params.query) search.set('query', params.query)
    if (params.status) search.set('status', params.status)
    if (params.page) search.set('page', String(params.page))
    if (params.pageSize) search.set('pageSize', String(params.pageSize))
    if (params.includeCancelled === false) search.set('includeCancelled', 'false')
    if (params.confirmed !== undefined) search.set('confirmed', String(params.confirmed))
    if (params.staff !== undefined) search.set('staff', String(params.staff))
    if (params.afterparty !== undefined) search.set('afterparty', String(params.afterparty))
    if (params.leader) search.set('leader', params.leader)
    if (params.unassigned) search.set('unassigned', params.unassigned)
    if (params.resubmitted) search.set('resubmitted', 'true')
    if (params.overridden) search.set('overridden', 'true')
    return request(`/admin/participants?${search.toString()}`, { auth: true })
  },

  /**
   * 참가자 수기 등록.
   *
   * 전화번호가 자연키라 같은 번호가 이미 있으면 409 로 거절된다. 나중에 같은
   * 번호로 폼 응답이 들어오면 이 행이 갱신되므로 중복 인원이 남지 않는다.
   */
  createParticipant(payload: {
    name: string
    phone: string
    studentId?: string
    department?: string
    gender?: string
    emergencyPhone?: string
    feeClass?: FeeClass
    joinsAfterparty?: boolean
    expectedAmount?: number
    memo?: string
  }): Promise<{
    participant: AdminParticipant
    /** 이 사람 이름으로 남아 있던 미매칭 입금을 다시 태운 결과 */
    rematch: { processed: number; byStatus: Record<string, number> }
  }> {
    return request('/admin/participants', { method: 'POST', body: payload, auth: true })
  },

  /** 스태프 참가비를 정한다. 스태프 전원의 예상 금액이 함께 따라간다. */
  setStaffFee(amount: number): Promise<{ amount: number; applied: number }> {
    return request('/admin/staff-fee', { method: 'POST', body: { amount }, auth: true })
  },

  /** 뒤풀이 참가비를 정한다. 뒤풀이 신청자 전원의 예상 금액이 함께 따라간다. */
  setAfterpartyFee(amount: number): Promise<{ amount: number; applied: number }> {
    return request('/admin/afterparty-fee', { method: 'POST', body: { amount }, auth: true })
  },

  updateParticipant(id: number, patch: Record<string, unknown>): Promise<AdminParticipant> {
    return request(`/admin/participants/${id}`, { method: 'PATCH', body: patch, auth: true })
  },

  /** participantIds 를 생략하면 '납입 완료 + 미확정' 전원을 확정한다. */
  confirmParticipants(participantIds?: number[]): Promise<{ confirmed: number; skipped: number }> {
    return request('/admin/participants/confirm', {
      method: 'POST',
      body: participantIds ? { participantIds } : {},
      auth: true,
    })
  },

  assignmentFields(): Promise<{ items: AssignmentField[] }> {
    return request('/admin/assignment-fields', { auth: true })
  },

  createAssignmentField(payload: {
    label: string
    kind: 'text' | 'choice'
    options?: string[]
    showOnCheckin?: boolean
  }): Promise<AssignmentField> {
    return request('/admin/assignment-fields', { method: 'POST', body: payload, auth: true })
  },

  updateAssignmentField(id: number, patch: Record<string, unknown>): Promise<AssignmentField> {
    return request(`/admin/assignment-fields/${id}`, { method: 'PATCH', body: patch, auth: true })
  },

  deleteAssignmentField(id: number): Promise<{ ok: boolean; clearedValues: number }> {
    return request(`/admin/assignment-fields/${id}`, { method: 'DELETE', auth: true })
  },

  /**
   * 개인 토큰이 붙은 확정자 명단.
   *
   * 명찰 인쇄가 여기서 이름 · 학과 · 조 · QR 주소를 가져간다.
   * 토큰이 없는 사람은 이 요청에서 발급된다.
   */
  roster(): Promise<RosterView> {
    return request('/admin/roster', { auth: true })
  },

  /** 체크인 완료 화면의 '내 QR 열기' 버튼을 올리고 내린다. */
  setCardLink(visible: boolean): Promise<{ visible: boolean }> {
    return request('/admin/card-link', { method: 'POST', body: { visible }, auth: true })
  },

  /**
   * 행사 당일 접수대에서 받은 참가비를 넣는다.
   *
   * 계좌로 다시 보내게 하면 거래내역 파일을 또 올릴 때까지 확정이 열리지 않아
   * 줄이 선다. 금액을 비우면 아직 안 낸 만큼을 그대로 채운다.
   */
  recordOnsitePayment(
    participantId: number,
    payload: { amount?: number; method?: string; memo?: string } = {},
  ): Promise<{ ok: true; amount: number; deposit: AdminDeposit; participant: AdminParticipant }> {
    return request(`/admin/participants/${participantId}/onsite-payment`, {
      method: 'POST',
      body: payload,
      auth: true,
    })
  },

  checkinSessions(): Promise<{ items: CheckinSession[] }> {
    return request('/admin/checkin-sessions', { auth: true })
  },

  createCheckinSession(payload: {
    label: string
    afterpartyOnly?: boolean
  }): Promise<CheckinSession> {
    return request('/admin/checkin-sessions', { method: 'POST', body: payload, auth: true })
  },

  updateCheckinSession(id: number, patch: Record<string, unknown>): Promise<CheckinSession> {
    return request(`/admin/checkin-sessions/${id}`, { method: 'PATCH', body: patch, auth: true })
  },

  /** 이미 출석 기록이 있는 회차는 force 를 줘야 지워진다. */
  deleteCheckinSession(id: number, force = false): Promise<{ ok: boolean }> {
    return request(`/admin/checkin-sessions/${id}${force ? '?force=true' : ''}`, {
      method: 'DELETE',
      auth: true,
    })
  },

  attendance(session?: string, groupBy?: string): Promise<Attendance> {
    const search = new URLSearchParams()
    if (session) search.set('session', session)
    if (groupBy) search.set('groupBy', groupBy)
    const query = search.toString()
    return request(`/admin/attendance${query ? `?${query}` : ''}`, { auth: true })
  },

  /**
   * 관리자가 명단에서 눌러 출석을 남기거나 지운다.
   *
   * **창구가 닫혀 있어도 된다** — 사람이 직접 확인하고 누르는 것이기 때문이다.
   * 뒤풀이처럼 인원이 적고 자리가 어수선한 데서는 이쪽이 QR 보다 빠르다.
   */
  markAttendance(
    session: string,
    participantId: number,
    present: boolean,
  ): Promise<{ ok: true; changed: boolean; checkedInAt: string | null; drawLabel: string | null }> {
    return request(`/admin/attendance/check?session=${encodeURIComponent(session)}`, {
      method: 'POST',
      body: { participantId, present },
      auth: true,
    })
  },

  setCheckInWindow(open: boolean, session?: string): Promise<{ open: boolean }> {
    const search = session ? `?session=${encodeURIComponent(session)}` : ''
    return request(`/admin/checkin-window${search}`, {
      method: 'POST',
      body: { open },
      auth: true,
    })
  },

  drawState(options: DrawOptions = {}): Promise<DrawState> {
    const search = new URLSearchParams()
    if (options.excludeStaff) search.set('excludeStaff', 'true')
    if (options.allowRepeat) search.set('allowRepeat', 'true')
    if (options.poolSession) search.set('poolSession', options.poolSession)
    return request(`/admin/draw?${search.toString()}`, { auth: true })
  },

  /**
   * 한 명을 뽑는다. 결과는 이 호출로 이미 확정되고 DB 에 박힌다.
   *
   * 돌려받는 `state` 는 **뽑기 전** 판이다. 연출은 그 판으로 돌려야
   * 당첨자 타일이 살아 있는 상태에서 번호가 나온다.
   */
  /** 상품 목록을 통째로 갈아끼운다. 이미 나간 당첨 기록은 그대로 남는다. */
  setDrawPrizes(
    prizes: { id?: string; label: string; count: number }[],
  ): Promise<{ ok: true; state: DrawState }> {
    return request('/admin/draw/prizes', { method: 'PUT', body: { prizes }, auth: true })
  },

  createDraw(
    payload: { prize?: string; prizeId?: string } & DrawOptions,
  ): Promise<{ ok: true; draw: DrawRecord; state: DrawState }> {
    return request('/admin/draw', { method: 'POST', body: payload, auth: true })
  },

  voidDraw(id: number, reason: string): Promise<{ ok: true; state: DrawState }> {
    return request(`/admin/draw/${id}/void`, { method: 'POST', body: { reason }, auth: true })
  },

  /**
   * 당첨 기록을 전부 지운다 (시연 후 정리용). **되돌릴 수 없다.**
   * 지운 사실은 작업 기록에 남고, 체크인 번호는 그대로 유지된다.
   */
  clearDraws(): Promise<{ ok: true; deleted: number; state: DrawState }> {
    return request('/admin/draw', { method: 'DELETE', auth: true })
  },

  deposits(params: {
    status?: string
    query?: string
    page?: number
    pageSize?: number
  }): Promise<{ items: AdminDeposit[]; pagination: Pagination }> {
    const search = new URLSearchParams()
    if (params.status) search.set('status', params.status)
    if (params.query) search.set('query', params.query)
    if (params.page) search.set('page', String(params.page))
    if (params.pageSize) search.set('pageSize', String(params.pageSize))
    return request(`/admin/deposits?${search.toString()}`, { auth: true })
  },

  createDeposit(payload: {
    rawName: string
    amount: number
    occurredAt?: string
    balanceAfter?: number
    memo?: string
  }): Promise<{ created: boolean; deposit: AdminDeposit }> {
    return request('/admin/deposits', { method: 'POST', body: payload, auth: true })
  },

  updateDeposit(id: number, patch: Record<string, unknown>): Promise<AdminDeposit> {
    return request(`/admin/deposits/${id}`, { method: 'PATCH', body: patch, auth: true })
  },

  allocate(
    id: number,
    allocations: { participantId: number; amount?: number }[],
    allowOverAllocation = false,
  ): Promise<AdminDeposit> {
    return request(`/admin/deposits/${id}/allocations`, {
      method: 'PUT',
      body: { allocations, allowOverAllocation },
      auth: true,
    })
  },

  clearAllocations(id: number): Promise<AdminDeposit> {
    return request(`/admin/deposits/${id}/allocations`, { method: 'DELETE', auth: true })
  },

  async importStatement(file: File): Promise<ImportResult> {
    const formData = new FormData()
    formData.append('file', file)
    return request('/admin/deposits/import', { method: 'POST', formData, auth: true })
  },

  rematch(onlyUnresolved = true): Promise<{ processed: number; byStatus: Record<string, number> }> {
    return request('/admin/rematch', { method: 'POST', body: { onlyUnresolved }, auth: true })
  },

  imports(): Promise<{ items: ImportRecord[] }> {
    return request('/admin/imports', { auth: true })
  },

  unparsedNotifications(): Promise<{ items: UnparsedNotification[] }> {
    return request('/admin/notifications', { auth: true })
  },

  reparseNotifications(): Promise<{ attempted: number; recovered: number }> {
    return request('/admin/notifications/reparse', { method: 'POST', auth: true })
  },

  dismissNotification(id: number): Promise<{ ok: boolean }> {
    return request(`/admin/notifications/${id}`, { method: 'DELETE', auth: true })
  },

  audit(limit = 100): Promise<{ items: AuditEntry[] }> {
    return request(`/admin/audit?limit=${limit}`, { auth: true })
  },

  downloadParticipantsCsv(): Promise<void> {
    return download(
      '/admin/export/participants.csv',
      `participants-${today()}.csv`,
      '명단을 내려받지 못했습니다.',
    )
  },

  /** 지금 배정 항목과 확정자 명단으로 만든 배정 양식(xlsx). */
  downloadAssignmentTemplate(): Promise<void> {
    return download(
      '/admin/assignments/template.xlsx',
      `assignments-${today()}.xlsx`,
      '배정 양식을 내려받지 못했습니다.',
    )
  },

  /** 채워 온 배정 엑셀(xlsx/csv)을 반영한다. */
  importAssignments(file: File): Promise<AssignmentImportResult> {
    const formData = new FormData()
    formData.append('file', file)
    return request('/admin/assignments/import', { method: 'POST', formData, auth: true })
  },
}

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

/** Bearer 인증이 필요하므로 링크가 아니라 fetch → Blob 으로 내려받는다. */
async function download(path: string, filename: string, failureMessage: string): Promise<void> {
  const token = getAdminToken()
  if (!token) throw new ApiError(401, 'unauthorized', '로그인이 필요합니다.')

  const response = await fetch(`${API_BASE}/api${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) {
    throw new ApiError(response.status, 'export_failed', failureMessage)
  }

  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
