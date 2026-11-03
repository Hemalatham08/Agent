import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'

export function AppLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)

  return (
    <div className="min-h-screen bg-slate-100">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      {sidebarOpen ? (
        <button
          type="button"
          aria-label="Close navigation overlay"
          onClick={() => setSidebarOpen(false)}
          className="fixed inset-0 z-40 bg-navy-950/50 backdrop-blur-sm lg:hidden"
        />
      ) : null}

      <div className="lg:pl-64">
        <Topbar onMenuClick={() => setSidebarOpen(true)} />
        <main className="mx-auto w-full max-w-[1600px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
