import {
  Boxes,
  ClipboardList,
  LayoutDashboard,
  Package,
  ShieldCheck,
  ShoppingCart,
  Sparkles,
  Truck,
  Wallet,
  X,
} from 'lucide-react'
import { NavLink } from 'react-router-dom'

const navItems = [
  { label: 'Dashboard', to: '/', icon: LayoutDashboard, end: true },
  { label: 'AI Assistant', to: '/assistant', icon: Sparkles },
  { label: 'Inventory', to: '/inventory', icon: Boxes },
  { label: 'Sales Orders', to: '/sales', icon: ShoppingCart },
  { label: 'Purchase Orders', to: '/purchase', icon: ClipboardList },
  { label: 'Dispatch', to: '/dispatch', icon: Truck },
  { label: 'Quality', to: '/quality', icon: ShieldCheck },
  { label: 'Accounting', to: '/accounting', icon: Wallet },
  { label: 'Products', to: '/products', icon: Package },
]

interface SidebarProps {
  open: boolean
  onClose: () => void
}

export function Sidebar({ open, onClose }: SidebarProps) {
  return (
    <aside
      className={`fixed inset-y-0 left-0 z-50 flex w-64 flex-col bg-navy-900 text-slate-300 transition-transform duration-300 ease-out lg:translate-x-0 ${
        open ? 'translate-x-0' : '-translate-x-full'
      }`}
    >
      <div className="flex h-16 items-center justify-between border-b border-white/5 px-5">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent-600 shadow-lg shadow-accent-600/30">
            <Boxes className="h-5 w-5 text-white" strokeWidth={2.2} />
          </div>
          <div>
            <p className="text-sm font-bold tracking-tight text-white">iFive ERP</p>
            <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-slate-500">
              AI Agent
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg p-1.5 text-slate-400 transition hover:bg-white/5 hover:text-white lg:hidden"
          aria-label="Close navigation"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      <nav className="scrollbar-thin flex-1 overflow-y-auto px-3 py-5">
        <p className="px-3 pb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-600">
          Workspace
        </p>
        <ul className="space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon

            return (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.end}
                  onClick={onClose}
                  className={({ isActive }) =>
                    `group flex items-center gap-3 rounded-xl px-3 py-2.5 text-[13px] font-medium transition-all ${
                      isActive
                        ? 'bg-accent-600 text-white shadow-lg shadow-accent-600/20'
                        : 'text-slate-400 hover:bg-white/5 hover:text-white'
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      <Icon
                        className={`h-4.5 w-4.5 shrink-0 ${
                          isActive ? 'text-white' : 'text-slate-500 group-hover:text-slate-300'
                        }`}
                        strokeWidth={2}
                      />
                      <span>{item.label}</span>
                      {item.label === 'AI Assistant' ? (
                        <span className="ml-auto rounded-md bg-white/10 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-slate-300">
                          New
                        </span>
                      ) : null}
                    </>
                  )}
                </NavLink>
              </li>
            )
          })}
        </ul>
      </nav>

      <div className="border-t border-white/5 p-4">
        <div className="rounded-xl bg-navy-800/70 p-3.5">
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
            </span>
            <p className="text-[11px] font-semibold text-slate-200">Demo environment</p>
          </div>
          <p className="mt-1.5 text-[10px] leading-4 text-slate-500">
            Backend API
            <br />
            <span className="font-mono text-slate-400">127.0.0.1:8000</span>
          </p>
        </div>
        <p className="mt-3 px-1 text-[10px] text-slate-600">
          © 2026 iFive Technologies
        </p>
      </div>
    </aside>
  )
}
