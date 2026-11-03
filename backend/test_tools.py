
from tools.database import (
    get_all_products,
    get_product_by_id,
    get_inventory_status,
    get_low_stock_products,
    get_pending_sales_orders,
    get_pending_purchase_orders,
    get_dispatch_issues,
    get_quality_issues,
    get_unpaid_invoices,
    get_invoice_outstanding,
    search_products
)


print("\n========== ALL PRODUCTS ==========")

for product in get_all_products():
    print(product["product_id"], "-", product["product_name"])


print("\n========== SEARCH PRODUCT ==========")

print(get_product_by_id("PRD001"))


print("\n========== INVENTORY STATUS ==========")

for item in get_inventory_status("PRD001"):
    print(
        item["product_name"],
        "| Warehouse:", item["warehouse_name"],
        "| Free Stock:", item["free_stock"]
    )


print("\n========== LOW STOCK PRODUCTS ==========")

for item in get_low_stock_products():
    print(
        item["product_name"],
        "| Warehouse:", item["warehouse_name"],
        "| Free Stock:", item["free_stock"],
        "| Reorder Level:", item["reorder_level"]
    )


print("\n========== PENDING SALES ORDERS ==========")

for order in get_pending_sales_orders():
    print(
        order["so_id"],
        "| Customer:", order["customer_name"],
        "| Status:", order["status"]
    )


print("\n========== PENDING PURCHASE ORDERS ==========")

for order in get_pending_purchase_orders():
    print(
        order["po_id"],
        "| Supplier:", order["supplier_name"],
        "| Status:", order["status"]
    )


print("\n========== DISPATCH ISSUES ==========")

for item in get_dispatch_issues():
    print(
        item["dispatch_id"],
        "| Order:", item["so_id"],
        "| Product:", item["product_name"],
        "| Picked:", item["picked_qty"],
        "| Dispatched:", item["dispatched_qty"],
        "| Barcode Verified:", item["barcode_verified"]
    )

print("\n========== QUALITY ISSUES ==========")

for issue in get_quality_issues():
    print(
        issue["inspection_id"],
        "| Product:", issue["product_name"],
        "| Rejected:", issue["rejected_qty"],
        "| Reason:", issue["rejection_reason"]
    )


print("\n========== UNPAID INVOICES ==========")

for invoice in get_unpaid_invoices():
    print(
        invoice["invoice_id"],
        "| Type:", invoice["invoice_type"],
        "| Total:", invoice["total_amount"],
        "| Paid:", invoice["paid_amount"],
        "| Outstanding:", invoice["outstanding_amount"]
    )


print("\n========== SPECIFIC INVOICE ==========")

invoice = get_invoice_outstanding("INV-S001")

print(invoice)

print("\n========== PRODUCT SEARCH TEST ==========")

results = search_products("M10")

for product in results:
    print(product)
