import sqlite3
from pathlib import Path

from sqlalchemy import text

from database import SessionLocal, ensure_database


ROOT = Path(__file__).resolve().parent
SQLITE_PATH = ROOT / "reima.db"
TABLES = [
    "company",
    "app_user",
    "approval_flow",
    "approval_step",
    "approval_rule",
    "expense",
    "expense_approval",
    "user_session",
    "email_verification_token",
    "password_reset_token",
    "notification",
    "audit_log",
]


def main() -> None:
    if not SQLITE_PATH.exists():
        raise FileNotFoundError(f"SQLite source not found: {SQLITE_PATH}")

    ensure_database()

    sqlite_connection = sqlite3.connect(SQLITE_PATH)
    sqlite_connection.row_factory = sqlite3.Row

    with SessionLocal() as session:
        for table in reversed(TABLES):
            session.execute(text(f"DELETE FROM {table}"))
        session.commit()

        for table in TABLES:
            rows = sqlite_connection.execute(f"SELECT * FROM {table}").fetchall()
            if not rows:
                continue
            columns = rows[0].keys()
            placeholders = ", ".join(f":{column}" for column in columns)
            insert_sql = text(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
            )
            session.execute(insert_sql, [dict(row) for row in rows])
            session.commit()

        # Reset PostgreSQL sequences to the imported max ids.
        for table in TABLES:
            id_exists = sqlite_connection.execute(
                f"SELECT COUNT(*) FROM pragma_table_info('{table}') WHERE name = 'id'"
            ).fetchone()[0]
            if not id_exists:
                continue
            max_id = sqlite_connection.execute(f"SELECT COALESCE(MAX(id), 1) FROM {table}").fetchone()[0]
            session.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence(:table_name, 'id'), :max_id, true)"
                ),
                {"table_name": table, "max_id": max_id},
            )
        session.commit()

    sqlite_connection.close()
    print("SQLite data migrated into PostgreSQL successfully.")


if __name__ == "__main__":
    main()
