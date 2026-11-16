---
doc_id: free-stock
title: Free Stock, Reserved Stock, and Low Stock
category: business_definitions
fact_kind: definition
version: 1.0.0
updated_at: 2026-11-01
summary: How free stock relates to on-hand stock, reservations, and reorder levels.
tags: [stock, reorder level, definition]
aliases: [available stock, low stock]
---

# Free Stock, Reserved Stock, and Low Stock

## On-hand stock

On-hand stock is the quantity recorded as physically present in a warehouse at
a point in time. It is the result of receipts, dispatches, and adjustments.

## Reserved stock

Reserved stock is the part of on-hand stock that has been committed to open
sales orders or internal allocations. Reserved items are still in the
warehouse, but they are no longer freely available.

## Free stock

Free stock is the quantity that can still be promised to new demand. It is
conceptually on-hand stock minus reserved stock. Free stock may be negative
when reservations exceed the recorded physical quantity, which usually signals
a data or process problem.

## Reorder level

The reorder level is a per-product, per-warehouse threshold used by
replenishment. Low stock means free stock has fallen to or below that
threshold. The threshold is configuration, not a live measurement.

## Live values

This page defines the concepts. Current on-hand quantities, reservations, and
reorder status must be read from the ERP database with the ERP tools.
