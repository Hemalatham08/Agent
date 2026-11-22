import {
  Bar,
  BarChart,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  CartesianGrid,
  Legend,
} from 'recharts'
import type { ChartSpec } from '../../services/api'

const COLORS = [
  '#8884d8',
  '#82ca9d',
  '#ffc658',
  '#ff7300',
  '#0088fe',
  '#00c49f',
  '#bbbbbb',
]

interface ErpChartProps {
  spec: ChartSpec
  height?: number
}

function commonAxes(xLabel: string, yLabel: string) {
  return [
    <CartesianGrid key="grid" strokeDasharray="3 3" />,
    <XAxis key="x" dataKey="x" name={xLabel} />,
    <YAxis key="y" name={yLabel} />,
    <Tooltip key="tooltip" />,
    <Legend key="legend" />,
  ]
}

function renderChart(spec: ChartSpec) {
  const { chart_type, data, x_field, y_fields, x_label, y_label } = spec
  const xLabel = x_label || x_field
  const yLabel = y_label || (y_fields[0] || 'Value')
  const primaryField = y_fields[0] || 'value'

  if (chart_type === 'line') {
    return (
      <LineChart data={data} margin={{ top: 20, right: 30, bottom: 40, left: 40 }}>
        {commonAxes(xLabel, yLabel)}
        <Line key="line" dataKey={primaryField} stroke={COLORS[0]} />
      </LineChart>
    )
  }

  if (chart_type === 'pie') {
    return (
      <PieChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
        <Pie
          data={data}
          dataKey={primaryField}
          nameKey="x"
          fill={COLORS[0]}
          label
        />
      </PieChart>
    )
  }

  if (chart_type === 'grouped_bar') {
    return (
      <BarChart
        data={data}
        margin={{ top: 20, right: 30, bottom: 40, left: 40 }}
      >
        {commonAxes(xLabel, yLabel)}
        {y_fields.map((field, i) => (
          <Bar
            key={field}
            dataKey={field}
            fill={COLORS[i % COLORS.length]}
          />
        ))}
      </BarChart>
    )
  }

  // default: bar
  return (
    <BarChart
      data={data}
      margin={{ top: 20, right: 30, bottom: 40, left: 40 }}
    >
      {commonAxes(xLabel, yLabel)}
      <Bar key="bar" dataKey={primaryField} fill={COLORS[0]} />
    </BarChart>
  )
}

export function ErpChart({ spec, height = 220 }: ErpChartProps) {
  const hasData = Array.isArray(spec.data) && spec.data.length > 0
  if (!hasData) {
    return null
  }
  return (
    <div
      data-testid="erp-chart"
      className="w-full"
      style={{ height, minHeight: 180 }}
    >
      <ResponsiveContainer width="100%" height="100%">
        {renderChart(spec)}
      </ResponsiveContainer>
    </div>
  )
}
