import {
  AlertTriangle,
  CalendarDays,
  ClipboardList,
  IndianRupee,
  Package,
  ShieldCheck,
  ShoppingCart,
  Truck,
  Wallet,
} from 'lucide-react'
import { AlertsPanel } from '../components/dashboard/AlertsPanel'
import { InventoryChart } from '../components/dashboard/InventoryChart'
import { KpiCard } from '../components/dashboard/KpiCard'
import { LowStockTable } from '../components/dashboard/LowStockTable'
import { RecentSalesTable } from '../components/dashboard/RecentSalesTable'
import { SalesChart } from '../components/dashboard/SalesChart'
import { PageHeader } from '../components/ui/PageHeader'
import {
  delayedPurchaseOrders,
  dispatchIssuesCount,
  lowStockAlerts,
  openSalesValue,
  pendingPurchaseOrders,
  pendingSalesOrders,
  qualityIssuesCount,
  rejectedUnits,
  totalInventoryValue,
  totalOutstanding,
  totalProducts,
  totalWarehouses,
  uniqueCategories,
  unpaidInvoices,
} from '../data/demo'
import { formatCurrency, formatNumber } from '../lib/format'

export default function Dashboard() {
  return (
    <>
      <PageHeader
        title="Dashboard"
        description="A live snapshot of inventory, sales, purchasing, dispatch, quality, and receivables."
        actions={
          <>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-[11px] font-semibold text-slate-500">
              <CalendarDays className="h-3.5 w-3.5" />
              Oct 2026
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-[11px] font-semibold text-emerald-700">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              Demo snapshot
            </span>
          </>
        }
      />

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Total Products"
          value={formatNumber(totalProducts)}
          helper={`${uniqueCategories.size} categories · ${totalWarehouses} warehouses`}
          icon={Package}
          tone="blue"
        />
        <KpiCard
          label="Inventory Value"
          value={formatCurrency(totalInventoryValue)}
          helper="Valued at purchase cost"
          icon={IndianRupee}
          tone="emerald"
        />
        <KpiCard
          label="Pending Sales Orders"
          value={formatNumber(pendingSalesOrders.length)}
          helper={`${formatCurrency(openSalesValue)} open value`}
          icon={ShoppingCart}
          tone="violet"
        />
        <KpiCard
          label="Pending Purchase Orders"
          value={formatNumber(pendingPurchaseOrders.length)}
          helper={`${delayedPurchaseOrders.length} delayed order`}
          icon={ClipboardList}
          tone="amber"
        />
        <KpiCard
          label="Low Stock Alerts"
          value={formatNumber(lowStockAlerts)}
          helper="At or below reorder level"
          icon={AlertTriangle}
          tone="rose"
        />
        <KpiCard
          label="Dispatch Issues"
          value={formatNumber(dispatchIssuesCount)}
          helper="Quantity and barcode exceptions"
          icon={Truck}
          tone="amber"
        />
        <KpiCard
          label="Quality Issues"
          value={formatNumber(qualityIssuesCount)}
          helper={`${rejectedUnits} units rejected`}
          icon={ShieldCheck}
          tone="rose"
        />
        <KpiCard
          label="Outstanding Invoices"
          value={formatNumber(unpaidInvoices.length)}
          helper={`${formatCurrency(totalOutstanding)} outstanding`}
          icon={Wallet}
          tone="slate"
        />
      </section>

      <section className="mt-5 grid grid-cols-1 gap-5 xl:grid-cols-2">
        <InventoryChart />
        <SalesChart />
      </section>

      <section className="mt-5 grid grid-cols-1 gap-5 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <RecentSalesTable />
        </div>
        <AlertsPanel />
      </section>

      <section className="mt-5">
        <LowStockTable />
      </section>
    </>
  )
}
