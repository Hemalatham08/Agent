import {
  CheckCircle2,
  CircleAlert,
  Percent,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { KpiCard } from '../components/dashboard/KpiCard'
import { Card, CardHeader } from '../components/ui/Card'
import { PageHeader } from '../components/ui/PageHeader'
import { StatusBadge } from '../components/ui/StatusBadge'
import { formatNumber, formatPercent } from '../lib/format'
import { erpApi } from '../services/api'
import type { QualityIssue } from '../types'

export default function Quality() {
  const [issues, setIssues] = useState<QualityIssue[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  const reload = useCallback(() => {
    setReloadKey((key) => key + 1)
  }, [])

  useEffect(() => {
    let cancelled = false

    async function load() {
      setIsLoading(true)
      setError(null)
      setIssues([])

      try {
        const qualityIssues = await erpApi.getQualityIssues()

        if (cancelled) {
          return
        }

        setIssues(qualityIssues)
      } catch (requestError) {
        if (cancelled) {
          return
        }

        setError(
          requestError instanceof Error
            ? requestError.message
            : 'Could not load live quality issues.',
        )
      } finally {
        if (!cancelled) {
          setIsLoading(false)
        }
      }
    }

    void load()

    return () => {
      cancelled = true
    }
  }, [reloadKey])

  const inspectedUnits = issues.reduce(
    (total, inspection) => total + inspection.inspected_qty,
    0,
  )
  const acceptedUnits = issues.reduce(
    (total, inspection) => total + inspection.accepted_qty,
    0,
  )
  const rejectedUnits = issues.reduce(
    (total, inspection) => total + inspection.rejected_qty,
    0,
  )
  const acceptanceRate =
    inspectedUnits > 0 ? (acceptedUnits / inspectedUnits) * 100 : 0
  const hasData = issues.length > 0
  const metricValue = (value: number) =>
    error !== null && !hasData ? '—' : formatNumber(value)
  const rateValue =
    error !== null && !hasData
      ? '—'
      : hasData
        ? formatPercent(acceptanceRate)
        : '—'

  return (
    <>
      <PageHeader
        title="Quality"
        description="Quality issue records from the live ERP API. Only inspections with rejected quantities are shown; the complete inspection register is not exposed by the current backend."
        actions={
          <span className="inline-flex items-center gap-1.5 rounded-full border border-rose-200 bg-rose-50 px-3 py-1.5 text-[11px] font-semibold text-rose-700">
            <span className="h-1.5 w-1.5 rounded-full bg-rose-500" />
            Issues only
          </span>
        }
      />

      {error ? (
        <div className="mb-5 flex flex-col gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 sm:flex-row sm:items-start">
          <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-rose-500" />
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold text-rose-700">
              Quality issue data could not be loaded
            </p>
            <p className="mt-0.5 text-[11px] leading-5 text-rose-600">{error}</p>
          </div>
          <button
            type="button"
            onClick={reload}
            disabled={isLoading}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-white px-3 py-1.5 text-[11px] font-semibold text-rose-600 ring-1 ring-rose-200 transition hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${isLoading ? 'animate-spin' : ''}`}
            />
            Retry
          </button>
        </div>
      ) : null}

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Issue Inspections"
          value={metricValue(issues.length)}
          helper="Inspections with rejections"
          icon={ShieldCheck}
          tone="blue"
          loading={isLoading}
        />
        <KpiCard
          label="Units Inspected"
          value={metricValue(inspectedUnits)}
          helper="Across returned issue inspections"
          icon={CheckCircle2}
          tone="emerald"
          loading={isLoading}
        />
        <KpiCard
          label="Rejected Units"
          value={metricValue(rejectedUnits)}
          helper="Requires supplier follow-up"
          icon={ShieldAlert}
          tone="rose"
          loading={isLoading}
        />
        <KpiCard
          label="Acceptance Rate"
          value={rateValue}
          helper="Across returned issue inspections"
          icon={Percent}
          tone="violet"
          loading={isLoading}
        />
      </section>

      <Card className="mt-5 overflow-hidden">
        <CardHeader
          title="Quality issue inspections"
          description="Inspections with rejected quantities · source: GET /quality/issues"
          icon={ShieldCheck}
          action={
            <span className="rounded-full bg-rose-50 px-2.5 py-1 text-[10px] font-semibold text-rose-700">
              {isLoading
                ? 'Loading…'
                : `${formatNumber(issues.length)} with rejections`}
            </span>
          }
        />
        <div className="scrollbar-thin overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead>
              <tr className="border-y border-slate-100 bg-slate-50/70 text-[10px] uppercase tracking-[0.12em] text-slate-400">
                <th className="px-5 py-3 font-semibold">Inspection</th>
                <th className="px-5 py-3 font-semibold">Receipt</th>
                <th className="px-5 py-3 font-semibold">Product</th>
                <th className="px-5 py-3 text-right font-semibold">Inspected</th>
                <th className="px-5 py-3 text-right font-semibold">Accepted</th>
                <th className="px-5 py-3 text-right font-semibold">Rejected</th>
                <th className="px-5 py-3 font-semibold">Reason</th>
                <th className="px-5 py-3 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {isLoading ? (
                <TableMessage>Loading live quality issues…</TableMessage>
              ) : issues.length === 0 ? (
                <TableMessage>
                  {error
                    ? 'Quality issue data unavailable.'
                    : 'No quality issue inspections found.'}
                </TableMessage>
              ) : (
                issues.map((inspection) => {
                  const isRejected = inspection.rejected_qty > 0

                  return (
                    <tr
                      key={inspection.inspection_id}
                      className="transition hover:bg-slate-50/70"
                    >
                      <td className="whitespace-nowrap px-5 py-3 font-mono text-[11px] font-semibold text-slate-700">
                        {inspection.inspection_id}
                      </td>
                      <td className="whitespace-nowrap px-5 py-3 font-mono text-[11px] text-slate-500">
                        {inspection.receipt_id}
                      </td>
                      <td className="whitespace-nowrap px-5 py-3 text-xs text-slate-700">
                        {inspection.product_name}
                      </td>
                      <td className="whitespace-nowrap px-5 py-3 text-right text-xs text-slate-600">
                        {formatNumber(inspection.inspected_qty)}
                      </td>
                      <td className="whitespace-nowrap px-5 py-3 text-right text-xs text-emerald-600">
                        {formatNumber(inspection.accepted_qty)}
                      </td>
                      <td
                        className={`whitespace-nowrap px-5 py-3 text-right text-xs font-semibold ${
                          isRejected ? 'text-rose-600' : 'text-slate-400'
                        }`}
                      >
                        {formatNumber(inspection.rejected_qty)}
                      </td>
                      <td className="max-w-[220px] truncate px-5 py-3 text-xs text-slate-500">
                        {inspection.rejection_reason || '—'}
                      </td>
                      <td className="whitespace-nowrap px-5 py-3">
                        <StatusBadge
                          status={isRejected ? 'Rejected' : 'Accepted'}
                        />
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  )
}

function TableMessage({ children }: { children: string }) {
  return (
    <tr>
      <td className="px-5 py-10 text-center text-xs font-medium text-slate-400" colSpan={8}>
        {children}
      </td>
    </tr>
  )
}
