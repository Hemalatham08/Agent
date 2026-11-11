
import type { ReactNode } from 'react'

interface PageHeaderProps {
  title: string
  description: string
  eyebrow?: string
  actions?: ReactNode
}

export function PageHeader({
  title,
  description,
  eyebrow = 'ABC Fasteners & Industrial Supplies',
  actions,
}: PageHeaderProps) {
  return (
    <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-accent-600">
          {eyebrow}
        </p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900 sm:text-[28px]">
          {title}
        </h1>
        <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-500">{description}</p>
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  )
}
