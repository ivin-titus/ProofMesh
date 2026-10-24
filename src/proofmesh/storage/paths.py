import errno
import os
from pathlib import Path
import re

PROJECT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")


def validate_project_id(project_id: str, base_dir: Path | None = None) -> str:
    """Validate project_id format and ensure it cannot escape the projects directory."""
    if not isinstance(project_id, str):
        raise ValueError(f"project_id must be a string, got {type(project_id).__name__}")

    if not project_id or not PROJECT_ID_PATTERN.match(project_id):
        raise ValueError(f"Invalid project_id '{project_id}': must match pattern ^[a-zA-Z0-9][a-zA-Z0-9_.-]{{0,63}}$")

    if ".." in project_id or "/" in project_id or "\\" in project_id or "\0" in project_id:
        raise ValueError(f"Path traversal detected in project_id: '{project_id}'")

    if base_dir is not None:
        projects_dir = (Path(base_dir).resolve() / "projects")
        resolved = (projects_dir / project_id).resolve()
        if resolved.parent != projects_dir:
            raise ValueError(f"Resolved path escapes projects directory: '{project_id}'")

    return project_id


UNSUPPORTED_CHMOD_ERRNOS = {
    errno.ENOSYS,
    getattr(errno, "EOPNOTSUPP", 95),
    getattr(errno, "ENOTSUP", 95),
}


def _secure_directory(dir_path: Path) -> None:
    """Create directory with 0700 permissions; fail if permission is denied."""
    dir_path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(dir_path, 0o700)
    except PermissionError as e:
        raise PermissionError(f"Cannot set secure permissions (0700) on {dir_path}: {e}") from e
    except OSError as e:
        # Ignore only if filesystem genuinely doesn't support chmod (e.g. FAT/exFAT)
        if e.errno in UNSUPPORTED_CHMOD_ERRNOS:
            pass
        else:
            raise


def get_proofmesh_data_dir(create: bool = False) -> Path:
    """Resolve the ProofMesh user data directory outside the workspace.
    
    Priority:
    1. PROOFMESH_HOME environment variable
    2. XDG_DATA_HOME/proofmesh environment variable
    3. Default ~/.local/share/proofmesh
    """
    custom_home = os.environ.get("PROOFMESH_HOME")
    if custom_home:
        data_dir = Path(custom_home).resolve()
    else:
        xdg_home = os.environ.get("XDG_DATA_HOME")
        if xdg_home:
            data_dir = (Path(xdg_home) / "proofmesh").resolve()
        else:
            data_dir = (Path.home() / ".local" / "share" / "proofmesh").resolve()

    if create:
        _secure_directory(data_dir)

    return data_dir


def get_project_db_path(project_id: str, base_dir: Path | None = None) -> Path:
    """Return the SQLite database path for a given project, strictly validating the project ID."""
    if base_dir is None:
        base_dir = get_proofmesh_data_dir(create=True)
    else:
        base_dir = Path(base_dir).resolve()
        _secure_directory(base_dir)

    # Validate against traversal
    validate_project_id(project_id, base_dir=base_dir)

    # Explicitly secure intermediate projects directory and per-project directory
    projects_dir = base_dir / "projects"
    _secure_directory(projects_dir)

    project_dir = projects_dir / project_id
    _secure_directory(project_dir)

    return project_dir / "proofmesh.db"


def secure_db_file(db_path: Path) -> None:
    """Ensure database file and companion WAL/SHM files have restrictive permissions (0600)."""
    for candidate in [
        db_path,
        db_path.with_name(db_path.name + "-wal"),
        db_path.with_name(db_path.name + "-shm"),
    ]:
        if candidate.exists():
            try:
                os.chmod(candidate, 0o600)
            except PermissionError as e:
                raise PermissionError(f"Cannot set secure permissions (0600) on {candidate}: {e}") from e
            except OSError as e:
                if e.errno in UNSUPPORTED_CHMOD_ERRNOS:
                    pass
                else:
                    raise
