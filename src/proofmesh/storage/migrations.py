from pathlib import Path
import sqlite3

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def get_current_schema_version(conn: sqlite3.Connection) -> int:
    """Return the database user_version."""
    cursor = conn.execute("PRAGMA user_version;")
    row = cursor.fetchone()
    return int(row[0]) if row else 0


def apply_migrations(conn: sqlite3.Connection) -> int:
    """Apply ordered SQL migrations and update user_version."""
    current_version = get_current_schema_version(conn)
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

    for migration_file in migration_files:
        # Expected file name format: 001_name.sql
        try:
            version = int(migration_file.name.split("_")[0])
        except (ValueError, IndexError):
            continue

        if version > current_version:
            sql = migration_file.read_text(encoding="utf-8")
            with conn:
                conn.executescript(sql)
                conn.execute(f"PRAGMA user_version = {version};")
            current_version = version

    return current_version
