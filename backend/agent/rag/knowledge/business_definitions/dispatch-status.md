---
doc_id: dispatch-status
title: Order and Dispatch Status Terms
category: business_definitions
fact_kind: definition
version: 1.0.0
updated_at: 2026-11-01
summary: The meaning of common order, allocation, and dispatch status labels.
tags: [dispatch, status, definition]
aliases: [order status, delivery status]
---

# Order and Dispatch Status Terms

Status labels describe where a document sits in its lifecycle. The label names
are stable; the documents that currently hold each label are live data.

## Sales order statuses

- Draft: captured but not yet confirmed.
- Confirmed: accepted and available for allocation.
- Allocated: stock has been reserved for the order lines.
- Partially dispatched: some lines have left the warehouse.
- Dispatched: every line has left the warehouse.
- Cancelled: the order will not be fulfilled.

## Dispatch statuses

- Picking: warehouse staff are collecting the allocated items.
- Packed: items are packed and waiting for the carrier.
- In transit: the carrier has collected the consignment.
- Delivered: the consignment has reached the customer.
- Returned: the consignment came back and is being processed.

## Reading a status

The current status of a specific order or dispatch is recorded in the ERP
database. Use the ERP tools to read it; this page only explains what the label
means.
