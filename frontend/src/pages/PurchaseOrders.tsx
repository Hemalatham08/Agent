import { AlertTriangle, ClipboardList, Clock3, PackageCheck } from 'lucide-react'
import { KpiCard } from '../components/dashboard/KpiCard'
import { Card, CardHeader } from '../components/ui/Card'
import { PageHeader } from '../components/ui/PageHeader'
import { StatusBadge } from '../components/ui/StatusBadge'
import {
  delayedPurchaseOrders,
  pendingPurchaseOrders,
  purchaseOrders,
} from '../data/demo'
import { formatDate, formatNumber } from '../lib/format'

const receivedOrders = purchaseOrders.filter((order) => order.status === 'Received')

export default function PurchaseOrders() {
  return (
    <>
      <PageHeader
        title="Purchase Orders"
        description="Supplier replenishment pipeline, expected receipts, and delivery exceptions."
      />

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Total Purchase Orders"
          value={formatNumber(purchaseOrders.length)}
          helper="Active procurement records"
          icon={ClipboardList}
          tone="blue"
        />
        <KpiCard
          label="Open Orders"
          value={formatNumber(pendingPurchaseOrders.length)}
          helper="Pending, partial, or delayed"
          icon={Clock3}
          tone="amber"
        />
        <KpiCard
          label="Delayed"
          value={formatNumber(delayedPurchaseOrders.length)}
          helper="Past expected receipt date"
          icon={AlertTriangle}
          tone="rose"
        />
        <KpiCard
          label="Fully Received"
          value={formatNumber(receivedOrders.length)}
          helper="Closed purchase orders"
          icon={PackageCheck}
          tone="emerald"
        />
      </section>

      <Card className="mt-5 overflow-hidden">
        <CardHeader
          title="Purchase order register"
          description="Supplier orders with expected dates and receipt status"
          icon={ClipboardList}
          action={
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-semibold text-slate-500">
              {purchaseOrders.length} purchase orders
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
                <th className="px-5 py-3 text-right font-semibold">Value</th>
                <th className="px-5 py-3 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {purchaseOrders.map((order) => (
                <tr key={order.po_id} className="transition hover:bg-slate-50/70">
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
                  <td className="whitespace-nowrap px-5 py-3 text-right text-xs font-semibold text-slate-800">
                    ₹{formatNumber(order.amount ?? 0)}
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
