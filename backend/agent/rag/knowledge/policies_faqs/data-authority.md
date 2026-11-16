---
doc_id: data-authority
title: Documentation and Live Data Policy
category: policies_faqs
fact_kind: policy
version: 1.0.0
updated_at: 2026-11-01
summary: The rule that documentation explains concepts while ERP tools report live values.
tags: [policy, grounding]
aliases: [live data policy, documentation policy]
---

# Documentation and Live Data Policy

## Rule

Documentation explains concepts, definitions, workflows, policies, and schema.
It never substitutes for a query against the ERP database.

## What documentation may contain

- definitions of business terms;
- descriptions of module behaviour;
- conceptual workflow steps;
- schema explanations;
- general policies and frequently asked questions.

## What documentation must not contain

- current stock quantities or availability;
- current prices, invoice totals, or sales totals;
- counts of products, orders, customers, or suppliers;
- the current status of a specific order, invoice, or dispatch;
- personal data about customers or employees.

## Why

Documentation is reviewed and versioned slowly, while operational values change
continuously. Mixing the two makes answers look authoritative when they are
stale. Live questions must be answered from the ERP database so that the
answer carries the time of the query and the source of the value.

## Applying the rule

If a question asks for a value that changes with business activity, use the ERP
tools. If it asks what a term means or how a process works, documentation is
the correct source.
