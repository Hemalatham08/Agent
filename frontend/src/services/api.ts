import type {
  DispatchIssue,
  InventoryStatus,
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

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatRequest {
  question: string
  history: ChatMessage[]
}

export interface ToolCallResult {
  tool_name: string
  status: string
  arguments?: Record<string, unknown>
  duration_ms?: number | null
  error?: string | null
  output?: unknown
}

export interface ChatResponse {
  answer: string
  model: string
  tool_calls?: ToolCallResult[]
  status?: string
  error?: string | null
}

export interface AiModelInfo {
  provider: string
  model: string
  base_url: string
  available: boolean
  active: boolean
  reason: string | null
}

export interface AiModelsResponse {
  providers: AiModelInfo[]
  active: AiModelInfo
}

export interface SwitchAiModelResponse extends AiModelInfo {
  previous_provider: string | null
}

export const AI_PROVIDER_LABELS: Record<string, string> = {
  ollama: 'Ollama — Llama 3.2',
  llamacpp: 'Qwen3 1.7B',
}

export function aiModelLabel(info: Pick<AiModelInfo, 'provider' | 'model'>): string {
  return AI_PROVIDER_LABELS[info.provider] ?? `${info.model} (${info.provider})`
}

const AI_SWITCH_TOKEN = (import.meta.env.VITE_AI_SWITCH_TOKEN ?? '').trim()

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
  chat: (payload: ChatRequest) =>
    request<ChatResponse>('/chat', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getAiModels: () => request<AiModelsResponse>('/ai/models'),
  getActiveAiModel: () => request<AiModelInfo>('/ai/models/active'),
  switchAiModel: (provider: string) =>
    request<SwitchAiModelResponse>('/ai/models/switch', {
      method: 'POST',
      headers: AI_SWITCH_TOKEN
        ? { Authorization: `Bearer ${AI_SWITCH_TOKEN}` }
        : undefined,
      body: JSON.stringify({ provider }),
    }),
  getProducts: () => request<Product[]>('/products'),
  getProduct: (productId: string) =>
    request<Product>(`/products/${encodeURIComponent(productId)}`),
  getInventory: (productId: string) =>
    request<InventoryStatus[]>(`/inventory/${encodeURIComponent(productId)}`),
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
