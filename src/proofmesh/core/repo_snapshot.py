import hashlib
from datetime import datetime, timezone
import fnmatch
from pathlib import Path, PurePosixPath
import subprocess
from typing import Sequence

from proofmesh.models import FileFingerprint, RepoSnapshot


DEFAULT_EXCLUDE_PATTERNS: tuple[str, ...] = (
    ".git/**",
    "__pycache__/**",
    "*.pyc",
    ".pytest_cache/**",
    "dist/**",
    ".venv/**",
    ".venv314/**",
)


def _is_excluded(rel_path: str, is_dir: bool, patterns: Sequence[str]) -> bool:
    """Check if relative POSIX path matches any of the exclude patterns."""
    pure = PurePosixPath(rel_path)
    name = pure.name

    for pat in patterns:
        norm_pat = pat.rstrip("/")

        if pat.endswith("/**"):
            prefix = pat[:-3]
            if rel_path == prefix or rel_path.startswith(prefix + "/"):
                return True
            if prefix in pure.parts:
                return True
        elif pat.endswith("/*"):
            prefix = pat[:-2]
            if rel_path == prefix or rel_path.startswith(prefix + "/"):
                return True
            if prefix in pure.parts:
                return True
        elif is_dir and (rel_path == norm_pat or rel_path.startswith(norm_pat + "/")):
            return True

        if pure.match(pat) or pure.match(f"**/{pat}"):
            return True

        if fnmatch.fnmatch(rel_path, pat) or fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel_path, f"*/{pat}"):
            return True

    return False


def _get_git_state(repo_root: Path) -> tuple[str | None, bool, set[str] | None]:
    """Inspect Git repository state (HEAD commit, dirty flag, tracked files).
    
    Gracefully returns (None, False, None) if not a git repository or git fails.
    """
    commit: str | None = None
    dirty: bool = False
    tracked_files: set[str] | None = None

    try:
        # Detect commit hash
        res_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if res_commit.returncode == 0:
            commit_str = res_commit.stdout.strip()
            if commit_str:
                commit = commit_str

        # Detect dirty status
        res_status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if res_status.returncode == 0:
            dirty = bool(res_status.stdout.strip())

        # Detect tracked files
        res_files = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=str(repo_root),
            capture_output=True,
            timeout=10,
            check=False,
        )
        if res_files.returncode == 0:
            tracked_files = {
                p.decode("utf-8", errors="replace")
                for p in res_files.stdout.split(b"\0")
                if p
            }

    except (subprocess.SubprocessError, OSError):
        return None, False, None

    return commit, dirty, tracked_files


def capture_snapshot(
    repo_root: Path | str,
    exclude_patterns: Sequence[str] | None = None,
) -> RepoSnapshot:
    """Capture a deterministic repository snapshot capturing file fingerprints and Git state.
    
    Args:
        repo_root: Path to the target repository directory.
        exclude_patterns: Optional list of additional glob/exclusion patterns.
        
    Returns:
        RepoSnapshot instance with deterministic file fingerprints and snapshot ID.
        
    Raises:
        FileNotFoundError: If repo_root does not exist.
        NotADirectoryError: If repo_root is not a directory.
    """
    repo_root_path = Path(repo_root).resolve()
    if not repo_root_path.exists():
        raise FileNotFoundError(f"Repository root does not exist: {repo_root}")
    if not repo_root_path.is_dir():
        raise NotADirectoryError(f"Repository root is not a directory: {repo_root}")

    all_patterns = list(DEFAULT_EXCLUDE_PATTERNS)
    if exclude_patterns:
        all_patterns.extend(exclude_patterns)

    git_commit, git_dirty, tracked_files = _get_git_state(repo_root_path)

    fingerprints: list[FileFingerprint] = []

    for root, dirs, files in os_walk_safe(repo_root_path, all_patterns):
        rel_root = Path(root).relative_to(repo_root_path).as_posix()
        if rel_root == ".":
            rel_root = ""

        for fname in files:
            file_rel = f"{rel_root}/{fname}" if rel_root else fname
            if _is_excluded(file_rel, is_dir=False, patterns=all_patterns):
                continue

            file_path = Path(root) / fname

            if file_path.is_symlink():
                try:
                    target = file_path.resolve(strict=True)
                except (OSError, ValueError, RuntimeError):
                    # Broken symlink or loop: skip
                    continue

                if not target.is_relative_to(repo_root_path):
                    # Escaping symlink: skip
                    continue

                if not target.is_file():
                    continue

                target_rel = target.relative_to(repo_root_path).as_posix()
                if _is_excluded(target_rel, is_dir=False, patterns=all_patterns):
                    continue
            else:
                if not file_path.is_file():
                    continue

            try:
                hasher = hashlib.sha256()
                size_bytes = 0
                with open(file_path, "rb") as fp:
                    while chunk := fp.read(65536):
                        hasher.update(chunk)
                        size_bytes += len(chunk)
            except OSError:
                continue

            sha256_hex = hasher.hexdigest()
            digest = f"sha256:{sha256_hex}"
            is_tracked = (file_rel in tracked_files) if tracked_files is not None else True

            fingerprints.append(
                FileFingerprint(
                    path=file_rel,
                    sha256=digest,
                    size_bytes=size_bytes,
                    is_tracked=is_tracked,
                )
            )

    sorted_files = tuple(sorted(fingerprints, key=lambda fp: fp.path))

    snapshot_hasher = hashlib.sha256()
    for fp in sorted_files:
        record = f"{fp.path}:{fp.sha256}:{fp.size_bytes}\n"
        snapshot_hasher.update(record.encode("utf-8"))
    snapshot_id = f"sha256:{snapshot_hasher.hexdigest()}"

    return RepoSnapshot(
        snapshot_id=snapshot_id,
        repo_root=str(repo_root_path),
        git_commit=git_commit,
        git_dirty=git_dirty,
        files=sorted_files,
        captured_at=datetime.now(timezone.utc),
    )


def os_walk_safe(repo_root: Path, patterns: Sequence[str]):
    """Walk repo_root pruning excluded directories and protecting against symlink escapes."""
    import os
    for root, dirs, files in os.walk(str(repo_root), followlinks=False):
        rel_root = Path(root).relative_to(repo_root).as_posix()
        if rel_root == ".":
            rel_root = ""

        pruned_dirs = []
        for d in dirs:
            dir_rel = f"{rel_root}/{d}" if rel_root else d
            if _is_excluded(dir_rel, is_dir=True, patterns=patterns):
                continue

            d_path = Path(root) / d
            if d_path.is_symlink():
                try:
                    target = d_path.resolve(strict=True)
                    if not target.is_relative_to(repo_root):
                        continue
                except (OSError, ValueError, RuntimeError):
                    continue

            pruned_dirs.append(d)

        dirs[:] = pruned_dirs
        yield root, dirs, files
