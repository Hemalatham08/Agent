import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'

const Dashboard = lazy(() => import('./pages/Dashboard'))
const AIAssistant = lazy(() => import('./pages/AIAssistant'))
const Inventory = lazy(() => import('./pages/Inventory'))
const SalesOrders = lazy(() => import('./pages/SalesOrders'))
const PurchaseOrders = lazy(() => import('./pages/PurchaseOrders'))
const Dispatch = lazy(() => import('./pages/Dispatch'))
const Quality = lazy(() => import('./pages/Quality'))
const Accounting = lazy(() => import('./pages/Accounting'))
const Products = lazy(() => import('./pages/Products'))

function PageLoader() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="flex flex-col items-center gap-3">
        <div className="h-7 w-7 animate-spin rounded-full border-2 border-slate-200 border-t-accent-500" />
        <p className="text-xs font-medium text-slate-400">Loading page...</p>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route element={<AppLayout />}>
            <Route index element={<Dashboard />} />
            <Route path="assistant" element={<AIAssistant />} />
            <Route path="inventory" element={<Inventory />} />
            <Route path="sales" element={<SalesOrders />} />
            <Route path="purchase" element={<PurchaseOrders />} />
            <Route path="dispatch" element={<Dispatch />} />
            <Route path="quality" element={<Quality />} />
            <Route path="accounting" element={<Accounting />} />
            <Route path="products" element={<Products />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
