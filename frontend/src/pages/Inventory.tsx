import { AlertTriangle, Boxes, Layers, Warehouse } from 'lucide-react'
import { KpiCard } from '../components/dashboard/KpiCard'
import { Card, CardHeader } from '../components/ui/Card'
import { PageHeader } from '../components/ui/PageHeader'
import { StatusBadge } from '../components/ui/StatusBadge'
import {
  freeUnits,
  inventoryRows,
  onHandUnits,
  reservedUnits,
  totalWarehouses,
} from '../data/demo'
import { formatNumber } from '../lib/format'

const lowStockRows = inventoryRows.filter(
  (row) => row.free_stock <= row.reorder_level,
)

export default function Inventory() {
  return (
    <>
      <PageHeader
        title="Inventory"
        description="Stock on hand, reserved quantities, and free stock across every warehouse."
        actions={
          <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-[11px] font-semibold text-slate-500">
            <Warehouse className="h-3.5 w-3.5" />
            {totalWarehouses} warehouses
          </span>
        }
      />

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="On-hand Units"
          value={formatNumber(onHandUnits)}
          helper="Across all stock records"
          icon={Boxes}
          tone="blue"
        />
        <KpiCard
          label="Reserved Units"
          value={formatNumber(reservedUnits)}
          helper="Committed to open orders"
          icon={Layers}
          tone="violet"
        />
        <KpiCard
          label="Free Stock"
          value={formatNumber(freeUnits)}
          helper="Available to promise"
          icon={Warehouse}
          tone="emerald"
        />
        <KpiCard
          label="Low-stock Records"
          value={formatNumber(lowStockRows.length)}
          helper="At or below reorder level"
          icon={AlertTriangle}
          tone="rose"
        />
      </section>

      <Card className="mt-5 overflow-hidden">
        <CardHeader
          title="Stock ledger"
          description="Warehouse-level inventory derived from the ERP database"
          icon={Boxes}
          action={
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-semibold text-slate-500">
              {inventoryRows.length} stock records
            </span>
          }
        />

        <div className="scrollbar-thin overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead>
              <tr className="border-y border-slate-100 bg-slate-50/70 text-[10px] uppercase tracking-[0.12em] text-slate-400">
                <th className="px-5 py-3 font-semibold">Product</th>
                <th className="px-5 py-3 font-semibold">SKU</th>
                <th className="px-5 py-3 font-semibold">Warehouse</th>
                <th className="px-5 py-3 text-right font-semibold">On hand</th>
                <th className="px-5 py-3 text-right font-semibold">Reserved</th>
                <th className="px-5 py-3 text-right font-semibold">Free stock</th>
                <th className="px-5 py-3 text-right font-semibold">Reorder</th>
                <th className="px-5 py-3 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {inventoryRows.map((row) => {
                const isLowStock = row.free_stock <= row.reorder_level

                return (
                  <tr key={row.inventory_id} className="transition hover:bg-slate-50/70">
                    <td className="whitespace-nowrap px-5 py-3">
                      <p className="text-xs font-semibold text-slate-800">
                        {row.product_name}
                      </p>
                      <p className="text-[10px] text-slate-400">{row.product_id}</p>
                    </td>
                    <td className="whitespace-nowrap px-5 py-3 font-mono text-[10px] text-slate-500">
                      {row.sku}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3 text-xs text-slate-600">
                      {row.warehouse_name}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3 text-right text-xs text-slate-700">
                      {formatNumber(row.on_hand_qty)}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3 text-right text-xs text-slate-500">
                      {formatNumber(row.reserved_qty)}
                    </td>
                    <td
                      className={`whitespace-nowrap px-5 py-3 text-right text-xs font-semibold ${
                        isLowStock ? 'text-rose-600' : 'text-emerald-600'
                      }`}
                    >
                      {formatNumber(row.free_stock)}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3 text-right text-xs text-slate-500">
                      {formatNumber(row.reorder_level)}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3">
                      <StatusBadge status={isLowStock ? 'Low Stock' : 'Healthy'} />
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
