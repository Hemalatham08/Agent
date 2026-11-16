---
doc_id: reporting-overview
title: Reporting Overview
category: erp_docs
fact_kind: overview
version: 1.0.0
updated_at: 2026-11-01
summary: What the reporting area covers and how reports relate to live ERP data.
tags: [reports, read-only]
aliases: [reports]
---

# Reporting Overview

The reporting area presents recorded transactions in a read-only form. Reports
are derived views over the same data that the operational modules write.

## Report families

- Inventory reports: stock movements, adjustments, and warehouse balances.
- Sales reports: order registers, dispatch registers, and revenue summaries.
- Purchasing reports: supplier orders, receipts, and outstanding quantities.
- Master data reports: product, supplier, and warehouse registers.

## Filters and periods

Most reports accept a date range, a warehouse filter, and a product or category
filter. A report with no filter shows the full recorded history for the
selected period.

## Live values

A report that is generated today reflects the database at the moment it runs.
The documentation describes what a report contains, not the values it will
show. Ask the ERP tools for current totals, counts, and statuses.
