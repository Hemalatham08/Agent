---
doc_id: purchase-to-stock
title: Purchase to Stock Workflow
category: workflows
fact_kind: workflow
version: 1.0.0
updated_at: 2026-11-01
summary: The conceptual steps from a purchasing need to stock being available.
tags: [purchasing, workflow, receipts]
aliases: [procurement workflow, goods receipt]
---

# Purchase to Stock Workflow

## Purpose

This workflow describes how a purchasing need becomes available stock. It is a
conceptual sequence; the documents created at each step are live records.

## Steps

1. Replenishment identifies products whose free stock is at or below the
   reorder level.
2. A purchase order is created for the chosen supplier and confirmed.
3. The supplier sends the goods together with a delivery note.
4. Warehouse staff receive the goods and record a goods receipt.
5. Received quantities are added to on-hand stock for the receiving warehouse.
6. Any difference between the ordered and received quantity is recorded as a
   receipt exception and reviewed.

## Controls

- Receipts are matched to confirmed purchase orders before stock is updated.
- Rejected goods are not added to available stock.
- A receipt that cannot be matched is held for review instead of being posted.

## Related topics

- Free stock, reserved stock, and low stock
- Core tables
