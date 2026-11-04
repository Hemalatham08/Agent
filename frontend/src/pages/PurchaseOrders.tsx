import {
  AlertTriangle,
  CircleAlert,
  ClipboardList,
  Clock3,
  PackageCheck,
  RefreshCw,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { KpiCard } from '../components/dashboard/KpiCard'
import { Card, CardHeader } from '../components/ui/Card'
import { PageHeader } from '../components/ui/PageHeader'
import { StatusBadge } from '../components/ui/StatusBadge'
import { formatDate, formatNumber } from '../lib/format'
import { erpApi } from '../services/api'
import type { PurchaseOrder } from '../types'

export default function PurchaseOrders() {
  const [orders, setOrders] = useState<PurchaseOrder[]>([])
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
      setOrders([])

      try {
        const pendingOrders = await erpApi.getPendingPurchaseOrders()

        if (cancelled) {
          return
        }

        setOrders(pendingOrders)
      } catch (requestError) {
        if (cancelled) {
          return
        }

        setError(
          requestError instanceof Error
            ? requestError.message
            : 'Could not load live purchase orders.',
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

  const pendingCount = orders.filter((order) => order.status === 'Pending').length
  const delayedCount = orders.filter((order) => order.status === 'Delayed').length
  const partiallyReceivedCount = orders.filter(
    (order) => order.status === 'Partially Received',
  ).length
  const hasData = orders.length > 0
  const metricValue = (value: number) =>
    error !== null && !hasData ? '—' : formatNumber(value)

  return (
    <>
      <PageHeader
        title="Purchase Orders"
        description="Pending supplier replenishment orders from the live ERP API, with expected receipt dates and status."
        actions={
          <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-3 py-1.5 text-[11px] font-semibold text-amber-700">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
            Pending only
          </span>
        }
      />

      {error ? (
        <div className="mb-5 flex flex-col gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 sm:flex-row sm:items-start">
          <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-rose-500" />
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold text-rose-700">
              Purchase order data could not be loaded
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
          label="Pending Purchase Orders"
          value={metricValue(orders.length)}
          helper="Returned by GET /purchase/pending"
          icon={ClipboardList}
          tone="blue"
          loading={isLoading}
        />
        <KpiCard
          label="Pending"
          value={metricValue(pendingCount)}
          helper="Awaiting supplier receipt"
          icon={Clock3}
          tone="amber"
          loading={isLoading}
        />
        <KpiCard
          label="Delayed"
          value={metricValue(delayedCount)}
          helper="Marked delayed in the ERP"
          icon={AlertTriangle}
          tone="rose"
          loading={isLoading}
        />
        <KpiCard
          label="Partially Received"
          value={metricValue(partiallyReceivedCount)}
          helper="Partially received orders"
          icon={PackageCheck}
          tone="emerald"
          loading={isLoading}
        />
      </section>

      <Card className="mt-5 overflow-hidden">
        <CardHeader
          title="Pending purchase order register"
          description="Orders not yet fully received · amounts not exposed by GET /purchase/pending"
          icon={ClipboardList}
          action={
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-semibold text-slate-500">
              {isLoading
                ? 'Loading…'
                : `${formatNumber(orders.length)} purchase orders`}
            </span>
          }
        />

        <div className="scrollbar-thin overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead>
              <tr className="border-y border-slate-100 bg-slate-50/70 text-[10px] uppercase tracking-[0.12em] text-slate-400">
                <th className="px-5 py-3 font-semibold">Order</th>
                <th className="px-5 py-3 font-semibold">Supplier</th>
                <th className="px-5 py-3 font-semibold">Order date</th>
                <th className="px-5 py-3 font-semibold">Expected date</th>
                <th className="px-5 py-3 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {isLoading ? (
                <TableMessage>Loading pending purchase orders…</TableMessage>
              ) : orders.length === 0 ? (
                <TableMessage>
                  {error
                    ? 'Purchase order data unavailable.'
                    : 'No pending purchase orders found.'}
                </TableMessage>
              ) : (
                orders.map((order) => (
                  <tr
                    key={order.po_id}
                    className="transition hover:bg-slate-50/70"
                  >
                    <td className="whitespace-nowrap px-5 py-3 font-mono text-[11px] font-semibold text-slate-700">
                      {order.po_id}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3 text-xs font-medium text-slate-700">
                      {order.supplier_name}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3 text-xs text-slate-500">
                      {formatDate(order.order_date)}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3 text-xs text-slate-500">
                      {formatDate(order.expected_date)}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3">
                      <StatusBadge status={order.status} />
                    </td>
                  </tr>
                ))
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
      <td className="px-5 py-10 text-center text-xs font-medium text-slate-400" colSpan={5}>
        {children}
      </td>
    </tr>
  )
}
