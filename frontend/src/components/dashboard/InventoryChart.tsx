import { Boxes } from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { inventoryOverview } from '../../data/demo'
import { formatNumber } from '../../lib/format'
import { Card, CardHeader } from '../ui/Card'

export function InventoryChart() {
  return (
    <Card>
      <CardHeader
        title="Inventory overview"
        description="Free and reserved stock by product across both warehouses"
        icon={Boxes}
        action={
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-semibold text-slate-500">
            2 warehouses
          </span>
        }
      />
      <div className="h-[300px] px-2 pb-4">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={inventoryOverview}
            barGap={6}
            margin={{ top: 8, right: 12, left: -14, bottom: 0 }}
          >
            <CartesianGrid strokeDasharray="4 4" vertical={false} stroke="#e2e8f0" />
            <XAxis
              dataKey="name"
              tick={{ fontSize: 10, fill: '#94a3b8' }}
              tickLine={false}
              axisLine={false}
              interval={0}
              angle={-18}
              textAnchor="end"
              height={62}
            />
            <YAxis
              tick={{ fontSize: 10, fill: '#94a3b8' }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(value) => formatNumber(Number(value))}
            />
            <Tooltip
              cursor={{ fill: '#f8fafc' }}
              contentStyle={{
                borderRadius: 12,
                border: '1px solid #e2e8f0',
                boxShadow: '0 12px 30px -12px rgba(15,23,42,0.25)',
                fontSize: 12,
              }}
              formatter={(value, name) => [
                formatNumber(Number(value)),
                name === 'free' ? 'Free stock' : 'Reserved',
              ]}
            />
            <Legend
              formatter={(value) => (value === 'free' ? 'Free stock' : 'Reserved')}
              wrapperStyle={{ fontSize: 11, paddingTop: 10 }}
            />
            <Bar dataKey="free" fill="#2563eb" radius={[6, 6, 0, 0]} maxBarSize={30} />
            <Bar
              dataKey="reserved"
              fill="#cbd5e1"
              radius={[6, 6, 0, 0]}
              maxBarSize={30}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  )
}
