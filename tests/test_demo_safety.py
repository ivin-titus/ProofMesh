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


def test_refuse_marked_target_with_foreign_math_service(tmp_path: Path):
    """Demo must refuse if marked target contains foreign src/math_service.py."""
    target_dir = tmp_path / "fixture_project"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / FIXTURE_MARKER).write_text("proofmesh-fixture\n", encoding="utf-8")

    src_dir = target_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    foreign_math = src_dir / "math_service.py"
    foreign_math.write_text("# Foreign user math code\ndef add(a, b): return a * b\n", encoding="utf-8")

    db_file = tmp_path / "storage" / "test.db"

    with pytest.raises(ValueError) as excinfo:
        run_seeded_demo(target_dir=target_dir, db_path=db_file)

    assert "foreign content" in str(excinfo.value)
    assert "src/math_service.py" in str(excinfo.value)
    # File must be preserved byte-for-byte
    assert foreign_math.read_text(encoding="utf-8") == "# Foreign user math code\ndef add(a, b): return a * b\n"


def test_refuse_marked_target_with_foreign_test_math_or_pytest_ini(tmp_path: Path):
    """Demo must refuse if marked target contains foreign tests/test_math.py or pytest.ini."""
    target_dir = tmp_path / "fixture_project"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / FIXTURE_MARKER).write_text("proofmesh-fixture\n", encoding="utf-8")

    pytest_ini = target_dir / "pytest.ini"
    pytest_ini.write_text("[pytest]\naddopts = --custom-flag\n", encoding="utf-8")

    db_file = tmp_path / "storage" / "test.db"

    with pytest.raises(ValueError) as excinfo:
        run_seeded_demo(target_dir=target_dir, db_path=db_file)

    assert "foreign content" in str(excinfo.value)
    assert "pytest.ini" in str(excinfo.value)
    assert pytest_ini.read_text(encoding="utf-8") == "[pytest]\naddopts = --custom-flag\n"


def test_refuse_marked_target_with_foreign_security_toml(tmp_path: Path):
    """Demo must refuse if marked target contains foreign config/security.toml before execution."""
    target_dir = tmp_path / "fixture_project"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / FIXTURE_MARKER).write_text("proofmesh-fixture\n", encoding="utf-8")

    config_dir = target_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    sec_file = config_dir / "security.toml"
    sec_file.write_text("user_auth = 'real_secret'\n", encoding="utf-8")

    db_file = tmp_path / "storage" / "test.db"

    with pytest.raises(ValueError) as excinfo:
        run_seeded_demo(target_dir=target_dir, db_path=db_file)

    assert "foreign content" in str(excinfo.value)
    assert "config/security.toml" in str(excinfo.value)
    assert sec_file.read_text(encoding="utf-8") == "user_auth = 'real_secret'\n"


def test_refuse_caller_database_with_same_project_id_but_foreign_task(tmp_path: Path):
    """Demo must refuse if database has project ID seeded-demo-project with foreign tasks."""
    target_dir = tmp_path / "demo_target"
    db_file = tmp_path / "storage" / "colliding_pm.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)

    from proofmesh.storage.store import ProofMeshStore
    store = ProofMeshStore(db_file)
    store.create_project("seeded-demo-project", root_path=str(tmp_path / "user_repo"))
    conn = store.get_connection()
    conn.execute("INSERT INTO tasks (task_id, project_id, created_at) VALUES ('task-user-foreign', 'seeded-demo-project', '2026-01-01');")
    conn.commit()
    conn.close()

    with pytest.raises(ValueError) as excinfo:
        run_seeded_demo(target_dir=target_dir, db_path=db_file)

    assert "non-demo tasks" in str(excinfo.value)


def test_repeatable_demo_run_preserves_valid_fixture(tmp_path: Path):
    """Demo must be repeatable in the same fixture workspace without crashing."""
    target_dir = tmp_path / "repeat_fixture"
    db_file = tmp_path / "storage" / "repeat.db"

    res1 = run_seeded_demo(target_dir=target_dir, db_path=db_file)
    assert res1["status"] == "success"
    assert res1["session"].integration_status.value == "unguarded"

    # Second run against the same fixture directory and DB
    res2 = run_seeded_demo(target_dir=target_dir, db_path=db_file)
    assert res2["status"] == "success"
    assert res2["session"].integration_status.value == "unguarded"

