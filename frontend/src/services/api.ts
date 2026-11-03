import type {
  DispatchIssue,
  Invoice,
  LowStockItem,
  Product,
  PurchaseOrder,
  QualityIssue,
  SalesOrder,
} from '../types'

export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'
).replace(/\/$/, '')

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`

    try {
      const body = (await response.json()) as { detail?: string }
      if (body.detail) {
        message = body.detail
      }
    } catch {
      // The backend may return an empty or non-JSON error body.
    }

    throw new Error(message)
  }

  return (await response.json()) as T
}

export const erpApi = {
  getProducts: () => request<Product[]>('/products'),
  getProduct: (productId: string) =>
    request<Product>(`/products/${encodeURIComponent(productId)}`),
  getInventory: (productId: string) =>
    request<LowStockItem[]>(`/inventory/${encodeURIComponent(productId)}`),
  getLowStock: () => request<LowStockItem[]>('/inventory/alerts/low-stock'),
  getPendingSalesOrders: () => request<SalesOrder[]>('/sales/pending'),
  getPendingPurchaseOrders: () => request<PurchaseOrder[]>('/purchase/pending'),
  getDispatchIssues: () => request<DispatchIssue[]>('/dispatch/issues'),
  getQualityIssues: () => request<QualityIssue[]>('/quality/issues'),
  getUnpaidInvoices: () => request<Invoice[]>('/accounting/unpaid'),
  getInvoiceOutstanding: (invoiceId: string) =>
    request<Invoice>(`/accounting/invoices/${encodeURIComponent(invoiceId)}`),
}

export type ErpApi = typeof erpApi
