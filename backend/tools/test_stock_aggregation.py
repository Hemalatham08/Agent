
from backend.tools.sql_executor import execute_readonly_sql

sql = """
SELECT
    p.product_id,
    p.product_name,
    p.reorder_level,
    COALESCE(SUM(i.on_hand_qty), 0) AS total_on_hand,
    COALESCE(SUM(i.reserved_qty), 0) AS total_reserved,
    COALESCE(
        SUM(i.on_hand_qty - i.reserved_qty), 0
    ) AS available_stock
FROM products p
LEFT JOIN inventory i
    ON p.product_id = i.product_id
GROUP BY
    p.product_id,
    p.product_name,
    p.reorder_level
ORDER BY p.product_id
LIMIT 100
"""

print(execute_readonly_sql(sql))
