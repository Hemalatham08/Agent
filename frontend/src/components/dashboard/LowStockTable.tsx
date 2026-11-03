import { AlertTriangle, ArrowUpRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { lowStockItems } from '../../data/demo'
import { formatNumber } from '../../lib/format'
import { Card, CardHeader } from '../ui/Card'
import { ProgressBar } from '../ui/ProgressBar'
import { StatusBadge } from '../ui/StatusBadge'

export function LowStockTable() {
  return (
    <Card className="overflow-hidden">
      <CardHeader
        title="Low-stock products"
        description="SKU and warehouse combinations at or below reorder level"
        icon={AlertTriangle}
        action={
          <Link
            to="/inventory"
            className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-semibold text-accent-600 transition hover:bg-accent-50"
          >
            Review inventory
            <ArrowUpRight className="h-3.5 w-3.5" />
          </Link>
        }
      />
      <div className="scrollbar-thin overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead>
            <tr className="border-y border-slate-100 bg-slate-50/70 text-[10px] uppercase tracking-[0.12em] text-slate-400">
              <th className="px-5 py-2.5 font-semibold">Product</th>
              <th className="px-5 py-2.5 font-semibold">Warehouse</th>
              <th className="px-5 py-2.5 font-semibold">Free stock</th>
              <th className="px-5 py-2.5 font-semibold">Reorder level</th>
              <th className="px-5 py-2.5 font-semibold">Stock coverage</th>
              <th className="px-5 py-2.5 font-semibold">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {lowStockItems.map((item) => (
              <tr
                key={`${item.product_id}-${item.warehouse_name}`}
                className="transition hover:bg-slate-50/70"
              >
                <td className="whitespace-nowrap px-5 py-3">
                  <p className="text-xs font-semibold text-slate-800">
                    {item.product_name}
                  </p>
                  <p className="font-mono text-[10px] text-slate-400">{item.product_id}</p>
                </td>
                <td className="whitespace-nowrap px-5 py-3 text-xs text-slate-500">
                  {item.warehouse_name}
                </td>
                <td className="whitespace-nowrap px-5 py-3 text-xs font-semibold text-rose-600">
                  {formatNumber(item.free_stock)}
                </td>
                <td className="whitespace-nowrap px-5 py-3 text-xs text-slate-500">
                  {formatNumber(item.reorder_level)}
                </td>
                <td className="w-44 px-5 py-3">
                  <div className="flex items-center gap-2">
                    <ProgressBar
                      value={item.free_stock}
                      max={item.reorder_level}
                      tone="danger"
                    />
                    <span className="w-9 text-right text-[10px] font-semibold text-slate-400">
                      {Math.round((item.free_stock / item.reorder_level) * 100)}%
                    </span>
                  </div>
                </td>
                <td className="whitespace-nowrap px-5 py-3">
                  <StatusBadge status="Low Stock" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
