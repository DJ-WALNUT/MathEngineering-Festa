/**
 * 현장 배정.
 *
 * 위쪽은 '무엇을 배정하는가'(항목 정의), 아래쪽은 '누구에게'(참가자별 값)다.
 * 조를 하나 만드는 일은 '조' 항목의 선택지에 한 줄 넣는 것과 같다.
 *
 * **기본 항목은 조 하나뿐이다.** 당일 행사라 숙소 호수도 버스도 없다. 그래도
 * 운영을 시작하면 분류가 더 필요해지므로(자리 · 조끼 색 · 담당 스태프…) 항목
 * 자체를 여기서 만들 수 있게 두었다 — 재배포가 필요하지 않다.
 *
 * 배정은 참가가 확정된 사람에게만 한다. 확정 전에 미리 조를 짜 두면
 * 입금이 끝내 확인되지 않은 사람이 조 편성에 남아 인원이 어긋난다.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  adminApi,
  type AdminParticipant,
  type AssignmentField,
  type AssignmentImportResult,
} from '../../lib/api'

/** 선택지 입력칸의 예시 문구. 기본 항목만 챙기고 나머지는 일반 문구를 쓴다. */
const OPTION_HINT: Record<string, string> = {
  group: '1조',
}

/** 목록 API 한 번에 받아올 수 있는 최대치(서버 상한과 같다). */
const PAGE_SIZE = 500

/** 여러 쪽에 걸친 명단을 한 번에 손에 쥔다. 기본값은 취소자·미확정자까지 전부다. */
async function fetchAllParticipants(
  params: Parameters<typeof adminApi.participants>[0] = {},
): Promise<AdminParticipant[]> {
  const first = await adminApi.participants({ ...params, pageSize: PAGE_SIZE })
  const items = [...first.items]
  for (let page = 2; page <= first.pagination.totalPages; page += 1) {
    const next = await adminApi.participants({ ...params, page, pageSize: PAGE_SIZE })
    items.push(...next.items)
  }
  return items
}

/**
 * 명단에서 사람 찾기.
 *
 * 서버에 매번 묻지 않고 이미 받아 둔 명단에서 거른다. 한 명 넣을 때마다 검색어를
 * 지우고 다시 치는 작업이라, 글자를 칠 때마다 결과가 즉시 따라와야 한다.
 */
function matches(participant: AdminParticipant, needle: string): boolean {
  const text = needle.trim().toLowerCase()
  if (!text) return true

  const digits = text.replace(/\D/g, '')
  return (
    participant.name.toLowerCase().includes(text) ||
    (participant.studentId ?? '').toLowerCase().includes(text) ||
    (participant.department ?? '').toLowerCase().includes(text) ||
    (digits.length >= 2 && participant.phone.includes(digits))
  )
}

/**
 * 선택지 이름 바꾸기.
 *
 * 배정에 쓰이고 있는 값은 목록에서 뺄 수 없다 — 빼면 그 사람의 배정이 갈 곳을
 * 잃기 때문이다. 그래서 이름 고치기는 '지우고 다시 만들기'가 아니라 '옮기기'다.
 *
 *   1. 새 이름을 선택지에 먼저 넣는다 (옛 이름은 그대로 둔다)
 *   2. 옛 이름으로 배정된 사람을 새 이름으로 옮긴다
 *   3. 아무도 쓰지 않게 된 옛 이름을 뺀다
 *
 * 중간에 끊겨도 두 이름이 잠깐 나란히 보일 뿐 누구의 배정도 사라지지 않는다.
 * 다시 누르면 아직 안 옮겨진 사람부터 이어서 처리한다.
 *
 * 배정 API 는 참가가 확정된 사람에게만 열려 있다. 확정이 풀린 뒤에도 옛 값을
 * 들고 있는 사람이 있으면 2 를 할 수 없으므로, 아무것도 건드리기 전에 멈춘다.
 */
async function renameOption(
  field: AssignmentField,
  from: string,
  to: string,
): Promise<number> {
  const renamed = field.options.map((item) => (item === from ? to : item))
  const holders = (await fetchAllParticipants()).filter(
    (participant) => participant.assignments[field.key] === from,
  )

  if (holders.length > 0 && !field.isActive) {
    throw new Error(
      `'${field.label}' 은(는) 사용 중지된 항목이라 배정을 옮길 수 없습니다. ` +
        '먼저 항목을 다시 사용으로 바꿔 주세요.',
    )
  }

  const blocked = holders.filter((participant) => !participant.isConfirmed)
  if (blocked.length > 0) {
    const names = blocked.slice(0, 3).map((participant) => participant.name).join(', ')
    throw new Error(
      `참가 확정이 아닌 ${blocked.length}명(${names}${blocked.length > 3 ? ' 외' : ''})이 ` +
        `'${from}' 을 갖고 있어 이름을 바꿀 수 없습니다. 참가자 탭에서 먼저 정리해 주세요.`,
    )
  }

  await adminApi.updateAssignmentField(field.id, { options: [...renamed, from] })
  for (const participant of holders) {
    await adminApi.updateParticipant(participant.id, { assignments: { [field.key]: to } })
  }
  await adminApi.updateAssignmentField(field.id, { options: renamed })
  return holders.length
}

export default function AssignmentsPanel({
  revision,
  onChanged,
}: {
  revision: number
  onChanged: () => void
}) {
  const [fields, setFields] = useState<AssignmentField[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const loadFields = useCallback(async () => {
    try {
      const response = await adminApi.assignmentFields()
      setFields(response.items)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '배정 항목을 불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadFields()
  }, [loadFields, revision])

  const activeFields = fields.filter((field) => field.isActive)

  return (
    <div className="space-y-6">
      {error && <p className="text-sm font-semibold text-brick-500">{error}</p>}

      {/* 항목이 바뀌면 아래 표의 드롭다운과 값이 함께 달라진다(이름 바꾸기는 참가자의
          배정값까지 건드린다). 그래서 이 패널만 다시 읽지 않고 화면 전체에 알린다. */}
      <FieldEditor fields={fields} loading={loading} onChanged={onChanged} />
      <SheetPanel onChanged={onChanged} />
      <BulkAssignPanel fields={activeFields} revision={revision} onChanged={onChanged} />
      <AssignmentTable fields={activeFields} revision={revision} onChanged={onChanged} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// 항목 정의
// ---------------------------------------------------------------------------

function FieldEditor({
  fields,
  loading,
  onChanged,
}: {
  fields: AssignmentField[]
  loading: boolean
  onChanged: () => void
}) {
  const [adding, setAdding] = useState(false)

  const run = async (task: Promise<unknown>) => {
    try {
      await task
      onChanged()
    } catch (caught) {
      alert(caught instanceof Error ? caught.message : '처리에 실패했습니다.')
    }
  }

  return (
    <section className="card p-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-black text-ink-900">배정 항목</h2>
          <p className="mt-1 text-xs leading-relaxed text-ink-500">
            선택지가 있는 항목은 여기에 값을 미리 만들어 두고 고릅니다. 조를 늘리려면 &lsquo;조&rsquo;에
            선택지를 추가하세요.
          </p>
        </div>
        <button type="button" className="btn-ghost shrink-0 text-xs" onClick={() => setAdding(true)}>
          + 항목 추가
        </button>
      </div>

      {loading ? (
        <p className="mt-4 text-sm text-ink-500">불러오는 중…</p>
      ) : (
        <ul className="mt-4 space-y-3">
          {fields.map((field) => (
            <FieldRow key={field.id} field={field} onRun={run} onChanged={onChanged} />
          ))}
        </ul>
      )}

      {adding && (
        <NewFieldForm
          onCancel={() => setAdding(false)}
          onSubmit={async (payload) => {
            await run(adminApi.createAssignmentField(payload))
            setAdding(false)
          }}
        />
      )}
    </section>
  )
}

function FieldRow({
  field,
  onRun,
  onChanged,
}: {
  field: AssignmentField
  onRun: (task: Promise<unknown>) => Promise<void>
  onChanged: () => void
}) {
  const [option, setOption] = useState('')
  // 이름을 고치는 중인 선택지. null 이면 아무것도 고치고 있지 않다.
  const [renaming, setRenaming] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [labelDraft, setLabelDraft] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const addOption = () => {
    const value = option.trim()
    if (!value || field.options.includes(value)) {
      setOption('')
      return
    }
    void onRun(adminApi.updateAssignmentField(field.id, { options: [...field.options, value] }))
    setOption('')
  }

  const removeOption = (target: string) => {
    void onRun(
      adminApi.updateAssignmentField(field.id, {
        options: field.options.filter((item) => item !== target),
      }),
    )
  }

  const startRename = (target: string) => {
    setRenaming(target)
    setDraft(target)
  }

  /**
   * 여러 번 부르는 작업이라 중간에 끊길 수 있다. 실패해도 목록을 다시 받아
   * '지금 어디까지 됐는지'를 화면에 그대로 보여 준다.
   */
  const submitRename = async () => {
    const from = renaming
    const to = draft.trim()
    if (!from || busy) return
    if (!to || to === from) {
      setRenaming(null)
      return
    }
    // 이미 있는 이름을 적었다면 두 선택지를 하나로 합치는 셈이 된다. 오타일 수도
    // 있으니 한 번 묻는다. (앞선 시도가 중간에 끊겨 두 이름이 함께 남았을 때
    // 다시 눌러 마무리하는 길도 여기다)
    if (
      field.options.includes(to) &&
      !confirm(`'${to}' 은(는) 이미 있습니다. '${from}' 에 배정된 사람을 '${to}' 로 합칠까요?`)
    ) {
      return
    }

    setBusy(true)
    try {
      const moved = await renameOption(field, from, to)
      setRenaming(null)
      if (moved > 0) alert(`'${from}' → '${to}' 로 바꾸고 ${moved}명의 배정을 옮겼습니다.`)
    } catch (caught) {
      alert(caught instanceof Error ? caught.message : '이름을 바꾸지 못했습니다.')
    } finally {
      setBusy(false)
      onChanged()
    }
  }

  const submitLabel = async () => {
    const next = (labelDraft ?? '').trim()
    if (!next || next === field.label) {
      setLabelDraft(null)
      return
    }
    setLabelDraft(null)
    void onRun(adminApi.updateAssignmentField(field.id, { label: next }))
  }

  return (
    <li className="rounded-2xl border-2 border-sand-200 bg-white px-4 py-3.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {labelDraft === null ? (
            <>
              <span className="text-sm font-black text-ink-900">{field.label}</span>
              <button
                type="button"
                className="text-xs font-semibold text-cobalt-600 hover:underline"
                onClick={() => setLabelDraft(field.label)}
              >
                이름 수정
              </button>
            </>
          ) : (
            <>
              <input
                className="input h-9 max-w-40 py-1 text-sm"
                value={labelDraft}
                autoFocus
                maxLength={30}
                onChange={(event) => setLabelDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    void submitLabel()
                  }
                  if (event.key === 'Escape') setLabelDraft(null)
                }}
              />
              <button
                type="button"
                className="btn-ghost px-3 py-1 text-xs"
                onClick={() => void submitLabel()}
              >
                저장
              </button>
              <button
                type="button"
                className="text-xs font-semibold text-ink-500 hover:underline"
                onClick={() => setLabelDraft(null)}
              >
                취소
              </button>
            </>
          )}
          <span className="rounded-full bg-sand-100 px-2 py-0.5 text-[11px] font-bold text-sand-700">
            {field.kind === 'choice' ? '선택지' : '자유 입력'}
          </span>
          {field.isSystem && (
            <span className="rounded-full border border-ink-400/30 px-2 py-0.5 text-[11px] font-semibold text-ink-500">
              기본
            </span>
          )}
        </div>

        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs font-semibold text-ink-500">
            <input
              type="checkbox"
              checked={field.showOnCheckin}
              onChange={(event) =>
                void onRun(
                  adminApi.updateAssignmentField(field.id, {
                    showOnCheckin: event.target.checked,
                  }),
                )
              }
            />
            체크인 화면에 표시
          </label>
          {!field.isSystem && (
            <button
              type="button"
              className="text-xs font-semibold text-brick-500 hover:underline"
              onClick={() => {
                if (!confirm(`'${field.label}' 항목과 이미 배정된 값을 모두 지울까요?`)) return
                void onRun(adminApi.deleteAssignmentField(field.id))
              }}
            >
              삭제
            </button>
          )}
        </div>
      </div>

      {field.kind === 'choice' && (
        <div className="mt-3">
          <div className="flex flex-wrap items-center gap-1.5">
            {field.options.map((item) =>
              renaming === item ? (
                <span key={item} className="flex items-center gap-1.5">
                  <input
                    className="input h-9 max-w-32 py-1 text-sm"
                    value={draft}
                    autoFocus
                    maxLength={20}
                    disabled={busy}
                    onChange={(event) => setDraft(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') {
                        event.preventDefault()
                        void submitRename()
                      }
                      if (event.key === 'Escape' && !busy) setRenaming(null)
                    }}
                  />
                  <button
                    type="button"
                    className="btn-ghost px-3 py-1 text-xs"
                    disabled={busy}
                    onClick={() => void submitRename()}
                  >
                    {busy ? '바꾸는 중…' : '저장'}
                  </button>
                  <button
                    type="button"
                    className="text-xs font-semibold text-ink-500 hover:underline disabled:opacity-45"
                    disabled={busy}
                    onClick={() => setRenaming(null)}
                  >
                    취소
                  </button>
                </span>
              ) : (
                <span
                  key={item}
                  className="flex items-center gap-1 rounded-full border-2 border-cobalt-200 bg-cobalt-50 py-1 pl-2.5 pr-1.5 text-xs font-bold text-cobalt-600"
                >
                  {/* 이름 고치기가 삭제보다 잦다. 값 자체를 눌러 바로 고칠 수 있게 둔다. */}
                  <button
                    type="button"
                    aria-label={`${item} 이름 수정`}
                    title="이름 수정"
                    className="hover:underline"
                    disabled={busy}
                    onClick={() => startRename(item)}
                  >
                    {item}
                  </button>
                  <button
                    type="button"
                    aria-label={`${item} 삭제`}
                    className="rounded-full px-1 text-cobalt-400 hover:text-brick-500"
                    disabled={busy}
                    onClick={() => removeOption(item)}
                  >
                    ×
                  </button>
                </span>
              ),
            )}
            {field.options.length === 0 && (
              <span className="text-xs text-ink-400">아직 선택지가 없습니다.</span>
            )}
          </div>

          <div className="mt-2 flex gap-2">
            <input
              className="input h-9 max-w-40 py-1 text-sm"
              value={option}
              onChange={(event) => setOption(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault()
                  addOption()
                }
              }}
              placeholder={OPTION_HINT[field.key] ?? '값 추가'}
              maxLength={20}
            />
            <button type="button" className="btn-ghost px-3 py-1 text-xs" onClick={addOption}>
              추가
            </button>
          </div>

          <p className="mt-2 text-xs leading-relaxed text-ink-400">
            선택지를 누르면 이름만 바꿉니다. 이미 배정된 사람은 새 이름으로 함께 옮겨져요.
          </p>
        </div>
      )}
    </li>
  )
}

function NewFieldForm({
  onCancel,
  onSubmit,
}: {
  onCancel: () => void
  onSubmit: (payload: {
    label: string
    kind: 'text' | 'choice'
    options: string[]
    showOnCheckin: boolean
  }) => Promise<void>
}) {
  const [label, setLabel] = useState('')
  const [kind, setKind] = useState<'text' | 'choice'>('text')
  const [options, setOptions] = useState('')
  const [showOnCheckin, setShowOnCheckin] = useState(true)
  const [busy, setBusy] = useState(false)

  return (
    <form
      className="mt-4 space-y-3 rounded-2xl border-2 border-cobalt-200 bg-cobalt-50 p-4"
      onSubmit={async (event) => {
        event.preventDefault()
        if (!label.trim() || busy) return
        setBusy(true)
        try {
          await onSubmit({
            label: label.trim(),
            kind,
            options: options
              .split(/[\n,]/)
              .map((item) => item.trim())
              .filter(Boolean),
            showOnCheckin,
          })
        } finally {
          setBusy(false)
        }
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="label" htmlFor="new-field-label">
            항목 이름
          </label>
          <input
            id="new-field-label"
            className="input"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            placeholder="예: 텐트 번호"
            maxLength={30}
            autoFocus
          />
        </div>
        <div>
          <label className="label" htmlFor="new-field-kind">
            종류
          </label>
          <select
            id="new-field-kind"
            className="input"
            value={kind}
            onChange={(event) => setKind(event.target.value as 'text' | 'choice')}
          >
            <option value="text">자유 입력</option>
            <option value="choice">선택지에서 고르기</option>
          </select>
        </div>
      </div>

      {kind === 'choice' && (
        <div>
          <label className="label" htmlFor="new-field-options">
            선택지 (쉼표 또는 줄바꿈으로 구분)
          </label>
          <textarea
            id="new-field-options"
            className="input min-h-16 resize-y"
            value={options}
            onChange={(event) => setOptions(event.target.value)}
            placeholder="1호차, 2호차, 3호차"
          />
        </div>
      )}

      <label className="flex items-center gap-2 text-sm font-semibold text-ink-600">
        <input
          type="checkbox"
          checked={showOnCheckin}
          onChange={(event) => setShowOnCheckin(event.target.checked)}
        />
        셀프 체크인 화면에서 참가자에게 보여주기
      </label>

      <div className="flex gap-2">
        <button type="submit" className="btn-primary px-4 py-2 text-sm" disabled={!label.trim() || busy}>
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
// 엑셀 왕복
// ---------------------------------------------------------------------------

/**
 * 양식 내려받기 → 엑셀에서 채우기 → 올리기.
 *
 * 조 편성은 대개 엑셀에서 끝난다. 그 결과를 화면에서 한 명씩 다시 고르게 두면
 * 편성을 두 번 하는 셈이라, 명단 그대로 내려받아 값만 채워 올리는 길을 둔다.
 * 양식의 열은 그때의 항목 정의로 만들어지므로 항목을 늘려도 따로 손댈 것이 없다.
 */
function SheetPanel({ onChanged }: { onChanged: () => void }) {
  const [busy, setBusy] = useState<'download' | 'upload' | null>(null)
  const [result, setResult] = useState<AssignmentImportResult | null>(null)
  const [error, setError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)

  const download = async () => {
    setBusy('download')
    setError('')
    try {
      await adminApi.downloadAssignmentTemplate()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '양식을 내려받지 못했습니다.')
    } finally {
      setBusy(null)
    }
  }

  const upload = async (file: File) => {
    setBusy('upload')
    setError('')
    setResult(null)
    try {
      setResult(await adminApi.importAssignments(file))
      onChanged()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '업로드에 실패했습니다.')
    } finally {
      setBusy(null)
      // 같은 파일을 고쳐 다시 올리는 일이 잦다. 값을 비워야 change 가 다시 온다.
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  return (
    <section className="card p-5">
      <h2 className="text-sm font-black text-ink-900">엑셀로 한 번에 배정</h2>
      <p className="mt-1 text-xs leading-relaxed text-ink-500">
        지금 확정자 명단과 배정 항목 그대로 양식을 만들어 드립니다. 엑셀에서 채운 뒤 그대로
        올리면 반영돼요. 선택지가 있는 항목은 엑셀에서도 목록에서 고르게 되어 있습니다.
      </p>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-ghost text-sm"
          disabled={busy !== null}
          onClick={() => void download()}
        >
          {busy === 'download' ? '만드는 중…' : '양식 내려받기'}
        </button>
        <input
          ref={fileInput}
          type="file"
          accept=".xlsx,.xlsm,.csv"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) void upload(file)
          }}
        />
        <button
          type="button"
          className="btn-ghost text-sm"
          disabled={busy !== null}
          onClick={() => fileInput.current?.click()}
        >
          {busy === 'upload' ? '반영 중…' : '채운 파일 올리기'}
        </button>
      </div>

      <ul className="mt-3 space-y-1 text-xs leading-relaxed text-ink-500">
        <li>
          · <strong className="font-bold text-ink-700">빈 칸은 건드리지 않습니다.</strong> 반쯤
          채워 올려도 나머지 배정은 그대로 남아요. 배정을 풀려면 그 칸에{' '}
          <code className="rounded bg-sand-100 px-1 font-bold">-</code> 라고 적어 주세요.
        </li>
        <li>· 참가자ID 열은 사람을 알아보는 열쇠입니다. 지웠다면 학번 · 이름으로 찾습니다.</li>
        <li>· 참가가 확정된 사람만 배정됩니다. 나머지는 건너뛰고 몇 행인지 알려 드려요.</li>
      </ul>

      {error && <p className="mt-3 text-sm font-semibold text-brick-500">{error}</p>}
      {result && <SheetImportSummary result={result} onClose={() => setResult(null)} />}
    </section>
  )
}

function SheetImportSummary({
  result,
  onClose,
}: {
  result: AssignmentImportResult
  onClose: () => void
}) {
  return (
    <div className="mt-4 rounded-2xl border-2 border-cobalt-200 bg-cobalt-50 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-black text-cobalt-600">{result.filename} 반영 완료</p>
          <p className="mt-1.5 text-sm font-semibold text-ink-700 tabular">
            {result.updated}명 배정 ({result.changedValues}건) · 그대로 {result.unchanged}명 ·
            건너뜀 {result.skippedCount}행
          </p>
          <p className="mt-1 text-xs text-ink-500">
            알아본 항목: {result.fields.length > 0 ? result.fields.join(' · ') : '없음'}
          </p>

          {result.skipped.length > 0 && (
            <details className="mt-2" open={result.updated === 0}>
              <summary className="cursor-pointer text-xs font-semibold text-ink-500">
                건너뛴 행 보기
              </summary>
              <ul className="mt-1.5 max-h-40 space-y-0.5 overflow-y-auto text-xs text-ink-600">
                {result.skipped.map((item) => (
                  <li key={item.row}>
                    {item.row}행 · {item.reason}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 text-sm font-semibold text-ink-400 hover:text-ink-700"
        >
          닫기
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 항목별 일괄 배정
// ---------------------------------------------------------------------------

/** 한 번에 그릴 후보 수. 넘으면 검색으로 좁히게 하고 몇 명이 더 있는지만 알린다. */
const CANDIDATE_LIMIT = 80

/**
 * 값 하나를 정해 놓고 사람을 모은다.
 *
 * 아래의 '참가자 배정'은 사람 한 명을 펼쳐 그 사람의 모든 항목을 채우는 화면이다.
 * 조를 짤 때는 방향이 반대다 — '1조'를 정해 두고 거기에 들어갈 사람을 하나씩
 * 찾는다. 사람마다 드롭다운을 열어 같은 값을 다시 고르는 일을 없애려고,
 * 값을 먼저 고른 뒤 검색 → 체크 → 한 번에 배정하는 길을 따로 둔다.
 *
 * 명단은 처음에 한 번만 받아 두고 검색은 화면 안에서 한다. 한 명 넣을 때마다
 * 검색어를 지우고 다시 치는 작업이라 글자마다 서버에 묻게 하면 손이 앞서 나간다.
 */
function BulkAssignPanel({
  fields,
  revision,
  onChanged,
}: {
  fields: AssignmentField[]
  revision: number
  onChanged: () => void
}) {
  const [fieldKey, setFieldKey] = useState('')
  const [value, setValue] = useState('')
  const [query, setQuery] = useState('')
  // 조를 처음 짤 때는 '아직 조가 없는 사람'만 보는 편이 훨씬 편하다.
  const [hideAssigned, setHideAssigned] = useState(true)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [people, setPeople] = useState<AdminParticipant[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')

  // 항목이 아직 안 왔거나 지워졌을 수 있다. 그때는 첫 항목으로 되돌린다.
  const field = fields.find((item) => item.key === fieldKey) ?? fields[0] ?? null

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      // 배정은 참가가 확정된 사람에게만 열려 있다 (서버가 거절한다).
      setPeople(await fetchAllParticipants({ confirmed: true }))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '명단을 불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, revision])

  /** 값별 현재 인원. 선택지 옆에 붙여 '몇 명 찼는지'를 고르기 전에 보여준다. */
  const counts = useMemo(() => {
    const map = new Map<string, number>()
    if (!field) return map
    for (const person of people) {
      const current = person.assignments[field.key]
      if (current) map.set(current, (map.get(current) ?? 0) + 1)
    }
    return map
  }, [people, field])

  const holders = useMemo(
    () => (field && value ? people.filter((item) => item.assignments[field.key] === value) : []),
    [people, field, value],
  )

  const candidates = useMemo(() => {
    if (!field) return []
    return people.filter(
      (item) =>
        // 이미 이 값인 사람은 위쪽 '현재 인원'에 있다. 후보에 또 내지 않는다.
        item.assignments[field.key] !== value &&
        (!hideAssigned || !item.assignments[field.key]) &&
        matches(item, query),
    )
  }, [people, field, value, hideAssigned, query])

  const targets = people.filter((item) => selected.has(item.id))

  const toggle = (id: number) =>
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const pickField = (key: string) => {
    setFieldKey(key)
    setValue('')
    setSelected(new Set())
    setNotice('')
  }

  const pickValue = (next: string) => {
    setValue(next)
    setSelected(new Set())
    setNotice('')
  }

  /**
   * 고른 사람들을 한 명씩 넣는다.
   *
   * 한 번에 보내는 API 가 없어 요청은 사람 수만큼 나간다. 중간에 하나가 실패해도
   * 나머지는 계속 넣고, 끝나서 누가 안 됐는지 이름으로 알린다 — 여기서 멈춰
   * 버리면 '어디까지 됐는지'를 사람이 다시 세어야 한다.
   */
  const assignSelected = async () => {
    if (!field || !value || busy || targets.length === 0) return

    setBusy(true)
    const failed: string[] = []
    let done = 0
    for (const person of targets) {
      try {
        await adminApi.updateParticipant(person.id, { assignments: { [field.key]: value } })
        done += 1
      } catch {
        failed.push(person.name)
      }
      setNotice(`${done + failed.length}/${targets.length}명 처리 중…`)
    }

    setSelected(new Set())
    setNotice(
      failed.length === 0
        ? `${done}명을 '${value}' 에 배정했습니다.`
        : `${done}명 배정 · ${failed.length}명 실패 (${failed.slice(0, 3).join(', ')}${
            failed.length > 3 ? ' 외' : ''
          })`,
    )
    await load()
    onChanged()
    setBusy(false)
  }

  const unassign = async (person: AdminParticipant) => {
    if (!field || busy) return
    setBusy(true)
    try {
      await adminApi.updateParticipant(person.id, { assignments: { [field.key]: '' } })
      setNotice(`${person.name} 님을 '${value}' 에서 뺐습니다.`)
      await load()
      onChanged()
    } catch (caught) {
      setNotice(caught instanceof Error ? caught.message : '배정을 풀지 못했습니다.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card p-5">
      <h2 className="text-sm font-black text-ink-900">항목별 일괄 배정</h2>
      <p className="mt-1 text-xs leading-relaxed text-ink-500">
        값을 먼저 고르고 사람을 찾아 한 번에 넣습니다. 참가가 확정된 사람만 나오고, 다른 값에
        배정되어 있던 사람은 고른 값으로 옮겨집니다.
      </p>

      {fields.length === 0 ? (
        <p className="mt-4 rounded-xl bg-sand-50 px-4 py-6 text-center text-sm text-ink-500">
          사용 중인 배정 항목이 없습니다. 위에서 항목을 먼저 만들어 주세요.
        </p>
      ) : (
        <>
          <div className="mt-4 flex flex-wrap gap-2">
            <select
              className="input h-10 max-w-40 py-1.5 text-sm"
              value={field?.key ?? ''}
              onChange={(event) => pickField(event.target.value)}
              aria-label="배정 항목"
            >
              {fields.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.label}
                </option>
              ))}
            </select>

            {field?.kind === 'choice' ? (
              <select
                className="input h-10 max-w-48 py-1.5 text-sm"
                value={value}
                onChange={(event) => pickValue(event.target.value)}
                aria-label={`${field.label} 값`}
              >
                <option value="">{field.label} 고르기</option>
                {field.options.map((option) => (
                  <option key={option} value={option}>
                    {option} · {counts.get(option) ?? 0}명
                  </option>
                ))}
              </select>
            ) : (
              <input
                className="input h-10 max-w-48 py-1.5 text-sm"
                value={value}
                // 자유 입력은 글자마다 값이 달라진다. 여기서 선택을 지우면
                // 사람을 먼저 골라 둔 경우 타이핑 한 번에 다 날아간다.
                onChange={(event) => {
                  setValue(event.target.value)
                  setNotice('')
                }}
                placeholder={`${field?.label ?? ''} 값 입력`}
                maxLength={20}
                aria-label={`${field?.label ?? ''} 값`}
              />
            )}
          </div>

          {field?.kind === 'choice' && field.options.length === 0 && (
            <p className="mt-3 text-xs font-semibold text-flame-600">
              &lsquo;{field.label}&rsquo; 에 선택지가 없습니다. 위에서 값을 먼저 추가해 주세요.
            </p>
          )}

          {error && <p className="mt-3 text-sm font-semibold text-brick-500">{error}</p>}
          {loading && <p className="mt-3 text-sm text-ink-500">명단 불러오는 중…</p>}

          {!loading && field && value && (
            <>
              <div className="mt-4 rounded-2xl border-2 border-sand-200 bg-sand-50/60 px-4 py-3">
                <p className="text-xs font-black text-ink-700">
                  현재 &lsquo;{value}&rsquo; 인원 {holders.length}명
                </p>
                {holders.length === 0 ? (
                  <p className="mt-1.5 text-xs text-ink-500">아직 아무도 없습니다.</p>
                ) : (
                  <ul className="mt-2 flex flex-wrap gap-1.5">
                    {holders.map((person) => (
                      <li
                        key={person.id}
                        className="flex items-center gap-1 rounded-full border border-sand-300 bg-white py-1 pl-2.5 pr-1.5 text-xs font-semibold text-ink-700"
                      >
                        <span>
                          {person.leaderPreference === 'want' && (
                            <span className="mr-1 text-gold-500" title="조장 희망">★</span>
                          )}
                          {person.name}
                          <span className="ml-1 text-ink-400 tabular">
                            {person.studentId ?? '학번 없음'}
                          </span>
                        </span>
                        <button
                          type="button"
                          aria-label={`${person.name} 배정 빼기`}
                          title="이 값에서 빼기"
                          className="rounded-full px-1 text-ink-400 hover:text-brick-500 disabled:opacity-45"
                          disabled={busy}
                          onClick={() => void unassign(person)}
                        >
                          ×
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="mt-4 flex flex-wrap items-center gap-2">
                <input
                  className="input h-10 max-w-56 py-1.5 text-sm"
                  placeholder="이름 · 학번 · 학과 · 전화번호"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
                <label className="flex items-center gap-1.5 text-xs font-semibold text-ink-500">
                  <input
                    type="checkbox"
                    checked={hideAssigned}
                    onChange={(event) => setHideAssigned(event.target.checked)}
                  />
                  {field.label} 미배정만 보기
                </label>
              </div>

              <p className="mt-3 text-xs font-semibold text-ink-500">
                후보 {candidates.length}명
                {candidates.length > CANDIDATE_LIMIT && ` (${CANDIDATE_LIMIT}명까지 표시)`}
              </p>

              {candidates.length === 0 ? (
                <p className="mt-2 rounded-xl bg-sand-50 px-4 py-6 text-center text-sm text-ink-500">
                  조건에 맞는 확정자가 없습니다.
                </p>
              ) : (
                <>
                  <button
                    type="button"
                    className="mt-2 text-xs font-semibold text-cobalt-600 hover:underline"
                    onClick={() =>
                      setSelected((current) => {
                        const next = new Set(current)
                        for (const person of candidates) next.add(person.id)
                        return next
                      })
                    }
                  >
                    후보 {candidates.length}명 모두 선택
                  </button>

                  <ul className="mt-2 space-y-1.5">
                    {candidates.slice(0, CANDIDATE_LIMIT).map((person) => {
                      const current = person.assignments[field.key]
                      const checked = selected.has(person.id)
                      return (
                        <li key={person.id}>
                          <label
                            className={`flex w-full cursor-pointer items-center gap-3 rounded-2xl border-2 px-3 py-2.5 transition ${
                              checked
                                ? 'border-cobalt-400 bg-cobalt-50'
                                : 'border-sand-200 bg-white hover:border-sand-300'
                            }`}
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => toggle(person.id)}
                              disabled={busy}
                            />
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-sm font-bold text-ink-900">
                                {person.name}
                                <span className="ml-2 text-xs font-semibold text-ink-500 tabular">
                                  {person.studentId ?? '학번 미기재'}
                                </span>
                                {/* 조마다 조장 한 명은 있어야 한다. 후보 목록에서 바로 보이게 한다. */}
                                {person.leaderPreference === 'want' && (
                                  <span className="ml-2 rounded-sm bg-gold-300 px-1.5 py-0.5 text-[11px] font-black text-ink-900">
                                    조장 희망
                                  </span>
                                )}
                                {person.leaderPreference === 'ok' && (
                                  <span className="ml-2 rounded-sm border border-gold-400 px-1.5 py-0.5 text-[11px] font-bold text-ink-700">
                                    조장 가능
                                  </span>
                                )}
                              </span>
                              <span className="block truncate text-xs text-ink-500">
                                {person.department ?? '학과 미기재'} · {person.phoneMasked}
                              </span>
                            </span>
                            {current && (
                              <span className="shrink-0 whitespace-nowrap rounded-full border border-flame-300 bg-flame-100 px-2 py-0.5 text-[11px] font-bold text-flame-600">
                                현재 {current}
                              </span>
                            )}
                          </label>
                        </li>
                      )
                    })}
                  </ul>
                </>
              )}

              <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-sand-200 pt-4">
                <button
                  type="button"
                  className="btn-primary px-4 py-2 text-sm"
                  disabled={busy || selected.size === 0}
                  onClick={() => void assignSelected()}
                >
                  {busy ? '배정 중…' : `선택한 ${selected.size}명을 '${value}' 로 배정`}
                </button>
                {selected.size > 0 && !busy && (
                  <button
                    type="button"
                    className="text-xs font-semibold text-ink-500 hover:underline"
                    onClick={() => setSelected(new Set())}
                  >
                    선택 해제
                  </button>
                )}
                {notice && <span className="text-xs font-semibold text-ink-600">{notice}</span>}
              </div>
            </>
          )}

          {!loading && field && !value && (
            <p className="mt-4 rounded-xl bg-sand-50 px-4 py-6 text-center text-sm text-ink-500">
              배정할 값을 먼저 고르면 여기에 사람 목록이 나옵니다.
            </p>
          )}
        </>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// 참가자별 배정
// ---------------------------------------------------------------------------

function AssignmentTable({
  fields,
  revision,
  onChanged,
}: {
  fields: AssignmentField[]
  revision: number
  onChanged: () => void
}) {
  const [query, setQuery] = useState('')
  const [unassigned, setUnassigned] = useState('')
  const [items, setItems] = useState<AdminParticipant[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const response = await adminApi.participants({
        query,
        confirmed: true,
        unassigned: unassigned || undefined,
        pageSize: 500,
      })
      setItems(response.items)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '명단을 불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }, [query, unassigned])

  useEffect(() => {
    const timer = setTimeout(load, query ? 250 : 0)
    return () => clearTimeout(timer)
  }, [load, revision])

  const assign = async (participant: AdminParticipant, key: string, value: string) => {
    try {
      await adminApi.updateParticipant(participant.id, { assignments: { [key]: value } })
      await load()
      onChanged()
    } catch (caught) {
      alert(caught instanceof Error ? caught.message : '배정에 실패했습니다.')
    }
  }

  return (
    <section className="card p-5">
      <h2 className="text-sm font-black text-ink-900">참가자 배정</h2>
      <p className="mt-1 text-xs leading-relaxed text-ink-500">
        참가가 확정된 사람만 나옵니다. 이름 · 학번 · 학과로 찾아 값을 고르면 바로 저장돼요.
      </p>

      <div className="mt-4 flex flex-wrap gap-2">
        <input
          className="input h-10 max-w-56 py-1.5 text-sm"
          placeholder="이름 · 전화번호 · 학번 검색"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <select
          className="input h-10 max-w-44 py-1.5 text-sm"
          value={unassigned}
          onChange={(event) => setUnassigned(event.target.value)}
        >
          <option value="">전체 확정자</option>
          {fields.map((field) => (
            <option key={field.key} value={field.key}>
              {field.label} 미배정만
            </option>
          ))}
        </select>
      </div>

      {error && <p className="mt-3 text-sm font-semibold text-brick-500">{error}</p>}
      <p className="mt-3 text-xs font-semibold text-ink-500">
        {loading ? '불러오는 중…' : `${items.length}명`}
      </p>

      {!loading && items.length === 0 && (
        <p className="mt-3 rounded-xl bg-sand-50 px-4 py-6 text-center text-sm text-ink-500">
          조건에 맞는 확정자가 없습니다. 참가자 탭에서 먼저 참가 확정을 눌러 주세요.
        </p>
      )}

      <ul className="mt-3 space-y-2">
        {items.map((participant) => (
          <li
            key={participant.id}
            className="rounded-2xl border-2 border-sand-200 bg-white px-4 py-3"
          >
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="text-sm font-black text-ink-900">{participant.name}</span>
              <span className="text-xs font-semibold text-ink-500 tabular">
                {participant.studentId ?? '학번 미기재'} · {participant.department ?? '학과 미기재'}
              </span>
              {participant.checkedInAt && (
                <span className="rounded-full bg-sand-100 px-2 py-0.5 text-[11px] font-bold text-sand-700">
                  출석
                </span>
              )}
            </div>

            <div className="mt-2.5 grid gap-2 sm:grid-cols-3">
              {fields.map((field) => (
                <label key={field.key} className="block">
                  <span className="text-[11px] font-bold text-ink-500">{field.label}</span>
                  {field.kind === 'choice' ? (
                    <select
                      className="input mt-0.5 h-9 py-1 text-sm"
                      value={participant.assignments[field.key] ?? ''}
                      onChange={(event) => assign(participant, field.key, event.target.value)}
                    >
                      <option value="">미배정</option>
                      {field.options.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      className="input mt-0.5 h-9 py-1 text-sm"
                      defaultValue={participant.assignments[field.key] ?? ''}
                      placeholder="미배정"
                      maxLength={20}
                      onBlur={(event) => {
                        const next = event.target.value.trim()
                        if (next !== (participant.assignments[field.key] ?? '')) {
                          void assign(participant, field.key, next)
                        }
                      }}
                    />
                  )}
                </label>
              ))}
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
