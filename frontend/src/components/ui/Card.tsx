import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

interface CardProps {
  children: ReactNode
  className?: string
}

export function Card({ children, className = '' }: CardProps) {
  return (
    <div
      className={`rounded-2xl border border-slate-200/80 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04),0_10px_30px_-18px_rgba(15,23,42,0.25)] ${className}`}
    >
      {children}
    </div>
  )
}

interface CardHeaderProps {
  title: string
  description?: string
  icon?: LucideIcon
  action?: ReactNode
}

export function CardHeader({
  title,
  description,
  icon: Icon,
  action,
}: CardHeaderProps) {
  return (
    <div className="flex flex-col gap-3 p-5 pb-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="flex items-start gap-3">
        {Icon ? (
          <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-xl bg-accent-50 text-accent-600">
            <Icon className="h-4.5 w-4.5" strokeWidth={2} />
          </div>
        ) : null}
        <div>
          <h2 className="text-sm font-semibold tracking-tight text-slate-900">
            {title}
          </h2>
          {description ? (
            <p className="mt-0.5 text-xs leading-5 text-slate-500">{description}</p>
          ) : null}
        </div>
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  )
}
