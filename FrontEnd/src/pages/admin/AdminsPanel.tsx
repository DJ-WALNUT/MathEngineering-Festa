/**
 * 관리자 · 역할군 · 탭 권한 · 로그인 등급 (최고 관리자 전용).
 *
 * 지금까지 관리자는 하나였다. 비밀번호를 아는 사람은 모두 같은 &lsquo;admin&rsquo;
 * 이었고 작업 기록도 그 한 이름으로 남았다 — 몇 달 뒤 "이건 누가 왜 이렇게
 * 했지"를 되짚을 수 없다는 뜻이다.
 *
 * 구분은 세 겹이고, 그중 **진짜 문은 하나**다.
 *
 *   등급 (국장단 / 국원)        ← 비밀번호가 갈린다. 이것만이 실제 잠금장치다
 *     └ 역할군 (학생회장 · 국장 …)  ← 사람이 바뀌어도 그대로인 것. 등급도 여기서 정한다
 *         └ 개인 지정              ← 그 사람만 예외로 둘 때
 *
 * 탭 권한은 각자에게 필요한 화면만 보이게 하는 정리이지, **같은 등급 안에서**
 * 서로를 막는 장치가 아니다 — 이 화면은 그 사실을 숨기지 않는다.
 */

import { useCallback, useEffect, useState } from 'react'

import {
  adminApi,
  type AdminAccount,
  type AdminRole,
  type AdminTab,
  type AdminTier,
  type AdminTierInfo,
} from '../../lib/api'
import { formatDateTime } from '../../lib/format'

export default function AdminsPanel({
  revision,
  onChanged,
}: {
  revision: number
  onChanged: () => void
}) {
  const [accounts, setAccounts] = useState<AdminAccount[]>([])
  const [roles, setRoles] = useState<AdminRole[]>([])
  const [tabs, setTabs] = useState<AdminTab[]>([])
  const [tiers, setTiers] = useState<AdminTierInfo[]>([])
  const [tiersSeparated, setTiersSeparated] = useState(true)
  const [superUsername, setSuperUsername] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [adding, setAdding] = useState(false)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [query, setQuery] = useState('')

  const needle = query.trim().toLowerCase()
  const visible = needle
    ? accounts.filter(
        (account) =>
          account.displayName.toLowerCase().includes(needle) ||
          account.username.toLowerCase().includes(needle) ||
          (account.roleName ?? '').toLowerCase().includes(needle),
      )
    : accounts

  const load = useCallback(async () => {
    setError('')
    try {
      const response = await adminApi.admins()
      setAccounts(response.accounts)
      setRoles(response.roles)
      setTabs(response.tabs)
      setTiers(response.tiers)
      setTiersSeparated(response.tiersSeparated)
      setSuperUsername(response.superUsername)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '관리자 목록을 불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, revision])

  const act = async (task: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await task()
      await load()
      onChanged()
    } catch (caught) {
      alert(caught instanceof Error ? caught.message : '처리하지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      <section className="card border-flame-200 bg-flame-100/50 p-5">
        <p className="text-sm font-black text-flame-600">비밀번호는 두 개, 나머지는 정리입니다</p>
        <p className="mt-1.5 text-xs leading-relaxed text-ink-600">
          <strong className="text-ink-800">등급</strong>이 실제 잠금장치입니다. 국장단
          비밀번호와 국원 비밀번호가 따로 있고, 등급이 어긋난 로그인은 서버가 막습니다 —
          국원에게 알려 준 비밀번호로는 국장단 계정에 들어올 수 없습니다. 등급은{' '}
          <strong className="text-ink-800">역할군</strong>에 매기므로, 사람이 바뀌어도
          역할군만 맞추면 됩니다.
        </p>
        <p className="mt-2 text-xs leading-relaxed text-ink-600">
          반면 <strong className="text-ink-800">로그인 ID 와 탭 권한은 잠금장치가 아닙니다.</strong>{' '}
          ID 는 작업 기록에 누가 했는지 남기는 이름표이고, 탭은 각자에게 필요한 화면만 보이게
          하는 정리입니다 (같은 등급 안에서는 남의 ID 로도 들어올 수 있습니다). 다만{' '}
          <strong className="text-ink-800">이 화면만은 최고 관리자에게만 열립니다</strong> —
          권한을 스스로 올리는 길까지 열어 두면 구분 자체가 무의미해지니까요.
        </p>
      </section>

      {!loading && !tiersSeparated && (
        <section className="card border-brick-300 bg-brick-50 p-5">
          <p className="text-sm font-black text-brick-600">아직 두 비밀번호가 갈리지 않았습니다</p>
          <p className="mt-1.5 text-xs leading-relaxed text-ink-600">
            서버의 <code className="rounded bg-white px-1 font-bold">.env</code> 에{' '}
            <code className="rounded bg-white px-1 font-bold">STAFF_PASSWORD_HASH</code> 가 비어
            있어, 지금은 <strong className="text-ink-800">국원도 국장단과 같은 비밀번호</strong>로
            들어옵니다. 아래에서 정한 등급은 그 값을 넣는 순간부터 실제로 작동합니다.
          </p>
          <p className="mt-2 text-xs leading-relaxed text-ink-500">
            만드는 법 :{' '}
            <code className="rounded bg-white px-1 font-bold">
              python scripts/hash_password.py --staff
            </code>{' '}
            → 출력된 한 줄을 <code className="rounded bg-white px-1 font-bold">.env</code> 에
            붙이고 백엔드 컨테이너를 다시 시작합니다.
          </p>
        </section>
      )}

      {error && <p className="text-sm font-semibold text-brick-500">{error}</p>}
      {loading && <p className="text-sm text-ink-500">불러오는 중…</p>}

      {!loading && (
        <>
          <section className="card p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-sm font-black text-ink-900">관리자 {accounts.length}명</h2>
                <p className="mt-1 text-xs leading-relaxed text-ink-500">
                  로그인 ID 는 보통 본인 이름입니다. 그 이름이 그대로 작업 기록에 남아요.
                </p>
              </div>
              <button
                type="button"
                className="btn-ghost shrink-0 text-xs"
                onClick={() => setAdding((open) => !open)}
              >
                + 관리자 추가
              </button>
            </div>

            {adding && (
              <NewAdminForm
                roles={roles}
                tiers={tiers}
                onCancel={() => setAdding(false)}
                onSubmit={async (payload) => {
                  await act(() => adminApi.createAdmin(payload))
                  setAdding(false)
                }}
              />
            )}

            <div className="mt-4 flex flex-wrap items-center gap-2">
              <input
                className="input flex-1 sm:max-w-xs"
                placeholder="이름 · 로그인 ID · 역할군 검색"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
              {needle && (
                <span className="text-xs font-semibold text-ink-500 tabular">
                  {visible.length}명 / {accounts.length}명
                </span>
              )}
            </div>

            {/* 인원이 늘면 이 목록만으로 화면이 끝나 버린다. 목록 안에서 스크롤한다. */}
            <ul className="mt-3 max-h-[26rem] space-y-2 overflow-y-auto pr-1">
              {visible.map((account) => (
                <AccountRow
                  key={account.id}
                  account={account}
                  roles={roles}
                  tabs={tabs}
                  tiers={tiers}
                  busy={busy}
                  expanded={expandedId === account.id}
                  onToggle={() =>
                    setExpandedId(expandedId === account.id ? null : account.id)
                  }
                  onAct={act}
                />
              ))}
              {visible.length === 0 && (
                <li className="rounded-xl bg-sand-50 px-4 py-6 text-center text-sm text-ink-500">
                  검색 결과가 없습니다.
                </li>
              )}
            </ul>
          </section>

          <RolesSection roles={roles} tabs={tabs} tiers={tiers} busy={busy} onAct={act} />

          <p className="text-xs leading-relaxed text-ink-400">
            최고 관리자 ID 는 <strong className="font-bold text-ink-500">{superUsername}</strong>{' '}
            입니다. 지우거나 중지할 수 없고, 모든 탭이 항상 열립니다.
          </p>
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 관리자 한 명
// ---------------------------------------------------------------------------

function AccountRow({
  account,
  roles,
  tabs,
  tiers,
  busy,
  expanded,
  onToggle,
  onAct,
}: {
  account: AdminAccount
  roles: AdminRole[]
  tabs: AdminTab[]
  tiers: AdminTierInfo[]
  busy: boolean
  expanded: boolean
  onToggle: () => void
  onAct: (task: () => Promise<unknown>) => Promise<void>
}) {
  const labels = new Map(tabs.map((tab) => [tab.key, tab.label]))
  const custom = account.ownTabs.length > 0
  const role = roles.find((item) => item.id === account.roleId) ?? null

  return (
    <li className="card overflow-hidden">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-start justify-between gap-3 px-4 py-3.5 text-left"
      >
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-black text-ink-900">{account.displayName}</span>
            <span className="text-xs font-semibold text-ink-500">{account.username}</span>
            {account.isSuper && (
              <span className="whitespace-nowrap rounded-full bg-flame-200 px-2 py-0.5 text-[11px] font-black text-flame-600">
                최고 관리자
              </span>
            )}
            {account.roleName && (
              <span className="whitespace-nowrap rounded-full bg-sand-100 px-2 py-0.5 text-[11px] font-bold text-sand-700">
                {account.roleName}
              </span>
            )}
            <TierBadge tier={account.tier} tiers={tiers} />
            {custom && (
              <span className="whitespace-nowrap rounded-full border border-heart-400/40 bg-heart-400/12 px-2 py-0.5 text-[11px] font-semibold text-heart-500">
                개인 지정
              </span>
            )}
            {!account.isActive && (
              <span className="whitespace-nowrap rounded-full border border-ink-400/40 bg-ink-400/10 px-2 py-0.5 text-[11px] font-semibold text-ink-500">
                중지
              </span>
            )}
          </span>
          <span className="mt-0.5 block truncate text-xs text-ink-500">
            {account.tabs.map((key) => labels.get(key) ?? key).join(' · ') || '열람 권한 없음'}
          </span>
        </span>
        <span className="shrink-0 text-xs text-ink-400 tabular">
          {account.lastLoginAt ? formatDateTime(account.lastLoginAt) : '로그인 기록 없음'}
        </span>
      </button>

      {expanded && (
        <div className="space-y-4 border-t border-sand-200 bg-sand-50/40 px-4 py-4">
          {account.isSuper ? (
            <p className="text-xs leading-relaxed text-ink-500">
              최고 관리자는 모든 탭이 열려 있고 권한을 바꿀 수 없습니다. 이름만 고칠 수 있어요.
              언제나 국장단 비밀번호로 들어옵니다.
            </p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="label" htmlFor={`role-${account.id}`}>
                  역할군
                </label>
                <select
                  id={`role-${account.id}`}
                  className="input"
                  value={account.roleId ?? ''}
                  disabled={busy}
                  onChange={(event) =>
                    void onAct(() =>
                      adminApi.updateAdmin(account.id, {
                        roleId: event.target.value ? Number(event.target.value) : null,
                      }),
                    )
                  }
                >
                  <option value="">(없음)</option>
                  {roles.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-xs leading-relaxed text-ink-400">
                  {role
                    ? `'${role.name}' 은(는) ${tierLabelOf(role.tier, tiers)} 비밀번호를 씁니다. 바꾸려면 아래 역할군에서 옮겨 주세요.`
                    : '역할군이 없으면 국원 비밀번호로 들어옵니다.'}
                </p>
              </div>

              <div>
                <label className="label" htmlFor={`name-${account.id}`}>
                  이름 (작업 기록에 남는 값)
                </label>
                <input
                  id={`name-${account.id}`}
                  className="input"
                  defaultValue={account.displayName}
                  disabled={busy}
                  onBlur={(event) => {
                    const next = event.target.value.trim()
                    if (next && next !== account.displayName) {
                      void onAct(() => adminApi.updateAdmin(account.id, { displayName: next }))
                    }
                  }}
                />
              </div>
            </div>
          )}

          {!account.isSuper && (
            <TabPicker
              tabs={tabs}
              selected={account.ownTabs}
              busy={busy}
              title="개인 지정 탭"
              hint={
                custom
                  ? '이 사람만 따로 정한 탭입니다. 모두 끄면 역할군을 그대로 따릅니다.'
                  : '지금은 역할군의 권한을 따릅니다. 여기서 고르면 그 사람만 예외가 됩니다.'
              }
              onChange={(next) => void onAct(() => adminApi.updateAdmin(account.id, { tabs: next }))}
            />
          )}

          {!account.isSuper && (
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="btn-ghost text-xs"
                disabled={busy}
                onClick={() =>
                  void onAct(() =>
                    adminApi.updateAdmin(account.id, { isActive: !account.isActive }),
                  )
                }
              >
                {account.isActive ? '사용 중지' : '다시 사용'}
              </button>
              <button
                type="button"
                className="text-xs font-semibold text-brick-500 hover:underline"
                disabled={busy}
                onClick={() => {
                  if (!confirm(`${account.displayName} 님의 계정을 지울까요?`)) return
                  void onAct(() => adminApi.deleteAdmin(account.id))
                }}
              >
                계정 삭제
              </button>
              <span className="self-center text-xs text-ink-400">
                지워도 작업 기록에 남은 이름은 그대로입니다.
              </span>
            </div>
          )}
        </div>
      )}
    </li>
  )
}

function NewAdminForm({
  roles,
  tiers,
  onCancel,
  onSubmit,
}: {
  roles: AdminRole[]
  tiers: AdminTierInfo[]
  onCancel: () => void
  onSubmit: (payload: { username: string; displayName: string; roleId: number | null }) => Promise<void>
}) {
  const [username, setUsername] = useState('')
  const [roleId, setRoleId] = useState<string>('')
  const [busy, setBusy] = useState(false)

  // 어느 비밀번호를 알려 줘야 하는지는 고른 역할군이 정한다. 만들면서 바로 보인다.
  const picked = roles.find((role) => String(role.id) === roleId) ?? null

  return (
    <form
      className="mt-4 space-y-3 rounded-2xl border-2 border-cobalt-200 bg-cobalt-50 p-4"
      onSubmit={async (event) => {
        event.preventDefault()
        if (!username.trim() || busy) return
        setBusy(true)
        try {
          await onSubmit({
            username: username.trim(),
            displayName: username.trim(),
            roleId: roleId ? Number(roleId) : null,
          })
          setUsername('')
        } finally {
          setBusy(false)
        }
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="label" htmlFor="new-admin-username">
            이름 (로그인 ID)
          </label>
          <input
            id="new-admin-username"
            className="input"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="홍길동"
            maxLength={40}
            autoFocus
          />
        </div>
        <div>
          <label className="label" htmlFor="new-admin-role">
            역할군
          </label>
          <select
            id="new-admin-role"
            className="input"
            value={roleId}
            onChange={(event) => setRoleId(event.target.value)}
          >
            <option value="">(없음 — 아무 탭도 열리지 않음)</option>
            {roles.map((role) => (
              <option key={role.id} value={role.id}>
                {role.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      <p className="text-xs leading-relaxed text-ink-500">
        이 이름으로 로그인합니다. 비밀번호는{' '}
        <strong className="font-bold text-ink-700">
          {tierLabelOf(picked?.tier ?? 'staff', tiers)}
        </strong>{' '}
        비밀번호를 알려 주세요 — 역할군이 정합니다.
      </p>

      <div className="flex gap-2">
        <button type="submit" className="btn-primary px-4 py-2 text-sm" disabled={!username.trim() || busy}>
          {busy ? '만드는 중…' : '만들기'}
        </button>
        <button type="button" className="btn-ghost px-4 py-2 text-sm" onClick={onCancel}>
          취소
        </button>
      </div>
    </form>
  )
}

// ---------------------------------------------------------------------------
// 역할군
// ---------------------------------------------------------------------------

/**
 * 역할군.
 *
 * 권한을 사람마다 매기면 인원이 바뀔 때마다 다시 짜야 한다. 역할에 매기고 사람을
 * 역할에 넣으면, 국원이 열 명이어도 한 번만 정하면 된다 — 역할의 탭을 고치는 순간
 * 그 역할을 쓰는 사람 전원의 화면이 함께 바뀐다.
 */
function RolesSection({
  roles,
  tabs,
  tiers,
  busy,
  onAct,
}: {
  roles: AdminRole[]
  tabs: AdminTab[]
  tiers: AdminTierInfo[]
  busy: boolean
  onAct: (task: () => Promise<unknown>) => Promise<void>
}) {
  const [name, setName] = useState('')

  return (
    <section className="card p-5">
      <h2 className="text-sm font-black text-ink-900">역할군</h2>
      <p className="mt-1 text-xs leading-relaxed text-ink-500">
        역할의 탭을 고치면 그 역할을 쓰는 사람 전원의 화면이 함께 바뀝니다. 사람이 바뀌어도
        권한을 다시 짤 필요가 없어요. <strong className="text-ink-700">등급</strong>도 여기서
        정합니다 — 등급을 옮기면 그 사람들이 쓰는 <strong className="text-ink-700">비밀번호가
        바뀌므로</strong> 옮긴 뒤 알려 주어야 합니다.
      </p>

      <ul className="mt-4 space-y-3">
        {roles.map((role) => (
          <li key={role.id} className="rounded-2xl border-2 border-sand-200 bg-white px-4 py-3.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <input
                  className="input h-9 max-w-36 py-1 text-sm font-black"
                  defaultValue={role.name}
                  maxLength={40}
                  disabled={busy}
                  aria-label={`${role.name} 이름`}
                  onBlur={(event) => {
                    const next = event.target.value.trim()
                    if (next && next !== role.name) {
                      void onAct(() => adminApi.updateRole(role.id, { name: next }))
                    }
                  }}
                />
                <span className="rounded-full bg-sand-100 px-2 py-0.5 text-[11px] font-bold text-sand-700">
                  {role.memberCount}명
                </span>
                <TierPicker
                  tiers={tiers}
                  value={role.tier}
                  busy={busy}
                  label={`${role.name} 등급`}
                  onChange={(next) => {
                    const to = tierLabelOf(next, tiers)
                    const people =
                      role.memberCount > 0 ? `${role.memberCount}명이 ` : ''
                    if (
                      !confirm(
                        `'${role.name}' 을(를) ${to} 등급으로 옮길까요?\n\n` +
                          `${people}지금부터 ${to} 비밀번호로 로그인하게 됩니다.`,
                      )
                    ) {
                      return
                    }
                    void onAct(() => adminApi.updateRole(role.id, { tier: next }))
                  }}
                />
              </div>
              <button
                type="button"
                className="text-xs font-semibold text-brick-500 hover:underline"
                disabled={busy}
                onClick={() => {
                  if (!confirm(`'${role.name}' 역할군을 지울까요?`)) return
                  void onAct(() => adminApi.deleteRole(role.id))
                }}
              >
                삭제
              </button>
            </div>

            <TabPicker
              tabs={tabs}
              selected={role.tabs}
              busy={busy}
              onChange={(next) => void onAct(() => adminApi.updateRole(role.id, { tabs: next }))}
            />
          </li>
        ))}
        {roles.length === 0 && (
          <li className="rounded-xl bg-sand-50 px-4 py-6 text-center text-sm text-ink-500">
            역할군이 없습니다. 아래에서 만들어 주세요.
          </li>
        )}
      </ul>

      <form
        className="mt-3 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          const next = name.trim()
          if (!next) return
          setName('')
          void onAct(() => adminApi.createRole({ name: next, tabs: [] }))
        }}
      >
        <input
          className="input h-9 max-w-40 py-1 text-sm"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="역할군 추가"
          maxLength={40}
        />
        <button type="submit" className="btn-ghost px-3 py-1 text-xs" disabled={!name.trim() || busy}>
          추가
        </button>
      </form>
    </section>
  )
}

// ---------------------------------------------------------------------------
// 등급
// ---------------------------------------------------------------------------

/** 등급 이름표. 목록은 서버가 단일 진실이라, 없으면 최소한의 기본값만 쓴다. */
function tierLabelOf(tier: AdminTier, tiers: AdminTierInfo[]): string {
  return tiers.find((item) => item.key === tier)?.label ?? shortTierLabel(tier)
}

/** 배지·버튼처럼 좁은 자리에서 쓰는 짧은 이름. 긴 이름표는 title 로 붙인다. */
function shortTierLabel(tier: AdminTier): string {
  return tier === 'lead' ? '국장단' : '국원'
}

/** 이 사람이 어느 비밀번호로 들어오는지. 목록에서 한눈에 갈리게 색을 나눈다. */
function TierBadge({ tier, tiers }: { tier: AdminTier; tiers: AdminTierInfo[] }) {
  const lead = tier === 'lead'
  return (
    <span
      className={`whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-black ${
        lead
          ? 'bg-cobalt-100 text-cobalt-600'
          : 'border border-ink-300/50 bg-white text-ink-500'
      }`}
      title={`${tierLabelOf(tier, tiers)} 비밀번호로 로그인합니다`}
    >
      {shortTierLabel(tier)}
    </span>
  )
}

/**
 * 역할군의 등급 고르기.
 *
 * 탭 체크박스와 달리 **누르는 순간 비밀번호가 바뀌는** 선택이라, 바로 반영하지 않고
 * 부모에서 한 번 물어본 뒤 저장한다.
 */
function TierPicker({
  tiers,
  value,
  busy,
  label,
  onChange,
}: {
  tiers: AdminTierInfo[]
  value: AdminTier
  busy: boolean
  label: string
  onChange: (next: AdminTier) => void
}) {
  // 등급 목록도 서버가 단일 진실이다. 아직 못 받았을 때만 최소한의 기본값을 쓴다.
  const options: AdminTier[] = tiers.length ? tiers.map((item) => item.key) : ['lead', 'staff']

  return (
    <span className="inline-flex overflow-hidden rounded-full border-2 border-sand-200" role="group" aria-label={label}>
      {options.map((key) => {
        const on = value === key
        return (
          <button
            key={key}
            type="button"
            disabled={busy}
            aria-pressed={on}
            onClick={() => !on && onChange(key)}
            title={`${tierLabelOf(key, tiers)} 비밀번호`}
            className={`px-2.5 py-0.5 text-[11px] font-bold transition ${
              on
                ? key === 'lead'
                  ? 'bg-cobalt-400 text-white'
                  : 'bg-ink-400 text-white'
                : 'bg-white text-ink-400 hover:bg-sand-50'
            }`}
          >
            {shortTierLabel(key)}
          </button>
        )
      })}
    </span>
  )
}

/** 탭 체크박스 한 줄. 역할군과 개인 지정이 같은 모양을 쓴다. */
function TabPicker({
  tabs,
  selected,
  busy,
  title,
  hint,
  onChange,
}: {
  tabs: AdminTab[]
  selected: string[]
  busy: boolean
  title?: string
  hint?: string
  onChange: (next: string[]) => void
}) {
  // '관리자' 탭은 최고 관리자 전용이라 나눠 줄 수 있는 대상이 아니다.
  const grantable = tabs.filter((tab) => tab.key !== 'admins')

  const toggle = (key: string) => {
    const next = selected.includes(key)
      ? selected.filter((item) => item !== key)
      : [...selected, key]
    onChange(grantable.filter((tab) => next.includes(tab.key)).map((tab) => tab.key))
  }

  return (
    <div className="mt-3">
      {title && <p className="text-[11px] font-bold text-ink-500">{title}</p>}
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {grantable.map((tab) => {
          const on = selected.includes(tab.key)
          return (
            <button
              key={tab.key}
              type="button"
              disabled={busy}
              aria-pressed={on}
              onClick={() => toggle(tab.key)}
              className={`rounded-full border-2 px-3 py-1 text-xs font-bold transition ${
                on
                  ? 'border-cobalt-400 bg-cobalt-50 text-cobalt-600'
                  : 'border-sand-200 bg-white text-ink-400 hover:border-sand-300'
              }`}
            >
              {tab.label}
            </button>
          )
        })}
      </div>
      {hint && <p className="mt-1.5 text-xs leading-relaxed text-ink-400">{hint}</p>}
    </div>
  )
}
