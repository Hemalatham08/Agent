
from tools.sql_security import validate_sql


test_queries = [
    # Safe queries
    ("SELECT * FROM products", True),
    (
        "SELECT product_name FROM products "
        "WHERE reorder_level > 100",
        True,
    ),
    (
        "SELECT p.product_name "
        "FROM products p "
        "JOIN inventory i ON p.product_id = i.product_id",
        True,
    ),

    # Unsafe queries
    ("DELETE FROM products", False),
    ("UPDATE inventory SET reserved_qty = 0", False),
    ("DROP TABLE products", False),
    ("INSERT INTO products VALUES ('X')", False),
    ("PRAGMA table_info(products)", False),
    ("SELECT * FROM sqlite_master", False),

    # Multiple statements
    ("SELECT * FROM products; DELETE FROM products", False),

    # Unknown table
    ("SELECT * FROM secret_table", False),
]


print("\n========== SQL SECURITY TESTS ==========\n")

passed = 0
failed = 0

for sql, expected in test_queries:
    valid, message = validate_sql(sql)

    test_passed = valid == expected

    if test_passed:
        passed += 1
        status = "PASS"
    else:
        failed += 1
        status = "FAIL"

    print(f"{status}: {sql}")
    print(f"  Result: {message}\n")

print("---------------------------------------")
print(f"Passed: {passed}")
print(f"Failed: {failed}")
print("---------------------------------------")
