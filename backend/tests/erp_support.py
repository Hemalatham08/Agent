from __future__ import annotations

import sqlite3
from pathlib import Path

ERP_FIXTURE_SCHEMA = """
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

CREATE TABLE warehouses (
    warehouse_id TEXT PRIMARY KEY,
    warehouse_name TEXT NOT NULL,
    city TEXT NOT NULL
);

CREATE TABLE inventory (
    inventory_id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(product_id),
    warehouse_id TEXT NOT NULL REFERENCES warehouses(warehouse_id),
    on_hand_qty INTEGER NOT NULL DEFAULT 0,
    reserved_qty INTEGER NOT NULL DEFAULT 0,
    UNIQUE(product_id, warehouse_id)
);

CREATE TABLE customers (
    customer_id TEXT PRIMARY KEY,
    customer_name TEXT NOT NULL,
    customer_type TEXT NOT NULL,
    city TEXT NOT NULL,
    phone TEXT
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
"""

ERP_FIXTURE_PRODUCTS = [
    (
        "PRD001",
        "HEX-M10-SS304",
        "Hex Bolt M10",
        "Bolts",
        "Stainless Steel",
        "M10",
        "SS304",
        "pieces",
        8.0,
        12.0,
        500,
    ),
    (
        "PRD002",
        "NUT-M10-SS304",
        "Hex Nut M10",
        "Nuts",
        "Stainless Steel",
        "M10",
        "SS304",
        "pieces",
        5.0,
        7.0,
        400,
    ),
    (
        "PRD003",
        "PLATE-100",
        "100% Steel Plate",
        "Plates",
        "Carbon Steel",
        "100x100",
        "A36",
        "pieces",
        20.0,
        30.0,
        10,
    ),
    (
        "PRD004",
        "WIDGET-UNDER",
        "Under_score Widget",
        "Widgets",
        "Aluminum",
        "20mm",
        "6061",
        "pieces",
        2.0,
        3.0,
        10,
    ),
    (
        "PRD005",
        "EMPTY-PRODUCT",
        "Empty Inventory Product",
        "Widgets",
        "Plastic",
        "10mm",
        "ABS",
        "pieces",
        1.0,
        2.0,
        5,
    ),
]

ERP_FIXTURE_WAREHOUSES = [
    ("WH001", "Main Warehouse", "Chennai"),
    ("WH002", "Secondary Warehouse", "Coimbatore"),
]

ERP_FIXTURE_INVENTORY = [
    ("INV001", "PRD001", "WH001", 420, 70),
    ("INV002", "PRD001", "WH002", 180, 20),
    ("INV003", "PRD002", "WH001", 1000, 100),
    ("INV004", "PRD002", "WH002", 300, 0),
    ("INV005", "PRD003", "WH001", 5, 0),
    ("INV006", "PRD004", "WH001", 50, 50),
    ("INV007", "PRD004", "WH002", 100, 0),
]

ERP_FIXTURE_CUSTOMERS = [
    ("CUS001", "Sri Venkateswara Engineering", "Business", "Chennai", "555-0100"),
    ("CUS002", "Another Customer", "Business", "Madurai", "555-0101"),
]

ERP_FIXTURE_SALES_ORDERS = [
    ("SO001", "CUS001", "2026-10-02", "2026-10-05", "Partially Dispatched"),
    ("SO002", "CUS002", "2026-10-03", "2026-10-06", "Pending"),
]

ERP_FIXTURE_SALES_ORDER_ITEMS = [
    ("SOI001", "SO001", "PRD001", 100, 12.0),
    ("SOI002", "SO001", "PRD002", 50, 7.0),
    ("SOI003", "SO002", "PRD003", 10, 30.0),
]

# dispatch_id, so_id, dispatch_date, carrier, tracking_number, status
ERP_FIXTURE_DISPATCHES = [
    ("DSP001", "SO001", "2026-10-04", "BlueDart", "BD10001", "Partially Dispatched"),
    ("DSP002", "SO002", "2026-10-06", "DTDC", "DT20002", "Dispatched"),
]

# dispatch_item_id, dispatch_id, product_id, picked_qty, dispatched_qty, barcode_verified
ERP_FIXTURE_DISPATCH_ITEMS = [
    ("DI001", "DSP001", "PRD001", 100, 100, 1),
    ("DI002", "DSP001", "PRD002", 50, 40, 1),
    ("DI003", "DSP002", "PRD003", 10, 10, 1),
]


def create_erp_fixture_db(path: Path) -> Path:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(ERP_FIXTURE_SCHEMA)
        connection.executemany(
            "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ERP_FIXTURE_PRODUCTS,
        )
        connection.executemany(
            "INSERT INTO warehouses VALUES (?, ?, ?)",
            ERP_FIXTURE_WAREHOUSES,
        )
        connection.executemany(
            "INSERT INTO inventory VALUES (?, ?, ?, ?, ?)",
            ERP_FIXTURE_INVENTORY,
        )
        connection.executemany(
            "INSERT INTO customers VALUES (?, ?, ?, ?, ?)",
            ERP_FIXTURE_CUSTOMERS,
        )
        connection.executemany(
            "INSERT INTO sales_orders VALUES (?, ?, ?, ?, ?)",
            ERP_FIXTURE_SALES_ORDERS,
        )
        connection.executemany(
            "INSERT INTO sales_order_items VALUES (?, ?, ?, ?, ?)",
            ERP_FIXTURE_SALES_ORDER_ITEMS,
        )
        connection.executemany(
            "INSERT INTO dispatches VALUES (?, ?, ?, ?, ?, ?)",
            ERP_FIXTURE_DISPATCHES,
        )
        connection.executemany(
            "INSERT INTO dispatch_items VALUES (?, ?, ?, ?, ?, ?)",
            ERP_FIXTURE_DISPATCH_ITEMS,
        )
        connection.commit()
    finally:
        connection.close()
    return path


__all__ = [
    "create_erp_fixture_db",
    "ERP_FIXTURE_DISPATCHES",
    "ERP_FIXTURE_DISPATCH_ITEMS",
]
