
import sqlite3
from pathlib import Path

# Locate the ERP database automatically
DB_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "ifive_erp.db"
)


def inspect_database_schema():
    connection = sqlite3.connect(DB_PATH)
    cursor = connection.cursor()

    try:
        # Discover every table automatically
        cursor.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """)

        tables = cursor.fetchall()

        print("\n========== ERP DATABASE SCHEMA ==========")

        for (table_name,) in tables:
            print(f"\n========== TABLE: {table_name} ==========")

            # Read columns and their properties
            cursor.execute(
                f'PRAGMA table_info("{table_name}")'
            )

            columns = cursor.fetchall()

            for column in columns:
                column_name = column[1]
                column_type = column[2]
                is_primary_key = column[5]

                print(
                    f"Column: {column_name}"
                    f" | Type: {column_type}"
                    f" | Primary Key: {bool(is_primary_key)}"
                )

            # Read relationships between tables
            cursor.execute(
                f'PRAGMA foreign_key_list("{table_name}")'
            )

            foreign_keys = cursor.fetchall()

            for foreign_key in foreign_keys:
                print(
                    "Relationship:",
                    foreign_key[3],
                    "->",
                    foreign_key[2],
                    "(" + foreign_key[4] + ")"
                )

    finally:
        connection.close()


if __name__ == "__main__":
    inspect_database_schema()
