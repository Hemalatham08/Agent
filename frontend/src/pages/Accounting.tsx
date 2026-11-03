import { AlertTriangle, CheckCircle2, IndianRupee, Wallet } from 'lucide-react'
import { KpiCard } from '../components/dashboard/KpiCard'
import { Card, CardHeader } from '../components/ui/Card'
import { PageHeader } from '../components/ui/PageHeader'
import { ProgressBar } from '../components/ui/ProgressBar'
import { StatusBadge } from '../components/ui/StatusBadge'
import {
  invoices,
  totalInvoiced,
  totalOutstanding,
  totalPaid,
  unpaidInvoices,
} from '../data/demo'
import { formatCurrency, formatDate, formatNumber } from '../lib/format'

export default function Accounting() {
  return (
    <>
      <PageHeader
        title="Accounting"
        description="Sales and purchase invoices, collections, and outstanding receivable balances."
      />

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Total Invoiced"
          value={formatCurrency(totalInvoiced)}
          helper={`${invoices.length} invoices in the ledger`}
          icon={IndianRupee}
          tone="blue"
        />
        <KpiCard
          label="Collected"
          value={formatCurrency(totalPaid)}
          helper="Payments received and made"
          icon={CheckCircle2}
          tone="emerald"
        />
        <KpiCard
          label="Outstanding"
          value={formatCurrency(totalOutstanding)}
          helper="Open receivable and payable"
          icon={AlertTriangle}
          tone="rose"
        />
        <KpiCard
          label="Unpaid Invoices"
          value={formatNumber(unpaidInvoices.length)}
          helper="Partially paid or unpaid"
          icon={Wallet}
          tone="amber"
        />
      </section>

      <Card className="mt-5 overflow-hidden">
        <CardHeader
          title="Invoice ledger"
          description="Invoice totals, payment progress, and outstanding balances in INR"
          icon={Wallet}
          action={
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-semibold text-slate-500">
              {invoices.length} invoices
            </span>
          }
        />
        <div className="scrollbar-thin overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead>
              <tr className="border-y border-slate-100 bg-slate-50/70 text-[10px] uppercase tracking-[0.12em] text-slate-400">
                <th className="px-5 py-3 font-semibold">Invoice</th>
                <th className="px-5 py-3 font-semibold">Type</th>
                <th className="px-5 py-3 font-semibold">Date</th>
                <th className="px-5 py-3 text-right font-semibold">Total</th>
                <th className="px-5 py-3 text-right font-semibold">Paid</th>
                <th className="px-5 py-3 text-right font-semibold">Outstanding</th>
                <th className="w-44 px-5 py-3 font-semibold">Collection</th>
                <th className="px-5 py-3 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {invoices.map((invoice) => (
                <tr key={invoice.invoice_id} className="transition hover:bg-slate-50/70">
                  <td className="whitespace-nowrap px-5 py-3 font-mono text-[11px] font-semibold text-slate-700">
                    {invoice.invoice_id}
                  </td>
                  <td className="whitespace-nowrap px-5 py-3 text-xs text-slate-600">
                    {invoice.invoice_type}
                  </td>
                  <td className="whitespace-nowrap px-5 py-3 text-xs text-slate-500">
                    {formatDate(invoice.invoice_date)}
                  </td>
                  <td className="whitespace-nowrap px-5 py-3 text-right text-xs font-semibold text-slate-800">
                    {formatCurrency(invoice.total_amount)}
                  </td>
                  <td className="whitespace-nowrap px-5 py-3 text-right text-xs text-emerald-600">
                    {formatCurrency(invoice.paid_amount)}
                  </td>
                  <td
                    className={`whitespace-nowrap px-5 py-3 text-right text-xs font-semibold ${
                      invoice.outstanding_amount > 0 ? 'text-rose-600' : 'text-slate-400'
                    }`}
                  >
                    {formatCurrency(invoice.outstanding_amount)}
                  </td>
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-2">
                      <ProgressBar
                        value={invoice.paid_amount}
                        max={invoice.total_amount}
                        tone={
                          invoice.outstanding_amount === 0
                            ? 'success'
                            : invoice.status === 'Unpaid'
                              ? 'danger'
                              : 'warning'
                        }
                      />
                      <span className="w-9 text-right text-[10px] font-semibold text-slate-400">
                        {Math.round((invoice.paid_amount / invoice.total_amount) * 100)}%
                      </span>
                    </div>
                  </td>
                  <td className="whitespace-nowrap px-5 py-3">
                    <StatusBadge status={invoice.status} />
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
