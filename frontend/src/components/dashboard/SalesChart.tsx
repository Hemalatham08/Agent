import { TrendingUp } from 'lucide-react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { salesOverview } from '../../data/demo'
import { formatCompactCurrency, formatCurrency } from '../../lib/format'
import { Card, CardHeader } from '../ui/Card'

export function SalesChart() {
  return (
    <Card>
      <CardHeader
        title="Sales overview"
        description="Order value by order date for October 2026"
        icon={TrendingUp}
        action={
          <span className="rounded-full bg-accent-50 px-2.5 py-1 text-[10px] font-semibold text-accent-700">
            ₹14,150 total
          </span>
        }
      />
      <div className="h-[300px] px-2 pb-4">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart
            data={salesOverview}
            margin={{ top: 8, right: 12, left: -10, bottom: 0 }}
          >
            <defs>
              <linearGradient id="salesGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#2563eb" stopOpacity={0.28} />
                <stop offset="95%" stopColor="#2563eb" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="4 4" vertical={false} stroke="#e2e8f0" />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 10, fill: '#94a3b8' }}
              tickLine={false}
              axisLine={false}
              dy={6}
            />
            <YAxis
              tick={{ fontSize: 10, fill: '#94a3b8' }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(value) => formatCompactCurrency(Number(value))}
            />
            <Tooltip
              contentStyle={{
                borderRadius: 12,
                border: '1px solid #e2e8f0',
                boxShadow: '0 12px 30px -12px rgba(15,23,42,0.25)',
                fontSize: 12,
              }}
              formatter={(value) => [formatCurrency(Number(value)), 'Order value']}
            />
            <Area
              type="monotone"
              dataKey="sales"
              stroke="#2563eb"
              strokeWidth={2.5}
              fill="url(#salesGradient)"
              activeDot={{ r: 4, strokeWidth: 2, stroke: '#ffffff' }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </Card>
  )
}
