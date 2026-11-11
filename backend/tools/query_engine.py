
import json
import ollama

from backend.tools.sql_generator import generate_sql
from backend.tools.sql_executor import execute_readonly_sql


MODEL_NAME = "llama3.2"


def ask_database(user_question):
    """
    Convert an ERP question into SQL, execute it safely,
    and generate a natural-language answer from the results.
    """

    # Step 1: Generate SQL from the user's question.
    sql = generate_sql(user_question)

    print("\n========== GENERATED SQL ==========")
    print(sql)

    # Step 2: Validate and execute SQL safely.
    result = execute_readonly_sql(sql)

    if not result["success"]:
        return {
            "success": False,
            "question": user_question,
            "sql": sql,
            "error": result["error"],
        }

    # Step 3: Give actual database results to Ollama.
    data = json.dumps(
        result["records"],
        indent=2,
        ensure_ascii=False,
    )

    prompt = f"""
You are an ERP assistant for ABC Fasteners & Industrial Supplies.

Answer the user's question using ONLY the database results below.

RULES:
1. Never invent values or records.
2. 2. If the results are empty, explain what that means
   for the user's specific ERP question.
3. For low-stock questions with empty results, say that
   no products are currently below their reorder level.
4. Explain quantities and amounts clearly.
5. Do not claim that an action was performed.
6. If appropriate, summarize the important findings.
7. Answer strictly from the database results.
8. Never contradict the database results.
9. Never claim values are equal unless the results prove equality.
10. If records exist, report the records accurately.
11. If records are empty, explain that no matching records were found.
12. Do not invent additional records or quantities.
13. Use simple, professional business language.
14. Do not claim that an action was performed.
15. For dispatch discrepancy questions:
    - Use dispatch_items for picked_qty and dispatched_qty.
    - Join dispatches using dispatch_id when order/date details are needed.
    - Join products using product_id when product names are needed.
    - Select picked_qty, dispatched_qty, and their difference.
    - Filter using picked_qty > dispatched_qty when requested.
16. IMPORTANT COLUMN OWNERSHIP:
    - dispatch_items.picked_qty
    - dispatch_items.dispatched_qty
    - dispatch_items.dispatch_id
    - dispatch_items.product_id
    - dispatches.dispatch_id
    - dispatches.so_id
    - dispatches.dispatch_date
    - dispatches.carrier
    - dispatches.tracking_number
    - products.product_id
    - products.product_name

17. Never reference picked_qty or dispatched_qty
    through the products table or its alias.

18. For dispatch discrepancy queries, calculate:
    di.picked_qty - di.dispatched_qty
USER QUESTION:
{user_question}

DATABASE RESULTS:
{data}

ANSWER:
"""

    response = ollama.chat(
        model=MODEL_NAME,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
    )

    answer = response["message"]["content"].strip()

    # Step 4: Return answer and execution details.
    return {
        "success": True,
        "question": user_question,
        "sql": sql,
        "answer": answer,
        "row_count": result["row_count"],
        "records": result["records"],
        "truncated": result["truncated"],
    }


if __name__ == "__main__":
    question = "Show dispatches where picked quantity is greater than dispatched quantity, including product name and quantity difference."

    response = ask_database(question)

    print("\n========== ERP ANSWER ==========")
    print(response.get("answer", response.get("error")))

    print("\n========== RESULT DETAILS ==========")
    print("Success:", response["success"])
    print("Rows:", response.get("row_count", 0))
    print("Records:", response.get("records", []))
