import os
from pathlib import Path


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
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(data_dir, 0o700)
        except OSError:
            pass

    return data_dir


def get_project_db_path(project_id: str, base_dir: Path | None = None) -> Path:
    """Return the SQLite database path for a given project."""
    if base_dir is None:
        base_dir = get_proofmesh_data_dir(create=True)
    else:
        base_dir = Path(base_dir).resolve()

    project_dir = base_dir / "projects" / project_id
    try:
        project_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(project_dir, 0o700)
    except OSError:
        pass

    return project_dir / "proofmesh.db"


def secure_db_file(db_path: Path) -> None:
    """Ensure database file has restrictive permissions (0600)."""
    if db_path.exists():
        try:
            os.chmod(db_path, 0o600)
        except OSError:
            pass
