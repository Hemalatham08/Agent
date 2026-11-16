---
doc_id: core-tables
title: Core ERP Tables and Columns
category: schema
fact_kind: schema
version: 1.0.0
updated_at: 2026-11-01
summary: Conceptual explanation of the core product, stock, order, and dispatch tables.
tags: [schema, tables]
aliases: [database schema]
---

# Core ERP Tables and Columns

This page explains the purpose of the core tables. Column names are shown in
inline code so they are not confused with business terms. The page does not
list row counts or sample values.

## Products

The `products` table stores the catalogue record. Key columns include
`product_id`, `name`, `sku`, `category_id`, `unit_of_measure`, `tax_class`,
and `is_active`.

## Warehouses

The `warehouses` table stores physical or logical storage locations. Key
columns include `warehouse_id`, `name`, and `is_active`.

## Stock

The `stock` table stores the recorded balance per product and warehouse. Key
columns include `product_id`, `warehouse_id`, `on_hand_qty`, and
`reserved_qty`. Free stock is derived as `on_hand_qty` minus `reserved_qty`; it
is not stored as a separate column.

## Sales orders and lines

The `sales_orders` table stores order headers, and `sales_order_lines` stores
the ordered products and quantities. Status columns record lifecycle labels,
not business outcomes.

## Dispatches

The `dispatches` table stores consignments created from allocated order lines.
It references the warehouse, the carrier, and the related sales order.

## Querying

Join tables on their identifier columns. Always filter by the warehouse or
period required by the question, and never assume that a table contains only
active records.

## Related topics

- Product and SKU
- Free stock, reserved stock, and low stock
