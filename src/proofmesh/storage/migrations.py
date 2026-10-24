import re
from pathlib import Path
import sqlite3

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
MIGRATION_FILE_PATTERN = re.compile(r"^(\d{3})_[a-zA-Z0-9_]+\.sql$")


class IncompatibleSchemaError(RuntimeError):
    """Raised when the database schema version is newer than the application supports."""


class MigrationError(RuntimeError):
    """Raised when a migration fails to apply cleanly."""


def get_current_schema_version(conn: sqlite3.Connection) -> int:
    """Return the database user_version."""
    cursor = conn.execute("PRAGMA user_version;")
    row = cursor.fetchone()
    return int(row[0]) if row else 0


def get_available_migrations() -> list[tuple[int, Path]]:
    """Scan and return sorted list of (version, path) for valid migration files."""
    if not MIGRATIONS_DIR.exists():
        return []

    migrations = []
    for file_path in MIGRATIONS_DIR.glob("*.sql"):
        match = MIGRATION_FILE_PATTERN.match(file_path.name)
        if not match:
            continue
        version = int(match.group(1))
        migrations.append((version, file_path))

    migrations.sort(key=lambda item: item[0])

    # Validate that versions are sequential starting from 1
    for expected_ver, (actual_ver, _) in enumerate(migrations, start=1):
        if expected_ver != actual_ver:
            raise MigrationError(
                f"Non-contiguous migration sequence: expected version {expected_ver}, found {actual_ver}"
            )

    return migrations


def apply_migrations(conn: sqlite3.Connection) -> int:
    """Apply ordered SQL migrations atomically and update user_version.
    
    Refuses databases with newer schema versions than the code supports.
    """
    migrations = get_available_migrations()
    max_supported_version = migrations[-1][0] if migrations else 0
    current_version = get_current_schema_version(conn)

    if current_version > max_supported_version:
        raise IncompatibleSchemaError(
            f"Database schema version {current_version} is newer than max supported version {max_supported_version}."
            " Upgrade ProofMesh to use this database."
        )

    for version, file_path in migrations:
        if version > current_version:
            sql = file_path.read_text(encoding="utf-8")
            statements = [s.strip() for s in sql.split(";") if s.strip()]

            # Execute all statements and bump user_version in one atomic transaction
            conn.execute("BEGIN IMMEDIATE;")
            try:
                for stmt in statements:
                    conn.execute(stmt)
                conn.execute(f"PRAGMA user_version = {version};")
                conn.execute("COMMIT;")
            except Exception as e:
                conn.execute("ROLLBACK;")
                raise MigrationError(
                    f"Failed to apply migration {file_path.name} (version {version}): {e}"
                ) from e

            current_version = version

    return current_version
