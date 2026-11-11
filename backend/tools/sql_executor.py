
import sqlite3
from pathlib import Path

from backend.tools.sql_security import validate_sql


DB_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "ifive_erp.db"
)

MAX_ROWS = 100
QUERY_TIMEOUT_SECONDS = 5


def execute_readonly_sql(sql):
    """
    Validate and execute one read-only SQL query.
    Returns column names and records.
    """

    # Step 1: Validate the SQL
    is_valid, message = validate_sql(sql)

    if not is_valid:
        return {
            "success": False,
            "error": message,
        }

    connection = None

    try:
        # Step 2: Open database in READ-ONLY mode
        connection = sqlite3.connect(
            f"file:{DB_PATH.as_posix()}?mode=ro",
            uri=True,
            timeout=QUERY_TIMEOUT_SECONDS,
        )

        # Step 3: Set a query execution time limit
        deadline = QUERY_TIMEOUT_SECONDS

        def stop_long_query():
            stop_long_query.calls += 1

            # SQLite invokes this every 1000 virtual machine steps
            return int(stop_long_query.calls > deadline * 1000)

        stop_long_query.calls = 0

        connection.set_progress_handler(
            stop_long_query,
            1000,
        )

        # Step 4: Execute the validated query
        cursor = connection.cursor()
        cursor.execute(sql)

        # Step 5: Read column names
        columns = [
            description[0]
            for description in cursor.description
        ]

        # Step 6: Fetch at most MAX_ROWS + 1 records
        rows = cursor.fetchmany(MAX_ROWS + 1)

        truncated = len(rows) > MAX_ROWS
        rows = rows[:MAX_ROWS]

        # Step 7: Convert records into dictionaries
        records = [
            dict(zip(columns, row))
            for row in rows
        ]

        return {
            "success": True,
            "columns": columns,
            "records": records,
            "row_count": len(records),
            "truncated": truncated,
        }

    except sqlite3.Error as error:
        return {
            "success": False,
            "error": f"Database execution error: {error}",
        }

    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    test_query = """
        SELECT product_id, product_name
        FROM products
        LIMIT 5
    """

    result = execute_readonly_sql(test_query)

    print("\n========== SQL EXECUTION TEST ==========")
    print(result)
