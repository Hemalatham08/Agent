import {
  Boxes,
  CircleAlert,
  IndianRupee,
  Package,
  RefreshCw,
  Search,
  Tags,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { KpiCard } from '../components/dashboard/KpiCard'
import { Card, CardHeader } from '../components/ui/Card'
import { PageHeader } from '../components/ui/PageHeader'
import { formatCurrency, formatNumber } from '../lib/format'
import { erpApi } from '../services/api'
import type { Product } from '../types'

export default function Products() {
  const [products, setProducts] = useState<Product[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('All')

  const reload = useCallback(() => {
    setReloadKey((key) => key + 1)
  }, [])

  useEffect(() => {
    let cancelled = false

    async function load() {
      setIsLoading(true)
      setError(null)
      setProducts([])

      try {
        const liveProducts = await erpApi.getProducts()

        if (cancelled) {
          return
        }

        setProducts(liveProducts)
      } catch (requestError) {
        if (cancelled) {
          return
        }

        setError(
          requestError instanceof Error
            ? requestError.message
            : 'Could not load the live product catalogue.',
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

  const categories = useMemo(
    () => ['All', ...Array.from(new Set(products.map((product) => product.category))).sort()],
    [products],
  )
  const uniqueCategories = useMemo(
    () => new Set(products.map((product) => product.category)),
    [products],
  )
  const uniqueMaterials = useMemo(
    () => new Set(products.map((product) => product.material)),
    [products],
  )
  const averageSellingPrice =
    products.length > 0
      ? products.reduce((total, product) => total + product.selling_price, 0) /
        products.length
      : 0

  const filteredProducts = useMemo(() => {
    const query = search.trim().toLowerCase()

    return products.filter((product) => {
      const matchesCategory = category === 'All' || product.category === category
      const matchesSearch =
        query.length === 0 ||
        [
          product.product_name,
          product.sku,
          product.material,
          product.size,
          product.grade,
        ].some((value) => value.toLowerCase().includes(query))

      return matchesCategory && matchesSearch
    })
  }, [category, products, search])

  const hasData = products.length > 0
  const metricValue = (value: number) =>
    error !== null && !hasData ? '—' : formatNumber(value)
  const priceValue =
    error !== null && !hasData
      ? '—'
      : hasData
        ? formatCurrency(averageSellingPrice)
        : '—'

  return (
    <>
      <PageHeader
        title="Products"
        description="Live product master data from the ERP API, including catalogue specifications, pricing, and reorder levels."
        actions={
          <>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search products..."
                className="h-9 w-full rounded-xl border border-slate-200 bg-white pl-9 pr-3 text-xs text-slate-700 outline-none transition placeholder:text-slate-400 focus:border-accent-300 focus:ring-4 focus:ring-accent-50 sm:w-56"
                aria-label="Search products"
              />
            </div>
            <select
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              className="h-9 rounded-xl border border-slate-200 bg-white px-3 text-xs font-medium text-slate-600 outline-none transition focus:border-accent-300 focus:ring-4 focus:ring-accent-50"
              aria-label="Filter by category"
            >
              {categories.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </>
        }
      />

      {error ? (
        <div className="mb-5 flex flex-col gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 sm:flex-row sm:items-start">
          <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-rose-500" />
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold text-rose-700">
              Product catalogue could not be loaded
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
          value={metricValue(products.length)}
          helper="Live catalogue records"
          icon={Package}
          tone="blue"
          loading={isLoading}
        />
        <KpiCard
          label="Categories"
          value={metricValue(uniqueCategories.size)}
          helper="Distinct product categories"
          icon={Tags}
          tone="violet"
          loading={isLoading}
        />
        <KpiCard
          label="Materials"
          value={metricValue(uniqueMaterials.size)}
          helper="Distinct material types"
          icon={Boxes}
          tone="emerald"
          loading={isLoading}
        />
        <KpiCard
          label="Avg. Selling Price"
          value={priceValue}
          helper="Across the live catalogue"
          icon={IndianRupee}
          tone="amber"
          loading={isLoading}
        />
      </section>

      <Card className="mt-5 overflow-hidden">
        <CardHeader
          title="Product catalogue"
          description="Live specifications, pricing, and reorder levels · source: GET /products"
          icon={Package}
          action={
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-semibold text-slate-500">
              {isLoading
                ? 'Loading…'
                : `${filteredProducts.length} of ${products.length} products`}
            </span>
          }
        />
        <div className="scrollbar-thin overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead>
              <tr className="border-y border-slate-100 bg-slate-50/70 text-[10px] uppercase tracking-[0.12em] text-slate-400">
                <th className="px-5 py-3 font-semibold">Product</th>
                <th className="px-5 py-3 font-semibold">SKU</th>
                <th className="px-5 py-3 font-semibold">Category</th>
                <th className="px-5 py-3 font-semibold">Material</th>
                <th className="px-5 py-3 font-semibold">Size / Grade</th>
                <th className="px-5 py-3 text-right font-semibold">Purchase</th>
                <th className="px-5 py-3 text-right font-semibold">Selling</th>
                <th className="px-5 py-3 text-right font-semibold">Reorder</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {isLoading ? (
                <TableMessage>Loading live products…</TableMessage>
              ) : products.length === 0 ? (
                <TableMessage>
                  {error
                    ? 'Product catalogue unavailable.'
                    : 'No products found.'}
                </TableMessage>
              ) : filteredProducts.length === 0 ? (
                <TableMessage>
                  No products match your search or category filter.
                </TableMessage>
              ) : (
                filteredProducts.map((product) => (
                  <tr
                    key={product.product_id}
                    className="transition hover:bg-slate-50/70"
                  >
                    <td className="whitespace-nowrap px-5 py-3">
                      <p className="text-xs font-semibold text-slate-800">
                        {product.product_name}
                      </p>
                      <p className="text-[10px] text-slate-400">{product.product_id}</p>
                    </td>
                    <td className="whitespace-nowrap px-5 py-3 font-mono text-[10px] text-slate-500">
                      {product.sku}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3">
                      <span className="rounded-full bg-accent-50 px-2.5 py-1 text-[10px] font-semibold text-accent-700">
                        {product.category}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-5 py-3 text-xs text-slate-600">
                      {product.material}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3 text-xs text-slate-500">
                      {product.size} · {product.grade}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3 text-right text-xs text-slate-600">
                      {formatCurrency(product.purchase_price)}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3 text-right text-xs font-semibold text-slate-800">
                      {formatCurrency(product.selling_price)}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3 text-right text-xs text-slate-500">
                      {formatNumber(product.reorder_level)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  )
}

function TableMessage({ children }: { children: string }) {
  return (
    <tr>
      <td className="px-5 py-10 text-center text-xs font-medium text-slate-400" colSpan={8}>
        {children}
      </td>
    </tr>
  )
}
