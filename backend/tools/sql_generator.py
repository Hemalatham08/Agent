
import ollama

from backend.tools.schema_context import get_database_schema_context


MODEL_NAME = "llama3.2"


def generate_sql(user_question):
    schema_context = get_database_schema_context()

    prompt = f"""
You are an expert SQLite SQL developer for ABC Fasteners & Industrial Supplies.

Your task is to convert the user's ERP question into one SQL query.

DATABASE SCHEMA:
{schema_context}

RULES:

RULES:
1. Generate exactly one SQLite SELECT query.
2. Use only actual tables and columns in the supplied schema.
3. Never invent column names or table names.
4. Never generate INSERT, UPDATE, DELETE, DROP, ALTER, or other write operations.
5. Use correct JOIN conditions based on foreign keys.
6. Return only SQL, without markdown or explanations.
7. For low-stock questions, ALWAYS use products and inventory.
8. Low stock means total available stock across all warehouses
   is less than products.reorder_level.
9. Available stock means on_hand_qty minus reserved_qty.
10. Aggregate inventory using SUM and GROUP BY product_id.
11. Do not use purchase_orders or purchase_order_items
    for inventory or reorder-level questions.
12. For low stock, use this SQL structure:

    SELECT p.product_id, p.product_name, p.reorder_level,
           COALESCE(SUM(i.on_hand_qty-i.reserved_qty),0)
           AS available_stock
    FROM products p
    LEFT JOIN inventory i ON p.product_id=i.product_id
    GROUP BY p.product_id,p.product_name,p.reorder_level
    HAVING COALESCE(SUM(i.on_hand_qty-i.reserved_qty),0)
           < p.reorder_level
    LIMIT 100

13. Use LIMIT 100 for ordinary detail queries.
14. Do not use columns that are not present in the schema.


USER QUESTION:
{user_question}

SQL QUERY:
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

    sql = response["message"]["content"].strip()

    # Remove markdown code fences if the model adds them.
    if sql.startswith("```"):
        sql = sql.replace("```sql", "").replace("```", "").strip()

    return sql


if __name__ == "__main__":
    question = "Show products whose stock is below reorder level."

    generated_sql = generate_sql(question)

    print("\n========== GENERATED SQL ==========")
    print(generated_sql)
