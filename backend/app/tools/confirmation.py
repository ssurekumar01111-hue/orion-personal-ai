"""
Confirmation Store (Phase 4A).

Provides in-memory tracking of pending user confirmations for tools that
require confirmation before execution.

NOTE: Confirmations are stored in-memory and do not persist across
process restarts.
"""
import copy
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class PendingConfirmation:
    confirmation_id: str
    tool: str
    arguments: dict[str, Any]
    session_id: str | None
    created_at: str
    status: str = "pending"  # "pending", "executed", "rejected", "error"


class ConfirmationStore:
    """
    In-memory store for pending tool confirmations.

    Confirmations are held in memory and do NOT persist across process restarts.
    """

    def __init__(self) -> None:
        self._confirmations: dict[str, PendingConfirmation] = {}

    def create(
        self,
        tool: str,
        arguments: dict[str, Any],
        session_id: str | None = None,
    ) -> PendingConfirmation:
        confirmation_id = f"conf_{uuid.uuid4().hex[:16]}"
        safe_args = copy.deepcopy(arguments)
        safe_args.pop("confirmed", None)

        record = PendingConfirmation(
            confirmation_id=confirmation_id,
            tool=tool,
            arguments=safe_args,
            session_id=session_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            status="pending",
        )
        self._confirmations[confirmation_id] = record
        return record

    def get(self, confirmation_id: str) -> PendingConfirmation | None:
        return self._confirmations.get(confirmation_id)

    def mark_approved(self, confirmation_id: str) -> PendingConfirmation:
        record = self.get(confirmation_id)
        if record is None:
            raise KeyError(f"Unknown confirmation ID '{confirmation_id}'.")
        if record.status != "pending":
            raise ValueError(
                f"Confirmation '{confirmation_id}' cannot be reused (current status: {record.status})."
            )
        record.status = "executed"
        return record

    def mark_rejected(self, confirmation_id: str) -> PendingConfirmation:
        record = self.get(confirmation_id)
        if record is None:
            raise KeyError(f"Unknown confirmation ID '{confirmation_id}'.")
        if record.status != "pending":
            raise ValueError(
                f"Confirmation '{confirmation_id}' cannot be reused (current status: {record.status})."
            )
        record.status = "rejected"
        return record

    def clear(self) -> None:
        """Clear all stored confirmations (primarily for tests)."""
        self._confirmations.clear()
