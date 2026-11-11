
import sqlite3
from pathlib import Path

import sqlglot
from sqlglot import exp


DB_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "ifive_erp.db"
)


def get_allowed_tables():
    """
    Return the actual ERP tables from the database.
    SQLite internal tables are excluded.
    """
    connection = sqlite3.connect(
        f"file:{DB_PATH.as_posix()}?mode=ro",
        uri=True,
    )

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
        """)

        return {
            row[0].lower()
            for row in cursor.fetchall()
        }

    finally:
        connection.close()


def validate_sql(sql):
    """
    Validate AI-generated SQL before database execution.

    Only one SELECT query is permitted.
    """

    if not isinstance(sql, str) or not sql.strip():
        return False, "SQL query is empty."

    try:
        # Parse SQL using SQLite syntax
        statements = sqlglot.parse(sql, read="sqlite")

    except sqlglot.errors.ParseError as error:
        return False, f"SQL syntax error: {error}"

    # Reject multiple statements
    if len(statements) != 1:
        return False, "Only one SQL statement is permitted."

    statement = statements[0]

    # Only SELECT queries are allowed
    if not isinstance(statement, exp.Select):
        return False, "Only SELECT queries are permitted."

    # Retrieve permitted ERP table names
    allowed_tables = get_allowed_tables()

    # Check every table referenced by the query
    for table in statement.find_all(exp.Table):
        table_name = table.name.lower()

        if table_name not in allowed_tables:
            return False, (
                f"Table '{table_name}' is not permitted."
            )

    return True, "SQL query passed validation."
