"""Trusted policy loading, canonical digest computation, and resolution."""

from __future__ import annotations

import hashlib
from importlib import resources
import json
import os
from pathlib import Path
import tomllib
from typing import Tuple

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


def compute_policy_digest(policy: TrustedPolicy) -> str:
    """Compute deterministic SHA-256 digest of canonicalized policy content."""
    canonical_repr = json.dumps(
        policy.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"sha256:{hashlib.sha256(canonical_repr.encode('utf-8')).hexdigest()}"


def resolve_trusted_policy(
    policy_path_override: Path | str | None = None,
) -> tuple[TrustedPolicy, str]:
    """Resolve trusted policy from explicit path, PROOFMESH_POLICY env var, or packaged default.

    Returns:
        tuple of (TrustedPolicy, policy_digest).

    Raises:
        FileNotFoundError: If the specified policy file cannot be found.
        ValidationError / ValueError: If the policy content is invalid.
    """
    if policy_path_override is not None:
        p_path = Path(policy_path_override).resolve()
        policy = load_policy_file(p_path)
    else:
        env_policy = os.environ.get("PROOFMESH_POLICY")
        if env_policy:
            p_path = Path(env_policy).resolve()
            policy = load_policy_file(p_path)
        else:
            policy = get_default_policy()

    digest = compute_policy_digest(policy)
    return policy, digest
