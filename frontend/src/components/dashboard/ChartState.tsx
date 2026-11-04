import { CircleAlert, LoaderCircle } from 'lucide-react'

interface ChartStateProps {
  loading?: boolean
  error?: string | null
  emptyMessage: string
}

export function ChartState({
  loading = false,
  error = null,
  emptyMessage,
}: ChartStateProps) {
  return (
    <div className="flex h-[300px] flex-col items-center justify-center gap-2 px-6 text-center">
      {loading ? (
        <>
          <LoaderCircle className="h-5 w-5 animate-spin text-accent-500" />
          <p className="text-xs font-medium text-slate-500">Loading live data…</p>
        </>
      ) : error ? (
        <>
          <CircleAlert className="h-5 w-5 text-rose-500" />
          <p className="text-xs font-medium text-rose-600">{error}</p>
        </>
      ) : (
        <p className="text-xs font-medium text-slate-400">{emptyMessage}</p>
      )}
    </div>
  )
}
