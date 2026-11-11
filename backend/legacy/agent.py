
import json
from ollama import chat
import inspect

from backend.tools.database import (
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
    get_stock_by_product_name,
)


# --------------------------------------------------
# 1. Define ERP tools that the AI can use
# --------------------------------------------------

tools = [
    
    {
        "type": "function",
        "function": {
            "name": "get_stock_by_product_name",
            "description": "Get actual stock quantities for a product using its exact product name. Use this for stock questions when the user provides a product name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {
                        "type": "string",
                        "description": "Exact product name, such as Hex Bolt M10"
                    }
                },
                "required": ["product_name"]
            }
        }
    },

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
    "get_stock_by_product_name":get_stock_by_product_name,
}


# --------------------------------------------------
# 3. ERP AI Agent
# --------------------------------------------------

# def ask_erp(question, history=None):

#     if history is None:
#         history = []

#     messages = [
#         {
#             "role": "system",
#             "content": """
# You are the AI ERP assistant for ABC Fasteners & Industrial Supplies.

# Your job is to understand natural-language ERP questions.
# When a user asks about a product's stock:
# 1. Use search_products to identify the product.
# 2. Get the product_id from the search result.
# 3. Call get_inventory_status using that product_id.
# 4. Report stock separately for each warehouse.
# 5. Clearly distinguish on_hand, reserved, and free_stock.
# 6. Never invent stock quantities.
# DISPATCH TOOL SELECTION RULES:
# - For questions about dispatch issues, always use get_dispatch_issues.
# - For questions about dispatch quantity mismatches, use get_dispatch_issues and identify records where picked_qty is different from dispatched_qty.
# - For questions about barcode verification problems, use get_dispatch_issues and identify records where barcode_verified is 0.
# - Never assume that every dispatch issue is a quantity mismatch.
# - Never assume that every dispatch issue is a barcode problem.
# - Explain the exact quantities and dispatch IDs from the tool results.
# - Never print tool-call JSON as a final answer.
# Rules:
# - Understand different ways users express the same question.
# - Use ERP tools whenever actual ERP data is required.
# - Never invent inventory quantities, order statuses, or payment balances.
# - If a product is mentioned by name, use the product catalog to identify its product ID.
# - For stock questions, retrieve inventory data.
# - For low stock or reorder questions, use the low-stock tool.
# - For sales questions, use pending sales orders.
# - For purchase questions, use pending purchase orders.
# - For dispatch problems, use dispatch issue tools.
# - For rejected items, use quality tools.
# - For outstanding payments, use unpaid invoice tools.
# - Explain results in simple business language.
# - If you do not have enough information, ask a clarification question.

# """
#         }
#     ]

#     messages.extend(history)

#     messages.append({
#         "role": "user",
#         "content": question
#     })

#     # Allow the AI to call tools
#     for _ in range(5):

#         response = chat(
#             model="llama3.2",
#             messages=messages,
#             tools=tools,
#         )

#         messages.append(response.message)

#         # If the AI doesn't request a tool, return its answer
#         # if not response.message.tool_calls:
#         #     return response.message.content, messages
#         if not response.message.tool_calls:
#             print("\nAI ANSWERED WITHOUT USING A TOOL")
#             print(response.message.content)
#             return response.message.content, messages

#         # Execute requested ERP tools
#         for tool_call in response.message.tool_calls:

#             function_name = tool_call.function.name
#             arguments = tool_call.function.arguments
#             print("\nAI IS CALLING A TOOL")
#             print("Function:", function_name)
#             print("Arguments:", arguments)
#             if function_name not in available_functions:
#                 result = {"error": "Unknown ERP tool"}
#             else:
#                 try:
#                     function = available_functions[function_name]
#                     result = function(**arguments)
#                 except Exception as error:
#                     result = {"error": str(error)}

#             # Convert result to JSON
#             result_json = json.dumps(result, default=str)
#             print("DATABASE RESULT")
#             print(result_json)
#             # Send ERP result back to the AI
#             messages.append({
#                 "role": "tool",
#                 "content": result_json,
#             })

#     return "I could not complete the ERP request.", messages

def ask_erp(question, history=None):

    if history is None:
        history = []
        
    # DIRECT ROUTING: Dispatch quantity mismatch questions
    question_lower = question.lower()

    mismatch_keywords = [
        "dispatch quantity mismatch",
        "dispatch quantity mismatches",
        "dispatch mismatches",
        "quantity mismatch in dispatch",
        "quantity mismatches in dispatch",
    ]

    if any(keyword in question_lower for keyword in mismatch_keywords):

        print("\nDIRECT ROUTING: Dispatch quantity mismatch")

        # Call the database function directly
        dispatch_records = available_functions["get_dispatch_issues"]()

        # Find records where picked and dispatched quantities differ
        mismatches = [
            record
            for record in dispatch_records
            if record["picked_qty"] != record["dispatched_qty"]
        ]

        # Construct the answer from actual database records
        if mismatches:

            answer = "Dispatch quantity mismatches found:\n"

            for record in mismatches:
                difference = (
                    record["picked_qty"] - record["dispatched_qty"]
                )

                answer += (
                    f"\nDispatch ID: {record['dispatch_id']}"
                    f"\nSales Order: {record['so_id']}"
                    f"\nProduct: {record['product_name']}"
                    f"\nPicked Quantity: {record['picked_qty']}"
                    f"\nDispatched Quantity: {record['dispatched_qty']}"
                    f"\nDifference: {difference} units\n"
                )

        else:
            answer = "No dispatch quantity mismatches found."

        print("\nDIRECT ROUTING RESULT")
        print(answer)

        return answer, history


    messages = [
        {
            "role": "system",
            "content": """
You are the AI ERP assistant for ABC Fasteners & Industrial Supplies.

Your job is to understand natural-language ERP questions.

STOCK RULES:
- For stock questions using a product name, use get_stock_by_product_name.
- Never invent product IDs or stock quantities.
- Report stock separately for each warehouse.
- Distinguish on_hand, reserved, and free_stock.


DISPATCH RULES:
- For dispatch issues, use get_dispatch_issues.
- For quantity mismatches, identify records where picked_qty != dispatched_qty.
- For barcode problems, identify records where barcode_verified == 0.
- Do not assume every dispatch issue is a quantity mismatch.
- Explain exact quantities and dispatch IDs.

GENERAL RULES:
- Use ERP tools whenever actual ERP data is required.
- Never invent inventory, order statuses, or payment balances.
- Use the correct ERP tool for sales, purchase, dispatch, quality, and accounting.
- Explain results in simple business language.
- Never print tool-call JSON as a final answer.
- If a tool call fails, correct it and retry.
- If you have no matching records, explain that clearly.
"""
        }
    ]

    messages.extend(history)

    messages.append({
        "role": "user",
        "content": question
    })

    # Allow the AI to call tools or retry
    for _ in range(5):

        response = chat(
            model="llama3.2",
            messages=messages,
            tools=tools,
        )

        messages.append(response.message)

        # Read AI response text safely
        answer = response.message.content or ""

        # CASE 1: AI did not provide a structured tool call
        if not response.message.tool_calls:

            # Detect text that looks like an unfinished tool call
            looks_like_fake_tool_call = (
                '"name":' in answer
                and '"parameters":' in answer
            )

            if looks_like_fake_tool_call:

                print("\nINVALID TOOL-CALL TEXT DETECTED")
                print(answer)

                messages.append({
                    "role": "user",
                    "content": """
Your previous response contained text that looked like a tool call,
but it was not a valid structured tool call.

Do not print tool-call JSON as text.

If ERP data is required, call the appropriate tool using
the available tool definitions.

Otherwise, answer normally using the available information.
"""
                })

                continue

            print("\nAI ANSWERED WITHOUT USING A TOOL")
            print(answer)

            return answer, messages

        # CASE 2: AI requested structured ERP tools
        for tool_call in response.message.tool_calls:

            function_name = tool_call.function.name
            arguments = tool_call.function.arguments or {}

            print("\nAI IS CALLING A TOOL")
            print("Function:", function_name)
            print("Arguments:", arguments)

            if function_name not in available_functions:

                result = {
                    "error": f"Unknown ERP tool: {function_name}"
                }

            else:

                try:

                    function = available_functions[function_name]

                    # Validate arguments before executing the function
                    function_signature = inspect.signature(function)

                    function_signature.bind(**arguments)

                    # Execute the validated function
                    result = function(**arguments)

                except TypeError as error:

                    result = {
                        "error": str(error),
                        "tool": function_name,
                        "received_arguments": arguments,
                        "expected_parameters": str(
                            inspect.signature(function)
                        ) if function_name in available_functions else None
                    }

                except Exception as error:

                    result = {
                        "error": str(error)
                    }

            # Convert result into JSON
            result_json = json.dumps(result, default=str)

            print("DATABASE / TOOL RESULT")
            print(result_json)

            # Send result back to Ollama
            messages.append({
                "role": "tool",
                "content": result_json,
            })

    return "I could not complete the ERP request after multiple attempts.", messages
