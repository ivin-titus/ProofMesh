"""ProofMesh Loop and Compounding-Error Detector.

Tracks failure attempts per session, gate, and error signature to detect
repetitive failures and budget exhaustion before models compound errors.
Supports optional persistence via ProofMeshStore surviving process restarts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from proofmesh.models import BudgetPolicy

if TYPE_CHECKING:
    from proofmesh.storage.store import ProofMeshStore


class LoopDetector:
    """Tracker of failure attempts per session, gate, and error signature.

    Supports both in-memory operation and persistence backed by ProofMeshStore,
    which survives process restarts and filters duplicate turn_id deliveries.
    """

    def __init__(self, store: ProofMeshStore | None = None) -> None:
        self._store = store
        self._failures: dict[tuple[str, str, str], int] = {}

    def record_failure(
        self,
        session_id: str,
        gate_id: str,
        error_signature: str = "",
        turn_id: str | None = None,
    ) -> int:
        """Record a failure attempt and return the updated failure count.

        Args:
            session_id: The session identifier.
            gate_id: The verification gate identifier.
            error_signature: Normalized error signature or message.
            turn_id: Optional host turn identifier for deduplicating retries.

        Returns:
            The updated failure attempt count for this (session_id, gate_id, error_signature).
        """
        if self._store is not None:
            return self._store.record_loop_attempt(
                session_id=session_id,
                gate_id=gate_id,
                failure_signature=error_signature,
                turn_id=turn_id,
            )

        key = (session_id, gate_id, error_signature)
        self._failures[key] = self._failures.get(key, 0) + 1
        return self._failures[key]

    def record_attempt(
        self,
        session_id: str,
        gate_id: str,
        failure_signature: str = "",
        turn_id: str | None = None,
    ) -> int:
        """Alias for record_failure matching CORE_API_CONTRACTS.md specification."""
        return self.record_failure(session_id, gate_id, failure_signature, turn_id=turn_id)

    def is_budget_exhausted(
        self,
        session_id: str,
        gate_id: str,
        error_signature: str | BudgetPolicy = "",
        budget: BudgetPolicy | None = None,
    ) -> bool:
        """Check if retry budget is exhausted for a session and gate.

        Supports two calling conventions:
          is_budget_exhausted(session_id, gate_id, error_signature, budget)
          is_budget_exhausted(session_id, gate_id, budget)

        Args:
            session_id: The session identifier.
            gate_id: The verification gate identifier.
            error_signature: Error signature string, or BudgetPolicy if 3 args passed.
            budget: BudgetPolicy instance (optional if passed as third arg).

        Returns:
            True if recorded failure attempts >= budget.max_retries, False otherwise.
        """
        if isinstance(error_signature, BudgetPolicy):
            budget_policy = error_signature
            if self._store is not None:
                conn = self._store.get_connection()
                try:
                    row = conn.execute(
                        "SELECT MAX(attempt_count) AS max_c FROM loop_attempts WHERE session_id = ? AND gate_id = ?;",
                        (session_id, gate_id),
                    ).fetchone()
                    attempts = int(row["max_c"]) if row and row["max_c"] is not None else 0
                finally:
                    conn.close()
            else:
                attempts = max(
                    (
                        count
                        for (s, g, _), count in self._failures.items()
                        if s == session_id and g == gate_id
                    ),
                    default=0,
                )
            return attempts >= budget_policy.max_retries
        else:
            budget_policy = budget if budget is not None else BudgetPolicy()
            sig = str(error_signature)
            if self._store is not None:
                attempts = self._store.get_loop_attempt_count(session_id, gate_id, sig)
            else:
                attempts = self._failures.get((session_id, gate_id, sig), 0)
            return attempts >= budget_policy.max_retries

    def get_failure_count(
        self,
        session_id: str,
        gate_id: str,
        error_signature: str = "",
    ) -> int:
        """Get the current failure attempt count for (session_id, gate_id, error_signature)."""
        if self._store is not None:
            return self._store.get_loop_attempt_count(session_id, gate_id, error_signature)
        return self._failures.get((session_id, gate_id, error_signature), 0)

    def reset(self, session_id: str | None = None, gate_id: str | None = None) -> None:
        """Reset failure counts. If session_id is provided, only resets that session."""
        if self._store is not None:
            if session_id is not None:
                self._store.reset_loop_attempts(session_id=session_id, gate_id=gate_id)
            else:
                with self._store.transaction() as conn:
                    conn.execute("DELETE FROM loop_attempts;")

        if session_id is None:
            self._failures.clear()
        else:
            self._failures = {
                k: v for k, v in self._failures.items() if k[0] != session_id
            }
