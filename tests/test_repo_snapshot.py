from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import subprocess
import pytest

from proofmesh.core.repo_snapshot import capture_snapshot, DEFAULT_EXCLUDE_PATTERNS
from proofmesh.models import FileFingerprint, RepoSnapshot
from proofmesh.storage import ProofMeshStore


def test_capture_snapshot_basic(tmp_path: Path):
    """Test capturing a snapshot in a directory with regular files."""
    (tmp_path / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("print('hello')\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.py").write_text("def test_app(): pass\n", encoding="utf-8")

    snapshot = capture_snapshot(tmp_path)

    assert isinstance(snapshot, RepoSnapshot)
    assert snapshot.repo_root == str(tmp_path.resolve())
    assert snapshot.git_commit is None
    assert snapshot.git_dirty is False
    assert len(snapshot.files) == 3

    assert snapshot.snapshot_id.startswith("sha256:")
    assert len(snapshot.snapshot_id) == 71

    # Check file paths and contents
    assert snapshot.file_paths == {"README.md", "src/app.py", "tests/test_app.py"}

    readme_fp = snapshot.get_file("README.md")
    assert readme_fp is not None
    assert readme_fp.path == "README.md"
    assert readme_fp.size_bytes == len(b"# Test Repo\n")
    expected_readme_sha = f"sha256:{hashlib.sha256(b'# Test Repo\n').hexdigest()}"
    assert readme_fp.sha256 == expected_readme_sha
    assert readme_fp.is_tracked is True

    # Files must be sorted by path
    paths = [f.path for f in snapshot.files]
    assert paths == sorted(paths)


def test_deterministic_snapshot_id(tmp_path: Path):
    """Ensure identical repository contents yield identical snapshot IDs."""
    repo1 = tmp_path / "repo1"
    repo2 = tmp_path / "repo2"
    repo1.mkdir()
    repo2.mkdir()

    for r in (repo1, repo2):
        (r / "file_b.txt").write_text("content B", encoding="utf-8")
        (r / "file_a.txt").write_text("content A", encoding="utf-8")
        sub = r / "subdir"
        sub.mkdir()
        (sub / "nested.txt").write_text("nested content", encoding="utf-8")

    snap1 = capture_snapshot(repo1)
    snap2 = capture_snapshot(repo2)

    assert snap1.snapshot_id == snap2.snapshot_id
    assert [f.path for f in snap1.files] == [f.path for f in snap2.files]
    for f1, f2 in zip(snap1.files, snap2.files):
        assert f1.path == f2.path
        assert f1.sha256 == f2.sha256
        assert f1.size_bytes == f2.size_bytes


def test_content_change_modifies_fingerprint_and_snapshot_id(tmp_path: Path):
    """Ensure file modifications change the individual fingerprint and the snapshot ID."""
    file_path = tmp_path / "code.py"
    file_path.write_text("version = 1\n", encoding="utf-8")

    snap_v1 = capture_snapshot(tmp_path)
    fp_v1 = snap_v1.get_file("code.py")
    assert fp_v1 is not None

    file_path.write_text("version = 2\n", encoding="utf-8")
    snap_v2 = capture_snapshot(tmp_path)
    fp_v2 = snap_v2.get_file("code.py")
    assert fp_v2 is not None

    assert fp_v1.sha256 != fp_v2.sha256
    assert snap_v1.snapshot_id != snap_v2.snapshot_id


def test_file_addition_and_deletion_changes_snapshot_id(tmp_path: Path):
    """Ensure adding or deleting files changes the snapshot ID."""
    (tmp_path / "alpha.txt").write_text("alpha", encoding="utf-8")
    snap_base = capture_snapshot(tmp_path)
    assert len(snap_base.files) == 1

    # Add file
    (tmp_path / "beta.txt").write_text("beta", encoding="utf-8")
    snap_added = capture_snapshot(tmp_path)
    assert len(snap_added.files) == 2
    assert snap_added.snapshot_id != snap_base.snapshot_id

    # Delete original file
    (tmp_path / "alpha.txt").unlink()
    snap_deleted = capture_snapshot(tmp_path)
    assert len(snap_deleted.files) == 1
    assert snap_deleted.get_file("alpha.txt") is None
    assert snap_deleted.get_file("beta.txt") is not None
    assert snap_deleted.snapshot_id != snap_added.snapshot_id
    assert snap_deleted.snapshot_id != snap_base.snapshot_id


def test_default_exclusions(tmp_path: Path):
    """Verify default excluded directories and patterns are ignored."""
    # Included regular files
    (tmp_path / "main.py").write_text("import sys\n", encoding="utf-8")
    (tmp_path / "config.toml").write_text("key = 'val'\n", encoding="utf-8")

    # Excluded dirs/files
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git_dir / "config").write_text("[core]\n", encoding="utf-8")

    pycache_dir = tmp_path / "__pycache__"
    pycache_dir.mkdir()
    (pycache_dir / "main.cpython-314.pyc").write_bytes(b"\x00\x01\x02")

    sub_pycache = tmp_path / "sub" / "__pycache__"
    sub_pycache.mkdir(parents=True)
    (sub_pycache / "mod.cpython-314.pyc").write_bytes(b"\x03\x04")

    (tmp_path / "sub" / "old.pyc").write_bytes(b"\x05\x06")

    pytest_cache = tmp_path / ".pytest_cache" / "v"
    pytest_cache.mkdir(parents=True)
    (pytest_cache / "cache").write_text("cache data", encoding="utf-8")

    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "pkg.whl").write_bytes(b"wheel content")

    venv_dir = tmp_path / ".venv" / "bin"
    venv_dir.mkdir(parents=True)
    (venv_dir / "python").write_text("#!/bin/sh\n", encoding="utf-8")

    venv314_dir = tmp_path / ".venv314" / "bin"
    venv314_dir.mkdir(parents=True)
    (venv314_dir / "pytest").write_text("#!/bin/sh\n", encoding="utf-8")

    snapshot = capture_snapshot(tmp_path)

    assert snapshot.file_paths == {"main.py", "config.toml"}
    for f in snapshot.files:
        assert not f.path.startswith(".git")
        assert not f.path.startswith(".venv")
        assert not f.path.startswith("dist")
        assert not f.path.startswith(".pytest_cache")
        assert not f.path.endswith(".pyc")
        assert "__pycache__" not in f.path


def test_custom_exclude_patterns(tmp_path: Path):
    """Verify user-provided exclude patterns are respected."""
    (tmp_path / "keep.py").write_text("keep", encoding="utf-8")
    (tmp_path / "app.log").write_text("log line", encoding="utf-8")
    (tmp_path / "sub" / "nested.log").parent.mkdir(parents=True)
    (tmp_path / "sub" / "nested.log").write_text("nested log", encoding="utf-8")
    (tmp_path / "temp" / "scratch.tmp").parent.mkdir(parents=True)
    (tmp_path / "temp" / "scratch.tmp").write_text("temp", encoding="utf-8")
    (tmp_path / "secrets.key").write_text("secret", encoding="utf-8")

    snapshot = capture_snapshot(
        tmp_path,
        exclude_patterns=["*.log", "*.key", "temp/**"],
    )

    assert snapshot.file_paths == {"keep.py"}


def test_binary_and_large_files(tmp_path: Path):
    """Verify binary data and large files are hashed and sized accurately."""
    # Binary file
    binary_data = bytes(range(256)) * 64  # 16 KiB of binary data
    (tmp_path / "binary.dat").write_bytes(binary_data)

    # Large file (~2 MiB)
    large_chunk = b"A" * 65536
    large_data = large_chunk * 32
    (tmp_path / "large.bin").write_bytes(large_data)

    snapshot = capture_snapshot(tmp_path)

    bin_fp = snapshot.get_file("binary.dat")
    assert bin_fp is not None
    assert bin_fp.size_bytes == len(binary_data)
    assert bin_fp.sha256 == f"sha256:{hashlib.sha256(binary_data).hexdigest()}"

    large_fp = snapshot.get_file("large.bin")
    assert large_fp is not None
    assert large_fp.size_bytes == len(large_data)
    assert large_fp.sha256 == f"sha256:{hashlib.sha256(large_data).hexdigest()}"


def test_symlink_inside_repo(tmp_path: Path):
    """Symlinks that point to valid files inside repo_root should be included."""
    target_file = tmp_path / "original.txt"
    target_file.write_text("original content", encoding="utf-8")

    link_file = tmp_path / "symlink_inside.txt"
    link_file.symlink_to(target_file)

    snapshot = capture_snapshot(tmp_path)

    assert "original.txt" in snapshot.file_paths
    assert "symlink_inside.txt" in snapshot.file_paths

    fp_orig = snapshot.get_file("original.txt")
    fp_link = snapshot.get_file("symlink_inside.txt")
    assert fp_orig is not None and fp_link is not None
    assert fp_orig.sha256 == fp_link.sha256
    assert fp_orig.size_bytes == fp_link.size_bytes


def test_symlink_escape_protection(tmp_path: Path):
    """Symlinks pointing outside repo_root must be skipped and never leak into snapshot."""
    repo_dir = tmp_path / "repo"
    outside_dir = tmp_path / "outside"
    repo_dir.mkdir()
    outside_dir.mkdir()

    # Secret file outside repo
    secret_file = outside_dir / "secret.txt"
    secret_file.write_text("confidential", encoding="utf-8")

    # Regular file inside repo
    (repo_dir / "valid.txt").write_text("valid", encoding="utf-8")

    # Escaping file symlink
    (repo_dir / "leak_file.txt").symlink_to(secret_file)

    # Chained symlink escape: link2 -> link1 -> outside secret
    (repo_dir / "leak_chained.txt").symlink_to(repo_dir / "leak_file.txt")

    # Escaping directory symlink
    (repo_dir / "leak_dir").symlink_to(outside_dir)

    # Symlink pointing to parent
    (repo_dir / "up_link").symlink_to(tmp_path)

    snapshot = capture_snapshot(repo_dir)

    assert snapshot.file_paths == {"valid.txt"}
    assert snapshot.get_file("leak_file.txt") is None
    assert snapshot.get_file("leak_chained.txt") is None
    assert snapshot.get_file("leak_dir") is None
    assert snapshot.get_file("up_link") is None


def test_broken_symlink_and_symlink_loop(tmp_path: Path):
    """Broken symlinks and recursive symlink loops must be safely skipped."""
    (tmp_path / "good.txt").write_text("good", encoding="utf-8")

    # Broken symlink
    (tmp_path / "broken_link.txt").symlink_to(tmp_path / "nonexistent.txt")

    # Symlink loop: loop_a -> loop_b -> loop_a
    link_a = tmp_path / "loop_a"
    link_b = tmp_path / "loop_b"
    link_a.symlink_to(link_b)
    link_b.symlink_to(link_a)

    snapshot = capture_snapshot(tmp_path)
    assert snapshot.file_paths == {"good.txt"}


def test_git_integration_and_tracked_status(tmp_path: Path):
    """Verify Git commit detection, dirty status, and is_tracked flag in a Git repo."""
    # Initialize a git repository
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=str(tmp_path), check=True, capture_output=True)

    # Before first commit, repo is clean or untracked
    snap_empty = capture_snapshot(tmp_path)
    assert snap_empty.git_commit is None

    # Track a file and commit
    tracked_file = tmp_path / "tracked.py"
    tracked_file.write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.py"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(tmp_path), check=True, capture_output=True)

    # Add an untracked file
    untracked_file = tmp_path / "untracked.txt"
    untracked_file.write_text("untracked", encoding="utf-8")

    snapshot = capture_snapshot(tmp_path)

    assert snapshot.git_commit is not None
    assert len(snapshot.git_commit) in (40, 64)
    assert snapshot.git_dirty is True

    fp_tracked = snapshot.get_file("tracked.py")
    fp_untracked = snapshot.get_file("untracked.txt")

    assert fp_tracked is not None
    assert fp_untracked is not None
    assert fp_tracked.is_tracked is True
    assert fp_untracked.is_tracked is False


def test_persistence_with_store(tmp_path: Path):
    """Verify RepoSnapshot persistence and roundtrip via ProofMeshStore."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "module.py").write_text("def run(): pass\n", encoding="utf-8")
    (repo_dir / "notes.md").write_text("some notes\n", encoding="utf-8")

    snapshot = capture_snapshot(repo_dir)

    db_path = tmp_path / "test_store.db"
    store = ProofMeshStore(db_path)

    # Save snapshot
    store.save_snapshot(snapshot)

    # Load snapshot
    loaded = store.get_snapshot(snapshot.snapshot_id)
    assert loaded is not None
    assert loaded.snapshot_id == snapshot.snapshot_id
    assert loaded.repo_root == snapshot.repo_root
    assert loaded.git_commit == snapshot.git_commit
    assert loaded.git_dirty == snapshot.git_dirty
    assert len(loaded.files) == len(snapshot.files)

    for orig_f, load_f in zip(snapshot.files, loaded.files):
        assert orig_f.path == load_f.path
        assert orig_f.sha256 == load_f.sha256
        assert orig_f.size_bytes == load_f.size_bytes
        assert orig_f.is_tracked == load_f.is_tracked

    # Idempotent save
    store.save_snapshot(snapshot)

    # Non-existent snapshot lookup
    non_existent_id = "sha256:" + "0" * 64
    assert store.get_snapshot(non_existent_id) is None


def test_invalid_repo_root_errors(tmp_path: Path):
    """Verify invalid repo_root paths raise FileNotFoundError or NotADirectoryError."""
    # Non-existent directory
    with pytest.raises(FileNotFoundError, match="does not exist"):
        capture_snapshot(tmp_path / "missing_dir")

    # Regular file passed as repo_root
    file_path = tmp_path / "not_a_dir.txt"
    file_path.write_text("hello", encoding="utf-8")
    with pytest.raises(NotADirectoryError, match="not a directory"):
        capture_snapshot(file_path)


def test_empty_directory(tmp_path: Path):
    """Verify empty repository directory produces valid snapshot with empty files list."""
    empty_dir = tmp_path / "empty_repo"
    empty_dir.mkdir()

    snapshot = capture_snapshot(empty_dir)

    assert isinstance(snapshot, RepoSnapshot)
    assert len(snapshot.files) == 0
    assert snapshot.file_paths == set()
    expected_empty_sha = f"sha256:{hashlib.sha256(b'').hexdigest()}"
    assert snapshot.snapshot_id == expected_empty_sha


def test_unicode_and_spaces_in_paths(tmp_path: Path):
    """Verify paths containing spaces and non-ASCII Unicode characters are properly fingerprinted."""
    docs = tmp_path / "my documents"
    docs.mkdir()
    (docs / "guide test.txt").write_text("spaces in filename", encoding="utf-8")

    src = tmp_path / "données"
    src.mkdir()
    (src / "résultats.json").write_text('{"status": "ok"}', encoding="utf-8")

    snapshot = capture_snapshot(str(tmp_path))

    assert "my documents/guide test.txt" in snapshot.file_paths
    assert "données/résultats.json" in snapshot.file_paths
    assert snapshot.get_file("my documents/guide test.txt") is not None
    assert snapshot.get_file("données/résultats.json") is not None

