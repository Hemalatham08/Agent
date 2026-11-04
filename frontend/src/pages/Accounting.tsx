import {
  AlertTriangle,
  CheckCircle2,
  CircleAlert,
  IndianRupee,
  RefreshCw,
  Wallet,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { KpiCard } from '../components/dashboard/KpiCard'
import { Card, CardHeader } from '../components/ui/Card'
import { PageHeader } from '../components/ui/PageHeader'
import { ProgressBar } from '../components/ui/ProgressBar'
import { StatusBadge } from '../components/ui/StatusBadge'
import { formatCurrency, formatDate, formatNumber } from '../lib/format'
import { erpApi } from '../services/api'
import type { Invoice } from '../types'

export default function Accounting() {
  const [invoices, setInvoices] = useState<Invoice[]>([])
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
      setInvoices([])

      try {
        const unpaidInvoices = await erpApi.getUnpaidInvoices()

        if (cancelled) {
          return
        }

        setInvoices(unpaidInvoices)
      } catch (requestError) {
        if (cancelled) {
          return
        }

        setError(
          requestError instanceof Error
            ? requestError.message
            : 'Could not load live unpaid invoices.',
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

  const totalInvoiceValue = invoices.reduce(
    (total, invoice) => total + invoice.total_amount,
    0,
  )
  const totalPaid = invoices.reduce(
    (total, invoice) => total + invoice.paid_amount,
    0,
  )
  const totalOutstanding = invoices.reduce(
    (total, invoice) => total + invoice.outstanding_amount,
    0,
  )
  const hasData = invoices.length > 0
  const metricValue = (value: number) =>
    error !== null && !hasData ? '—' : formatNumber(value)
  const currencyValue = (value: number) =>
    error !== null && !hasData ? '—' : formatCurrency(value)

  return (
    <>
      <PageHeader
        title="Accounting"
        description="Unpaid invoice records from the live ERP API. Only invoices with an outstanding balance are shown; the complete invoice register is not exposed by the current backend."
        actions={
          <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-3 py-1.5 text-[11px] font-semibold text-amber-700">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
            Unpaid only
          </span>
        }
      />

      {error ? (
        <div className="mb-5 flex flex-col gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 sm:flex-row sm:items-start">
          <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-rose-500" />
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold text-rose-700">
              Unpaid invoice data could not be loaded
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
          label="Unpaid Invoices"
          value={metricValue(invoices.length)}
          helper="Invoices with outstanding balance"
          icon={Wallet}
          tone="blue"
          loading={isLoading}
        />
        <KpiCard
          label="Outstanding"
          value={currencyValue(totalOutstanding)}
          helper="Open balance on returned invoices"
          icon={AlertTriangle}
          tone="rose"
          loading={isLoading}
        />
        <KpiCard
          label="Unpaid Invoice Value"
          value={currencyValue(totalInvoiceValue)}
          helper="Total value of returned invoices"
          icon={IndianRupee}
          tone="amber"
          loading={isLoading}
        />
        <KpiCard
          label="Paid Amount"
          value={currencyValue(totalPaid)}
          helper="Paid against returned unpaid invoices"
          icon={CheckCircle2}
          tone="emerald"
          loading={isLoading}
        />
      </section>

      <Card className="mt-5 overflow-hidden">
        <CardHeader
          title="Unpaid invoices"
          description="Invoices with outstanding balances · source: GET /accounting/unpaid"
          icon={Wallet}
          action={
            <span className="rounded-full bg-amber-50 px-2.5 py-1 text-[10px] font-semibold text-amber-700">
              {isLoading
                ? 'Loading…'
                : `${formatNumber(invoices.length)} unpaid`}
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
              {isLoading ? (
                <TableMessage>Loading live unpaid invoices…</TableMessage>
              ) : invoices.length === 0 ? (
                <TableMessage>
                  {error
                    ? 'Unpaid invoice data unavailable.'
                    : 'No unpaid invoices found.'}
                </TableMessage>
              ) : (
                invoices.map((invoice) => {
                  const paidPercent =
                    invoice.total_amount > 0
                      ? Math.round(
                          (invoice.paid_amount / invoice.total_amount) * 100,
                        )
                      : 0

                  return (
                    <tr
                      key={invoice.invoice_id}
                      className="transition hover:bg-slate-50/70"
                    >
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
                          invoice.outstanding_amount > 0
                            ? 'text-rose-600'
                            : 'text-slate-400'
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
                            {paidPercent}%
                          </span>
                        </div>
                      </td>
                      <td className="whitespace-nowrap px-5 py-3">
                        <StatusBadge status={invoice.status} />
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
