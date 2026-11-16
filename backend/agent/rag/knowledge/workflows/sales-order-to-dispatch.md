---
doc_id: sales-order-to-dispatch
title: Sales Order to Dispatch Workflow
category: workflows
fact_kind: workflow
version: 1.0.0
updated_at: 2026-11-01
summary: The conceptual steps from an accepted sales order to a dispatched consignment.
tags: [sales, dispatch, workflow]
aliases: [order fulfilment, delivery workflow]
---

# Sales Order to Dispatch Workflow

## Purpose

This workflow describes how an accepted sales order becomes a dispatched
consignment. It explains the sequence of documents and checks, not the current
state of any order.

## Steps

1. A sales order is captured with customer, delivery address, and order lines.
2. The order is confirmed, which makes it available for allocation.
3. Allocation reserves free stock against the order lines.
4. Warehouse staff pick the allocated items and confirm the picked quantities.
5. The consignment is packed and a dispatch document is created.
6. The carrier collects the consignment and the dispatch moves to in transit.
7. Delivery is confirmed, and the order moves to dispatched.

## Exceptions

- If free stock is insufficient, the order line stays unallocated until stock
  is received or the line is cancelled.
- If the picked quantity differs from the allocated quantity, the difference
  is recorded and reviewed before dispatch.
- A dispatch that is returned is processed as a returns document rather than
  being deleted.

## Related topics

- Order and dispatch status terms
- Free stock, reserved stock, and low stock
