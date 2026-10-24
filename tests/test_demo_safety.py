"""Safety and non-destructive behavior tests for ProofMesh Demo.

Validates:
- Demo refuses non-empty target directories lacking the .proofmesh-fixture marker.
- Demo never recursively deletes user directories (e.g. 'config', 'security', or arbitrary folders).
- Demo never overwrites or deletes caller-supplied database files or non-demo files.
- Existing files remain completely intact upon refusal.
- A marked or empty fixture workspace allows execution safely.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
import pytest

from proofmesh.demo import FIXTURE_MARKER, run_seeded_demo


def test_refuse_non_empty_target_without_fixture_marker(tmp_path: Path):
    """Demo must refuse to touch a non-empty directory without .proofmesh-fixture."""
    target_dir = tmp_path / "user_project"
    target_dir.mkdir(parents=True, exist_ok=True)

    user_code = target_dir / "user_script.py"
    user_code.write_text("print('precious user code')\n", encoding="utf-8")

    config_dir = target_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    user_config = config_dir / "custom.toml"
    user_config.write_text("api_key = 'secret'\n", encoding="utf-8")

    db_file = tmp_path / "storage" / "test.db"

    # Must raise ValueError with clear actionable explanation
    with pytest.raises(ValueError) as excinfo:
        run_seeded_demo(target_dir=target_dir, db_path=db_file)

    assert "non-empty" in str(excinfo.value)
    assert FIXTURE_MARKER in str(excinfo.value)

    # Verify user files and directories were NOT deleted or modified
    assert user_code.is_file()
    assert user_code.read_text(encoding="utf-8") == "print('precious user code')\n"
    assert user_config.is_file()
    assert user_config.read_text(encoding="utf-8") == "api_key = 'secret'\n"
    assert not (target_dir / FIXTURE_MARKER).exists()


def test_existing_target_with_fixture_marker_preserves_unrelated_files(tmp_path: Path):
    """When fixture marker is present, demo runs without wiping unrelated caller files."""
    target_dir = tmp_path / "fixture_project"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / FIXTURE_MARKER).write_text("proofmesh-fixture\n", encoding="utf-8")

    # Add an unrelated user directory with files
    unrelated_dir = target_dir / "unrelated_tooling"
    unrelated_dir.mkdir(parents=True, exist_ok=True)
    keep_file = unrelated_dir / "tool.py"
    keep_file.write_text("# Unrelated developer tool\n", encoding="utf-8")

    # Add a custom file in config (demo must not delete config directory or custom file)
    config_dir = target_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    custom_cfg = config_dir / "app_settings.json"
    custom_cfg.write_text('{"keep_me": true}\n', encoding="utf-8")

    db_file = tmp_path / "storage" / "test.db"

    result = run_seeded_demo(target_dir=target_dir, db_path=db_file)
    assert result["status"] == "success"

    # Verify unrelated tooling and config files are completely intact
    assert keep_file.is_file()
    assert keep_file.read_text(encoding="utf-8") == "# Unrelated developer tool\n"
    assert custom_cfg.is_file()
    assert custom_cfg.read_text(encoding="utf-8") == '{"keep_me": true}\n'


def test_refuse_caller_database_with_non_proofmesh_schema(tmp_path: Path):
    """Demo must refuse to overwrite or delete caller-supplied non-ProofMesh database."""
    target_dir = tmp_path / "demo_target"
    db_file = tmp_path / "storage" / "production_user.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)

    # Create caller's own database with user schema and data
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT);")
    conn.execute("INSERT INTO users VALUES (1, 'alice@example.com');")
    conn.commit()
    conn.close()

    with pytest.raises(ValueError) as excinfo:
        run_seeded_demo(target_dir=target_dir, db_path=db_file)

    assert "does not contain ProofMesh schema" in str(excinfo.value)

    # Ensure caller database file was NOT deleted and data is preserved
    assert db_file.is_file()
    verify_conn = sqlite3.connect(db_file)
    row = verify_conn.execute("SELECT email FROM users WHERE id = 1;").fetchone()
    verify_conn.close()
    assert row is not None
    assert row[0] == "alice@example.com"


def test_refuse_caller_database_with_foreign_proofmesh_project(tmp_path: Path):
    """Demo must refuse if database belongs to a different ProofMesh project."""
    target_dir = tmp_path / "demo_target"
    db_file = tmp_path / "storage" / "foreign_pm.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)

    # Create ProofMesh store with foreign project
    from proofmesh.storage.store import ProofMeshStore
    store = ProofMeshStore(db_file)
    store.create_project("my-real-project", root_path=str(tmp_path / "real_repo"))

    with pytest.raises(ValueError) as excinfo:
        run_seeded_demo(target_dir=target_dir, db_path=db_file)

    assert "contains non-demo projects" in str(excinfo.value)
    assert db_file.is_file()


def test_refuse_invalid_sqlite_file_as_db_path(tmp_path: Path):
    """Demo must refuse if db_path exists but is not a valid SQLite database."""
    target_dir = tmp_path / "demo_target"
    db_file = tmp_path / "storage" / "plain_text.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    db_file.write_text("THIS IS NOT SQLITE\n", encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        run_seeded_demo(target_dir=target_dir, db_path=db_file)

    assert "not a valid SQLite database" in str(excinfo.value)
    assert db_file.is_file()
    assert db_file.read_text(encoding="utf-8") == "THIS IS NOT SQLITE\n"
