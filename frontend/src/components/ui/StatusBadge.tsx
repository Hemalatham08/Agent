const statusStyles: Record<string, string> = {
  Pending: 'bg-amber-50 text-amber-700 ring-amber-600/20',
  Processing: 'bg-blue-50 text-blue-700 ring-blue-600/20',
  'Partially Dispatched': 'bg-indigo-50 text-indigo-700 ring-indigo-600/20',
  'Partially Received': 'bg-indigo-50 text-indigo-700 ring-indigo-600/20',
  'Partially Paid': 'bg-amber-50 text-amber-700 ring-amber-600/20',
  Dispatched: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  Received: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  Paid: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  Delayed: 'bg-rose-50 text-rose-700 ring-rose-600/20',
  Unpaid: 'bg-rose-50 text-rose-700 ring-rose-600/20',
  'Low Stock': 'bg-rose-50 text-rose-700 ring-rose-600/20',
  Healthy: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  Accepted: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  Rejected: 'bg-rose-50 text-rose-700 ring-rose-600/20',
  Verified: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  'Not verified': 'bg-rose-50 text-rose-700 ring-rose-600/20',
  'On track': 'bg-accent-50 text-accent-700 ring-accent-600/20',
}

interface StatusBadgeProps {
  status: string
  className?: string
}

export function StatusBadge({ status, className = '' }: StatusBadgeProps) {
  const style =
    statusStyles[status] ?? 'bg-slate-100 text-slate-600 ring-slate-500/20'

  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ring-inset ${style} ${className}`}
    >
      {status}
    </span>
  )
}
