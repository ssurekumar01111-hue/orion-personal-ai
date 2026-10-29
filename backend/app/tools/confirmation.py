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
from datetime import datetime, timezone, timedelta
from typing import Any

DEFAULT_CONFIRMATION_TTL_SECONDS = 300  # 5 minutes


@dataclass
class PendingConfirmation:
    confirmation_id: str
    tool: str
    arguments: dict[str, Any]
    session_id: str | None
    created_at: str
    status: str = "pending"  # "pending", "executed", "rejected", "expired", "error"
    ttl_seconds: int = DEFAULT_CONFIRMATION_TTL_SECONDS

    def is_expired(self) -> bool:
        if self.status == "expired":
            return True
        try:
            created_dt = datetime.fromisoformat(self.created_at)
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - created_dt > timedelta(seconds=self.ttl_seconds):
                self.status = "expired"
                return True
        except Exception:
            pass
        return False


class ConfirmationStore:
    """
    In-memory store for pending tool confirmations.

    Confirmations are held in memory and do NOT persist across process restarts.
    """

    def __init__(self, default_ttl_seconds: int = DEFAULT_CONFIRMATION_TTL_SECONDS) -> None:
        self._confirmations: dict[str, PendingConfirmation] = {}
        self.default_ttl_seconds = default_ttl_seconds

    def create(
        self,
        tool: str,
        arguments: dict[str, Any],
        session_id: str | None = None,
        ttl_seconds: int | None = None,
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
            ttl_seconds=ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds,
        )
        self._confirmations[confirmation_id] = record
        return record

    def get(self, confirmation_id: str) -> PendingConfirmation | None:
        record = self._confirmations.get(confirmation_id)
        if record is not None and record.is_expired():
            return record
        return record

    def mark_approved(self, confirmation_id: str) -> PendingConfirmation:
        record = self.get(confirmation_id)
        if record is None:
            raise KeyError(f"Unknown confirmation ID '{confirmation_id}'.")
        if record.is_expired() or record.status == "expired":
            raise ValueError(
                f"Confirmation '{confirmation_id}' has expired."
            )
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
        if record.is_expired() or record.status == "expired":
            raise ValueError(
                f"Confirmation '{confirmation_id}' has expired."
            )
        if record.status != "pending":
            raise ValueError(
                f"Confirmation '{confirmation_id}' cannot be reused (current status: {record.status})."
            )
        record.status = "rejected"
        return record

    def clear(self) -> None:
        """Clear all stored confirmations (primarily for tests)."""
        self._confirmations.clear()
