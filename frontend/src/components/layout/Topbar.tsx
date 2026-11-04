import { Bell, Menu, Search } from 'lucide-react'
import { useLocation } from 'react-router-dom'

const pageTitles: Record<string, string> = {
  '/': 'Dashboard',
  '/assistant': 'AI Assistant',
  '/inventory': 'Inventory',
  '/sales': 'Sales Orders',
  '/purchase': 'Purchase Orders',
  '/dispatch': 'Dispatch',
  '/quality': 'Quality',
  '/accounting': 'Accounting',
  '/products': 'Products',
}

interface TopbarProps {
  onMenuClick: () => void
}

export function Topbar({ onMenuClick }: TopbarProps) {
  const location = useLocation()
  const title = pageTitles[location.pathname] ?? 'Dashboard'

  return (
    <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-white/85 backdrop-blur-xl">
      <div className="mx-auto flex h-16 w-full max-w-[1600px] items-center gap-3 px-4 sm:px-6 lg:px-8">
        <button
          type="button"
          onClick={onMenuClick}
          className="rounded-xl p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-900 lg:hidden"
          aria-label="Open navigation"
        >
          <Menu className="h-5 w-5" />
        </button>

        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-slate-900">{title}</p>
          <p className="hidden text-[11px] text-slate-400 sm:block">
            Enterprise resource planning
          </p>
        </div>

        <div className="ml-auto flex items-center gap-2 sm:gap-3">
          <div className="relative hidden md:block">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              type="search"
              placeholder="Search ERP..."
              className="h-9 w-52 rounded-xl border border-slate-200 bg-slate-50 pl-9 pr-3 text-xs text-slate-700 outline-none transition placeholder:text-slate-400 focus:border-accent-300 focus:bg-white focus:ring-4 focus:ring-accent-50 lg:w-64"
              aria-label="Search ERP"
            />
          </div>

          <span className="hidden rounded-full bg-emerald-50 px-2.5 py-1 text-[10px] font-semibold text-emerald-700 ring-1 ring-inset ring-emerald-600/20 sm:inline-flex">
            Demo data
          </span>

          <button
            type="button"
            className="relative rounded-xl p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"
            aria-label="Notifications"
          >
            <Bell className="h-5 w-5" />
            <span className="absolute right-2 top-2 h-1.5 w-1.5 rounded-full bg-rose-500 ring-2 ring-white" />
          </button>

          <div className="flex items-center gap-2.5 border-l border-slate-200 pl-2 sm:pl-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-navy-900 text-[11px] font-bold text-white">
              AF
            </div>
            <div className="hidden leading-tight sm:block">
              <p className="text-xs font-semibold text-slate-800">ABC Fasteners</p>
              <p className="text-[10px] text-slate-400">Administrator</p>
            </div>
          </div>
        </div>
      </div>
    </header>
  )
}
