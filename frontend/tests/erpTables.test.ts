import { describe, expect, it } from 'vitest'
import {
  buildErpTables,
  parseAnswerContent,
  unwrapToolOutput,
} from '../src/lib/erpTables'
import type { ToolCallResult } from '../src/services/api'

function succeeded(output: unknown): ToolCallResult {
  return {
    tool_name: 'erp.dispatches.list',
    status: 'succeeded',
    arguments: {},
    duration_ms: 12,
    error: null,
    output,
  }
}

function dispatchesOutput(items: Array<Record<string, unknown>>) {
  return {
    ok: true,
    data: { items, row_count: items.length, truncated: false },
  }
}

const dispatchRecords = [
  {
    dispatch_id: 'DSP001',
    so_id: 'SO001',
    dispatch_date: '2026-02-10',
    status: 'Dispatched',
    carrier: 'BlueDart',
    tracking_number: 'BD123456',
  },
  {
    dispatch_id: 'DSP002',
    so_id: 'SO002',
    dispatch_date: null,
    status: 'Partially Dispatched',
    carrier: null,
    tracking_number: null,
  },
]

describe('unwrapToolOutput', () => {
  it('unwraps the backend success envelope', () => {
    expect(unwrapToolOutput({ ok: true, data: { items: [] } })).toEqual({
      items: [],
    })
  })

  it('keeps plain payloads as-is', () => {
    expect(unwrapToolOutput({ items: [] })).toEqual({ items: [] })
    expect(unwrapToolOutput(null)).toBeNull()
  })
})

describe('buildErpTables', () => {
  it('builds a dispatch table with the required columns and missing values', () => {
    const specs = buildErpTables(
      [succeeded(dispatchesOutput(dispatchRecords))],
      'Which dispatches are pending?',
    )

    expect(specs).toHaveLength(1)
    const spec = specs[0]
    expect(spec.id).toBe('dispatches')
    expect(spec.columns.map((column) => column.label)).toEqual([
      'Dispatch ID',
      'Sales Order ID',
      'Status',
      'Carrier',
      'Tracking Number',
      'Dispatch Date',
      'Notes / Issues',
    ])
    expect(spec.rows).toHaveLength(2)
    expect(spec.rows[0].dispatch_id).toBe('DSP001')
    expect(spec.rows[1].carrier).toBeNull()
    expect(spec.rows[1].issues).toContain('Partial dispatch')
    expect(spec.rows[1].issues).toContain('Tracking number not recorded')
    expect(spec.rows[0].issues).toBe('—')
  })

  it('orders the most relevant table first based on the question', () => {
    const products = succeeded({
      ok: true,
      data: {
        items: [
          {
            product_id: 'PRD001',
            sku: 'HB-M10',
            product_name: 'Hex Bolt M10',
            category: 'Fastener',
            material: 'Steel',
            size: 'M10',
            grade: '8.8',
            unit: 'Nos',
          },
        ],
        row_count: 1,
        truncated: false,
      },
    })

    const specs = buildErpTables(
      [products, succeeded(dispatchesOutput(dispatchRecords))],
      'Show dispatch records and their carriers',
    )

    expect(specs.map((spec) => spec.id)).toEqual(['dispatches', 'products'])
  })

  it('ignores failed calls and calls without output', () => {
    expect(
      buildErpTables(
        [
          {
            tool_name: 'erp.dispatches.list',
            status: 'failed',
            error: 'ERP query failed',
          },
          { tool_name: 'erp.products.search', status: 'succeeded' },
        ],
        'Show dispatches',
      ),
    ).toEqual([])
  })

  it('derives inventory columns and flags low stock', () => {
    const specs = buildErpTables(
      [
        succeeded({
          ok: true,
          data: {
            items: [
              {
                product_id: 'PRD001',
                product_name: 'Hex Bolt M10',
                warehouse_id: 'WH001',
                warehouse_name: 'Main Warehouse',
                on_hand_qty: 12,
                reserved_qty: 10,
                free_stock: 2,
                reorder_level: 5,
                low_stock: true,
              },
            ],
            row_count: 1,
            truncated: false,
          },
        }),
      ],
      'Which products are below their reorder level?',
    )

    expect(specs).toHaveLength(1)
    expect(specs[0].title).toBe('Low-stock inventory')
    const statusColumn = specs[0].columns.find(
      (column) => column.key === 'low_stock',
    )
    expect(statusColumn?.kind).toBe('low-stock')
  })

  it('extracts sales order headers and line items from nested results', () => {
    const specs = buildErpTables(
      [
        succeeded({
          ok: true,
          data: {
            items: [
              {
                order: {
                  so_id: 'SO001',
                  customer_id: 'CUST001',
                  customer_name: 'Sri Venkateswara Engineering',
                  order_date: '2026-02-01',
                  required_date: '2026-02-15',
                  status: 'Pending',
                },
                items: [
                  {
                    product_id: 'PRD001',
                    product_name: 'Hex Bolt M10',
                    ordered_qty: 100,
                  },
                ],
                items_row_count: 1,
                items_truncated: false,
              },
            ],
            row_count: 1,
            truncated: false,
          },
        }),
      ],
      'Show pending sales orders',
    )

    expect(specs.map((spec) => spec.id)).toEqual([
      'salesOrders',
      'salesOrderItems',
    ])
    expect(specs[0].rows[0].customer_name).toBe(
      'Sri Venkateswara Engineering',
    )
    expect(specs[1].rows[0].ordered_qty).toBe(100)
  })
})

describe('parseAnswerContent', () => {
  it('renders markdown tables as table segments', () => {
    const segments = parseAnswerContent(
      [
        'Here are the dispatch records:',
        '',
        '| Dispatch ID | Status | Carrier |',
        '| --- | --- | --- |',
        '| DSP001 | Dispatched | BlueDart |',
        '| DSP002 | Partially Dispatched | — |',
      ].join('\n'),
    )

    expect(segments).toHaveLength(2)
    expect(segments[0]).toEqual({
      type: 'text',
      text: 'Here are the dispatch records:',
    })

    const table = segments[1]
    expect(table.type).toBe('table')
    if (table.type !== 'table') {
      return
    }

    expect(table.spec.columns.map((column) => column.label)).toEqual([
      'Dispatch ID',
      'Status',
      'Carrier',
    ])
    expect(table.spec.columns[1].kind).toBe('status')
    expect(table.spec.rows).toHaveLength(2)
    expect(table.spec.rows[1].c0).toBe('DSP002')
  })

  it('leaves plain text untouched', () => {
    expect(parseAnswerContent('No records were found.')).toEqual([
      { type: 'text', text: 'No records were found.' },
    ])
  })
})
