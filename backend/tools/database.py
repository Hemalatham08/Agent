import sqlite3
from pathlib import Path
from contextlib import closing

# Locate the SQLite database
DB_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "ifive_erp.db"
)


# Reusable database connection
def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


# Convert database rows into Python dictionaries
def fetch_all(query, parameters=()):
    with closing(get_connection()) as connection:
        rows = connection.execute(
            query, parameters
        ).fetchall()

        return [dict(row) for row in rows]


# 1. Retrieve all products
def get_all_products():
    query = """
        SELECT *
        FROM products
        ORDER BY product_id
    """

    return fetch_all(query)


# 2. Retrieve a particular product
def get_product_by_id(product_id):
    query = """
        SELECT *
        FROM products
        WHERE product_id = ?
    """

    results = fetch_all(query, (product_id,))

    return results[0] if results else None


# 3. Retrieve inventory for a particular product
def get_inventory_status(product_id):
    query = """
        SELECT
            p.product_id,
            p.product_name,
            w.warehouse_name,
            i.on_hand_qty,
            i.reserved_qty,
            (i.on_hand_qty - i.reserved_qty) AS free_stock,
            p.reorder_level

        FROM inventory i

        JOIN products p
            ON i.product_id = p.product_id

        JOIN warehouses w
            ON i.warehouse_id = w.warehouse_id

        WHERE p.product_id = ?

        ORDER BY w.warehouse_id
    """

    return fetch_all(query, (product_id,))


# 4. Find products below their reorder level
def get_low_stock_products():
    query = """
        SELECT
            p.product_id,
            p.product_name,
            w.warehouse_name,
            (i.on_hand_qty - i.reserved_qty) AS free_stock,
            p.reorder_level

        FROM inventory i

        JOIN products p
            ON i.product_id = p.product_id

        JOIN warehouses w
            ON i.warehouse_id = w.warehouse_id

        WHERE (i.on_hand_qty - i.reserved_qty)
              <= p.reorder_level

        ORDER BY p.product_id
    """

    return fetch_all(query)

# 5. Find sales orders that are not fully dispatched
def get_pending_sales_orders():
    query = """
        SELECT
            so.so_id,
            c.customer_name,
            so.order_date,
            so.required_date,
            so.status

        FROM sales_orders so

        JOIN customers c
            ON so.customer_id = c.customer_id

        WHERE so.status != 'Dispatched'

        ORDER BY so.so_id
    """

    return fetch_all(query)


# 6. Find purchase orders that are not fully received
def get_pending_purchase_orders():
    query = """
        SELECT
            po.po_id,
            s.supplier_name,
            po.order_date,
            po.expected_date,
            po.status

        FROM purchase_orders po

        JOIN suppliers s
            ON po.supplier_id = s.supplier_id

        WHERE po.status != 'Received'

        ORDER BY po.po_id
    """

    return fetch_all(query)


# 7. Find dispatch issues
def get_dispatch_issues():
    query = """
        SELECT
            d.dispatch_id,
            d.so_id,
            p.product_name,
            di.picked_qty,
            di.dispatched_qty,
            di.barcode_verified

        FROM dispatches d

        JOIN dispatch_items di
            ON d.dispatch_id = di.dispatch_id

        JOIN products p
            ON di.product_id = p.product_id

        WHERE
            di.picked_qty != di.dispatched_qty
            OR di.barcode_verified = 0

        ORDER BY d.dispatch_id
    """

    return fetch_all(query)


# 8. Find quality inspection issues
def get_quality_issues():
    query = """
        SELECT
            qi.inspection_id,
            qi.receipt_id,
            p.product_name,
            qi.inspected_qty,
            qi.accepted_qty,
            qi.rejected_qty,
            qi.rejection_reason

        FROM quality_inspections qi

        JOIN products p
            ON qi.product_id = p.product_id

        WHERE qi.rejected_qty > 0

        ORDER BY qi.inspection_id
    """

    return fetch_all(query)


# 9. Find invoices with outstanding balances
def get_unpaid_invoices():
    query = """
        SELECT
            i.invoice_id,
            i.invoice_type,
            i.invoice_date,
            i.total_amount,
            i.status,

            COALESCE(SUM(p.amount), 0) AS paid_amount,

            i.total_amount -
            COALESCE(SUM(p.amount), 0) AS outstanding_amount

        FROM invoices i

        LEFT JOIN payments p
            ON i.invoice_id = p.invoice_id

        GROUP BY i.invoice_id

        HAVING outstanding_amount > 0

        ORDER BY i.invoice_date
    """

    return fetch_all(query)


# 10. Calculate outstanding balance of a particular invoice
def get_invoice_outstanding(invoice_id):
    query = """
        SELECT
            i.invoice_id,
            i.invoice_type,
            i.total_amount,

            COALESCE(SUM(p.amount), 0) AS paid_amount,

            i.total_amount -
            COALESCE(SUM(p.amount), 0) AS outstanding_amount

        FROM invoices i

        LEFT JOIN payments p
            ON i.invoice_id = p.invoice_id

        WHERE i.invoice_id = ?

        GROUP BY i.invoice_id
    """

    results = fetch_all(query, (invoice_id,))

    return results[0] if results else None

def search_products(search_text):
    query = """
        SELECT product_id, sku, product_name, category,
               material, size, grade, unit
        FROM products
        WHERE product_name LIKE ?
           OR sku LIKE ?
           OR material LIKE ?
           OR size LIKE ?
           OR grade LIKE ?
        ORDER BY product_name
    """

    search_pattern = f"%{search_text}%"

    return fetch_all(
        query,
        (search_pattern,) * 5
    )
