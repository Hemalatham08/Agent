
import json
from ollama import chat

from tools.database import (
    get_all_products,
    get_product_by_id,
    get_inventory_status,
    get_low_stock_products,
    get_pending_sales_orders,
    get_pending_purchase_orders,
    get_dispatch_issues,
    get_quality_issues,
    get_unpaid_invoices,
    get_invoice_outstanding,
    search_products,
)


# --------------------------------------------------
# 1. Define ERP tools that the AI can use
# --------------------------------------------------

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_low_stock_products",
            "description": "Find products below their reorder level. Use for questions about low stock, shortages, replenishment, or items needing reorder.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_all_products",
            "description": "Get the complete product catalog.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_inventory_status",
            "description": "Get stock information for a particular product using its product ID. Use this for questions about stock availability or quantity of a specific product.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "Product ID, such as PRD001",
                    }
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pending_sales_orders",
            "description": "Find pending or partially dispatched customer sales orders.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pending_purchase_orders",
            "description": "Find pending, delayed, or partially received purchase orders.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dispatch_issues",
            "description": "Find dispatch discrepancies, quantity mismatches, and barcode verification problems.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_quality_issues",
            "description": "Find rejected products and quality inspection problems.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_unpaid_invoices",
            "description": "Find invoices with outstanding payment balances.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    
{
    "type": "function",
    "function": {
        "name": "search_products",
        "description": "Search ERP products by name, SKU, material, size, or grade.",
        "parameters": {
            "type": "object",
            "properties": {
                "search_text": {
                    "type": "string",
                    "description": "Product name, SKU, material, size, or grade to search"
                }
            },
            "required": ["search_text"]
        }
    }
}

]


# --------------------------------------------------
# 2. Map AI tool names to actual Python functions
# --------------------------------------------------

available_functions = {
    "get_all_products": get_all_products,
    "get_low_stock_products": get_low_stock_products,
    "get_inventory_status": get_inventory_status,
    "get_pending_sales_orders": get_pending_sales_orders,
    "get_pending_purchase_orders": get_pending_purchase_orders,
    "get_dispatch_issues": get_dispatch_issues,
    "get_quality_issues": get_quality_issues,
    "get_unpaid_invoices": get_unpaid_invoices,
    "search_products": search_products,
}


# --------------------------------------------------
# 3. ERP AI Agent
# --------------------------------------------------

def ask_erp(question, history=None):

    if history is None:
        history = []

    messages = [
        {
            "role": "system",
            "content": """
You are the AI ERP assistant for ABC Fasteners & Industrial Supplies.

Your job is to understand natural-language ERP questions.
When a user asks about a product's stock:
1. Use search_products to identify the product.
2. Get the product_id from the search result.
3. Call get_inventory_status using that product_id.
4. Report stock separately for each warehouse.
5. Clearly distinguish on_hand, reserved, and free_stock.
6. Never invent stock quantities.
Rules:
- Understand different ways users express the same question.
- Use ERP tools whenever actual ERP data is required.
- Never invent inventory quantities, order statuses, or payment balances.
- If a product is mentioned by name, use the product catalog to identify its product ID.
- For stock questions, retrieve inventory data.
- For low stock or reorder questions, use the low-stock tool.
- For sales questions, use pending sales orders.
- For purchase questions, use pending purchase orders.
- For dispatch problems, use dispatch issue tools.
- For rejected items, use quality tools.
- For outstanding payments, use unpaid invoice tools.
- Explain results in simple business language.
- If you do not have enough information, ask a clarification question.

"""
        }
    ]

    messages.extend(history)

    messages.append({
        "role": "user",
        "content": question
    })

    # Allow the AI to call tools
    for _ in range(5):

        response = chat(
            model="llama3.2",
            messages=messages,
            tools=tools,
        )

        messages.append(response.message)

        # If the AI doesn't request a tool, return its answer
        if not response.message.tool_calls:
            return response.message.content, messages

        # Execute requested ERP tools
        for tool_call in response.message.tool_calls:

            function_name = tool_call.function.name
            arguments = tool_call.function.arguments

            if function_name not in available_functions:
                result = {"error": "Unknown ERP tool"}
            else:
                try:
                    function = available_functions[function_name]
                    result = function(**arguments)
                except Exception as error:
                    result = {"error": str(error)}

            # Convert result to JSON
            result_json = json.dumps(result, default=str)

            # Send ERP result back to the AI
            messages.append({
                "role": "tool",
                "content": result_json,
            })

    return "I could not complete the ERP request.", messages
