---
doc_id: product-catalogue
title: Product Catalogue Module
category: erp_docs
fact_kind: overview
version: 1.0.0
updated_at: 2026-11-01
summary: How the product catalogue stores products, SKUs, categories, and prices.
tags: [products, catalogue]
aliases: [product master, item master]
---

# Product Catalogue Module

The product catalogue is the master record for everything the business buys,
stores, sells, or dispatches. Other modules reference catalogue entries rather
than copying product details.

## Product record

A product record contains:

- an internal product identifier;
- a human-readable name;
- a SKU (stock keeping unit) used by warehouse staff;
- a category used for reporting and grouping;
- a unit of measure;
- a default tax classification;
- an active or inactive flag.

## SKU conventions

SKUs are stable identifiers. They should not be reused for a different product
after the original product is retired. When a product is replaced, the old SKU
is marked inactive and a new SKU is created.

## Pricing rules

Selling prices and purchase prices are stored as rules with an effective date.
The catalogue explains which price applies; the actual price for a transaction
is always read from the ERP database.

## Related documentation

- Business definitions: product and SKU
- Schema: core tables
