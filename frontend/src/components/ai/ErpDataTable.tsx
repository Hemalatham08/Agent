import { StatusBadge } from '../ui/StatusBadge'
import { formatNumber } from '../../lib/format'
import type { TableCellKind, ErpTableSpec } from '../../lib/erpTables'

interface ErpDataTableProps {
  spec: ErpTableSpec
}

function formatCellValue(value: unknown): string {
  if (value === null || value === undefined) {
    return '—'
  }
  if (typeof value === 'string') {
    return value.trim() === '' ? '—' : value
  }
  if (typeof value === 'number') {
    return Number.isFinite(value) ? formatNumber(value) : String(value)
  }
  if (typeof value === 'boolean') {
    return value ? 'Yes' : 'No'
  }
  return '—'
}

function isTruthyFlag(value: unknown): boolean {
  return value === true || value === 1 || value === 'true'
}

function CellValue({
  value,
  kind,
}: {
  value: unknown
  kind: TableCellKind
}) {
  if (kind === 'status') {
    const text = formatCellValue(value)
    if (text === '—') {
      return <span className="text-slate-400">—</span>
    }
    return <StatusBadge status={text} />
  }

  if (kind === 'low-stock') {
    const lowStock = isTruthyFlag(value)
    return <StatusBadge status={lowStock ? 'Low Stock' : 'Healthy'} />
  }

  if (kind === 'barcode') {
    const verified = isTruthyFlag(value)
    return <StatusBadge status={verified ? 'Verified' : 'Not verified'} />
  }

  const text = formatCellValue(value)

  if (kind === 'issue') {
    return (
      <span
        className={
          text === '—'
            ? 'text-slate-400'
            : 'font-medium text-amber-700'
        }
      >
        {text}
      </span>
    )
  }

  return (
    <span className={text === '—' ? 'text-slate-400' : undefined}>
      {text}
    </span>
  )
}

export function ErpDataTable({ spec }: ErpDataTableProps) {
  const recordLabel = spec.rows.length === 1 ? 'record' : 'records'

  return (
    <div
      data-testid="erp-data-table"
      data-table-id={spec.id}
      className="mt-3 min-w-0 overflow-hidden rounded-xl border border-slate-200 bg-white"
    >
      {spec.title ? (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 bg-slate-50/80 px-3 py-2">
          <p className="text-[11px] font-semibold text-slate-600">
            {spec.title}
          </p>
          <p className="text-[10px] font-medium text-slate-400">
            {formatNumber(spec.rows.length)} {recordLabel}
            {spec.truncated ? ' · showing a partial list' : ''}
          </p>
        </div>
      ) : null}

      <div className="scrollbar-thin overflow-x-auto">
        <table className="min-w-full border-collapse text-left">
          <thead>
            <tr>
              {spec.columns.map((column) => (
                <th
                  key={column.key}
                  scope="col"
                  className="whitespace-nowrap border-b border-slate-100 bg-slate-50/60 px-3 py-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400"
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {spec.rows.map((row, rowIndex) => (
              <tr
                key={`${spec.id}-row-${rowIndex}`}
                className="transition hover:bg-slate-50/70"
              >
                {spec.columns.map((column) => (
                  <td
                    key={column.key}
                    className="border-b border-slate-50 px-3 py-2 align-top text-[11px] leading-4 text-slate-600 last:border-b-0"
                  >
                    <CellValue value={row[column.key]} kind={column.kind} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
