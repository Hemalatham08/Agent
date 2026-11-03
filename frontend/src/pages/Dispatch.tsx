import { AlertTriangle, CheckCircle2, Truck, XCircle } from 'lucide-react'
import { KpiCard } from '../components/dashboard/KpiCard'
import { Card, CardHeader } from '../components/ui/Card'
import { PageHeader } from '../components/ui/PageHeader'
import { StatusBadge } from '../components/ui/StatusBadge'
import { dispatchIssues, dispatches } from '../data/demo'
import { formatDate, formatNumber } from '../lib/format'

const quantityMismatches = dispatchIssues.filter(
  (issue) => issue.picked_qty !== issue.dispatched_qty,
).length
const barcodeFailures = dispatchIssues.filter(
  (issue) => issue.barcode_verified === 0,
).length

export default function Dispatch() {
  return (
    <>
      <PageHeader
        title="Dispatch"
        description="Shipment tracking, picked-versus-dispatched quantities, and barcode verification exceptions."
      />

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Total Dispatches"
          value={formatNumber(dispatches.length)}
          helper="Shipments in the current cycle"
          icon={Truck}
          tone="blue"
        />
        <KpiCard
          label="Dispatch Issues"
          value={formatNumber(dispatchIssues.length)}
          helper="Shipments requiring review"
          icon={AlertTriangle}
          tone="rose"
        />
        <KpiCard
          label="Quantity Mismatches"
          value={formatNumber(quantityMismatches)}
          helper="Picked differs from dispatched"
          icon={XCircle}
          tone="amber"
        />
        <KpiCard
          label="Barcode Failures"
          value={formatNumber(barcodeFailures)}
          helper="Missing scan verification"
          icon={CheckCircle2}
          tone="violet"
        />
      </section>

      <Card className="mt-5 overflow-hidden">
        <CardHeader
          title="Dispatch register"
          description="Carrier and tracking information for each shipment"
          icon={Truck}
          action={
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-semibold text-slate-500">
              {dispatches.length} dispatches
            </span>
          }
        />
        <div className="scrollbar-thin overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead>
              <tr className="border-y border-slate-100 bg-slate-50/70 text-[10px] uppercase tracking-[0.12em] text-slate-400">
                <th className="px-5 py-3 font-semibold">Dispatch</th>
                <th className="px-5 py-3 font-semibold">Sales order</th>
                <th className="px-5 py-3 font-semibold">Date</th>
                <th className="px-5 py-3 font-semibold">Carrier</th>
                <th className="px-5 py-3 font-semibold">Tracking</th>
                <th className="px-5 py-3 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {dispatches.map((dispatch) => (
                <tr key={dispatch.dispatch_id} className="transition hover:bg-slate-50/70">
                  <td className="whitespace-nowrap px-5 py-3 font-mono text-[11px] font-semibold text-slate-700">
                    {dispatch.dispatch_id}
                  </td>
                  <td className="whitespace-nowrap px-5 py-3 font-mono text-[11px] text-slate-500">
                    {dispatch.so_id}
                  </td>
                  <td className="whitespace-nowrap px-5 py-3 text-xs text-slate-500">
                    {formatDate(dispatch.dispatch_date)}
                  </td>
                  <td className="whitespace-nowrap px-5 py-3 text-xs text-slate-600">
                    {dispatch.carrier}
                  </td>
                  <td className="whitespace-nowrap px-5 py-3 font-mono text-[10px] text-slate-500">
                    {dispatch.tracking_number}
                  </td>
                  <td className="whitespace-nowrap px-5 py-3">
                    <StatusBadge status={dispatch.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="mt-5 overflow-hidden">
        <CardHeader
          title="Dispatch exceptions"
          description="Quantity discrepancies and missing barcode verification"
          icon={AlertTriangle}
          action={
            <span className="rounded-full bg-rose-50 px-2.5 py-1 text-[10px] font-semibold text-rose-700">
              {dispatchIssues.length} exceptions
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
                <th className="px-5 py-3 font-semibold">Barcode</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {dispatchIssues.map((issue) => {
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
                      {variance > 0 ? `−${formatNumber(variance)}` : formatNumber(variance)}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3">
                      <StatusBadge
                        status={issue.barcode_verified ? 'Verified' : 'Not verified'}
                      />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  )
}
