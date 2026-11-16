---
doc_id: stock-adjustment
title: Stock Adjustment Workflow
category: workflows
fact_kind: workflow
version: 1.0.0
updated_at: 2026-11-01
summary: How stock differences are documented, approved, and posted.
tags: [inventory, adjustment, workflow]
aliases: [cycle count, stock correction]
---

# Stock Adjustment Workflow

## Purpose

A stock adjustment corrects the recorded quantity when it differs from the
physical count. Adjustments are controlled documents, not direct edits to
stock balances.

## Steps

1. A count is requested for a warehouse, zone, or product range.
2. Warehouse staff record the counted quantity for each selected SKU.
3. The system compares the counted quantity with the recorded on-hand quantity.
4. Differences are collected on an adjustment document with a reason code.
5. A supervisor reviews and approves the adjustment.
6. Approved differences are posted as stock movements.

## Controls

- Every adjustment carries a reason code such as damage, shrinkage, or a
  counting error.
- Posted adjustments are immutable; a correction is posted as a new movement.
- Adjustments never change reserved stock directly. Reservations are released
  or reallocated through the sales process.

## Related topics

- Free stock, reserved stock, and low stock
- Core tables
