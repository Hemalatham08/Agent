import {
  AlertOctagon,
  AlertTriangle,
  BellRing,
  ChevronRight,
  Info,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { dashboardAlerts } from '../../data/demo'
import type { AlertSeverity } from '../../types'
import { Card, CardHeader } from '../ui/Card'

const severityStyles: Record<
  AlertSeverity,
  { wrap: string; icon: typeof AlertOctagon; dot: string }
> = {
  critical: {
    wrap: 'bg-rose-50 text-rose-600',
    icon: AlertOctagon,
    dot: 'bg-rose-500',
  },
  warning: {
    wrap: 'bg-amber-50 text-amber-600',
    icon: AlertTriangle,
    dot: 'bg-amber-500',
  },
  info: {
    wrap: 'bg-accent-50 text-accent-600',
    icon: Info,
    dot: 'bg-accent-500',
  },
}

export function AlertsPanel() {
  return (
    <Card className="flex h-full flex-col overflow-hidden">
      <CardHeader
        title="Alerts"
        description="Operational items that need attention"
        icon={BellRing}
        action={
          <span className="rounded-full bg-rose-50 px-2.5 py-1 text-[10px] font-semibold text-rose-700">
            {dashboardAlerts.length} open
          </span>
        }
      />
      <div className="scrollbar-thin flex-1 divide-y divide-slate-100 overflow-y-auto">
        {dashboardAlerts.map((alert) => {
          const styles = severityStyles[alert.severity]
          const Icon = styles.icon

          return (
            <Link
              key={alert.id}
              to={alert.href}
              className="group flex items-start gap-3 px-5 py-3.5 transition hover:bg-slate-50/80"
            >
              <div
                className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${styles.wrap}`}
              >
                <Icon className="h-4 w-4" strokeWidth={2} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${styles.dot}`} />
                  <p className="truncate text-xs font-semibold text-slate-800">
                    {alert.title}
                  </p>
                  <span className="ml-auto shrink-0 text-[9px] font-semibold uppercase tracking-wide text-slate-400">
                    {alert.category}
                  </span>
                </div>
                <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-500">
                  {alert.detail}
                </p>
              </div>
              <ChevronRight className="mt-1 h-3.5 w-3.5 shrink-0 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-slate-400" />
            </Link>
          )
        })}
      </div>
    </Card>
  )
}
