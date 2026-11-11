
import sqlite3
from pathlib import Path


DB_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "ifive_erp.db"
)


def get_database_schema_context():
    connection = sqlite3.connect(DB_PATH)
    cursor = connection.cursor()

    try:
        # Discover all ERP tables
        cursor.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """)

        tables = cursor.fetchall()

        schema_context = []

        for (table_name,) in tables:
            schema_context.append(f"\nTABLE: {table_name}")

            # Get table columns
            cursor.execute(
                f'PRAGMA table_info("{table_name}")'
            )

            columns = cursor.fetchall()

            schema_context.append("Columns:")

            for column in columns:
                column_name = column[1]
                column_type = column[2]
                is_primary_key = column[5]

                column_description = (
                    f"- {column_name} ({column_type})"
                )

                if is_primary_key:
                    column_description += " PRIMARY KEY"

                schema_context.append(column_description)

            # Get table relationships
            cursor.execute(
                f'PRAGMA foreign_key_list("{table_name}")'
            )

            foreign_keys = cursor.fetchall()

            if foreign_keys:
                schema_context.append("Relationships:")

                for foreign_key in foreign_keys:
                    referenced_table = foreign_key[2]
                    source_column = foreign_key[3]
                    referenced_column = foreign_key[4]

                    schema_context.append(
                        f"- {source_column} references "
                        f"{referenced_table}.{referenced_column}"
                    )

        return "\n".join(schema_context)

    finally:
        connection.close()


if __name__ == "__main__":
    print(get_database_schema_context())
