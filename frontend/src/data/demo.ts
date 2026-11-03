import { formatShortDate } from '../lib/format'
import type {
  DashboardAlert,
  DispatchIssue,
  DispatchRecord,
  InventoryChartPoint,
  InventoryRecord,
  InventoryRow,
  Invoice,
  LowStockItem,
  Product,
  PurchaseOrder,
  QualityIssue,
  SalesChartPoint,
  SalesOrder,
  Warehouse,
} from '../types'

export const warehouses: Warehouse[] = [
  { warehouse_id: 'WH001', warehouse_name: 'Main Warehouse', city: 'Chennai' },
  {
    warehouse_id: 'WH002',
    warehouse_name: 'Secondary Warehouse',
    city: 'Coimbatore',
  },
]

export const products: Product[] = [
  {
    product_id: 'PRD001',
    sku: 'HEX-M10-SS304',
    product_name: 'Hex Bolt M10',
    category: 'Bolts',
    material: 'Stainless Steel',
    size: 'M10',
    grade: 'SS304',
    unit: 'pieces',
    purchase_price: 8,
    selling_price: 12,
    reorder_level: 500,
  },
  {
    product_id: 'PRD002',
    sku: 'NUT-M10-SS304',
    product_name: 'Hex Nut M10',
    category: 'Nuts',
    material: 'Stainless Steel',
    size: 'M10',
    grade: 'SS304',
    unit: 'pieces',
    purchase_price: 4,
    selling_price: 7,
    reorder_level: 400,
  },
  {
    product_id: 'PRD003',
    sku: 'SCR-M6-CS88',
    product_name: 'Machine Screw M6',
    category: 'Screws',
    material: 'Carbon Steel',
    size: 'M6',
    grade: 'Grade 8.8',
    unit: 'pieces',
    purchase_price: 3,
    selling_price: 5,
    reorder_level: 600,
  },
  {
    product_id: 'PRD004',
    sku: 'WSH-M10-SS304',
    product_name: 'Flat Washer M10',
    category: 'Washers',
    material: 'Stainless Steel',
    size: 'M10',
    grade: 'SS304',
    unit: 'pieces',
    purchase_price: 2,
    selling_price: 4,
    reorder_level: 300,
  },
  {
    product_id: 'PRD005',
    sku: 'ANC-M12-CS88',
    product_name: 'Anchor Bolt M12',
    category: 'Bolts',
    material: 'Carbon Steel',
    size: 'M12',
    grade: 'Grade 8.8',
    unit: 'pieces',
    purchase_price: 15,
    selling_price: 22,
    reorder_level: 200,
  },
  {
    product_id: 'PRD006',
    sku: 'HEX-M12-SS316',
    product_name: 'Hex Bolt M12',
    category: 'Bolts',
    material: 'Stainless Steel',
    size: 'M12',
    grade: 'SS316',
    unit: 'pieces',
    purchase_price: 12,
    selling_price: 18,
    reorder_level: 250,
  },
]

export const inventory: InventoryRecord[] = [
  { inventory_id: 'INV001', product_id: 'PRD001', warehouse_id: 'WH001', on_hand_qty: 420, reserved_qty: 70 },
  { inventory_id: 'INV002', product_id: 'PRD002', warehouse_id: 'WH001', on_hand_qty: 900, reserved_qty: 100 },
  { inventory_id: 'INV003', product_id: 'PRD003', warehouse_id: 'WH001', on_hand_qty: 500, reserved_qty: 80 },
  { inventory_id: 'INV004', product_id: 'PRD004', warehouse_id: 'WH002', on_hand_qty: 650, reserved_qty: 50 },
  { inventory_id: 'INV005', product_id: 'PRD005', warehouse_id: 'WH002', on_hand_qty: 150, reserved_qty: 20 },
  { inventory_id: 'INV006', product_id: 'PRD006', warehouse_id: 'WH001', on_hand_qty: 310, reserved_qty: 40 },
  { inventory_id: 'INV007', product_id: 'PRD001', warehouse_id: 'WH002', on_hand_qty: 180, reserved_qty: 20 },
  { inventory_id: 'INV008', product_id: 'PRD002', warehouse_id: 'WH002', on_hand_qty: 350, reserved_qty: 25 },
  { inventory_id: 'INV009', product_id: 'PRD003', warehouse_id: 'WH002', on_hand_qty: 720, reserved_qty: 100 },
  { inventory_id: 'INV010', product_id: 'PRD004', warehouse_id: 'WH001', on_hand_qty: 400, reserved_qty: 30 },
  { inventory_id: 'INV011', product_id: 'PRD005', warehouse_id: 'WH001', on_hand_qty: 260, reserved_qty: 10 },
  { inventory_id: 'INV012', product_id: 'PRD006', warehouse_id: 'WH002', on_hand_qty: 120, reserved_qty: 10 },
]

export const lowStockItems: LowStockItem[] = [
  {
    product_id: 'PRD001',
    product_name: 'Hex Bolt M10',
    warehouse_name: 'Main Warehouse',
    free_stock: 350,
    reorder_level: 500,
  },
  {
    product_id: 'PRD001',
    product_name: 'Hex Bolt M10',
    warehouse_name: 'Secondary Warehouse',
    free_stock: 160,
    reorder_level: 500,
  },
  {
    product_id: 'PRD002',
    product_name: 'Hex Nut M10',
    warehouse_name: 'Secondary Warehouse',
    free_stock: 325,
    reorder_level: 400,
  },
  {
    product_id: 'PRD003',
    product_name: 'Machine Screw M6',
    warehouse_name: 'Main Warehouse',
    free_stock: 420,
    reorder_level: 600,
  },
  {
    product_id: 'PRD005',
    product_name: 'Anchor Bolt M12',
    warehouse_name: 'Secondary Warehouse',
    free_stock: 130,
    reorder_level: 200,
  },
  {
    product_id: 'PRD006',
    product_name: 'Hex Bolt M12',
    warehouse_name: 'Secondary Warehouse',
    free_stock: 110,
    reorder_level: 250,
  },
]

export const salesOrders: SalesOrder[] = [
  {
    so_id: 'SO001',
    customer_id: 'CUS001',
    customer_name: 'Sri Venkateswara Engineering',
    order_date: '2026-10-02',
    required_date: '2026-10-05',
    status: 'Partially Dispatched',
    amount: 1900,
  },
  {
    so_id: 'SO002',
    customer_id: 'CUS002',
    customer_name: 'Metro Machinery Works',
    order_date: '2026-10-04',
    required_date: '2026-10-07',
    status: 'Dispatched',
    amount: 1600,
  },
  {
    so_id: 'SO003',
    customer_id: 'CUS003',
    customer_name: 'Kaveri Industrial Stores',
    order_date: '2026-10-10',
    required_date: '2026-10-15',
    status: 'Pending',
    amount: 2840,
  },
  {
    so_id: 'SO004',
    customer_id: 'CUS004',
    customer_name: 'Southern Auto Components',
    order_date: '2026-10-12',
    required_date: '2026-10-16',
    status: 'Dispatched',
    amount: 1840,
  },
  {
    so_id: 'SO005',
    customer_id: 'CUS005',
    customer_name: 'Precision Tools & Traders',
    order_date: '2026-10-18',
    required_date: '2026-10-22',
    status: 'Pending',
    amount: 3250,
  },
  {
    so_id: 'SO006',
    customer_id: 'CUS001',
    customer_name: 'Sri Venkateswara Engineering',
    order_date: '2026-10-21',
    required_date: '2026-10-27',
    status: 'Processing',
    amount: 2720,
  },
]

export const purchaseOrders: PurchaseOrder[] = [
  {
    po_id: 'PO001',
    supplier_id: 'SUP001',
    supplier_name: 'Apex Fastener Manufacturing',
    order_date: '2026-10-01',
    expected_date: '2026-10-08',
    status: 'Partially Received',
    amount: 5600,
  },
  {
    po_id: 'PO002',
    supplier_id: 'SUP002',
    supplier_name: 'Prime Metal Components',
    order_date: '2026-10-05',
    expected_date: '2026-10-12',
    status: 'Received',
    amount: 2800,
  },
  {
    po_id: 'PO003',
    supplier_id: 'SUP003',
    supplier_name: 'Eastern Industrial Supplies',
    order_date: '2026-10-15',
    expected_date: '2026-10-25',
    status: 'Pending',
    amount: 7500,
  },
  {
    po_id: 'PO004',
    supplier_id: 'SUP004',
    supplier_name: 'Reliable Bolt & Nut Co.',
    order_date: '2026-10-20',
    expected_date: '2026-10-29',
    status: 'Delayed',
    amount: 6200,
  },
]

export const dispatches: DispatchRecord[] = [
  {
    dispatch_id: 'DSP001',
    so_id: 'SO001',
    dispatch_date: '2026-10-04',
    carrier: 'BlueDart',
    tracking_number: 'BD10001',
    status: 'Partially Dispatched',
  },
  {
    dispatch_id: 'DSP002',
    so_id: 'SO002',
    dispatch_date: '2026-10-06',
    carrier: 'DTDC',
    tracking_number: 'DT20002',
    status: 'Dispatched',
  },
  {
    dispatch_id: 'DSP003',
    so_id: 'SO004',
    dispatch_date: '2026-10-15',
    carrier: 'BlueDart',
    tracking_number: 'BD10004',
    status: 'Dispatched',
  },
]

export const dispatchIssues: DispatchIssue[] = [
  {
    dispatch_id: 'DSP001',
    so_id: 'SO001',
    product_name: 'Hex Nut M10',
    picked_qty: 100,
    dispatched_qty: 80,
    barcode_verified: 1,
  },
  {
    dispatch_id: 'DSP003',
    so_id: 'SO004',
    product_name: 'Flat Washer M10',
    picked_qty: 100,
    dispatched_qty: 100,
    barcode_verified: 0,
  },
]

export const qualityInspections: QualityIssue[] = [
  {
    inspection_id: 'QI001',
    receipt_id: 'GR001',
    product_name: 'Hex Bolt M10',
    inspected_qty: 300,
    accepted_qty: 294,
    rejected_qty: 6,
    rejection_reason: 'Minor thread damage',
  },
  {
    inspection_id: 'QI002',
    receipt_id: 'GR001',
    product_name: 'Hex Nut M10',
    inspected_qty: 400,
    accepted_qty: 400,
    rejected_qty: 0,
    rejection_reason: '—',
  },
  {
    inspection_id: 'QI003',
    receipt_id: 'GR002',
    product_name: 'Machine Screw M6',
    inspected_qty: 600,
    accepted_qty: 590,
    rejected_qty: 10,
    rejection_reason: 'Surface defects',
  },
  {
    inspection_id: 'QI004',
    receipt_id: 'GR002',
    product_name: 'Flat Washer M10',
    inspected_qty: 500,
    accepted_qty: 498,
    rejected_qty: 2,
    rejection_reason: 'Packaging damage',
  },
]

export const qualityIssues: QualityIssue[] = qualityInspections.filter(
  (inspection) => inspection.rejected_qty > 0,
)

export const invoices: Invoice[] = [
  {
    invoice_id: 'INV-S001',
    invoice_type: 'Sales',
    invoice_date: '2026-10-04',
    total_amount: 1760,
    status: 'Partially Paid',
    paid_amount: 1000,
    outstanding_amount: 760,
  },
  {
    invoice_id: 'INV-S002',
    invoice_type: 'Sales',
    invoice_date: '2026-10-06',
    total_amount: 1600,
    status: 'Paid',
    paid_amount: 1600,
    outstanding_amount: 0,
  },
  {
    invoice_id: 'INV-S004',
    invoice_type: 'Sales',
    invoice_date: '2026-10-15',
    total_amount: 1840,
    status: 'Unpaid',
    paid_amount: 0,
    outstanding_amount: 1840,
  },
  {
    invoice_id: 'INV-P001',
    invoice_type: 'Purchase',
    invoice_date: '2026-10-06',
    total_amount: 4000,
    status: 'Partially Paid',
    paid_amount: 2000,
    outstanding_amount: 2000,
  },
  {
    invoice_id: 'INV-P002',
    invoice_type: 'Purchase',
    invoice_date: '2026-10-11',
    total_amount: 2800,
    status: 'Paid',
    paid_amount: 2800,
    outstanding_amount: 0,
  },
]

export const dashboardAlerts: DashboardAlert[] = [
  {
    id: 'alert-dispatch-qty',
    title: 'Dispatch quantity mismatch',
    detail: 'DSP001 picked 100 units of Hex Nut M10 but dispatched 80.',
    severity: 'critical',
    category: 'Dispatch',
    href: '/dispatch',
  },
  {
    id: 'alert-barcode',
    title: 'Barcode verification missing',
    detail: 'DSP003 Flat Washer M10 was dispatched without barcode verification.',
    severity: 'critical',
    category: 'Dispatch',
    href: '/dispatch',
  },
  {
    id: 'alert-low-stock',
    title: '6 low-stock alerts',
    detail: 'Six SKU/warehouse combinations are at or below reorder level.',
    severity: 'warning',
    category: 'Inventory',
    href: '/inventory',
  },
  {
    id: 'alert-purchase-delay',
    title: 'PO004 is delayed',
    detail: 'Reliable Bolt & Nut Co. delivery was expected on 29 Oct 2026.',
    severity: 'warning',
    category: 'Purchase',
    href: '/purchase',
  },
  {
    id: 'alert-quality',
    title: '18 units rejected',
    detail: 'Three inspections recorded thread, surface, and packaging defects.',
    severity: 'warning',
    category: 'Quality',
    href: '/quality',
  },
  {
    id: 'alert-accounting',
    title: '₹4,600 outstanding',
    detail: 'Three invoices remain partially paid or unpaid.',
    severity: 'critical',
    category: 'Accounting',
    href: '/accounting',
  },
]

const productById = new Map(products.map((product) => [product.product_id, product]))
const warehouseById = new Map(
  warehouses.map((warehouse) => [warehouse.warehouse_id, warehouse]),
)

export const inventoryRows: InventoryRow[] = inventory.map((record) => {
  const product = productById.get(record.product_id)
  const warehouse = warehouseById.get(record.warehouse_id)

  return {
    ...record,
    product_name: product?.product_name ?? record.product_id,
    sku: product?.sku ?? '—',
    warehouse_name: warehouse?.warehouse_name ?? record.warehouse_id,
    free_stock: record.on_hand_qty - record.reserved_qty,
    reorder_level: product?.reorder_level ?? 0,
  }
})

export const inventoryOverview: InventoryChartPoint[] = products.map((product) => {
  const records = inventory.filter((record) => record.product_id === product.product_id)

  return {
    name: product.product_name,
    free: records.reduce(
      (total, record) => total + record.on_hand_qty - record.reserved_qty,
      0,
    ),
    reserved: records.reduce((total, record) => total + record.reserved_qty, 0),
  }
})

export const salesOverview: SalesChartPoint[] = salesOrders.map((order) => ({
  label: formatShortDate(order.order_date),
  sales: order.amount ?? 0,
}))

export const totalProducts = products.length
export const totalWarehouses = warehouses.length
export const totalInventoryValue = inventory.reduce((total, record) => {
  const product = productById.get(record.product_id)
  return total + record.on_hand_qty * (product?.purchase_price ?? 0)
}, 0)

export const onHandUnits = inventory.reduce(
  (total, record) => total + record.on_hand_qty,
  0,
)
export const reservedUnits = inventory.reduce(
  (total, record) => total + record.reserved_qty,
  0,
)
export const freeUnits = onHandUnits - reservedUnits

export const pendingSalesOrders = salesOrders.filter(
  (order) => order.status !== 'Dispatched',
)
export const pendingPurchaseOrders = purchaseOrders.filter(
  (order) => order.status !== 'Received',
)
export const delayedPurchaseOrders = purchaseOrders.filter(
  (order) => order.status === 'Delayed',
)
export const dispatchedSalesOrders = salesOrders.filter(
  (order) => order.status === 'Dispatched',
)
export const openSalesValue = pendingSalesOrders.reduce(
  (total, order) => total + (order.amount ?? 0),
  0,
)

export const lowStockAlerts = lowStockItems.length
export const dispatchIssuesCount = dispatchIssues.length
export const qualityIssuesCount = qualityIssues.length

export const rejectedUnits = qualityInspections.reduce(
  (total, inspection) => total + inspection.rejected_qty,
  0,
)
export const inspectedUnits = qualityInspections.reduce(
  (total, inspection) => total + inspection.inspected_qty,
  0,
)
export const acceptedUnits = qualityInspections.reduce(
  (total, inspection) => total + inspection.accepted_qty,
  0,
)
export const qualityAcceptanceRate =
  inspectedUnits > 0 ? (acceptedUnits / inspectedUnits) * 100 : 0

export const unpaidInvoices = invoices.filter(
  (invoice) => invoice.outstanding_amount > 0,
)
export const totalInvoiced = invoices.reduce(
  (total, invoice) => total + invoice.total_amount,
  0,
)
export const totalPaid = invoices.reduce(
  (total, invoice) => total + invoice.paid_amount,
  0,
)
export const totalOutstanding = invoices.reduce(
  (total, invoice) => total + invoice.outstanding_amount,
  0,
)
export const totalRejectedUnits = rejectedUnits
export const uniqueCategories = new Set(products.map((product) => product.category))
export const averageSellingPrice =
  products.reduce((total, product) => total + product.selling_price, 0) /
  Math.max(products.length, 1)
