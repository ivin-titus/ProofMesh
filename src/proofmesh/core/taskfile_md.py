"""Strict parser, validator, and renderer for ProofMesh TaskFiles."""

from datetime import timezone
import hashlib
import json
import re
from typing import Sequence
import unicodedata
import tomllib

from proofmesh.models import (
    AcceptanceCriterion,
    ApprovalStatus,
    RiskLevel,
    ScopePolicy,
    TaskRevision,
)

MAX_TASKFILE_SIZE_BYTES = 64 * 1024  # 64 KiB cap per TRD §5.6 / §6

ALLOWED_FRONT_MATTER_FIELDS = {
    "task_id",
    "version",
    "summary",
    "risk_level",
    "allow_paths",
    "restricted_paths",
    "required_gates",
    "constraints",
    "max_changed_files",
}

REQUIRED_FRONT_MATTER_FIELDS = {
    "task_id",
    "version",
    "summary",
    "risk_level",
    "allow_paths",
    "restricted_paths",
}

IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
CRITERION_ID_PATTERN = re.compile(r"^(?:AC-\d{1,4}|[a-z0-9][a-z0-9-]{0,63})$")
CRITERION_START_PATTERN = re.compile(r"^\s*[-*]\s*\[([^\]]+)\]\s*(.*)$")
INLINE_GATES_PATTERN = re.compile(r"^(.*?)\s*\(\s*gates:\s*([^)]*)\)\s*$")
SUB_GATES_PATTERN = re.compile(r"^\s*[-*]?\s*gates:\s*(.*)$", re.IGNORECASE)
SECTION_HEADING_PATTERN = re.compile(r"^##\s+(.+)$")


def compute_contract_digest(
    task_id: str,
    version: int,
    summary: str,
    risk_level: str,
    allow_paths: Sequence[str],
    restricted_paths: Sequence[str],
    max_changed_files: int | None,
    required_gates: Sequence[str],
    constraints: Sequence[str],
    acceptance_criteria: Sequence[AcceptanceCriterion],
) -> str:
    """Compute deterministic SHA-256 digest over canonical JSON representation."""
    canonical_data = {
        "acceptance_criteria": [
            {
                "criterion_id": str(ac.criterion_id),
                "description": str(ac.description),
                "required_gates": list(ac.required_gates),
            }
            for ac in acceptance_criteria
        ],
        "constraints": list(constraints),
        "max_changed_files": max_changed_files,
        "required_gates": list(required_gates),
        "risk_level": str(risk_level),
        "scope": {
            "allow_paths": list(allow_paths),
            "max_changed_files": max_changed_files,
            "restricted_paths": list(restricted_paths),
        },
        "summary": str(summary),
        "task_id": str(task_id),
        "version": int(version),
    }

    canonical_json = json.dumps(
        canonical_data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    canonical_json = unicodedata.normalize("NFC", canonical_json)
    hex_digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    return f"sha256:{hex_digest}"


def parse_taskfile(content: str, known_gates: set[str] | None = None) -> TaskRevision:
    """Strictly parse a structured Markdown TaskFile with TOML front matter.

    Args:
        content: The raw TaskFile markdown text.
        known_gates: Optional set of allowed gate IDs. If provided, any referenced gate
            not present in this set will cause a ValueError to be raised.

    Returns:
        A validated TaskRevision domain model with ApprovalStatus.PROPOSED.

    Raises:
        ValueError: If content size exceeds 64 KiB, TOML is malformed, required fields
            or sections are missing, unexpected front-matter fields exist, or gate IDs /
            criterion IDs fail validation.
    """
    raw_bytes = content.encode("utf-8")
    if len(raw_bytes) > MAX_TASKFILE_SIZE_BYTES:
        raise ValueError(
            f"TaskFile content size ({len(raw_bytes)} bytes) exceeds maximum limit "
            f"of 64 KiB ({MAX_TASKFILE_SIZE_BYTES} bytes)"
        )

    if not content.strip():
        raise ValueError("TaskFile content is empty")

    normalized_content = unicodedata.normalize("NFC", content).replace("\r\n", "\n").replace("\r", "\n")

    lines = normalized_content.splitlines()

    start_idx: int | None = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "+++":
            start_idx = idx
            break
        raise ValueError("TaskFile must begin with front matter delimited by '+++'")

    if start_idx is None:
        raise ValueError("TaskFile is missing opening front-matter delimiter '+++'")

    end_idx: int | None = None
    for idx in range(start_idx + 1, len(lines)):
        if lines[idx].strip() == "+++":
            end_idx = idx
            break

    if end_idx is None:
        raise ValueError("TaskFile front matter closing '+++' delimiter not found")

    toml_text = "\n".join(lines[start_idx + 1 : end_idx])
    body_text = "\n".join(lines[end_idx + 1 :])

    try:
        fm = tomllib.loads(toml_text)
    except Exception as exc:
        raise ValueError(f"Malformed TOML in TaskFile front matter: {exc}") from exc

    if not isinstance(fm, dict):
        raise ValueError("TaskFile front matter must be a valid TOML table")

    # Strict validation of unexpected fields
    extra_fields = set(fm.keys()) - ALLOWED_FRONT_MATTER_FIELDS
    if extra_fields:
        raise ValueError(f"Unexpected front-matter field(s): {', '.join(sorted(extra_fields))}")

    # Strict validation of missing required fields
    missing_fields = REQUIRED_FRONT_MATTER_FIELDS - set(fm.keys())
    if missing_fields:
        raise ValueError(f"Missing required front-matter field(s): {', '.join(sorted(missing_fields))}")

    # Validate task_id
    task_id = fm["task_id"]
    if not isinstance(task_id, str) or not IDENTIFIER_PATTERN.match(task_id):
        raise ValueError(
            f"Invalid task_id: '{task_id}'. Must be a lowercase identifier matching ^[a-z0-9][a-z0-9-]{{0,63}}$"
        )

    # Validate version
    version = fm["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError(f"Invalid version: {version}. Must be an integer >= 1")

    # Validate summary
    summary = fm["summary"]
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("summary must be a non-empty string")
    if len(summary) > 2000:
        raise ValueError("summary exceeds maximum length of 2000 characters")

    # Validate risk_level
    raw_risk = fm["risk_level"]
    if not isinstance(raw_risk, str):
        raise ValueError("risk_level must be a string")
    risk_str = raw_risk.strip().lower()
    if risk_str not in ("low", "medium", "high"):
        raise ValueError(f"Invalid risk_level: '{raw_risk}'. Must be 'low', 'medium', or 'high'")
    risk_level = RiskLevel(risk_str)

    # Validate allow_paths
    allow_paths = fm["allow_paths"]
    if not isinstance(allow_paths, list) or not all(isinstance(p, str) for p in allow_paths):
        raise ValueError("allow_paths must be a list of strings")

    # Validate restricted_paths
    restricted_paths = fm["restricted_paths"]
    if not isinstance(restricted_paths, list) or not all(isinstance(p, str) for p in restricted_paths):
        raise ValueError("restricted_paths must be a list of strings")

    # Validate optional required_gates
    raw_required_gates = fm.get("required_gates", [])
    if not isinstance(raw_required_gates, list) or not all(isinstance(g, str) for g in raw_required_gates):
        raise ValueError("required_gates must be a list of strings")
    for gate in raw_required_gates:
        if not IDENTIFIER_PATTERN.match(gate):
            raise ValueError(f"Invalid gate ID in required_gates: '{gate}'")
        if known_gates is not None and gate not in known_gates:
            raise ValueError(f"Unknown gate ID in required_gates: '{gate}'")
    required_gates = tuple(raw_required_gates)

    # Validate optional constraints
    raw_constraints = fm.get("constraints", [])
    if not isinstance(raw_constraints, list) or not all(isinstance(c, str) for c in raw_constraints):
        raise ValueError("constraints must be a list of strings")
    constraints = tuple(raw_constraints)

    # Validate optional max_changed_files
    max_changed_files = fm.get("max_changed_files")
    if max_changed_files is not None:
        if isinstance(max_changed_files, bool) or not isinstance(max_changed_files, int) or max_changed_files < 1 or max_changed_files > 1000:
            raise ValueError("max_changed_files must be an integer between 1 and 1000")

    # Parse body sections
    sections: dict[str, list[str]] = {}
    current_section: str | None = None
    for line in body_text.splitlines():
        heading_match = SECTION_HEADING_PATTERN.match(line)
        if heading_match:
            sec_name = heading_match.group(1).strip().lower()
            if sec_name in sections:
                raise ValueError(f"Duplicate section heading in body: '## {heading_match.group(1).strip()}'")
            current_section = sec_name
            sections[current_section] = []
        elif current_section is not None:
            sections[current_section].append(line)

    if "acceptance criteria" not in sections:
        raise ValueError("Missing required section: '## Acceptance criteria'")

    ac_lines = sections["acceptance criteria"]
    criteria: list[AcceptanceCriterion] = []
    seen_criterion_ids: set[str] = set()

    current_crit_id: str | None = None
    current_desc_parts: list[str] = []
    current_gates: list[str] = []

    def commit_current_criterion() -> None:
        nonlocal current_crit_id, current_desc_parts, current_gates
        if current_crit_id is None:
            return
        full_desc = " ".join(part for part in current_desc_parts if part).strip()
        if not full_desc:
            raise ValueError(f"Acceptance criterion '{current_crit_id}' has empty description")
        if len(full_desc) > 1000:
            raise ValueError(f"Acceptance criterion '{current_crit_id}' description exceeds 1000 characters")

        for gate in current_gates:
            if not IDENTIFIER_PATTERN.match(gate):
                raise ValueError(f"Invalid gate ID '{gate}' in criterion '{current_crit_id}'")
            if known_gates is not None and gate not in known_gates:
                raise ValueError(f"Unknown gate ID '{gate}' referenced in criterion '{current_crit_id}'")

        criteria.append(
            AcceptanceCriterion(
                criterion_id=current_crit_id,
                description=full_desc,
                required_gates=tuple(current_gates),
            )
        )
        current_crit_id = None
        current_desc_parts = []
        current_gates = []

    for line in ac_lines:
        crit_match = CRITERION_START_PATTERN.match(line)
        if crit_match:
            commit_current_criterion()
            raw_id = crit_match.group(1).strip()
            rest = crit_match.group(2).strip()

            if not CRITERION_ID_PATTERN.match(raw_id):
                raise ValueError(
                    f"Invalid criterion ID: '{raw_id}'. Must match '^AC-\\d{{1,4}}$' or identifier pattern."
                )
            if raw_id in seen_criterion_ids:
                raise ValueError(f"Duplicate criterion ID: '{raw_id}'")
            seen_criterion_ids.add(raw_id)

            current_crit_id = raw_id
            inline_match = INLINE_GATES_PATTERN.match(rest)
            if inline_match:
                desc = inline_match.group(1).strip()
                raw_gates = inline_match.group(2).strip()
                current_desc_parts.append(desc)
                if raw_gates:
                    current_gates = [g.strip() for g in raw_gates.split(",") if g.strip()]
            else:
                current_desc_parts.append(rest)
        else:
            if current_crit_id is not None:
                sub_gate_match = SUB_GATES_PATTERN.match(line)
                if sub_gate_match:
                    raw_sub = sub_gate_match.group(1).strip()
                    if raw_sub:
                        current_gates.extend(g.strip() for g in raw_sub.split(",") if g.strip())
                elif line.strip():
                    current_desc_parts.append(line.strip())
            else:
                stripped_line = line.strip()
                if stripped_line and (stripped_line.startswith("-") or stripped_line.startswith("*")):
                    raise ValueError(
                        f"Invalid acceptance criterion format: '{stripped_line}'. Expected '- [AC-X] Description'"
                    )

    commit_current_criterion()

    if not criteria:
        raise ValueError("Acceptance criteria section must contain at least one criterion")

    scope_policy = ScopePolicy(
        allow_paths=tuple(allow_paths),
        restricted_paths=tuple(restricted_paths),
        max_changed_files=max_changed_files,
    )

    contract_digest = compute_contract_digest(
        task_id=task_id,
        version=version,
        summary=summary,
        risk_level=risk_level.value,
        allow_paths=allow_paths,
        restricted_paths=restricted_paths,
        max_changed_files=max_changed_files,
        required_gates=required_gates,
        constraints=constraints,
        acceptance_criteria=criteria,
    )

    return TaskRevision(
        task_id=task_id,
        revision=version,
        summary=summary,
        acceptance_criteria=tuple(criteria),
        scope=scope_policy,
        required_gates=required_gates,
        constraints=constraints,
        risk_level=risk_level,
        approval_status=ApprovalStatus.PROPOSED,
        contract_digest=contract_digest,
        raw_markdown=content,
    )


def render_taskfile(revision: TaskRevision) -> str:
    """Render a canonical Markdown TaskFile representation from a TaskRevision."""
    lines: list[str] = ["+++"]
    lines.append(f'task_id = "{revision.task_id}"')
    lines.append(f"version = {revision.revision}")
    escaped_summary = revision.summary.replace('"', '\\"')
    lines.append(f'summary = "{escaped_summary}"')
    lines.append(f'risk_level = "{revision.risk_level.value}"')
    allow_paths_json = json.dumps(list(revision.scope.allow_paths))
    lines.append(f"allow_paths = {allow_paths_json}")
    restricted_paths_json = json.dumps(list(revision.scope.restricted_paths))
    lines.append(f"restricted_paths = {restricted_paths_json}")

    if revision.required_gates:
        req_gates_json = json.dumps(list(revision.required_gates))
        lines.append(f"required_gates = {req_gates_json}")

    if revision.constraints:
        constraints_json = json.dumps(list(revision.constraints))
        lines.append(f"constraints = {constraints_json}")

    if revision.scope.max_changed_files is not None:
        lines.append(f"max_changed_files = {revision.scope.max_changed_files}")

    lines.append("+++\n")
    lines.append(f"# {revision.task_id}: {revision.summary}\n")
    lines.append("## Acceptance criteria\n")
    for ac in revision.acceptance_criteria:
        if ac.required_gates:
            gates_str = ", ".join(ac.required_gates)
            lines.append(f"- [{ac.criterion_id}] {ac.description} (gates: {gates_str})")
        else:
            lines.append(f"- [{ac.criterion_id}] {ac.description}")

    return "\n".join(lines) + "\n"
