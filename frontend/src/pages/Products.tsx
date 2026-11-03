import { IndianRupee, Package, Search, Tags, Warehouse } from 'lucide-react'
import { useMemo, useState } from 'react'
import { KpiCard } from '../components/dashboard/KpiCard'
import { Card, CardHeader } from '../components/ui/Card'
import { PageHeader } from '../components/ui/PageHeader'
import {
  averageSellingPrice,
  products,
  totalWarehouses,
  uniqueCategories,
} from '../data/demo'
import { formatCurrency, formatNumber } from '../lib/format'

const categories = ['All', ...Array.from(uniqueCategories)]

export default function Products() {
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('All')

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
  }, [category, search])

  return (
    <>
      <PageHeader
        title="Products"
        description="Master catalogue of fasteners and industrial supplies with pricing and reorder rules."
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

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Total Products"
          value={formatNumber(products.length)}
          helper="Active catalogue records"
          icon={Package}
          tone="blue"
        />
        <KpiCard
          label="Categories"
          value={formatNumber(uniqueCategories.size)}
          helper="Bolts, nuts, screws, washers"
          icon={Tags}
          tone="violet"
        />
        <KpiCard
          label="Warehouses"
          value={formatNumber(totalWarehouses)}
          helper="Stocking locations"
          icon={Warehouse}
          tone="emerald"
        />
        <KpiCard
          label="Avg. Selling Price"
          value={formatCurrency(averageSellingPrice)}
          helper="Across the product catalogue"
          icon={IndianRupee}
          tone="amber"
        />
      </section>

      <Card className="mt-5 overflow-hidden">
        <CardHeader
          title="Product catalogue"
          description="Pricing, material specifications, and reorder levels"
          icon={Package}
          action={
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-semibold text-slate-500">
              {filteredProducts.length} of {products.length} products
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
              {filteredProducts.map((product) => (
                <tr key={product.product_id} className="transition hover:bg-slate-50/70">
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
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  )
}
