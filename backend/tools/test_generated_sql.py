
from backend.tools.sql_executor import execute_readonly_sql

sql = """
SELECT
    d.dispatch_id,
    d.so_id,
    d.dispatch_date,
    p.product_name,
    di.picked_qty,
    di.dispatched_qty,
    di.picked_qty - di.dispatched_qty AS quantity_difference
FROM dispatch_items di
JOIN dispatches d
    ON di.dispatch_id = d.dispatch_id
JOIN products p
    ON di.product_id = p.product_id
WHERE di.picked_qty > di.dispatched_qty
LIMIT 100
"""

print(execute_readonly_sql(sql))
