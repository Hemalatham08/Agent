from __future__ import annotations

import json
from contextlib import suppress

from backend.agent.erp.registration import register_erp_tools
from backend.agent.erp.definitions import ERP_TOOL_NAMES
from backend.agent.erp.service import ErpReadService
from backend.agent.erp.runner import ErpToolRunner
from backend.agent.tools.contracts import ToolExecutionRequest, ToolExecutionStatus
from backend.agent.tools.executor import ToolExecutor
from backend.agent.tools.registry import ToolRegistry


def print_result(title: str, result) -> None:
    print("\n" + "=" * 72)
    print(title)
    print(f"Tool:   {result.tool_name}")
    print(f"Status: {result.status.value}")
    if result.status is ToolExecutionStatus.SUCCEEDED:
        print(json.dumps(result.output, indent=2, ensure_ascii=False, default=str))
    elif result.error:
        print(f"Error:  {result.error.code} — {result.error.message}")
    else:
        print("No output returned.")
    print("=" * 72)


def main() -> None:
    print("\niFive AI ERP Agent — Read-only live demo")
    print("Initializing ERP service and tools...")

    service = ErpReadService.from_env()
    registry = ToolRegistry()
    executor = ToolExecutor(registry)
    registration = None

    try:
        registration = register_erp_tools(registry, executor, service)
        runner = ErpToolRunner(executor)

        # Fetch a real product and sales order ID for subsequent demonstrations.
        products = service.search_products(query="a", limit=5)
        product_id = products.items[0].product_id if products.items else None

        # Use the first available sales order ID from a read-only fixture query
        # through the adapter's fixed service interface is not available.
        # Supply an SO ID via environment or edit the placeholder below.
        import os
        so_id = os.getenv("ERP_DEMO_SO_ID", "").strip()

        demos = [
            ("1) PRODUCT SEARCH", "erp.products.search", {"query": "a", "limit": 5}),
        ]
        if product_id:
            demos.extend([
                ("2) PRODUCT DETAILS", "erp.products.get", {"product_id": product_id}),
                ("3) INVENTORY", "erp.inventory.get", {"product_id": product_id}),
            ])
        demos.extend([
            ("4) WAREHOUSES", "erp.warehouses.list", {}),
            ("5) LOW STOCK", "erp.inventory.low_stock", {"limit": 10}),
        ])
        if so_id:
            demos.append(("6) SALES ORDER DETAILS", "erp.sales_orders.get", {"so_id": so_id}))
        else:
            print("\nSales order demo skipped: set ERP_DEMO_SO_ID to a valid sales order ID.")

        print(f"\nRegistered {len(ERP_TOOL_NAMES)} ERP tool definitions.")
        for title, tool_name, arguments in demos:
            request = ToolExecutionRequest(tool_name=tool_name, arguments=arguments)
            result = runner.execute(request)
            print_result(title, result)

        print("\nDemo completed. No ERP data was modified.")
    finally:
        if registration is not None:
            with suppress(Exception):
                registration.unregister()
        executor.shutdown(wait=True)
        print("\nTool registrations cleaned up; executor shut down.")


if __name__ == "__main__":
    main()
