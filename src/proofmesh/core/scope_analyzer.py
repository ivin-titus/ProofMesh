"""Deterministic scope analyzer comparing repository snapshots against ScopePolicy.

Identifies added, modified, and deleted files between baseline and current
snapshots and evaluates each change against allowlisted and restricted path
policies, enforcing file count limits and violation detection.
"""

from __future__ import annotations

import fnmatch

from proofmesh.models import (
    PathChange,
    RepoSnapshot,
    ScopeAnalysisResult,
    ScopeChangeType,
    ScopeFinding,
    ScopePolicy,
)


def analyze_scope(
    baseline: RepoSnapshot,
    current: RepoSnapshot,
    policy: ScopePolicy,
) -> ScopeAnalysisResult:
    """Compare baseline and current repository snapshots against a scope policy.

    Args:
        baseline: The baseline RepoSnapshot representing starting code state.
        current: The current RepoSnapshot representing current code state.
        policy: The ScopePolicy containing allow_paths, restricted_paths, and max_changed_files.

    Returns:
        ScopeAnalysisResult with classified changes, individual findings,
        total changed file count, file limit status, and violation flag.

    Raises:
        TypeError: If baseline or current is not a RepoSnapshot, or policy is not a ScopePolicy.
    """
    if not isinstance(baseline, RepoSnapshot):
        raise TypeError(f"baseline must be a RepoSnapshot, got {type(baseline).__name__}")
    if not isinstance(current, RepoSnapshot):
        raise TypeError(f"current must be a RepoSnapshot, got {type(current).__name__}")
    if not isinstance(policy, ScopePolicy):
        raise TypeError(f"policy must be a ScopePolicy, got {type(policy).__name__}")

    baseline_map = {f.path: f for f in baseline.files}
    current_map = {f.path: f for f in current.files}

    # All unique paths across both snapshots
    all_paths = sorted(set(baseline_map.keys()) | set(current_map.keys()))

    changes: list[PathChange] = []
    for path in all_paths:
        old_file = baseline_map.get(path)
        new_file = current_map.get(path)

        if old_file is None and new_file is not None:
            # File added
            changes.append(
                PathChange(
                    path=path,
                    change_type=ScopeChangeType.ADDED,
                    old_sha256=None,
                    new_sha256=new_file.sha256,
                )
            )
        elif old_file is not None and new_file is None:
            # File deleted
            changes.append(
                PathChange(
                    path=path,
                    change_type=ScopeChangeType.DELETED,
                    old_sha256=old_file.sha256,
                    new_sha256=None,
                )
            )
        elif old_file is not None and new_file is not None:
            if old_file.sha256 != new_file.sha256:
                # File modified
                changes.append(
                    PathChange(
                        path=path,
                        change_type=ScopeChangeType.MODIFIED,
                        old_sha256=old_file.sha256,
                        new_sha256=new_file.sha256,
                    )
                )

    # Evaluate each changed path against policy
    findings: list[ScopeFinding] = []
    for change in changes:
        path = change.path

        # 1. Check if path matches any restricted pattern
        matched_restricted: str | None = None
        for pattern in policy.restricted_paths:
            if fnmatch.fnmatch(path, pattern):
                matched_restricted = pattern
                break

        if matched_restricted is not None:
            allowed = False
            restricted = True
            reason = f"Path '{path}' matches restricted pattern '{matched_restricted}'"
        elif not any(fnmatch.fnmatch(path, p) for p in policy.allow_paths):
            allowed = False
            restricted = False
            reason = f"Path '{path}' is not covered by allow_paths"
        else:
            # Path is explicitly allowlisted
            allowed = True
            restricted = False
            reason = "Path is allowlisted"

        findings.append(
            ScopeFinding(
                path=path,
                allowed=allowed,
                restricted=restricted,
                reason=reason,
            )
        )

    # Check total changed files
    total_changed_files = len(changes)
    exceeded_file_limit = False
    if policy.max_changed_files is not None and total_changed_files > policy.max_changed_files:
        exceeded_file_limit = True

    # Determine if there are any violations
    has_violations = exceeded_file_limit or any(
        (not f.allowed or f.restricted) for f in findings
    )

    return ScopeAnalysisResult(
        baseline_snapshot_id=baseline.snapshot_id,
        current_snapshot_id=current.snapshot_id,
        changes=tuple(changes),
        findings=tuple(findings),
        total_changed_files=total_changed_files,
        exceeded_file_limit=exceeded_file_limit,
        has_violations=has_violations,
    )
