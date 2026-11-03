export interface Product {
  product_id: string
  sku: string
  product_name: string
  category: string
  material: string
  size: string
  grade: string
  unit: string
  purchase_price: number
  selling_price: number
  reorder_level: number
}

export interface Warehouse {
  warehouse_id: string
  warehouse_name: string
  city: string
}

export interface InventoryRecord {
  inventory_id: string
  product_id: string
  warehouse_id: string
  on_hand_qty: number
  reserved_qty: number
}

export interface LowStockItem {
  product_id: string
  product_name: string
  warehouse_name: string
  free_stock: number
  reorder_level: number
}

export interface SalesOrder {
  so_id: string
  customer_id: string
  customer_name: string
  order_date: string
  required_date: string
  status: string
  amount?: number
}

export interface PurchaseOrder {
  po_id: string
  supplier_id: string
  supplier_name: string
  order_date: string
  expected_date: string
  status: string
  amount?: number
}

export interface DispatchIssue {
  dispatch_id: string
  so_id: string
  product_name: string
  picked_qty: number
  dispatched_qty: number
  barcode_verified: number
}

export interface DispatchRecord {
  dispatch_id: string
  so_id: string
  dispatch_date: string
  carrier: string
  tracking_number: string
  status: string
}

export interface QualityIssue {
  inspection_id: string
  receipt_id: string
  product_name: string
  inspected_qty: number
  accepted_qty: number
  rejected_qty: number
  rejection_reason: string
}

export interface Invoice {
  invoice_id: string
  invoice_type: 'Sales' | 'Purchase'
  invoice_date: string
  total_amount: number
  status: string
  paid_amount: number
  outstanding_amount: number
}

export interface InventoryChartPoint {
  name: string
  free: number
  reserved: number
}

export interface SalesChartPoint {
  label: string
  sales: number
}

export type AlertSeverity = 'critical' | 'warning' | 'info'

export interface DashboardAlert {
  id: string
  title: string
  detail: string
  severity: AlertSeverity
  category: string
  href: string
}

export interface InventoryRow extends InventoryRecord {
  product_name: string
  sku: string
  warehouse_name: string
  free_stock: number
  reorder_level: number
}
