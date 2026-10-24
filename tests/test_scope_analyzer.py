"""Tests for ProofMesh scope analyzer."""

from datetime import datetime, timezone
import hashlib
import pytest

from proofmesh.core.scope_analyzer import analyze_scope
from proofmesh.models import (
    FileFingerprint,
    RepoSnapshot,
    ScopeChangeType,
    ScopePolicy,
)


def _make_digest(seed: str) -> str:
    """Generate a valid sha256: hex digest string from a seed string."""
    return f"sha256:{hashlib.sha256(seed.encode('utf-8')).hexdigest()}"


def _make_file(path: str, content: str = "default_content") -> FileFingerprint:
    """Helper to create a valid FileFingerprint with deterministic hash and size."""
    raw = content.encode("utf-8")
    return FileFingerprint(
        path=path,
        sha256=_make_digest(content),
        size_bytes=len(raw),
        is_tracked=True,
    )


def _make_snapshot(
    snapshot_id_seed: str,
    files: tuple[FileFingerprint, ...] = (),
    git_commit: str | None = "0123456789abcdef",
) -> RepoSnapshot:
    """Helper to construct a valid RepoSnapshot."""
    return RepoSnapshot(
        snapshot_id=_make_digest(snapshot_id_seed),
        repo_root="/repo",
        git_commit=git_commit,
        git_dirty=False,
        files=files,
        captured_at=datetime.now(timezone.utc),
    )


class TestScopeAnalyzer:
    """Comprehensive test suite for analyze_scope function."""

    def test_identical_snapshots_have_no_changes(self) -> None:
        """When baseline and current have identical files, no changes or violations are reported."""
        file1 = _make_file("src/main.py", "print('hello')")
        file2 = _make_file("tests/test_main.py", "assert True")
        baseline = _make_snapshot("snap1", (file1, file2))
        current = _make_snapshot("snap2", (file1, file2))
        policy = ScopePolicy(allow_paths=("src/**", "tests/**"))

        result = analyze_scope(baseline, current, policy)

        assert result.baseline_snapshot_id == baseline.snapshot_id
        assert result.current_snapshot_id == current.snapshot_id
        assert result.changes == ()
        assert result.findings == ()
        assert result.total_changed_files == 0
        assert result.exceeded_file_limit is False
        assert result.has_violations is False

    def test_allowlisted_added_file(self) -> None:
        """Adding a file matching allow_paths is marked ADDED and allowed with no violations."""
        file1 = _make_file("src/existing.py")
        file2 = _make_file("src/new.py", "new_content")
        baseline = _make_snapshot("snap_base", (file1,))
        current = _make_snapshot("snap_curr", (file1, file2))
        policy = ScopePolicy(allow_paths=("src/**",))

        result = analyze_scope(baseline, current, policy)

        assert len(result.changes) == 1
        change = result.changes[0]
        assert change.path == "src/new.py"
        assert change.change_type == ScopeChangeType.ADDED
        assert change.old_sha256 is None
        assert change.new_sha256 == file2.sha256

        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding.path == "src/new.py"
        assert finding.allowed is True
        assert finding.restricted is False
        assert finding.reason == "Path is allowlisted"

        assert result.total_changed_files == 1
        assert result.exceeded_file_limit is False
        assert result.has_violations is False

    def test_allowlisted_modified_file(self) -> None:
        """Modifying a file matching allow_paths is marked MODIFIED and allowed."""
        old_file = _make_file("src/service.py", "v1")
        new_file = _make_file("src/service.py", "v2")
        baseline = _make_snapshot("base", (old_file,))
        current = _make_snapshot("curr", (new_file,))
        policy = ScopePolicy(allow_paths=("src/**",))

        result = analyze_scope(baseline, current, policy)

        assert len(result.changes) == 1
        change = result.changes[0]
        assert change.path == "src/service.py"
        assert change.change_type == ScopeChangeType.MODIFIED
        assert change.old_sha256 == old_file.sha256
        assert change.new_sha256 == new_file.sha256

        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding.path == "src/service.py"
        assert finding.allowed is True
        assert finding.restricted is False
        assert finding.reason == "Path is allowlisted"
        assert result.has_violations is False

    def test_allowlisted_deleted_file(self) -> None:
        """Deleting a file matching allow_paths is marked DELETED and allowed."""
        file1 = _make_file("tests/old_test.py", "def test_old(): pass")
        baseline = _make_snapshot("base", (file1,))
        current = _make_snapshot("curr", ())
        policy = ScopePolicy(allow_paths=("tests/**",))

        result = analyze_scope(baseline, current, policy)

        assert len(result.changes) == 1
        change = result.changes[0]
        assert change.path == "tests/old_test.py"
        assert change.change_type == ScopeChangeType.DELETED
        assert change.old_sha256 == file1.sha256
        assert change.new_sha256 is None

        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding.path == "tests/old_test.py"
        assert finding.allowed is True
        assert finding.restricted is False
        assert finding.reason == "Path is allowlisted"
        assert result.has_violations is False

    def test_out_of_scope_path_detected(self) -> None:
        """Files changed outside allow_paths are marked allowed=False and flag violations."""
        file1 = _make_file("src/app.py", "v1")
        file2 = _make_file("docs/architecture.md", "new docs")
        baseline = _make_snapshot("base", (file1,))
        current = _make_snapshot("curr", (file1, file2))
        policy = ScopePolicy(allow_paths=("src/**",))

        result = analyze_scope(baseline, current, policy)

        assert len(result.changes) == 1
        assert result.changes[0].path == "docs/architecture.md"

        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding.path == "docs/architecture.md"
        assert finding.allowed is False
        assert finding.restricted is False
        assert finding.reason == "Path 'docs/architecture.md' is not covered by allow_paths"

        assert result.has_violations is True

    def test_restricted_path_detected(self) -> None:
        """Changes matching restricted_paths are flagged as restricted even if in allow_paths."""
        secret_file = _make_file("src/secrets/key.json", '{"key": "xyz"}')
        baseline = _make_snapshot("base", ())
        current = _make_snapshot("curr", (secret_file,))
        policy = ScopePolicy(
            allow_paths=("src/**",),
            restricted_paths=("src/secrets/**", "*.json"),
        )

        result = analyze_scope(baseline, current, policy)

        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding.path == "src/secrets/key.json"
        assert finding.allowed is False
        assert finding.restricted is True
        assert finding.reason == "Path 'src/secrets/key.json' matches restricted pattern 'src/secrets/**'"
        assert result.has_violations is True

    def test_deleted_file_in_restricted_path_detected(self) -> None:
        """Deleting a file in a restricted path is flagged as restricted and violates policy."""
        migration = _make_file("database/migrations/0001_initial.sql", "CREATE TABLE users;")
        baseline = _make_snapshot("base", (migration,))
        current = _make_snapshot("curr", ())
        policy = ScopePolicy(
            allow_paths=("src/**", "database/**"),
            restricted_paths=("database/migrations/**",),
        )

        result = analyze_scope(baseline, current, policy)

        assert len(result.changes) == 1
        assert result.changes[0].change_type == ScopeChangeType.DELETED

        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding.path == "database/migrations/0001_initial.sql"
        assert finding.allowed is False
        assert finding.restricted is True
        assert (
            finding.reason
            == "Path 'database/migrations/0001_initial.sql' matches restricted pattern 'database/migrations/**'"
        )
        assert result.has_violations is True

    def test_nested_paths_and_glob_wildcards(self) -> None:
        """Glob wildcards like src/**, *.py, and config/*.toml match accurately."""
        py_root = _make_file("setup.py", "version 1")
        py_deep = _make_file("src/pkg/sub/module.py", "def fn(): pass")
        config_toml = _make_file("config/database.toml", "[db]")
        unmatched = _make_file("deploy/k8s.yaml", "kind: Pod")

        baseline = _make_snapshot("base", ())
        current = _make_snapshot("curr", (py_root, py_deep, config_toml, unmatched))
        policy = ScopePolicy(
            allow_paths=("src/**", "*.py", "config/*.toml"),
            restricted_paths=(".git/**",),
        )

        result = analyze_scope(baseline, current, policy)

        # Changes are sorted by path
        paths = [c.path for c in result.changes]
        assert paths == ["config/database.toml", "deploy/k8s.yaml", "setup.py", "src/pkg/sub/module.py"]

        findings_by_path = {f.path: f for f in result.findings}
        assert findings_by_path["config/database.toml"].allowed is True
        assert findings_by_path["config/database.toml"].reason == "Path is allowlisted"

        assert findings_by_path["deploy/k8s.yaml"].allowed is False
        assert findings_by_path["deploy/k8s.yaml"].reason == "Path 'deploy/k8s.yaml' is not covered by allow_paths"

        assert findings_by_path["setup.py"].allowed is True
        assert findings_by_path["setup.py"].reason == "Path is allowlisted"

        assert findings_by_path["src/pkg/sub/module.py"].allowed is True
        assert findings_by_path["src/pkg/sub/module.py"].reason == "Path is allowlisted"

        assert result.has_violations is True  # due to deploy/k8s.yaml

    def test_file_limit_within_threshold(self) -> None:
        """Total changed files equal to or below max_changed_files does not exceed limit."""
        f1 = _make_file("src/a.py", "a")
        f2 = _make_file("src/b.py", "b")
        baseline = _make_snapshot("base", ())
        current = _make_snapshot("curr", (f1, f2))
        policy = ScopePolicy(allow_paths=("src/**",), max_changed_files=2)

        result = analyze_scope(baseline, current, policy)

        assert result.total_changed_files == 2
        assert result.exceeded_file_limit is False
        assert result.has_violations is False

    def test_file_limit_exceeded(self) -> None:
        """When total changed files exceed max_changed_files, exceeded_file_limit and has_violations are True."""
        f1 = _make_file("src/a.py", "a")
        f2 = _make_file("src/b.py", "b")
        f3 = _make_file("src/c.py", "c")
        baseline = _make_snapshot("base", ())
        current = _make_snapshot("curr", (f1, f2, f3))
        policy = ScopePolicy(allow_paths=("src/**",), max_changed_files=2)

        result = analyze_scope(baseline, current, policy)

        assert result.total_changed_files == 3
        assert result.exceeded_file_limit is True
        # Even though all individual findings are allowlisted, exceeding file limit causes violations
        assert all(f.allowed for f in result.findings)
        assert result.has_violations is True

    def test_empty_policy_behavior(self) -> None:
        """When ScopePolicy has empty allow_paths, all changed files are rejected (fail closed)."""
        f1 = _make_file("anywhere/file.txt", "content")
        f2 = _make_file("scripts/run.sh", "#!/bin/bash")
        baseline = _make_snapshot("base", (f1,))
        current = _make_snapshot("curr", (_make_file("anywhere/file.txt", "changed"), f2))
        policy = ScopePolicy()

        result = analyze_scope(baseline, current, policy)

        assert result.total_changed_files == 2
        assert result.exceeded_file_limit is False
        assert result.has_violations is True
        for f in result.findings:
            assert f.allowed is False
            assert f.restricted is False
            assert "is not covered by allow_paths" in f.reason

    def test_changes_and_findings_are_sorted_by_path(self) -> None:
        """Path changes and findings are sorted lexicographically by path regardless of snapshot order."""
        fz = _make_file("z_last.py", "z")
        fa = _make_file("a_first.py", "a")
        fm = _make_file("m_middle.py", "m")
        # In snapshot, order is intentionally unsorted
        baseline = _make_snapshot("base", (fz, fa, fm))
        current = _make_snapshot("curr", ())
        policy = ScopePolicy()

        result = analyze_scope(baseline, current, policy)

        assert [c.path for c in result.changes] == ["a_first.py", "m_middle.py", "z_last.py"]
        assert [f.path for f in result.findings] == ["a_first.py", "m_middle.py", "z_last.py"]

    def test_unchanged_files_are_ignored(self) -> None:
        """Files present in both snapshots with matching sha256 are excluded from changes."""
        same1 = _make_file("src/same1.py", "same_content_1")
        same2 = _make_file("src/same2.py", "same_content_2")
        changed = _make_file("src/changed.py", "old")
        baseline = _make_snapshot("base", (same1, same2, changed))
        current = _make_snapshot("curr", (same1, same2, _make_file("src/changed.py", "new")))
        policy = ScopePolicy(allow_paths=("src/**",))

        result = analyze_scope(baseline, current, policy)

        assert result.total_changed_files == 1
        assert [c.path for c in result.changes] == ["src/changed.py"]
        assert [f.path for f in result.findings] == ["src/changed.py"]
        assert result.has_violations is False

    def test_invalid_argument_types_raise_type_error(self) -> None:
        """Passing non-RepoSnapshot or non-ScopePolicy raises explicit TypeError."""
        snap = _make_snapshot("base", ())
        policy = ScopePolicy()

        with pytest.raises(TypeError, match="baseline must be a RepoSnapshot"):
            analyze_scope("not_a_snapshot", snap, policy)  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="current must be a RepoSnapshot"):
            analyze_scope(snap, "not_a_snapshot", policy)  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="policy must be a ScopePolicy"):
            analyze_scope(snap, snap, "not_a_policy")  # type: ignore[arg-type]

    def test_multiple_violations_combined(self) -> None:
        """Simultaneous restricted path and out-of-scope path produce accurate individual findings."""
        f_allowed = _make_file("src/feature.py", "code")
        f_out = _make_file("infra/terraform.tf", "provider")
        f_restr = _make_file(".github/workflows/ci.yml", "name: CI")

        baseline = _make_snapshot("base", ())
        current = _make_snapshot("curr", (f_allowed, f_out, f_restr))
        policy = ScopePolicy(
            allow_paths=("src/**",),
            restricted_paths=(".github/**",),
        )

        result = analyze_scope(baseline, current, policy)

        assert result.total_changed_files == 3
        assert result.has_violations is True

        findings_map = {f.path: f for f in result.findings}
        assert findings_map["src/feature.py"].allowed is True
        assert findings_map["src/feature.py"].restricted is False

        assert findings_map["infra/terraform.tf"].allowed is False
        assert findings_map["infra/terraform.tf"].restricted is False
        assert findings_map["infra/terraform.tf"].reason == "Path 'infra/terraform.tf' is not covered by allow_paths"

        assert findings_map[".github/workflows/ci.yml"].allowed is False
        assert findings_map[".github/workflows/ci.yml"].restricted is True
        assert (
            findings_map[".github/workflows/ci.yml"].reason
            == "Path '.github/workflows/ci.yml' matches restricted pattern '.github/**'"
        )
