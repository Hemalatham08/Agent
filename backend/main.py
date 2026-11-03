
from fastapi import FastAPI, HTTPException

from backend.tools.database import (
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
)

# Create the FastAPI application
app = FastAPI(
    title="iFive AI ERP Agent API",
    description="API for ABC Fasteners ERP demo system",
    version="1.0.0",
)


# Home endpoint
@app.get("/")
def home():
    return {
        "message": "Welcome to iFive AI ERP Agent API",
        "status": "running",
    }


# 1. Get all products
@app.get("/products")
def products():
    return get_all_products()


# 2. Search a product by ID
@app.get("/products/{product_id}")
def product(product_id: str):
    result = get_product_by_id(product_id)

    if result is None:
        raise HTTPException(status_code=404, detail="Product not found")

    return result


# 3. Get inventory for a product
@app.get("/inventory/{product_id}")
def inventory(product_id: str):
    return get_inventory_status(product_id)


# 4. Get low-stock products
@app.get("/inventory/alerts/low-stock")
def low_stock():
    return get_low_stock_products()


# 5. Get pending sales orders
@app.get("/sales/pending")
def pending_sales():
    return get_pending_sales_orders()


# 6. Get pending purchase orders
@app.get("/purchase/pending")
def pending_purchase():
    return get_pending_purchase_orders()


# 7. Get dispatch issues
@app.get("/dispatch/issues")
def dispatch_issues():
    return get_dispatch_issues()


# 8. Get quality issues
@app.get("/quality/issues")
def quality_issues():
    return get_quality_issues()


# 9. Get unpaid invoices
@app.get("/accounting/unpaid")
def unpaid_invoices():
    return get_unpaid_invoices()


# 10. Get outstanding amount for a particular invoice
@app.get("/accounting/invoices/{invoice_id}")
def invoice_outstanding(invoice_id: str):
    result = get_invoice_outstanding(invoice_id)

    if result is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    return result
