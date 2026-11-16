---
doc_id: system-overview
title: iFive ERP System Overview
category: erp_docs
fact_kind: overview
version: 1.0.0
updated_at: 2026-11-01
summary: Conceptual overview of the ERP modules and how they fit together.
tags: [overview, modules]
aliases: [erp overview]
---

# iFive ERP System Overview

The iFive ERP is organised into modules that share a common product and
warehouse catalogue. Each module owns a specific part of the business process
while relying on the same master data.

## Modules

- Product catalogue: maintains products, SKUs, categories, and pricing rules.
- Inventory: tracks stock movements and warehouse balances.
- Sales: records orders, allocations, and dispatch documents.
- Purchasing: records supplier orders and goods receipts.
- Reporting: presents read-only summaries of recorded transactions.

## Shared master data

Products, warehouses, and suppliers are defined once and referenced by the
other modules. A change to master data is visible to every module that uses it.

## Documentation versus live data

This documentation explains how the system is organised. It does not contain
current stock levels, current prices, or current order statuses. Those values
belong to the ERP database and must be read with the ERP query tools.
