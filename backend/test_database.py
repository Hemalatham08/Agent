import sqlite3

connection = sqlite3.connect(
    "backend/data/ifive_erp.db"
)

connection.row_factory = sqlite3.Row

products = connection.execute(
    "SELECT * FROM products"
).fetchall()

print("PRODUCT CATALOGUE")

for product in products:
    print(dict(product))

connection.close()