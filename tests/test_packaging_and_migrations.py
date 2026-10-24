import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import zipfile
import pytest

from proofmesh.storage.migrations import (
    IncompatibleSchemaError,
    MigrationError,
    apply_migrations,
    get_available_migrations,
    get_current_schema_version,
)
from proofmesh.storage.store import ProofMeshStore


def get_or_build_wheel() -> Path:
    """Retrieve the built wheel or build one dynamically if absent or stale.
    
    This ensures packaging tests are fully reproducible on a clean clone without
    requiring a manual pre-build step.
    """
    repo_root = Path(__file__).parent.parent
    dist_dir = repo_root / "dist"
    wheels = list(dist_dir.glob("proofmesh-*.whl")) if dist_dir.exists() else []

    if wheels:
        return sorted(wheels)[-1]

    # In a clean checkout without dist/, build a wheel
    dist_dir.mkdir(parents=True, exist_ok=True)
    uv_bin = repo_root / ".venv" / "bin" / "uv"
    if not uv_bin.exists():
        uv_bin = repo_root / ".venv314" / "bin" / "uv"

    env = os.environ.copy()
    env["UV_CACHE_DIR"] = "/tmp/uv_cache"
    env["UV_PYTHON_INSTALL_DIR"] = "/tmp/uv_python"

    if uv_bin.exists():
        cmd = [
            str(uv_bin),
            "build",
            "--wheel",
            "--out-dir",
            str(dist_dir),
            str(repo_root),
        ]
    else:
        cmd = [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "-w",
            str(dist_dir),
            str(repo_root),
        ]

    subprocess.run(cmd, env=env, check=True, capture_output=True)
    built_wheels = sorted(dist_dir.glob("proofmesh-*.whl"))
    assert built_wheels, f"Failed to build wheel into {dist_dir}"
    return built_wheels[-1]


def test_wheel_contains_migration_sql_and_default_policy():
    """Verify built wheel package explicitly includes migrations/001_init.sql and resources/default-policy.toml."""
    latest_wheel = get_or_build_wheel()
    with zipfile.ZipFile(latest_wheel, "r") as zf:
        namelist = zf.namelist()
        assert "proofmesh/storage/migrations/001_init.sql" in namelist, (
            f"001_init.sql missing from wheel: {namelist}"
        )
        assert "proofmesh/resources/default-policy.toml" in namelist, (
            f"default-policy.toml missing from wheel: {namelist}"
        )


def test_installed_wheel_migration_execution(tmp_path: Path):
    """Verify that an installed wheel outside the repo checkout can locate and run migrations."""
    latest_wheel = get_or_build_wheel()

    # Target directory for isolated installation
    target_install = tmp_path / "site_packages"
    target_install.mkdir()

    # Unpack wheel directly into isolated site_packages
    with zipfile.ZipFile(latest_wheel, "r") as zf:
        zf.extractall(target_install)

    # Run Python in a subprocess with ONLY the target_install directory in PYTHONPATH
    db_file = tmp_path / "installed_wheel_test.db"
    script = f"""
import sys
from proofmesh.storage import ProofMeshStore
import sqlite3

store = ProofMeshStore(r'{db_file}')
conn = sqlite3.connect(r'{db_file}')
version = conn.execute("PRAGMA user_version;").fetchone()[0]
assert version == 1, f"Expected version 1, got {{version}}"

# Verify table created
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
assert "task_revisions" in tables
print("INSTALLED_WHEEL_MIGRATION_SUCCESS")
"""
    python_bin = sys.executable
    env = {
        "PYTHONPATH": str(target_install),
        "PATH": "/usr/bin:/bin",
    }
    result = subprocess.run(
        [python_bin, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "INSTALLED_WHEEL_MIGRATION_SUCCESS" in result.stdout


def test_installed_wheel_default_policy_execution(tmp_path: Path):
    """Verify that an installed wheel outside the repo checkout loads the packaged default policy with gates."""
    latest_wheel = get_or_build_wheel()

    target_install = tmp_path / "site_packages_policy"
    target_install.mkdir()

    with zipfile.ZipFile(latest_wheel, "r") as zf:
        zf.extractall(target_install)

    script = """
import sys
from proofmesh.config import get_default_policy

policy = get_default_policy()
assert policy is not None
assert policy.schema_version == 1
assert policy.budget.max_retries == 3
assert policy.budget.max_continuation_steps == 10
assert policy.scope.default_allow_paths == ("src/**", "tests/**")
assert "test" in policy.gates, f"test gate missing from packaged policy: {list(policy.gates.keys())}"
test_gate = policy.gates["test"]
assert test_gate.provider == "pytest"
assert test_gate.mandatory is True
assert "lint" in policy.gates
assert policy.gates["lint"].provider == "ruff"
print("INSTALLED_WHEEL_POLICY_SUCCESS")
"""
    python_bin = sys.executable
    env = {
        "PYTHONPATH": str(target_install),
        "PATH": "/usr/bin:/bin",
    }
    result = subprocess.run(
        [python_bin, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "INSTALLED_WHEEL_POLICY_SUCCESS" in result.stdout


def test_packaged_policy_matches_repo_sample():
    """Ensure repository sample config/default-policy.toml matches packaged resource."""
    repo_root = Path(__file__).parent.parent
    repo_sample = (repo_root / "config" / "default-policy.toml").read_text(encoding="utf-8")
    packaged_resource = (
        repo_root / "src" / "proofmesh" / "resources" / "default-policy.toml"
    ).read_text(encoding="utf-8")
    assert repo_sample == packaged_resource, (
        "Sample config/default-policy.toml has drifted from src/proofmesh/resources/default-policy.toml"
    )


def test_rejection_of_future_schema_version():
    """Verify that a database with a schema version newer than supported is rejected."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA user_version = 99;")
    with pytest.raises(IncompatibleSchemaError) as exc:
        apply_migrations(conn)
    assert "newer than max supported" in str(exc.value)


def test_atomic_migration_rollback_on_failure(tmp_path: Path, monkeypatch):
    """Verify that a failing migration rolls back all statements and does not bump user_version."""
    conn = sqlite3.connect(":memory:", isolation_level=None)

    # First apply valid migrations
    apply_migrations(conn)
    assert get_current_schema_version(conn) == 1

    # Create a mock failing migration file 002_fail.sql
    mock_migrations_dir = tmp_path / "mock_migrations"
    mock_migrations_dir.mkdir()
    (mock_migrations_dir / "001_init.sql").write_text(
        "CREATE TABLE IF NOT EXISTS test_t1 (id INT);", encoding="utf-8"
    )
    # 002 has valid statement followed by a syntax error
    (mock_migrations_dir / "002_fail.sql").write_text(
        "CREATE TABLE test_partial (id INT); INVALID SQL SYNTAX HERE;", encoding="utf-8"
    )

    monkeypatch.setattr("proofmesh.storage.migrations.MIGRATIONS_DIR", mock_migrations_dir)

    with pytest.raises(MigrationError):
        apply_migrations(conn)

    # user_version must remain 1 (not bumped)
    assert get_current_schema_version(conn) == 1

    # Partial table test_partial must NOT exist (rolled back)
    tables = [
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
    ]
    assert "test_partial" not in tables
