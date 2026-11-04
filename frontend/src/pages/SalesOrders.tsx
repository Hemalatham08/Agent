import {
  CircleAlert,
  Clock3,
  IndianRupee,
  RefreshCw,
  ShoppingCart,
  Truck,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { KpiCard } from '../components/dashboard/KpiCard'
import { Card, CardHeader } from '../components/ui/Card'
import { PageHeader } from '../components/ui/PageHeader'
import { StatusBadge } from '../components/ui/StatusBadge'
import { formatDate, formatNumber } from '../lib/format'
import { erpApi } from '../services/api'
import type { SalesOrder } from '../types'

type SalesFilter = 'All' | 'Pending' | 'In Progress'

const filters: SalesFilter[] = ['All', 'Pending', 'In Progress']

export default function SalesOrders() {
  const [orders, setOrders] = useState<SalesOrder[]>([])
  const [filter, setFilter] = useState<SalesFilter>('All')
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
        const pendingOrders = await erpApi.getPendingSalesOrders()

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
            : 'Could not load live sales orders.',
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

  const visibleOrders = orders.filter((order) => {
    if (filter === 'Pending') {
      return order.status === 'Pending'
    }

    if (filter === 'In Progress') {
      return (
        order.status === 'Processing' || order.status === 'Partially Dispatched'
      )
    }

    return true
  })

  const pendingCount = orders.filter((order) => order.status === 'Pending').length
  const inProgressCount = orders.filter(
    (order) =>
      order.status === 'Processing' || order.status === 'Partially Dispatched',
  ).length
  const hasData = orders.length > 0
  const metricValue = (value: number) =>
    error !== null && !hasData ? '—' : formatNumber(value)

  return (
    <>
      <PageHeader
        title="Sales Orders"
        description="Pending customer orders from the live ERP API, with required dates and fulfilment status."
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
              Sales order data could not be loaded
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
          label="Pending Sales Orders"
          value={metricValue(orders.length)}
          helper="Returned by GET /sales/pending"
          icon={ShoppingCart}
          tone="blue"
          loading={isLoading}
        />
        <KpiCard
          label="Pending"
          value={metricValue(pendingCount)}
          helper="Awaiting processing"
          icon={Clock3}
          tone="amber"
          loading={isLoading}
        />
        <KpiCard
          label="In Progress"
          value={metricValue(inProgressCount)}
          helper="Processing or partially dispatched"
          icon={Truck}
          tone="emerald"
          loading={isLoading}
        />
        <KpiCard
          label="Open Order Value"
          value="—"
          helper="Amount missing from GET /sales/pending"
          icon={IndianRupee}
          tone="violet"
          loading={isLoading}
        />
      </section>

      <Card className="mt-5 overflow-hidden">
        <CardHeader
          title="Pending sales order register"
          description="Orders not yet fully dispatched · amounts not exposed by GET /sales/pending"
          icon={ShoppingCart}
          action={
            <div className="flex rounded-xl bg-slate-100 p-1">
              {filters.map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => setFilter(item)}
                  className={`rounded-lg px-3 py-1.5 text-[11px] font-semibold transition ${
                    filter === item
                      ? 'bg-white text-slate-900 shadow-sm'
                      : 'text-slate-500 hover:text-slate-700'
                  }`}
                >
                  {item}
                </button>
              ))}
            </div>
          }
        />

        <div className="scrollbar-thin overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead>
              <tr className="border-y border-slate-100 bg-slate-50/70 text-[10px] uppercase tracking-[0.12em] text-slate-400">
                <th className="px-5 py-3 font-semibold">Order</th>
                <th className="px-5 py-3 font-semibold">Customer</th>
                <th className="px-5 py-3 font-semibold">Order date</th>
                <th className="px-5 py-3 font-semibold">Required date</th>
                <th className="px-5 py-3 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {isLoading ? (
                <TableMessage>Loading pending sales orders…</TableMessage>
              ) : orders.length === 0 ? (
                <TableMessage>
                  {error
                    ? 'Sales order data unavailable.'
                    : 'No pending sales orders found.'}
                </TableMessage>
              ) : visibleOrders.length === 0 ? (
                <TableMessage>
                  {`No orders match the ${filter.toLowerCase()} filter.`}
                </TableMessage>
              ) : (
                visibleOrders.map((order) => (
                  <tr
                    key={order.so_id}
                    className="transition hover:bg-slate-50/70"
                  >
                    <td className="whitespace-nowrap px-5 py-3 font-mono text-[11px] font-semibold text-slate-700">
                      {order.so_id}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3 text-xs font-medium text-slate-700">
                      {order.customer_name}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3 text-xs text-slate-500">
                      {formatDate(order.order_date)}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3 text-xs text-slate-500">
                      {formatDate(order.required_date)}
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
