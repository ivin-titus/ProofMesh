from pathlib import Path
import tomllib
from proofmesh.models.policy import TrustedPolicy

DEFAULT_POLICY_PATH = Path(__file__).parent.parent.parent / "config" / "default-policy.toml"


def load_policy(toml_content: str) -> TrustedPolicy:
    """Parse and validate a trusted policy TOML string."""
    raw_dict = tomllib.loads(toml_content)
    return TrustedPolicy.model_validate(raw_dict)


def load_policy_file(path: Path | str) -> TrustedPolicy:
    """Load and validate a trusted policy file from disk."""
    file_path = Path(path).resolve()
    content = file_path.read_text(encoding="utf-8")
    return load_policy(content)


def get_default_policy() -> TrustedPolicy:
    """Retrieve the default trusted policy."""
    if DEFAULT_POLICY_PATH.exists():
        return load_policy_file(DEFAULT_POLICY_PATH)
    return TrustedPolicy()
