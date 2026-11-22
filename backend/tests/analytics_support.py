"""Deterministic ERP fixtures for the financial analytics tools.

The base fixture mirrors the live ERP dataset exactly (October 2026 only) so
the reconciliation figures asserted by the analytics tests are reproducible.
A second builder adds August and September rows so month/quarter grouping and
time-series charts can be tested without changing the base totals.

These fixtures are additive: they never modify ``erp_support.py`` or the live
database at ``backend/data/ifive_erp.db``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

ANALYTICS_SCHEMA = """
CREATE TABLE company (
    company_id TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    industry TEXT NOT NULL,
    business_type TEXT NOT NULL,
    currency TEXT NOT NULL
);

CREATE TABLE customers (
    customer_id TEXT PRIMARY KEY,
    customer_name TEXT NOT NULL,
    customer_type TEXT NOT NULL,
    city TEXT NOT NULL,
    phone TEXT
);

CREATE TABLE suppliers (
    supplier_id TEXT PRIMARY KEY,
    supplier_name TEXT NOT NULL,
    city TEXT NOT NULL,
    contact_email TEXT
);

CREATE TABLE warehouses (
    warehouse_id TEXT PRIMARY KEY,
    warehouse_name TEXT NOT NULL,
    city TEXT NOT NULL
);

CREATE TABLE products (
    product_id TEXT PRIMARY KEY,
    sku TEXT UNIQUE NOT NULL,
    product_name TEXT NOT NULL,
    category TEXT NOT NULL,
    material TEXT NOT NULL,
    size TEXT NOT NULL,
    grade TEXT NOT NULL,
    unit TEXT NOT NULL,
    purchase_price REAL NOT NULL,
    selling_price REAL NOT NULL,
    reorder_level INTEGER NOT NULL
);

CREATE TABLE inventory (
    inventory_id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(product_id),
    warehouse_id TEXT NOT NULL REFERENCES warehouses(warehouse_id),
    on_hand_qty INTEGER NOT NULL DEFAULT 0,
    reserved_qty INTEGER NOT NULL DEFAULT 0,
    UNIQUE(product_id, warehouse_id)
);

CREATE TABLE sales_orders (
    so_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(customer_id),
    order_date TEXT NOT NULL,
    required_date TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE sales_order_items (
    so_item_id TEXT PRIMARY KEY,
    so_id TEXT NOT NULL REFERENCES sales_orders(so_id),
    product_id TEXT NOT NULL REFERENCES products(product_id),
    ordered_qty INTEGER NOT NULL,
    unit_price REAL NOT NULL
);

CREATE TABLE dispatches (
    dispatch_id TEXT PRIMARY KEY,
    so_id TEXT NOT NULL REFERENCES sales_orders(so_id),
    dispatch_date TEXT,
    carrier TEXT,
    tracking_number TEXT,
    status TEXT NOT NULL
);

CREATE TABLE dispatch_items (
    dispatch_item_id TEXT PRIMARY KEY,
    dispatch_id TEXT NOT NULL REFERENCES dispatches(dispatch_id),
    product_id TEXT NOT NULL REFERENCES products(product_id),
    picked_qty INTEGER NOT NULL,
    dispatched_qty INTEGER NOT NULL,
    barcode_verified INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE purchase_orders (
    po_id TEXT PRIMARY KEY,
    supplier_id TEXT NOT NULL REFERENCES suppliers(supplier_id),
    warehouse_id TEXT NOT NULL REFERENCES warehouses(warehouse_id),
    order_date TEXT NOT NULL,
    expected_date TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE purchase_order_items (
    po_item_id TEXT PRIMARY KEY,
    po_id TEXT NOT NULL REFERENCES purchase_orders(po_id),
    product_id TEXT NOT NULL REFERENCES products(product_id),
    ordered_qty INTEGER NOT NULL,
    unit_cost REAL NOT NULL,
    received_qty INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE goods_receipts (
    receipt_id TEXT PRIMARY KEY,
    po_id TEXT NOT NULL REFERENCES purchase_orders(po_id),
    received_date TEXT NOT NULL,
    warehouse_id TEXT NOT NULL REFERENCES warehouses(warehouse_id),
    received_by TEXT NOT NULL
);

CREATE TABLE quality_inspections (
    inspection_id TEXT PRIMARY KEY,
    receipt_id TEXT NOT NULL REFERENCES goods_receipts(receipt_id),
    product_id TEXT NOT NULL REFERENCES products(product_id),
    inspected_qty INTEGER NOT NULL,
    accepted_qty INTEGER NOT NULL,
    rejected_qty INTEGER NOT NULL,
    rejection_reason TEXT
);

CREATE TABLE invoices (
    invoice_id TEXT PRIMARY KEY,
    so_id TEXT REFERENCES sales_orders(so_id),
    po_id TEXT REFERENCES purchase_orders(po_id),
    invoice_date TEXT NOT NULL,
    invoice_type TEXT NOT NULL,
    total_amount REAL NOT NULL,
    status TEXT NOT NULL,
    CHECK ((so_id IS NOT NULL AND po_id IS NULL) OR (so_id IS NULL AND po_id IS NOT NULL))
);

CREATE TABLE payments (
    payment_id TEXT PRIMARY KEY,
    invoice_id TEXT NOT NULL REFERENCES invoices(invoice_id),
    payment_date TEXT NOT NULL,
    amount REAL NOT NULL,
    payment_method TEXT NOT NULL
);

CREATE TABLE stock_movements (
    movement_id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(product_id),
    warehouse_id TEXT NOT NULL REFERENCES warehouses(warehouse_id),
    movement_date TEXT NOT NULL,
    movement_type TEXT NOT NULL,
    reference_id TEXT,
    quantity_change INTEGER NOT NULL,
    notes TEXT
);

CREATE INDEX idx_inventory_product ON inventory(product_id);
CREATE INDEX idx_purchase_order_date ON purchase_orders(order_date);
CREATE INDEX idx_sales_order_date ON sales_orders(order_date);
CREATE INDEX idx_stock_movements_product_date ON stock_movements(product_id, movement_date);
"""

ANALYTICS_COMPANY = [
    (
        "ABC001",
        "ABC Fasteners & Industrial Supplies",
        "Industrial Trading and Distribution",
        "Wholesale Distribution",
        "INR",
    ),
]

ANALYTICS_CUSTOMERS = [
    ("CUS001", "Sri Venkateswara Engineering", "Manufacturer", "Chennai", "9000000001"),
    ("CUS002", "Metro Machinery Works", "Manufacturer", "Coimbatore", "9000000002"),
    ("CUS003", "Kaveri Industrial Stores", "Dealer", "Madurai", "9000000003"),
    ("CUS004", "Southern Auto Components", "Manufacturer", "Hosur", "9000000004"),
    ("CUS005", "Precision Tools & Traders", "Dealer", "Tiruchirappalli", "9000000005"),
]

ANALYTICS_SUPPLIERS = [
    ("SUP001", "Apex Fastener Manufacturing", "Pune", "sales@apexfasteners.example"),
    ("SUP002", "Prime Metal Components", "Chennai", "orders@primemetal.example"),
    ("SUP003", "Eastern Industrial Supplies", "Kolkata", "sales@easternindustrial.example"),
    ("SUP004", "Reliable Bolt & Nut Co.", "Coimbatore", "contact@reliablebolt.example"),
]

ANALYTICS_WAREHOUSES = [
    ("WH001", "Main Warehouse", "Chennai"),
    ("WH002", "Secondary Warehouse", "Coimbatore"),
]

ANALYTICS_PRODUCTS = [
    ("PRD001", "HEX-M10-SS304", "Hex Bolt M10", "Bolts", "Stainless Steel", "M10", "SS304", "pieces", 8.0, 12.0, 500),
    ("PRD002", "NUT-M10-SS304", "Hex Nut M10", "Nuts", "Stainless Steel", "M10", "SS304", "pieces", 4.0, 7.0, 400),
    ("PRD003", "SCR-M6-CS88", "Machine Screw M6", "Screws", "Carbon Steel", "M6", "Grade 8.8", "pieces", 3.0, 5.0, 600),
    ("PRD004", "WSH-M10-SS304", "Flat Washer M10", "Washers", "Stainless Steel", "M10", "SS304", "pieces", 2.0, 4.0, 300),
    ("PRD005", "ANC-M12-CS88", "Anchor Bolt M12", "Bolts", "Carbon Steel", "M12", "Grade 8.8", "pieces", 15.0, 22.0, 200),
    ("PRD006", "HEX-M12-SS316", "Hex Bolt M12", "Bolts", "Stainless Steel", "M12", "SS316", "pieces", 12.0, 18.0, 250),
]

ANALYTICS_INVENTORY = [
    ("INV001", "PRD001", "WH001", 420, 70),
    ("INV002", "PRD002", "WH001", 900, 100),
    ("INV003", "PRD003", "WH001", 500, 80),
    ("INV004", "PRD004", "WH002", 650, 50),
    ("INV005", "PRD005", "WH002", 150, 20),
    ("INV006", "PRD006", "WH001", 310, 40),
    ("INV007", "PRD001", "WH002", 180, 20),
    ("INV008", "PRD002", "WH002", 350, 25),
    ("INV009", "PRD003", "WH002", 720, 100),
    ("INV010", "PRD004", "WH001", 400, 30),
    ("INV011", "PRD005", "WH001", 260, 10),
    ("INV012", "PRD006", "WH002", 120, 10),
]

ANALYTICS_SALES_ORDERS = [
    ("SO001", "CUS001", "2026-10-02", "2026-10-05", "Partially Dispatched"),
    ("SO002", "CUS002", "2026-10-04", "2026-10-07", "Dispatched"),
    ("SO003", "CUS003", "2026-10-10", "2026-10-15", "Pending"),
    ("SO004", "CUS004", "2026-10-12", "2026-10-16", "Dispatched"),
    ("SO005", "CUS005", "2026-10-18", "2026-10-22", "Pending"),
    ("SO006", "CUS001", "2026-10-21", "2026-10-27", "Processing"),
]

ANALYTICS_SALES_ORDER_ITEMS = [
    ("SOI001", "SO001", "PRD001", 100, 12.0),
    ("SOI002", "SO001", "PRD002", 100, 7.0),
    ("SOI003", "SO002", "PRD003", 200, 5.0),
    ("SOI004", "SO002", "PRD004", 150, 4.0),
    ("SOI005", "SO003", "PRD005", 80, 22.0),
    ("SOI006", "SO003", "PRD006", 60, 18.0),
    ("SOI007", "SO004", "PRD001", 120, 12.0),
    ("SOI008", "SO004", "PRD004", 100, 4.0),
    ("SOI009", "SO005", "PRD002", 250, 7.0),
    ("SOI010", "SO005", "PRD003", 300, 5.0),
    ("SOI011", "SO006", "PRD006", 90, 18.0),
    ("SOI012", "SO006", "PRD005", 50, 22.0),
]

ANALYTICS_DISPATCHES = [
    ("DSP001", "SO001", "2026-10-04", "BlueDart", "BD10001", "Partially Dispatched"),
    ("DSP002", "SO002", "2026-10-06", "DTDC", "DT20002", "Dispatched"),
    ("DSP003", "SO004", "2026-10-15", "BlueDart", "BD10004", "Dispatched"),
]

ANALYTICS_DISPATCH_ITEMS = [
    ("DI001", "DSP001", "PRD001", 100, 100, 1),
    ("DI002", "DSP001", "PRD002", 100, 80, 1),
    ("DI003", "DSP002", "PRD003", 200, 200, 1),
    ("DI004", "DSP002", "PRD004", 150, 150, 1),
    ("DI005", "DSP003", "PRD001", 120, 120, 1),
    ("DI006", "DSP003", "PRD004", 100, 100, 0),
]

ANALYTICS_PURCHASE_ORDERS = [
    ("PO001", "SUP001", "WH001", "2026-10-01", "2026-10-08", "Partially Received"),
    ("PO002", "SUP002", "WH002", "2026-10-05", "2026-10-12", "Received"),
    ("PO003", "SUP003", "WH001", "2026-10-15", "2026-10-25", "Pending"),
    ("PO004", "SUP004", "WH002", "2026-10-20", "2026-10-29", "Delayed"),
]

ANALYTICS_PURCHASE_ORDER_ITEMS = [
    ("POI001", "PO001", "PRD001", 500, 8.0, 300),
    ("POI002", "PO001", "PRD002", 400, 4.0, 400),
    ("POI003", "PO002", "PRD003", 600, 3.0, 600),
    ("POI004", "PO002", "PRD004", 500, 2.0, 500),
    ("POI005", "PO003", "PRD005", 300, 15.0, 0),
    ("POI006", "PO003", "PRD006", 250, 12.0, 0),
    ("POI007", "PO004", "PRD001", 400, 8.0, 0),
    ("POI008", "PO004", "PRD005", 200, 15.0, 0),
]

ANALYTICS_GOODS_RECEIPTS = [
    ("GR001", "PO001", "2026-10-06", "WH001", "Warehouse Team A"),
    ("GR002", "PO002", "2026-10-11", "WH002", "Warehouse Team B"),
]

ANALYTICS_QUALITY_INSPECTIONS = [
    ("QI001", "GR001", "PRD001", 300, 294, 6, "Minor thread damage"),
    ("QI002", "GR001", "PRD002", 400, 400, 0, None),
    ("QI003", "GR002", "PRD003", 600, 590, 10, "Surface defects"),
    ("QI004", "GR002", "PRD004", 500, 498, 2, "Packaging damage"),
]

ANALYTICS_INVOICES = [
    ("INV-S001", "SO001", None, "2026-10-04", "Sales", 1760.0, "Partially Paid"),
    ("INV-S002", "SO002", None, "2026-10-06", "Sales", 1600.0, "Paid"),
    ("INV-S004", "SO004", None, "2026-10-15", "Sales", 1840.0, "Unpaid"),
    ("INV-P001", None, "PO001", "2026-10-06", "Purchase", 4000.0, "Partially Paid"),
    ("INV-P002", None, "PO002", "2026-10-11", "Purchase", 2800.0, "Paid"),
]

ANALYTICS_PAYMENTS = [
    ("PAY001", "INV-S001", "2026-10-10", 1000.0, "Bank Transfer"),
    ("PAY002", "INV-S002", "2026-10-08", 1600.0, "UPI"),
    ("PAY003", "INV-P001", "2026-10-12", 2000.0, "Bank Transfer"),
    ("PAY004", "INV-P002", "2026-10-14", 2800.0, "Bank Transfer"),
]

ANALYTICS_STOCK_MOVEMENTS = [
    ("MOV001", "PRD001", "WH001", "2026-10-01", "Opening Balance", None, 120, "Opening stock"),
    ("MOV002", "PRD001", "WH001", "2026-10-06", "Purchase Receipt", "GR001", 294, "Accepted receipt quantity"),
    ("MOV003", "PRD001", "WH001", "2026-10-04", "Sales Dispatch", "DSP001", -100, "Dispatched against SO001"),
    ("MOV004", "PRD002", "WH001", "2026-10-01", "Opening Balance", None, 600, "Opening stock"),
    ("MOV005", "PRD002", "WH001", "2026-10-06", "Purchase Receipt", "GR001", 400, "Accepted receipt quantity"),
    ("MOV006", "PRD002", "WH001", "2026-10-04", "Sales Dispatch", "DSP001", -80, "Partially dispatched against SO001"),
    ("MOV007", "PRD003", "WH002", "2026-10-01", "Opening Balance", None, 120, "Opening stock"),
    ("MOV008", "PRD003", "WH002", "2026-10-11", "Purchase Receipt", "GR002", 590, "Accepted receipt quantity"),
    ("MOV009", "PRD003", "WH002", "2026-10-06", "Sales Dispatch", "DSP002", -200, "Dispatched against SO002"),
    ("MOV010", "PRD004", "WH002", "2026-10-01", "Opening Balance", None, 150, "Opening stock"),
    ("MOV011", "PRD004", "WH002", "2026-10-11", "Purchase Receipt", "GR002", 498, "Accepted receipt quantity"),
    ("MOV012", "PRD004", "WH002", "2026-10-06", "Sales Dispatch", "DSP002", -150, "Dispatched against SO002"),
]

# Additive rows for month and quarter grouping tests.
MULTI_PERIOD_SALES_ORDERS = [
    ("SO007", "CUS001", "2026-08-10", "2026-08-14", "Dispatched"),
    ("SO008", "CUS002", "2026-09-05", "2026-09-09", "Dispatched"),
    ("SO009", "CUS003", "2026-09-20", "2026-09-24", "Pending"),
]

MULTI_PERIOD_SALES_ORDER_ITEMS = [
    ("SOI013", "SO007", "PRD001", 10, 12.0),
    ("SOI014", "SO008", "PRD002", 20, 7.0),
    ("SOI015", "SO009", "PRD003", 30, 5.0),
]

MULTI_PERIOD_DISPATCHES = [
    ("DSP004", "SO007", "2026-08-12", "BlueDart", "BD10007", "Dispatched"),
    ("DSP005", "SO008", "2026-09-07", "DTDC", "DT20008", "Dispatched"),
]

MULTI_PERIOD_DISPATCH_ITEMS = [
    ("DI007", "DSP004", "PRD001", 10, 10, 1),
    ("DI008", "DSP005", "PRD002", 20, 20, 1),
]

MULTI_PERIOD_PURCHASE_ORDERS = [
    ("PO005", "SUP001", "WH001", "2026-08-01", "2026-08-05", "Received"),
    ("PO006", "SUP002", "WH002", "2026-09-01", "2026-09-05", "Received"),
]

MULTI_PERIOD_PURCHASE_ORDER_ITEMS = [
    ("POI009", "PO005", "PRD001", 10, 8.0, 10),
    ("POI010", "PO006", "PRD002", 20, 4.0, 20),
]

MULTI_PERIOD_STOCK_MOVEMENTS = [
    ("MOV013", "PRD001", "WH001", "2026-08-01", "Opening Balance", None, 50, "Opening stock"),
    ("MOV014", "PRD001", "WH001", "2026-08-05", "Purchase Receipt", "GR003", 10, "Accepted receipt quantity"),
    ("MOV015", "PRD002", "WH002", "2026-09-01", "Opening Balance", None, 30, "Opening stock"),
    ("MOV016", "PRD002", "WH002", "2026-09-05", "Purchase Receipt", "GR004", 20, "Accepted receipt quantity"),
]


def create_analytics_fixture_db(path: Path) -> Path:
    """Create an ERP database matching the live October 2026 dataset."""

    connection = sqlite3.connect(path)
    try:
        connection.executescript(ANALYTICS_SCHEMA)
        _insert_base_rows(connection)
        connection.commit()
    finally:
        connection.close()
    return path


def create_multi_period_fixture_db(path: Path) -> Path:
    """Create the analytics fixture plus August/September rows."""

    connection = sqlite3.connect(path)
    try:
        connection.executescript(ANALYTICS_SCHEMA)
        _insert_base_rows(connection)
        connection.executemany(
            "INSERT INTO sales_orders VALUES (?, ?, ?, ?, ?)",
            MULTI_PERIOD_SALES_ORDERS,
        )
        connection.executemany(
            "INSERT INTO sales_order_items VALUES (?, ?, ?, ?, ?)",
            MULTI_PERIOD_SALES_ORDER_ITEMS,
        )
        connection.executemany(
            "INSERT INTO dispatches VALUES (?, ?, ?, ?, ?, ?)",
            MULTI_PERIOD_DISPATCHES,
        )
        connection.executemany(
            "INSERT INTO dispatch_items VALUES (?, ?, ?, ?, ?, ?)",
            MULTI_PERIOD_DISPATCH_ITEMS,
        )
        connection.executemany(
            "INSERT INTO purchase_orders VALUES (?, ?, ?, ?, ?, ?)",
            MULTI_PERIOD_PURCHASE_ORDERS,
        )
        connection.executemany(
            "INSERT INTO purchase_order_items VALUES (?, ?, ?, ?, ?, ?)",
            MULTI_PERIOD_PURCHASE_ORDER_ITEMS,
        )
        connection.executemany(
            "INSERT INTO stock_movements VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            MULTI_PERIOD_STOCK_MOVEMENTS,
        )
        connection.commit()
    finally:
        connection.close()
    return path


def _insert_base_rows(connection: sqlite3.Connection) -> None:
    connection.executemany("INSERT INTO company VALUES (?, ?, ?, ?, ?)", ANALYTICS_COMPANY)
    connection.executemany(
        "INSERT INTO customers VALUES (?, ?, ?, ?, ?)",
        ANALYTICS_CUSTOMERS,
    )
    connection.executemany(
        "INSERT INTO suppliers VALUES (?, ?, ?, ?)",
        ANALYTICS_SUPPLIERS,
    )
    connection.executemany(
        "INSERT INTO warehouses VALUES (?, ?, ?)",
        ANALYTICS_WAREHOUSES,
    )
    connection.executemany(
        "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ANALYTICS_PRODUCTS,
    )
    connection.executemany(
        "INSERT INTO inventory VALUES (?, ?, ?, ?, ?)",
        ANALYTICS_INVENTORY,
    )
    connection.executemany(
        "INSERT INTO sales_orders VALUES (?, ?, ?, ?, ?)",
        ANALYTICS_SALES_ORDERS,
    )
    connection.executemany(
        "INSERT INTO sales_order_items VALUES (?, ?, ?, ?, ?)",
        ANALYTICS_SALES_ORDER_ITEMS,
    )
    connection.executemany(
        "INSERT INTO dispatches VALUES (?, ?, ?, ?, ?, ?)",
        ANALYTICS_DISPATCHES,
    )
    connection.executemany(
        "INSERT INTO dispatch_items VALUES (?, ?, ?, ?, ?, ?)",
        ANALYTICS_DISPATCH_ITEMS,
    )
    connection.executemany(
        "INSERT INTO purchase_orders VALUES (?, ?, ?, ?, ?, ?)",
        ANALYTICS_PURCHASE_ORDERS,
    )
    connection.executemany(
        "INSERT INTO purchase_order_items VALUES (?, ?, ?, ?, ?, ?)",
        ANALYTICS_PURCHASE_ORDER_ITEMS,
    )
    connection.executemany(
        "INSERT INTO goods_receipts VALUES (?, ?, ?, ?, ?)",
        ANALYTICS_GOODS_RECEIPTS,
    )
    connection.executemany(
        "INSERT INTO quality_inspections VALUES (?, ?, ?, ?, ?, ?, ?)",
        ANALYTICS_QUALITY_INSPECTIONS,
    )
    connection.executemany(
        "INSERT INTO invoices VALUES (?, ?, ?, ?, ?, ?, ?)",
        ANALYTICS_INVOICES,
    )
    connection.executemany(
        "INSERT INTO payments VALUES (?, ?, ?, ?, ?)",
        ANALYTICS_PAYMENTS,
    )
    connection.executemany(
        "INSERT INTO stock_movements VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ANALYTICS_STOCK_MOVEMENTS,
    )


__all__ = [
    "create_analytics_fixture_db",
    "create_multi_period_fixture_db",
]
