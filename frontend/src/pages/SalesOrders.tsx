import { Clock3, IndianRupee, ShoppingCart, Truck } from 'lucide-react'
import { useState } from 'react'
import { KpiCard } from '../components/dashboard/KpiCard'
import { Card, CardHeader } from '../components/ui/Card'
import { PageHeader } from '../components/ui/PageHeader'
import { StatusBadge } from '../components/ui/StatusBadge'
import {
  dispatchedSalesOrders,
  openSalesValue,
  pendingSalesOrders,
  salesOrders,
} from '../data/demo'
import { formatCurrency, formatDate, formatNumber } from '../lib/format'

type SalesFilter = 'All' | 'Open' | 'Dispatched'

const filters: SalesFilter[] = ['All', 'Open', 'Dispatched']

export default function SalesOrders() {
  const [filter, setFilter] = useState<SalesFilter>('All')

  const visibleOrders = salesOrders.filter((order) => {
    if (filter === 'Open') {
      return order.status !== 'Dispatched'
    }

    if (filter === 'Dispatched') {
      return order.status === 'Dispatched'
    }

    return true
  })

  return (
    <>
      <PageHeader
        title="Sales Orders"
        description="Customer demand, required dates, order values, and dispatch progress."
      />

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Total Sales Orders"
          value={formatNumber(salesOrders.length)}
          helper="October 2026 order book"
          icon={ShoppingCart}
          tone="blue"
        />
        <KpiCard
          label="Open Orders"
          value={formatNumber(pendingSalesOrders.length)}
          helper="Pending, processing, or partial"
          icon={Clock3}
          tone="amber"
        />
        <KpiCard
          label="Dispatched"
          value={formatNumber(dispatchedSalesOrders.length)}
          helper="Fully dispatched orders"
          icon={Truck}
          tone="emerald"
        />
        <KpiCard
          label="Open Order Value"
          value={formatCurrency(openSalesValue)}
          helper="Value awaiting dispatch"
          icon={IndianRupee}
          tone="violet"
        />
      </section>

      <Card className="mt-5 overflow-hidden">
        <CardHeader
          title="Sales order register"
          description="All customer orders with current fulfilment status"
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
                <th className="px-5 py-3 text-right font-semibold">Value</th>
                <th className="px-5 py-3 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {visibleOrders.map((order) => (
                <tr key={order.so_id} className="transition hover:bg-slate-50/70">
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
                  <td className="whitespace-nowrap px-5 py-3 text-right text-xs font-semibold text-slate-800">
                    {formatCurrency(order.amount ?? 0)}
                  </td>
                  <td className="whitespace-nowrap px-5 py-3">
                    <StatusBadge status={order.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  )
}
