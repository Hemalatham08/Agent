import {
  AlertTriangle,
  Boxes,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Layers,
  RefreshCw,
  Search,
  Warehouse,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { KpiCard } from '../components/dashboard/KpiCard'
import { Card, CardHeader } from '../components/ui/Card'
import { PageHeader } from '../components/ui/PageHeader'
import { StatusBadge } from '../components/ui/StatusBadge'
import { formatNumber } from '../lib/format'
import { erpApi } from '../services/api'
import type { InventoryStatus } from '../types'

interface InventoryLedgerRow extends InventoryStatus {
  sku: string
}

const PAGE_SIZE = 6

export default function Inventory() {
  const [rows, setRows] = useState<InventoryLedgerRow[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [searchQuery, setSearchQuery] = useState('')
  const [warehouseFilter, setWarehouseFilter] = useState('all')
  const [stockFilter, setStockFilter] = useState<'all' | 'low' | 'healthy'>('all')
  const [page, setPage] = useState(1)

  const reload = useCallback(() => {
    setReloadKey((key) => key + 1)
  }, [])

  const clearFilters = useCallback(() => {
    setSearchQuery('')
    setWarehouseFilter('all')
    setStockFilter('all')
    setPage(1)
  }, [])

  useEffect(() => {
    let cancelled = false

    async function load() {
      setIsLoading(true)
      setError(null)
      setRows([])

      try {
        const products = await erpApi.getProducts()
        const inventoryResults = await Promise.allSettled(
          products.map((product) => erpApi.getInventory(product.product_id)),
        )

        if (cancelled) {
          return
        }

        const nextRows: InventoryLedgerRow[] = []
        let failedProducts = 0

        inventoryResults.forEach((result, index) => {
          if (result.status === 'fulfilled') {
            const product = products[index]

            result.value.forEach((item) => {
              nextRows.push({
                ...item,
                sku: product.sku,
              })
            })
          } else {
            failedProducts += 1
          }
        })

        nextRows.sort(
          (left, right) =>
            left.product_id.localeCompare(right.product_id) ||
            left.warehouse_name.localeCompare(right.warehouse_name),
        )

        setRows(nextRows)

        if (failedProducts > 0) {
          setError(
            `${failedProducts} product inventory record${
              failedProducts === 1 ? '' : 's'
            } could not be loaded.`,
          )
        }
      } catch (requestError) {
        if (cancelled) {
          return
        }

        setError(
          requestError instanceof Error
            ? requestError.message
            : 'Could not load live inventory data.',
        )
      } finally {
        if (!cancelled) {
          setIsLoading(false)
        }
      }
    }

    void load()

    return () => {
      cancelled = true
    }
  }, [reloadKey])

  const onHandUnits = rows.reduce((total, row) => total + row.on_hand_qty, 0)
  const reservedUnits = rows.reduce((total, row) => total + row.reserved_qty, 0)
  const freeUnits = rows.reduce((total, row) => total + row.free_stock, 0)
  const lowStockRows = rows.filter((row) => row.free_stock <= row.reorder_level)
  const warehouseCount = new Set(rows.map((row) => row.warehouse_name)).size
  const hasData = rows.length > 0
  const metricValue = (value: number) =>
    error !== null && !hasData ? '—' : formatNumber(value)

  const warehouseOptions = useMemo(
    () =>
      Array.from(new Set(rows.map((row) => row.warehouse_name))).sort((a, b) =>
        a.localeCompare(b),
      ),
    [rows],
  )

  const normalizedQuery = searchQuery.trim().toLowerCase()

  const filteredRows = useMemo(() => {
    return rows.filter((row) => {
      const isLowStock = row.free_stock <= row.reorder_level

      if (warehouseFilter !== 'all' && row.warehouse_name !== warehouseFilter) {
        return false
      }

      if (stockFilter === 'low' && !isLowStock) {
        return false
      }

      if (stockFilter === 'healthy' && isLowStock) {
        return false
      }

      if (normalizedQuery) {
        const haystack = [
          row.product_name,
          row.product_id,
          row.sku,
          row.warehouse_name,
        ]
          .join(' ')
          .toLowerCase()

        if (!haystack.includes(normalizedQuery)) {
          return false
        }
      }

      return true
    })
  }, [normalizedQuery, rows, stockFilter, warehouseFilter])



  const totalRecords = rows.length
  const filteredCount = filteredRows.length
  const totalPages = Math.max(1, Math.ceil(filteredCount / PAGE_SIZE))
  const currentPage = Math.min(page, totalPages)
  const pageStartIndex = (currentPage - 1) * PAGE_SIZE
  const paginatedRows = filteredRows.slice(pageStartIndex, pageStartIndex + PAGE_SIZE)
  const hasActiveFilters =
    normalizedQuery.length > 0 || warehouseFilter !== 'all' || stockFilter !== 'all'
  const showingFrom = filteredCount === 0 ? 0 : pageStartIndex + 1
  const showingTo = Math.min(pageStartIndex + PAGE_SIZE, filteredCount)

  return (
    <>
      <PageHeader
        title="Inventory"
        description="Stock on hand, reserved quantities, and free stock across every warehouse."
        actions={
          <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-[11px] font-semibold text-slate-500">
            <Warehouse className="h-3.5 w-3.5" />
            {isLoading
              ? 'Loading warehouses…'
              : error !== null && !hasData
                ? 'Warehouses unavailable'
                : `${formatNumber(warehouseCount)} warehouse${
                    warehouseCount === 1 ? '' : 's'
                  }`}
          </span>
        }
      />

      {error ? (
        <div className="mb-5 flex flex-col gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 sm:flex-row sm:items-start">
          <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-rose-500" />
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold text-rose-700">
              Some inventory data could not be loaded
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
          label="On-hand Units"
          value={metricValue(onHandUnits)}
          helper="Across all stock records"
          icon={Boxes}
          tone="blue"
          loading={isLoading}
        />
        <KpiCard
          label="Reserved Units"
          value={metricValue(reservedUnits)}
          helper="Committed to open orders"
          icon={Layers}
          tone="violet"
          loading={isLoading}
        />
        <KpiCard
          label="Free Stock"
          value={metricValue(freeUnits)}
          helper="Available to promise"
          icon={Warehouse}
          tone="emerald"
          loading={isLoading}
        />
        <KpiCard
          label="Low-stock Records"
          value={metricValue(lowStockRows.length)}
          helper="At or below reorder level"
          icon={AlertTriangle}
          tone="rose"
          loading={isLoading}
        />
      </section>

      <Card className="mt-5 overflow-hidden">
        <CardHeader
          title="Stock ledger"
          description="Warehouse-level inventory derived from the ERP database"
          icon={Boxes}
          action={
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-semibold text-slate-500">
              {isLoading
                ? 'Loading…'
                : hasActiveFilters
                  ? `${formatNumber(filteredCount)} of ${formatNumber(totalRecords)} stock records`
                  : `${formatNumber(totalRecords)} stock records`}
            </span>
          }
        />

        <div className="border-y border-slate-100 bg-slate-50/40 px-5 py-4">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
            <div className="relative min-w-0 flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={searchQuery}
                onChange={(event) => {
                  setSearchQuery(event.target.value)
                  setPage(1)
                }}
                placeholder="Search by product, product ID, SKU, or warehouse"
                className="h-10 w-full rounded-xl border border-slate-200 bg-white py-2 pl-9 pr-9 text-xs text-slate-700 outline-none transition placeholder:text-slate-400 focus:border-accent-300 focus:ring-4 focus:ring-accent-50"
                aria-label="Search stock ledger"
              />
              {searchQuery ? (
                <button
                  type="button"
                  onClick={() => {
                    setSearchQuery('')
                    setPage(1)
                  }}
                  className="absolute right-2 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-md text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
                  aria-label="Clear search"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              ) : null}
            </div>

            <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap xl:justify-end">
              <select
                value={warehouseFilter}
                onChange={(event) => {
                  setWarehouseFilter(event.target.value)
                  setPage(1)
                }}
                className="h-10 min-w-[180px] rounded-xl border border-slate-200 bg-white px-3 text-xs font-medium text-slate-700 outline-none transition focus:border-accent-300 focus:ring-4 focus:ring-accent-50"
                aria-label="Filter by warehouse"
              >
                <option value="all">All Warehouses</option>
                {warehouseOptions.map((warehouse) => (
                  <option key={warehouse} value={warehouse}>
                    {warehouse}
                  </option>
                ))}
              </select>

              <select
                value={stockFilter}
                onChange={(event) => {
                  setStockFilter(event.target.value as 'all' | 'low' | 'healthy')
                  setPage(1)
                }}
                className="h-10 min-w-[150px] rounded-xl border border-slate-200 bg-white px-3 text-xs font-medium text-slate-700 outline-none transition focus:border-accent-300 focus:ring-4 focus:ring-accent-50"
                aria-label="Filter by stock status"
              >
                <option value="all">All Statuses</option>
                <option value="low">Low Stock</option>
                <option value="healthy">Healthy</option>
              </select>

              <button
                type="button"
                onClick={clearFilters}
                disabled={!hasActiveFilters}
                className="inline-flex h-10 items-center justify-center rounded-xl border border-slate-200 bg-white px-4 text-xs font-semibold text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Clear Filters
              </button>
            </div>
          </div>

          {!isLoading ? (
            <p className="mt-3 text-[11px] text-slate-500">
              {hasActiveFilters
                ? `Showing ${formatNumber(filteredCount)} of ${formatNumber(totalRecords)} stock records`
                : `Showing ${formatNumber(totalRecords)} stock records`}
            </p>
          ) : null}
        </div>

        <div className="scrollbar-thin overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead>
              <tr className="border-y border-slate-100 bg-slate-50/70 text-[10px] uppercase tracking-[0.12em] text-slate-400">
                <th className="px-5 py-3 font-semibold">Product</th>
                <th className="px-5 py-3 font-semibold">SKU</th>
                <th className="px-5 py-3 font-semibold">Warehouse</th>
                <th className="px-5 py-3 text-right font-semibold">On hand</th>
                <th className="px-5 py-3 text-right font-semibold">Reserved</th>
                <th className="px-5 py-3 text-right font-semibold">Free stock</th>
                <th className="px-5 py-3 text-right font-semibold">Reorder</th>
                <th className="px-5 py-3 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {isLoading ? (
                <TableMessage>Loading live inventory…</TableMessage>
              ) : rows.length === 0 ? (
                <TableMessage>
                  {error
                    ? 'Inventory data unavailable.'
                    : 'No inventory records found.'}
                </TableMessage>
              ) : filteredRows.length === 0 ? (
                <tr>
                  <td className="px-5 py-10 text-center" colSpan={8}>
                    <p className="text-xs font-medium text-slate-500">
                      No inventory records match your filters.
                    </p>
                    <button
                      type="button"
                      onClick={clearFilters}
                      className="mt-3 inline-flex items-center justify-center rounded-lg bg-accent-50 px-3 py-1.5 text-[11px] font-semibold text-accent-700 transition hover:bg-accent-100"
                    >
                      Clear filters
                    </button>
                  </td>
                </tr>
              ) : (
                paginatedRows.map((row) => {
                  const isLowStock = row.free_stock <= row.reorder_level

                  return (
                    <tr
                      key={`${row.product_id}-${row.warehouse_name}`}
                      className="transition hover:bg-slate-50/70"
                    >
                      <td className="whitespace-nowrap px-5 py-3">
                        <p className="text-xs font-semibold text-slate-800">
                          {row.product_name}
                        </p>
                        <p className="text-[10px] text-slate-400">
                          {row.product_id}
                        </p>
                      </td>
                      <td className="whitespace-nowrap px-5 py-3 font-mono text-[10px] text-slate-500">
                        {row.sku}
                      </td>
                      <td className="whitespace-nowrap px-5 py-3 text-xs text-slate-600">
                        {row.warehouse_name}
                      </td>
                      <td className="whitespace-nowrap px-5 py-3 text-right text-xs text-slate-700">
                        {formatNumber(row.on_hand_qty)}
                      </td>
                      <td className="whitespace-nowrap px-5 py-3 text-right text-xs text-slate-500">
                        {formatNumber(row.reserved_qty)}
                      </td>
                      <td
                        className={`whitespace-nowrap px-5 py-3 text-right text-xs font-semibold ${
                          isLowStock ? 'text-rose-600' : 'text-emerald-600'
                        }`}
                      >
                        {formatNumber(row.free_stock)}
                      </td>
                      <td className="whitespace-nowrap px-5 py-3 text-right text-xs text-slate-500">
                        {formatNumber(row.reorder_level)}
                      </td>
                      <td className="whitespace-nowrap px-5 py-3">
                        <StatusBadge status={isLowStock ? 'Low Stock' : 'Healthy'} />
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>

        {!isLoading && rows.length > 0 && filteredRows.length > 0 ? (
          <div className="flex flex-col gap-3 border-t border-slate-100 px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-[11px] text-slate-500">
              Showing{' '}
              <span className="font-semibold text-slate-700">
                {formatNumber(showingFrom)}–{formatNumber(showingTo)}
              </span>{' '}
              of{' '}
              <span className="font-semibold text-slate-700">
                {formatNumber(filteredCount)}
              </span>{' '}
              {hasActiveFilters ? 'filtered records' : 'records'}
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setPage((current) => Math.max(1, current - 1))}
                disabled={currentPage === 1}
                className="inline-flex h-8 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 text-[11px] font-semibold text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
                Previous
              </button>
              <span className="px-1 text-[11px] font-medium text-slate-500">
                Page {currentPage} of {totalPages}
              </span>
              <button
                type="button"
                onClick={() =>
                  setPage((current) => Math.min(totalPages, current + 1))
                }
                disabled={currentPage === totalPages}
                className="inline-flex h-8 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 text-[11px] font-semibold text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Next
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        ) : null}
      </Card>
    </>
  )
}

function TableMessage({ children }: { children: ReactNode }) {
  return (
    <tr>
      <td className="px-5 py-10 text-center text-xs font-medium text-slate-400" colSpan={8}>
        {children}
      </td>
    </tr>
  )
}
