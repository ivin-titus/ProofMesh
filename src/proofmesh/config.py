from importlib import resources
from pathlib import Path
import tomllib
from proofmesh.models.policy import TrustedPolicy


def load_policy(toml_content: str) -> TrustedPolicy:
    """Parse and validate a trusted policy TOML string."""
    raw_dict = tomllib.loads(toml_content)
    return TrustedPolicy.model_validate(raw_dict)


def load_policy_file(path: Path | str) -> TrustedPolicy:
    """Load and validate a trusted policy file from disk."""
    file_path = Path(path).resolve()
    if not file_path.is_file():
        raise FileNotFoundError(f"Policy file not found: {file_path}")
    content = file_path.read_text(encoding="utf-8")
    return load_policy(content)


def get_default_policy() -> TrustedPolicy:
    """Retrieve the canonical packaged default trusted policy.
    
    Loads 'default-policy.toml' from 'proofmesh.resources'.
    Raises FileNotFoundError if the packaged resource cannot be located.
    """
    try:
        resource_ref = resources.files("proofmesh.resources").joinpath("default-policy.toml")
        content = resource_ref.read_text(encoding="utf-8")
    except Exception as e:
        raise FileNotFoundError(
            f"Canonical default policy 'default-policy.toml' is missing from proofmesh.resources: {e}"
        ) from e

    return load_policy(content)
