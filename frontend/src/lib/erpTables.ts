import type { ToolCallResult } from '../services/api'

export type TableCellKind =
  | 'status'
  | 'low-stock'
  | 'barcode'
  | 'issue'
  | 'text'

export interface TableColumn {
  key: string
  label: string
  kind: TableCellKind
}

export interface ErpTableSpec {
  id: string
  title: string
  columns: TableColumn[]
  rows: Array<Record<string, unknown>>
  truncated: boolean
}

export type AnswerSegment =
  | { type: 'text'; text: string }
  | { type: 'table'; spec: ErpTableSpec }

type JsonRecord = Record<string, unknown>

type GroupKey =
  | 'dispatches'
  | 'dispatchItems'
  | 'salesOrders'
  | 'salesOrderItems'
  | 'inventory'
  | 'products'
  | 'warehouses'

const COLUMN_LABELS: Record<string, string> = {
  dispatch_id: 'Dispatch ID',
  so_id: 'Sales Order ID',
  status: 'Status',
  carrier: 'Carrier',
  tracking_number: 'Tracking Number',
  dispatch_date: 'Dispatch Date',
  issues: 'Notes / Issues',
  dispatch_item_id: 'Item ID',
  product_id: 'Product ID',
  product_name: 'Product',
  sku: 'SKU',
  category: 'Category',
  material: 'Material',
  size: 'Size',
  grade: 'Grade',
  unit: 'Unit',
  warehouse_id: 'Warehouse ID',
  warehouse_name: 'Warehouse',
  city: 'City',
  on_hand_qty: 'On Hand',
  reserved_qty: 'Reserved',
  free_stock: 'Free Stock',
  reorder_level: 'Reorder Level',
  low_stock: 'Stock Status',
  picked_qty: 'Picked Qty',
  dispatched_qty: 'Dispatched Qty',
  barcode_verified: 'Barcode Verified',
  customer_id: 'Customer ID',
  customer_name: 'Customer',
  order_date: 'Order Date',
  required_date: 'Required Date',
  ordered_qty: 'Ordered Qty',
}

interface GroupConfig {
  title: string
  order: string[]
  kinds?: Partial<Record<string, TableCellKind>>
  alwaysInclude?: string[]
}

const GROUP_CONFIG: Record<GroupKey, GroupConfig> = {
  dispatches: {
    title: 'Dispatch records',
    order: [
      'dispatch_id',
      'so_id',
      'status',
      'carrier',
      'tracking_number',
      'dispatch_date',
      'issues',
    ],
    alwaysInclude: [
      'dispatch_id',
      'so_id',
      'status',
      'carrier',
      'tracking_number',
      'dispatch_date',
    ],
    kinds: { status: 'status', issues: 'issue' },
  },
  dispatchItems: {
    title: 'Dispatch items',
    order: [
      'dispatch_item_id',
      'product_id',
      'product_name',
      'picked_qty',
      'dispatched_qty',
      'barcode_verified',
    ],
    kinds: { barcode_verified: 'barcode' },
  },
  salesOrders: {
    title: 'Sales orders',
    order: [
      'so_id',
      'customer_name',
      'customer_id',
      'order_date',
      'required_date',
      'status',
    ],
    kinds: { status: 'status' },
  },
  salesOrderItems: {
    title: 'Order items',
    order: ['product_id', 'product_name', 'ordered_qty'],
  },
  inventory: {
    title: 'Inventory',
    order: [
      'product_id',
      'product_name',
      'warehouse_id',
      'warehouse_name',
      'on_hand_qty',
      'reserved_qty',
      'free_stock',
      'reorder_level',
      'low_stock',
    ],
    kinds: { low_stock: 'low-stock' },
  },
  products: {
    title: 'Products',
    order: [
      'product_id',
      'sku',
      'product_name',
      'category',
      'material',
      'size',
      'grade',
      'unit',
    ],
  },
  warehouses: {
    title: 'Warehouses',
    order: ['warehouse_id', 'warehouse_name', 'city'],
  },
}

const GROUP_ORDER: GroupKey[] = [
  'dispatches',
  'dispatchItems',
  'salesOrders',
  'salesOrderItems',
  'inventory',
  'products',
  'warehouses',
]

const GROUP_KEYWORDS: Record<GroupKey, string[]> = {
  dispatches: ['dispatch', 'shipment', 'shipped', 'deliver', 'carrier', 'tracking'],
  dispatchItems: ['dispatch', 'shipment', 'shipped', 'deliver', 'item', 'barcode'],
  salesOrders: ['sales order', 'sales', 'order', 'customer', 'pending'],
  salesOrderItems: ['order', 'item', 'ordered'],
  inventory: ['inventory', 'stock', 'reorder', 'quantity', 'warehouse'],
  products: ['product', 'sku', 'catalogue', 'catalog', 'item'],
  warehouses: ['warehouse', 'location', 'city'],
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function unwrapToolOutput(output: unknown): unknown {
  if (isRecord(output) && output.ok === true && 'data' in output) {
    return output.data
  }

  return output
}

function emptyGroups(): Record<GroupKey, JsonRecord[]> {
  return {
    dispatches: [],
    dispatchItems: [],
    salesOrders: [],
    salesOrderItems: [],
    inventory: [],
    products: [],
    warehouses: [],
  }
}

function classifyRow(row: JsonRecord): GroupKey | null {
  if ('dispatch_item_id' in row) {
    return 'dispatchItems'
  }
  if ('dispatch_id' in row) {
    return 'dispatches'
  }
  if ('ordered_qty' in row) {
    return 'salesOrderItems'
  }
  if ('on_hand_qty' in row) {
    return 'inventory'
  }
  if ('warehouse_id' in row) {
    return 'warehouses'
  }
  if ('sku' in row) {
    return 'products'
  }
  if ('so_id' in row && 'status' in row) {
    return 'salesOrders'
  }
  return null
}

function collectRow(groups: Record<GroupKey, JsonRecord[]>, row: JsonRecord) {
  const key = classifyRow(row)
  if (key) {
    groups[key].push(row)
  }
}

function collectNestedItems(
  groups: Record<GroupKey, JsonRecord[]>,
  value: unknown,
  key: GroupKey,
) {
  if (!Array.isArray(value)) {
    return
  }

  for (const item of value) {
    if (isRecord(item)) {
      groups[key].push(item)
    }
  }
}

function countRows(groups: Record<GroupKey, JsonRecord[]>) {
  return Object.fromEntries(
    GROUP_ORDER.map((key) => [key, groups[key].length]),
  ) as Record<GroupKey, number>
}

function collectData(
  groups: Record<GroupKey, JsonRecord[]>,
  truncated: Record<GroupKey, boolean>,
  data: JsonRecord,
) {
  const before = countRows(groups)
  const isDispatchDetail = 'dispatch_id' in data

  if (isDispatchDetail) {
    groups.dispatches.push(data)
  }

  if (isRecord(data.order)) {
    groups.salesOrders.push(data.order)
  }

  if (Array.isArray(data.items)) {
    for (const item of data.items) {
      if (!isRecord(item)) {
        continue
      }

      // Sales order search results nest the header and its line items.
      if (isRecord(item.order)) {
        groups.salesOrders.push(item.order)
        collectNestedItems(groups, item.items, 'salesOrderItems')
        continue
      }

      collectRow(groups, item)
    }
  }

  if (Array.isArray(data.dispatches)) {
    for (const dispatch of data.dispatches) {
      if (!isRecord(dispatch)) {
        continue
      }
      groups.dispatches.push(dispatch)
      collectNestedItems(groups, dispatch.items, 'dispatchItems')
    }
  }

  if (!isDispatchDetail) {
    collectRow(groups, data)
  }

  const wasTruncated =
    data.truncated === true ||
    data.items_truncated === true ||
    data.dispatches_truncated === true

  if (wasTruncated) {
    const after = countRows(groups)
    for (const key of GROUP_ORDER) {
      if (after[key] > before[key]) {
        truncated[key] = true
      }
    }
  }
}

function dispatchIssue(row: JsonRecord): string {
  const issues: string[] = []
  const status = String(row.status ?? '')

  if (/partial/i.test(status)) {
    issues.push('Partial dispatch — balance pending')
  }
  if (!row.carrier) {
    issues.push('Carrier not recorded')
  }
  if (!row.tracking_number) {
    issues.push('Tracking number not recorded')
  }

  return issues.length > 0 ? issues.join('; ') : '—'
}

function humanize(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (character) => character.toUpperCase())
}

function columnsFor(
  rows: JsonRecord[],
  config: GroupConfig,
): TableColumn[] {
  const present = new Set<string>()
  for (const row of rows) {
    for (const columnKey of Object.keys(row)) {
      present.add(columnKey)
    }
  }

  const alwaysInclude = new Set(config.alwaysInclude ?? [])
  const orderedKeys = config.order.filter(
    (columnKey) => present.has(columnKey) || alwaysInclude.has(columnKey),
  )
  const extraKeys = [...present]
    .filter(
      (columnKey) =>
        !config.order.includes(columnKey) && !columnKey.startsWith('__'),
    )
    .sort()

  return [...orderedKeys, ...extraKeys].map((columnKey) => ({
    key: columnKey,
    label: COLUMN_LABELS[columnKey] ?? humanize(columnKey),
    kind: config.kinds?.[columnKey] ?? 'text',
  }))
}

function dedupeRows(rows: JsonRecord[]): JsonRecord[] {
  const seen = new Set<string>()
  return rows.filter((row) => {
    const signature = JSON.stringify(row)
    if (seen.has(signature)) {
      return false
    }
    seen.add(signature)
    return true
  })
}

function relevanceScore(key: GroupKey, question: string): number {
  const text = question.toLowerCase()
  return GROUP_KEYWORDS[key].reduce(
    (score, keyword) => (text.includes(keyword) ? score + 1 : score),
    0,
  )
}

function titleFor(key: GroupKey, rows: JsonRecord[], fallback: string): string {
  if (key === 'inventory' && rows.some((row) => row.low_stock === true)) {
    return 'Low-stock inventory'
  }
  return fallback
}

export function buildErpTables(
  toolCalls: ToolCallResult[] | undefined,
  question = '',
): ErpTableSpec[] {
  const groups = emptyGroups()
  const truncated = Object.fromEntries(
    GROUP_ORDER.map((key) => [key, false]),
  ) as Record<GroupKey, boolean>

  for (const call of toolCalls ?? []) {
    if (call.status !== 'succeeded' || call.output == null) {
      continue
    }

    const data = unwrapToolOutput(call.output)
    if (isRecord(data)) {
      collectData(groups, truncated, data)
    }
  }

  const specs: ErpTableSpec[] = []

  for (const key of GROUP_ORDER) {
    const rows = dedupeRows(groups[key])
    if (rows.length === 0) {
      continue
    }

    const normalizedRows =
      key === 'dispatches'
        ? rows.map((row) => ({ ...row, issues: dispatchIssue(row) }))
        : rows

    const config = GROUP_CONFIG[key]
    const columns = columnsFor(normalizedRows, config)
    if (columns.length === 0) {
      continue
    }

    specs.push({
      id: key,
      title: titleFor(key, normalizedRows, config.title),
      columns,
      rows: normalizedRows,
      truncated: truncated[key],
    })
  }

  return specs.sort(
    (left, right) =>
      relevanceScore(right.id as GroupKey, question) -
      relevanceScore(left.id as GroupKey, question),
  )
}

function splitTableRow(line: string): string[] {
  let trimmed = line.trim()
  if (trimmed.startsWith('|')) {
    trimmed = trimmed.slice(1)
  }
  if (trimmed.endsWith('|')) {
    trimmed = trimmed.slice(0, -1)
  }
  return trimmed.split('|').map((cell) => cell.trim())
}

function isSeparatorRow(line: string): boolean {
  const cells = splitTableRow(line)
  return (
    cells.length >= 2 && cells.every((cell) => /^:?-{3,}:?$/.test(cell))
  )
}

function kindForHeader(header: string): TableCellKind {
  if (/status/i.test(header)) {
    return 'status'
  }
  if (/(issue|note)/i.test(header)) {
    return 'issue'
  }
  return 'text'
}

/**
 * Split an assistant answer into plain-text and Markdown-table segments.
 * Tables produced by the model are rendered with the same table component as
 * the structured ERP data, so both paths share one visual treatment.
 */
export function parseAnswerContent(content: string): AnswerSegment[] {
  const lines = content.replace(/\r\n?/g, '\n').split('\n')
  const segments: AnswerSegment[] = []
  let textBuffer: string[] = []
  let tableIndex = 0

  function flushText() {
    if (textBuffer.length === 0) {
      return
    }
    const text = textBuffer.join('\n').trim()
    if (text) {
      segments.push({ type: 'text', text })
    }
    textBuffer = []
  }

  let index = 0
  while (index < lines.length) {
    const line = lines[index]
    const nextLine = lines[index + 1]

    if (
      line.includes('|') &&
      nextLine !== undefined &&
      nextLine.includes('|') &&
      isSeparatorRow(nextLine)
    ) {
      const headers = splitTableRow(line)
      const bodyLines: string[] = []
      let cursor = index + 2

      while (
        cursor < lines.length &&
        lines[cursor].includes('|') &&
        lines[cursor].trim() !== ''
      ) {
        bodyLines.push(lines[cursor])
        cursor += 1
      }

      if (headers.length >= 2 && bodyLines.length > 0) {
        flushText()

        const rows = bodyLines.map((bodyLine) => {
          const cells = splitTableRow(bodyLine)
          const row: JsonRecord = {}
          headers.forEach((_header, headerIndex) => {
            row[`c${headerIndex}`] = cells[headerIndex] ?? ''
          })
          return row
        })

        segments.push({
          type: 'table',
          spec: {
            id: `markdown-${tableIndex}`,
            title: '',
            columns: headers.map((header, headerIndex) => ({
              key: `c${headerIndex}`,
              label: header || '—',
              kind: kindForHeader(header),
            })),
            rows,
            truncated: false,
          },
        })

        tableIndex += 1
        index = cursor
        continue
      }
    }

    textBuffer.push(line)
    index += 1
  }

  flushText()
  return segments
}
