import type { LucideIcon } from 'lucide-react'
import { Card } from '../ui/Card'

type KpiTone = 'blue' | 'emerald' | 'amber' | 'rose' | 'violet' | 'slate'

const toneStyles: Record<KpiTone, { icon: string; value: string }> = {
  blue: { icon: 'bg-accent-50 text-accent-600', value: 'text-slate-900' },
  emerald: { icon: 'bg-emerald-50 text-emerald-600', value: 'text-slate-900' },
  amber: { icon: 'bg-amber-50 text-amber-600', value: 'text-slate-900' },
  rose: { icon: 'bg-rose-50 text-rose-600', value: 'text-slate-900' },
  violet: { icon: 'bg-violet-50 text-violet-600', value: 'text-slate-900' },
  slate: { icon: 'bg-slate-100 text-slate-600', value: 'text-slate-900' },
}

interface KpiCardProps {
  label: string
  value: string
  helper: string
  icon: LucideIcon
  tone?: KpiTone
}

export function KpiCard({
  label,
  value,
  helper,
  icon: Icon,
  tone = 'blue',
}: KpiCardProps) {
  const styles = toneStyles[tone]

  return (
    <Card className="group p-5 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_2px_4px_rgba(15,23,42,0.04),0_18px_38px_-20px_rgba(15,23,42,0.32)]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[12px] font-medium text-slate-500">{label}</p>
          <p className={`mt-2 text-2xl font-bold tracking-tight ${styles.value}`}>
            {value}
          </p>
        </div>
        <div
          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl transition-transform duration-200 group-hover:scale-105 ${styles.icon}`}
        >
          <Icon className="h-5 w-5" strokeWidth={2} />
        </div>
      </div>
      <p className="mt-3 text-[11px] font-medium text-slate-400">{helper}</p>
    </Card>
  )
}
