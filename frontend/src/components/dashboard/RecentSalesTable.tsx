import { ArrowUpRight, ShoppingCart } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { SalesOrder } from '../../types'
import { formatDate } from '../../lib/format'
import { Card, CardHeader } from '../ui/Card'
import { StatusBadge } from '../ui/StatusBadge'

interface RecentSalesTableProps {
  orders: SalesOrder[]
  loading?: boolean
  error?: string | null
}

export function RecentSalesTable({
  orders,
  loading = false,
  error = null,
}: RecentSalesTableProps) {
  const recentOrders = [...orders]
    .sort((a, b) => b.order_date.localeCompare(a.order_date))
    .slice(0, 5)

  return (
    <Card className="overflow-hidden">
      <CardHeader
        title="Recent sales orders"
        description="Latest customer orders and dispatch status · order values not exposed by API"
        icon={ShoppingCart}
        action={
          <Link
            to="/sales"
            className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-semibold text-accent-600 transition hover:bg-accent-50"
          >
            View all
            <ArrowUpRight className="h-3.5 w-3.5" />
          </Link>
        }
      />
      <div className="scrollbar-thin overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead>
            <tr className="border-y border-slate-100 bg-slate-50/70 text-[10px] uppercase tracking-[0.12em] text-slate-400">
              <th className="px-5 py-2.5 font-semibold">Order</th>
              <th className="px-5 py-2.5 font-semibold">Customer</th>
              <th className="px-5 py-2.5 font-semibold">Ordered</th>
              <th className="px-5 py-2.5 font-semibold">Required</th>
              <th className="px-5 py-2.5 font-semibold">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <TableMessage>Loading sales orders…</TableMessage>
            ) : error ? (
              <TableMessage tone="error">{error}</TableMessage>
            ) : recentOrders.length === 0 ? (
              <TableMessage>No pending sales orders.</TableMessage>
            ) : (
              recentOrders.map((order) => (
                <tr key={order.so_id} className="transition hover:bg-slate-50/70">
                  <td className="whitespace-nowrap px-5 py-3 font-mono text-[11px] font-semibold text-slate-700">
                    {order.so_id}
                  </td>
                  <td className="max-w-[220px] truncate px-5 py-3 text-xs font-medium text-slate-700">
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
  )
}

function TableMessage({
  children,
  tone = 'muted',
}: {
  children: string
  tone?: 'muted' | 'error'
}) {
  return (
    <tr>
      <td
        colSpan={5}
        className={`px-5 py-10 text-center text-xs font-medium ${
          tone === 'error' ? 'text-rose-600' : 'text-slate-400'
        }`}
      >
        {children}
      </td>
    </tr>
  )
}
