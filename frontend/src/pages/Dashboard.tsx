import {
  AlertTriangle,
  CalendarDays,
  CircleAlert,
  ClipboardList,
  IndianRupee,
  Package,
  RefreshCw,
  ShieldCheck,
  ShoppingCart,
  Truck,
  Wallet,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertsPanel } from '../components/dashboard/AlertsPanel'
import { InventoryChart } from '../components/dashboard/InventoryChart'
import { KpiCard } from '../components/dashboard/KpiCard'
import { LowStockTable } from '../components/dashboard/LowStockTable'
import { RecentSalesTable } from '../components/dashboard/RecentSalesTable'
import { SalesChart } from '../components/dashboard/SalesChart'
import { PageHeader } from '../components/ui/PageHeader'
import { formatCurrency, formatNumber, formatShortDate } from '../lib/format'
import { erpApi } from '../services/api'
import type {
  DashboardAlert,
  DispatchIssue,
  InventoryChartPoint,
  InventoryStatus,
  Invoice,
  LowStockItem,
  PendingOrdersChartPoint,
  Product,
  PurchaseOrder,
  QualityIssue,
  SalesOrder,
} from '../types'

interface DashboardData {
  products: Product[]
  inventory: InventoryStatus[]
  lowStock: LowStockItem[]
  pendingSales: SalesOrder[]
  pendingPurchase: PurchaseOrder[]
  dispatchIssues: DispatchIssue[]
  qualityIssues: QualityIssue[]
  unpaidInvoices: Invoice[]
}

const emptyDashboardData: DashboardData = {
  products: [],
  inventory: [],
  lowStock: [],
  pendingSales: [],
  pendingPurchase: [],
  dispatchIssues: [],
  qualityIssues: [],
  unpaidInvoices: [],
}

function unwrap<T>(
  result: PromiseSettledResult<T>,
  label: string,
  failures: string[],
  fallback: T,
): T {
  if (result.status === 'fulfilled') {
    return result.value
  }

  failures.push(label)
  return fallback
}

function useDashboardData() {
  const [data, setData] = useState<DashboardData>(emptyDashboardData)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [failedSources, setFailedSources] = useState<string[]>([])
  const [reloadKey, setReloadKey] = useState(0)

  const reload = useCallback(() => {
    setReloadKey((key) => key + 1)
  }, [])

  useEffect(() => {
    let cancelled = false

    async function load() {
      setIsLoading(true)
      setError(null)
      setFailedSources([])
      setData(emptyDashboardData)

      const [
        productsResult,
        lowStockResult,
        pendingSalesResult,
        pendingPurchaseResult,
        dispatchResult,
        qualityResult,
        invoicesResult,
      ] = await Promise.allSettled([
        erpApi.getProducts(),
        erpApi.getLowStock(),
        erpApi.getPendingSalesOrders(),
        erpApi.getPendingPurchaseOrders(),
        erpApi.getDispatchIssues(),
        erpApi.getQualityIssues(),
        erpApi.getUnpaidInvoices(),
      ])

      const failures: string[] = []

      const products = unwrap(productsResult, 'products', failures, [])
      const lowStock = unwrap(lowStockResult, 'low-stock', failures, [])
      const pendingSales = unwrap(
        pendingSalesResult,
        'pending-sales',
        failures,
        [],
      )
      const pendingPurchase = unwrap(
        pendingPurchaseResult,
        'pending-purchases',
        failures,
        [],
      )
      const dispatchIssues = unwrap(
        dispatchResult,
        'dispatch-issues',
        failures,
        [],
      )
      const qualityIssues = unwrap(
        qualityResult,
        'quality-issues',
        failures,
        [],
      )
      const unpaidInvoices = unwrap(
        invoicesResult,
        'unpaid-invoices',
        failures,
        [],
      )

      const inventory: InventoryStatus[] = []

      if (productsResult.status === 'fulfilled') {
        const inventoryResults = await Promise.allSettled(
          products.map((product) => erpApi.getInventory(product.product_id)),
        )

        inventoryResults.forEach((result) => {
          if (result.status === 'fulfilled') {
            inventory.push(...result.value)
          } else {
            failures.push('inventory')
          }
        })
      } else {
        failures.push('inventory')
      }

      if (cancelled) {
        return
      }

      const uniqueFailures = [...new Set(failures)]

      setData({
        products,
        inventory,
        lowStock,
        pendingSales,
        pendingPurchase,
        dispatchIssues,
        qualityIssues,
        unpaidInvoices,
      })
      setFailedSources(uniqueFailures)
      setError(
        uniqueFailures.length > 0
          ? `Some live data could not be loaded: ${uniqueFailures.join(', ')}.`
          : null,
      )
      setIsLoading(false)
    }

    void load().catch((requestError) => {
      if (cancelled) {
        return
      }

      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Could not load live dashboard data.',
      )
      setFailedSources(['dashboard'])
      setIsLoading(false)
    })

    return () => {
      cancelled = true
    }
  }, [reloadKey])

  return { data, isLoading, error, failedSources, reload }
}

export default function Dashboard() {
  const { data, isLoading, error, failedSources, reload } = useDashboardData()

  const productById = useMemo(
    () => new Map(data.products.map((product) => [product.product_id, product])),
    [data.products],
  )

  const categoryCount = useMemo(
    () => new Set(data.products.map((product) => product.category)).size,
    [data.products],
  )

  const warehouseCount = useMemo(
    () => new Set(data.inventory.map((item) => item.warehouse_name)).size,
    [data.inventory],
  )

  const inventoryValue = useMemo(
    () =>
      data.inventory.reduce((total, record) => {
        const product = productById.get(record.product_id)
        return total + record.on_hand_qty * (product?.purchase_price ?? 0)
      }, 0),
    [data.inventory, productById],
  )

  const delayedPurchaseCount = useMemo(
    () =>
      data.pendingPurchase.filter((order) => order.status === 'Delayed').length,
    [data.pendingPurchase],
  )

  const rejectedUnits = useMemo(
    () =>
      data.qualityIssues.reduce(
        (total, inspection) => total + inspection.rejected_qty,
        0,
      ),
    [data.qualityIssues],
  )

  const totalOutstanding = useMemo(
    () =>
      data.unpaidInvoices.reduce(
        (total, invoice) => total + invoice.outstanding_amount,
        0,
      ),
    [data.unpaidInvoices],
  )

  const inventoryChartData = useMemo<InventoryChartPoint[]>(
    () =>
      data.products.flatMap((product) => {
        const records = data.inventory.filter(
          (record) => record.product_id === product.product_id,
        )

        if (records.length === 0) {
          return []
        }

        return [
          {
            name: product.product_name,
            free: records.reduce(
              (total, record) =>
                total + record.on_hand_qty - record.reserved_qty,
              0,
            ),
            reserved: records.reduce(
              (total, record) => total + record.reserved_qty,
              0,
            ),
          },
        ]
      }),
    [data.products, data.inventory],
  )

  const pendingOrdersChartData = useMemo<PendingOrdersChartPoint[]>(() => {
    const counts = new Map<string, number>()

    for (const order of data.pendingSales) {
      counts.set(order.order_date, (counts.get(order.order_date) ?? 0) + 1)
    }

    return [...counts.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([date, orders]) => ({
        label: formatShortDate(date),
        orders,
      }))
  }, [data.pendingSales])

  const alerts = useMemo<DashboardAlert[]>(() => {
    const items: DashboardAlert[] = []

    if (data.dispatchIssues.length > 0) {
      items.push({
        id: 'live-dispatch-issues',
        title: `${formatNumber(data.dispatchIssues.length)} dispatch issue${
          data.dispatchIssues.length === 1 ? '' : 's'
        }`,
        detail:
          'Picked quantities differ from dispatched quantities or barcode verification is missing.',
        severity: 'critical',
        category: 'Dispatch',
        href: '/dispatch',
      })
    }

    if (data.lowStock.length > 0) {
      items.push({
        id: 'live-low-stock',
        title: `${formatNumber(data.lowStock.length)} low-stock alert${
          data.lowStock.length === 1 ? '' : 's'
        }`,
        detail: `${formatNumber(data.lowStock.length)} SKU/warehouse combination${
          data.lowStock.length === 1 ? ' is' : 's are'
        } at or below reorder level.`,
        severity: 'warning',
        category: 'Inventory',
        href: '/inventory',
      })
    }

    if (delayedPurchaseCount > 0) {
      items.push({
        id: 'live-purchase-delay',
        title: `${formatNumber(delayedPurchaseCount)} delayed purchase order${
          delayedPurchaseCount === 1 ? '' : 's'
        }`,
        detail: 'Purchase orders are marked as delayed and still awaiting receipt.',
        severity: 'warning',
        category: 'Purchase',
        href: '/purchase',
      })
    }

    if (data.qualityIssues.length > 0) {
      items.push({
        id: 'live-quality',
        title: `${formatNumber(rejectedUnits)} units rejected`,
        detail: `${formatNumber(data.qualityIssues.length)} inspection${
          data.qualityIssues.length === 1 ? '' : 's'
        } recorded rejected quantity.`,
        severity: 'warning',
        category: 'Quality',
        href: '/quality',
      })
    }

    if (data.unpaidInvoices.length > 0) {
      items.push({
        id: 'live-accounting',
        title: `${formatCurrency(totalOutstanding)} outstanding`,
        detail: `${formatNumber(data.unpaidInvoices.length)} invoice${
          data.unpaidInvoices.length === 1 ? '' : 's'
        } remain partially paid or unpaid.`,
        severity: 'critical',
        category: 'Accounting',
        href: '/accounting',
      })
    }

    if (data.pendingSales.length > 0) {
      items.push({
        id: 'live-pending-sales',
        title: `${formatNumber(data.pendingSales.length)} pending sales order${
          data.pendingSales.length === 1 ? '' : 's'
        }`,
        detail: 'Sales orders are not yet fully dispatched.',
        severity: 'info',
        category: 'Sales',
        href: '/sales',
      })
    }

    return items
  }, [
    data.dispatchIssues.length,
    data.lowStock.length,
    data.qualityIssues.length,
    data.pendingSales.length,
    data.unpaidInvoices.length,
    delayedPurchaseCount,
    rejectedUnits,
    totalOutstanding,
  ])

  const sourceFailed = (source: string) => failedSources.includes(source)
  const metricValue = (source: string, value: string) =>
    !isLoading && sourceFailed(source) ? '—' : value
  const metricHelper = (source: string, helper: string) =>
    !isLoading && sourceFailed(source) ? 'Live data unavailable' : helper

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="A live snapshot of inventory, sales, purchasing, dispatch, quality, and receivables."
        actions={
          <>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-[11px] font-semibold text-slate-500">
              <CalendarDays className="h-3.5 w-3.5" />
              Oct 2026
            </span>
            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[11px] font-semibold ${
                isLoading
                  ? 'border-amber-200 bg-amber-50 text-amber-700'
                  : error
                    ? 'border-rose-200 bg-rose-50 text-rose-700'
                    : 'border-emerald-200 bg-emerald-50 text-emerald-700'
              }`}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  isLoading
                    ? 'animate-pulse bg-amber-500'
                    : error
                      ? 'bg-rose-500'
                      : 'bg-emerald-500'
                }`}
              />
              {isLoading ? 'Connecting…' : error ? 'Data issue' : 'Live data'}
            </span>
          </>
        }
      />

      {error ? (
        <div className="mb-5 flex flex-col gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 sm:flex-row sm:items-start">
          <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-rose-500" />
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold text-rose-700">
              Some dashboard data could not be loaded
            </p>
            <p className="mt-0.5 text-[11px] leading-5 text-rose-600">{error}</p>
          </div>
          <button
            type="button"
            onClick={reload}
            disabled={isLoading}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-white px-3 py-1.5 text-[11px] font-semibold text-rose-600 ring-1 ring-rose-200 transition hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${isLoading ? 'animate-spin' : ''}`}
            />
            Retry
          </button>
        </div>
      ) : null}

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Total Products"
          value={metricValue('products', formatNumber(data.products.length))}
          helper={metricHelper(
            'products',
            `${formatNumber(categoryCount)} categories · ${formatNumber(
              warehouseCount,
            )} warehouses`,
          )}
          icon={Package}
          tone="blue"
          loading={isLoading}
        />
        <KpiCard
          label="Inventory Value"
          value={metricValue('inventory', formatCurrency(inventoryValue))}
          helper={metricHelper('inventory', 'Valued at purchase cost')}
          icon={IndianRupee}
          tone="emerald"
          loading={isLoading}
        />
        <KpiCard
          label="Pending Sales Orders"
          value={metricValue(
            'pending-sales',
            formatNumber(data.pendingSales.length),
          )}
          helper={metricHelper(
            'pending-sales',
            'Order value missing from /sales/pending',
          )}
          icon={ShoppingCart}
          tone="violet"
          loading={isLoading}
        />
        <KpiCard
          label="Pending Purchase Orders"
          value={metricValue(
            'pending-purchases',
            formatNumber(data.pendingPurchase.length),
          )}
          helper={metricHelper(
            'pending-purchases',
            `${formatNumber(delayedPurchaseCount)} delayed order${
              delayedPurchaseCount === 1 ? '' : 's'
            }`,
          )}
          icon={ClipboardList}
          tone="amber"
          loading={isLoading}
        />
        <KpiCard
          label="Low Stock Alerts"
          value={metricValue('low-stock', formatNumber(data.lowStock.length))}
          helper={metricHelper('low-stock', 'At or below reorder level')}
          icon={AlertTriangle}
          tone="rose"
          loading={isLoading}
        />
        <KpiCard
          label="Dispatch Issues"
          value={metricValue(
            'dispatch-issues',
            formatNumber(data.dispatchIssues.length),
          )}
          helper={metricHelper(
            'dispatch-issues',
            'Quantity and barcode exceptions',
          )}
          icon={Truck}
          tone="amber"
          loading={isLoading}
        />
        <KpiCard
          label="Quality Issues"
          value={metricValue(
            'quality-issues',
            formatNumber(data.qualityIssues.length),
          )}
          helper={metricHelper(
            'quality-issues',
            `${formatNumber(rejectedUnits)} units rejected`,
          )}
          icon={ShieldCheck}
          tone="rose"
          loading={isLoading}
        />
        <KpiCard
          label="Outstanding Invoices"
          value={metricValue(
            'unpaid-invoices',
            formatNumber(data.unpaidInvoices.length),
          )}
          helper={metricHelper(
            'unpaid-invoices',
            `${formatCurrency(totalOutstanding)} outstanding`,
          )}
          icon={Wallet}
          tone="slate"
          loading={isLoading}
        />
      </section>

      <section className="mt-5 grid grid-cols-1 gap-5 xl:grid-cols-2">
        <InventoryChart
          data={inventoryChartData}
          warehouseCount={warehouseCount}
          loading={isLoading}
          error={
            sourceFailed('inventory') || sourceFailed('products')
              ? 'Inventory data unavailable.'
              : null
          }
        />
        <SalesChart
          data={pendingOrdersChartData}
          totalOrders={data.pendingSales.length}
          loading={isLoading}
          error={
            sourceFailed('pending-sales')
              ? 'Pending sales data unavailable.'
              : null
          }
        />
      </section>

      <section className="mt-5 grid grid-cols-1 gap-5 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <RecentSalesTable
            orders={data.pendingSales}
            loading={isLoading}
            error={
              sourceFailed('pending-sales')
                ? 'Pending sales data unavailable.'
                : null
            }
          />
        </div>
        <AlertsPanel alerts={alerts} loading={isLoading} error={error} />
      </section>

      <section className="mt-5">
        <LowStockTable
          items={data.lowStock}
          loading={isLoading}
          error={
            sourceFailed('low-stock') ? 'Low-stock data unavailable.' : null
          }
        />
      </section>
    </>
  )
}
