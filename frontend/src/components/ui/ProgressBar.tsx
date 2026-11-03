interface ProgressBarProps {
  value: number
  max: number
  tone?: 'accent' | 'danger' | 'warning' | 'success'
}

const toneStyles = {
  accent: 'bg-accent-600',
  danger: 'bg-rose-500',
  warning: 'bg-amber-500',
  success: 'bg-emerald-500',
}

export function ProgressBar({ value, max, tone = 'accent' }: ProgressBarProps) {
  const percentage = max > 0 ? Math.min(Math.max((value / max) * 100, 0), 100) : 0

  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
      <div
        className={`h-full rounded-full transition-all duration-500 ${toneStyles[tone]}`}
        style={{ width: `${percentage}%` }}
      />
    </div>
  )
}
