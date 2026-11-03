import { CheckCircle2, Percent, ShieldAlert, ShieldCheck } from 'lucide-react'
import { KpiCard } from '../components/dashboard/KpiCard'
import { Card, CardHeader } from '../components/ui/Card'
import { PageHeader } from '../components/ui/PageHeader'
import { StatusBadge } from '../components/ui/StatusBadge'
import {
  inspectedUnits,
  qualityAcceptanceRate,
  qualityInspections,
  qualityIssues,
  rejectedUnits,
} from '../data/demo'
import { formatNumber, formatPercent } from '../lib/format'

export default function Quality() {
  return (
    <>
      <PageHeader
        title="Quality"
        description="Incoming inspection results, rejected quantities, and supplier quality exceptions."
      />

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Inspections"
          value={formatNumber(qualityInspections.length)}
          helper="Incoming goods inspections"
          icon={ShieldCheck}
          tone="blue"
        />
        <KpiCard
          label="Units Inspected"
          value={formatNumber(inspectedUnits)}
          helper="Total inspected quantity"
          icon={CheckCircle2}
          tone="emerald"
        />
        <KpiCard
          label="Rejected Units"
          value={formatNumber(rejectedUnits)}
          helper="Requires supplier follow-up"
          icon={ShieldAlert}
          tone="rose"
        />
        <KpiCard
          label="Acceptance Rate"
          value={formatPercent(qualityAcceptanceRate)}
          helper="Accepted versus inspected"
          icon={Percent}
          tone="violet"
        />
      </section>

      <Card className="mt-5 overflow-hidden">
        <CardHeader
          title="Inspection register"
          description="Quality results linked to goods receipts and products"
          icon={ShieldCheck}
          action={
            <span className="rounded-full bg-rose-50 px-2.5 py-1 text-[10px] font-semibold text-rose-700">
              {qualityIssues.length} with rejections
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
              {qualityInspections.map((inspection) => {
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
                      {inspection.rejection_reason}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3">
                      <StatusBadge status={isRejected ? 'Rejected' : 'Accepted'} />
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
