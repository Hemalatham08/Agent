
import sqlite3
from pathlib import Path

DB_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "ifive_erp.db"
)

connection = sqlite3.connect(DB_PATH)
cursor = connection.cursor()

tables = [
    "quality_inspections",
    "invoices",
    "payments"
]

for table in tables:
    print(f"\n========== {table.upper()} ==========")

    cursor.execute(f"PRAGMA table_info({table})")

    columns = cursor.fetchall()

    for column in columns:
        print(
            "Column:", column[1],
            "| Type:", column[2]
        )

connection.close()
