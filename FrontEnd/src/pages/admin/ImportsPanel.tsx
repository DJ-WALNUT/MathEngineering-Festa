import { useCallback, useEffect, useRef, useState } from 'react'

import {
  adminApi,
  type ImportRecord,
  type ImportResult,
  type UnparsedNotification,
} from '../../lib/api'
import { formatDateTime } from '../../lib/format'

/**
 * 거래내역 업로드 — 유일한 입금 수집 경로.
 *
 * 카카오뱅크 개인 계좌에는 공개 API가 없고, 유심 없는 공기계로는 앱 로그인조차
 * 되지 않아 알림 포워딩을 쓸 수 없다. 그래서 담당자가 주기적으로 거래내역
 * 파일을 내려받아 여기에 올리는 것이 전부다.
 */
export default function ImportsPanel({
  revision,
  onChanged,
}: {
  revision: number
  onChanged: () => void
}) {
  const [records, setRecords] = useState<ImportRecord[]>([])
  const [unparsed, setUnparsed] = useState<UnparsedNotification[]>([])
  const [result, setResult] = useState<ImportResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [history, notifications] = await Promise.all([
        adminApi.imports(),
        adminApi.unparsedNotifications().catch(() => ({ items: [] })),
      ])
      setRecords(history.items)
      setUnparsed(notifications.items)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '이력을 불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, revision])

  const upload = async (file: File) => {
    setUploading(true)
    setResult(null)
    try {
      setResult(await adminApi.importStatement(file))
      onChanged()
    } catch (caught) {
      alert(caught instanceof Error ? caught.message : '업로드에 실패했습니다.')
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  const latest = records[0]

  return (
    <div className="space-y-5">
      <div className="card p-6">
        <h2 className="text-base font-black text-ink-900">거래내역 파일 올리기</h2>
        <ol className="mt-3 space-y-1.5 text-sm leading-relaxed text-ink-600">
          <li>1. 카카오뱅크 앱 → 계좌 → 거래내역 → 조회기간 설정 → 내역 내려받기(엑셀)</li>
          <li>2. 받은 파일을 아래에 올리면 입금이 자동으로 대조됩니다.</li>
          <li>3. 기간이 겹치게 받아도 됩니다. 이미 등록된 입금은 자동으로 걸러집니다.</li>
        </ol>
        <p className="mt-2.5 text-xs leading-relaxed text-ink-500">
          비밀번호가 걸린 파일도 그대로 올리면 됩니다. 서버에 등록된 비밀번호로 알아서 열기
          때문에, 따로 해제해서 다시 저장할 필요가 없습니다.
        </p>

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
          className="btn-primary mt-5"
          onClick={() => fileInput.current?.click()}
          disabled={uploading}
        >
          {uploading ? '올리는 중…' : '거래내역 파일 선택'}
        </button>

        {latest && (
          <p className="mt-4 text-xs text-ink-500">
            마지막 반영 · {formatDateTime(latest.importedAt)}
            {latest.latestTransactionAt &&
              ` · ${formatDateTime(latest.latestTransactionAt)}까지의 입금 확인됨`}
          </p>
        )}
      </div>

      {result && <UploadResult result={result} onClose={() => setResult(null)} />}

      {unparsed.length > 0 && (
        <div className="card border-brick-400/50 bg-brick-400/8 p-5">
          <p className="text-sm font-black text-brick-500">
            해석하지 못한 알림 {unparsed.length}건
          </p>
          <p className="mt-1 text-xs leading-relaxed text-ink-600">
            예전 알림 포워딩으로 들어온 원문입니다. 원문은 보관되어 있으니 필요하면 확인하세요.
          </p>
          <ul className="mt-3 space-y-1.5">
            {unparsed.map((entry) => (
              <li key={entry.id} className="flex items-start justify-between gap-3">
                <span className="min-w-0 break-words text-xs text-ink-700">{entry.preview}</span>
                <button
                  type="button"
                  className="btn-ghost shrink-0 px-2.5 py-1 text-[11px]"
                  onClick={async () => {
                    await adminApi.dismissNotification(entry.id)
                    onChanged()
                  }}
                >
                  치우기
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && <p className="text-sm font-semibold text-brick-500">{error}</p>}
      {loading && <p className="text-sm text-ink-500">불러오는 중…</p>}

      {!loading && (
        <div>
          <h3 className="mb-2 text-sm font-black text-ink-800">업로드 이력</h3>
          {records.length === 0 ? (
            <p className="card p-8 text-center text-sm text-ink-500">
              아직 올린 파일이 없습니다.
            </p>
          ) : (
            <ul className="space-y-2">
              {records.map((record) => (
                <li key={record.id} className="card px-4 py-3">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="min-w-0 break-all text-sm font-bold text-ink-900">
                      {record.filename}
                    </span>
                    <span className="text-xs text-ink-400 tabular">
                      {formatDateTime(record.importedAt)}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-ink-600 tabular">
                    입금 {record.parsedRows}건 중 신규 {record.createdCount} · 중복{' '}
                    {record.duplicatedCount} · 제외 {record.skippedCount}
                  </p>
                  {(record.periodFrom || record.latestTransactionAt) && (
                    <p className="mt-0.5 text-xs text-ink-400 tabular">
                      {record.periodFrom && record.periodTo && (
                        <>
                          조회기간 {formatDateTime(record.periodFrom)} ~{' '}
                          {formatDateTime(record.periodTo)}
                        </>
                      )}
                      {record.latestTransactionAt && (
                        <> · 마지막 거래 {formatDateTime(record.latestTransactionAt)}</>
                      )}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

function UploadResult({ result, onClose }: { result: ImportResult; onClose: () => void }) {
  return (
    <div className="card border-cobalt-200 bg-cobalt-50 p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="break-all text-sm font-black text-cobalt-600">
            {result.filename} 반영 완료
          </p>
          <p className="mt-1.5 text-sm font-semibold text-ink-700 tabular">
            신규 {result.created}건 · 중복 {result.duplicated}건 · 제외 {result.skippedCount}건
          </p>
          {result.decrypted && (
            <p className="mt-1 text-xs text-ink-500">비밀번호가 걸린 파일을 열어서 읽었습니다.</p>
          )}
          {result.latestTransactionAt && (
            <p className="mt-1 text-xs text-ink-600">
              {formatDateTime(result.latestTransactionAt)}까지의 입금이 확인되었습니다.
            </p>
          )}
          <p className="mt-1 text-xs text-ink-500">
            재매칭 {result.rematch.processed}건 처리됨
          </p>
          {result.skipped.length > 0 && (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs font-semibold text-ink-500">
                제외된 행 보기 (출금 · 형식 오류)
              </summary>
              <ul className="mt-1.5 max-h-40 space-y-0.5 overflow-y-auto text-xs text-ink-500">
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
