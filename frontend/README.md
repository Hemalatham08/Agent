# iFive AI ERP Agent — Frontend

React + TypeScript dashboard for the iFive AI ERP backend (ABC Fasteners & Industrial Supplies).

## Stack

- React 19 + TypeScript
- Vite 8
- Tailwind CSS v4
- React Router
- Recharts
- Lucide React

## Run locally

```bash
npm install
npm run dev
```

The app runs at `http://localhost:5173`.

## Build and preview

```bash
npm run build
npm run preview
```

## Backend connection

The Vite dev server proxies `/api` to `http://127.0.0.1:8000`.

To use a different backend URL, copy `.env.example` to `.env` and set:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## Pages

- Dashboard — KPIs, inventory and sales charts, alerts
- AI Assistant — preview UI pending a backend `POST /chat` endpoint
- Inventory — stock levels, warehouse coverage, reorder alerts
- Sales Orders — pending sales, fulfilment progress, payment status
- Purchase Orders — pending receipts, delays, order values
- Dispatch — shipment register and dispatch exceptions
- Quality — incoming inspection results and rejections
- Accounting — invoice ledger, collections, outstanding balances
- Products — searchable product catalogue

## Data

The interface currently runs on demo data derived from the backend SQLite seed data. The API client in `src/services/api.ts` is prepared for live GET endpoints but is not yet wired into the pages.

## Checks

```bash
npm run lint
npm run build
```
