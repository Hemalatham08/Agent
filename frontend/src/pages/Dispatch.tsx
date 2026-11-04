import {
  AlertTriangle,
  CheckCircle2,
  CircleAlert,
  RefreshCw,
  Truck,
  XCircle,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { KpiCard } from '../components/dashboard/KpiCard'
import { Card, CardHeader } from '../components/ui/Card'
import { PageHeader } from '../components/ui/PageHeader'
import { StatusBadge } from '../components/ui/StatusBadge'
import { formatNumber } from '../lib/format'
import { erpApi } from '../services/api'
import type { DispatchIssue } from '../types'

function getIssueType(issue: DispatchIssue): string {
  const quantityMismatch = issue.picked_qty !== issue.dispatched_qty
  const barcodeMissing = issue.barcode_verified === 0

  if (quantityMismatch && barcodeMissing) {
    return 'Quantity + barcode'
  }

  if (quantityMismatch) {
    return 'Quantity mismatch'
  }

  if (barcodeMissing) {
    return 'Barcode missing'
  }

  return '—'
}

export default function Dispatch() {
  const [issues, setIssues] = useState<DispatchIssue[]>([])
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
        const dispatchIssues = await erpApi.getDispatchIssues()

        if (cancelled) {
          return
        }

        setIssues(dispatchIssues)
      } catch (requestError) {
        if (cancelled) {
          return
        }

        setError(
          requestError instanceof Error
            ? requestError.message
            : 'Could not load live dispatch issues.',
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

  const quantityMismatches = issues.filter(
    (issue) => issue.picked_qty !== issue.dispatched_qty,
  ).length
  const barcodeFailures = issues.filter(
    (issue) => issue.barcode_verified === 0,
  ).length
  const affectedDispatches = new Set(issues.map((issue) => issue.dispatch_id)).size
  const hasData = issues.length > 0
  const metricValue = (value: number) =>
    error !== null && !hasData ? '—' : formatNumber(value)

  return (
    <>
      <PageHeader
        title="Dispatch"
        description="Dispatch exceptions from the live ERP API. The complete dispatch register is not exposed by the current backend."
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
              Dispatch issue data could not be loaded
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
          label="Total Dispatches"
          value="—"
          helper="Missing endpoint: GET /dispatch"
          icon={Truck}
          tone="blue"
          loading={isLoading}
        />
        <KpiCard
          label="Dispatch Issues"
          value={metricValue(issues.length)}
          helper={`${formatNumber(affectedDispatches)} affected dispatch${
            affectedDispatches === 1 ? '' : 'es'
          }`}
          icon={AlertTriangle}
          tone="rose"
          loading={isLoading}
        />
        <KpiCard
          label="Quantity Mismatches"
          value={metricValue(quantityMismatches)}
          helper="Picked differs from dispatched"
          icon={XCircle}
          tone="amber"
          loading={isLoading}
        />
        <KpiCard
          label="Barcode Failures"
          value={metricValue(barcodeFailures)}
          helper="Missing scan verification"
          icon={CheckCircle2}
          tone="violet"
          loading={isLoading}
        />
      </section>

      <Card className="mt-5 overflow-hidden">
        <CardHeader
          title="Dispatch register"
          description="Complete shipment register with carrier and tracking information"
          icon={Truck}
          action={
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-semibold text-slate-500">
              Not available
            </span>
          }
        />
        <div className="flex min-h-[170px] flex-col items-center justify-center gap-2 px-6 py-8 text-center">
          <CircleAlert className="h-5 w-5 text-slate-400" />
          <p className="text-xs font-semibold text-slate-700">
            Complete dispatch register unavailable
          </p>
          <p className="max-w-md text-[11px] leading-5 text-slate-500">
            The backend currently exposes only GET /dispatch/issues. A
            GET /dispatch endpoint is needed to list all shipments, carriers,
            tracking numbers, and dispatch statuses.
          </p>
        </div>
      </Card>

      <Card className="mt-5 overflow-hidden">
        <CardHeader
          title="Dispatch exceptions"
          description="Quantity discrepancies and missing barcode verification"
          icon={AlertTriangle}
          action={
            <span className="rounded-full bg-rose-50 px-2.5 py-1 text-[10px] font-semibold text-rose-700">
              {isLoading ? 'Loading…' : `${formatNumber(issues.length)} exceptions`}
            </span>
          }
        />
        <div className="scrollbar-thin overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead>
              <tr className="border-y border-slate-100 bg-slate-50/70 text-[10px] uppercase tracking-[0.12em] text-slate-400">
                <th className="px-5 py-3 font-semibold">Dispatch</th>
                <th className="px-5 py-3 font-semibold">Order</th>
                <th className="px-5 py-3 font-semibold">Product</th>
                <th className="px-5 py-3 text-right font-semibold">Picked</th>
                <th className="px-5 py-3 text-right font-semibold">Dispatched</th>
                <th className="px-5 py-3 text-right font-semibold">Variance</th>
                <th className="px-5 py-3 font-semibold">Issue</th>
                <th className="px-5 py-3 font-semibold">Barcode</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {isLoading ? (
                <TableMessage>Loading live dispatch issues…</TableMessage>
              ) : issues.length === 0 ? (
                <TableMessage>
                  {error
                    ? 'Dispatch issue data unavailable.'
                    : 'No dispatch issues found.'}
                </TableMessage>
              ) : (
                issues.map((issue) => {
                  const variance = issue.picked_qty - issue.dispatched_qty

                  return (
                    <tr
                      key={`${issue.dispatch_id}-${issue.product_name}`}
                      className="transition hover:bg-slate-50/70"
                    >
                      <td className="whitespace-nowrap px-5 py-3 font-mono text-[11px] font-semibold text-slate-700">
                        {issue.dispatch_id}
                      </td>
                      <td className="whitespace-nowrap px-5 py-3 font-mono text-[11px] text-slate-500">
                        {issue.so_id}
                      </td>
                      <td className="whitespace-nowrap px-5 py-3 text-xs text-slate-700">
                        {issue.product_name}
                      </td>
                      <td className="whitespace-nowrap px-5 py-3 text-right text-xs text-slate-600">
                        {formatNumber(issue.picked_qty)}
                      </td>
                      <td className="whitespace-nowrap px-5 py-3 text-right text-xs text-slate-600">
                        {formatNumber(issue.dispatched_qty)}
                      </td>
                      <td
                        className={`whitespace-nowrap px-5 py-3 text-right text-xs font-semibold ${
                          variance > 0 ? 'text-rose-600' : 'text-slate-500'
                        }`}
                      >
                        {variance > 0
                          ? `−${formatNumber(variance)}`
                          : formatNumber(variance)}
                      </td>
                      <td className="whitespace-nowrap px-5 py-3 text-xs font-medium text-slate-600">
                        {getIssueType(issue)}
                      </td>
                      <td className="whitespace-nowrap px-5 py-3">
                        <StatusBadge
                          status={
                            issue.barcode_verified ? 'Verified' : 'Not verified'
                          }
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
