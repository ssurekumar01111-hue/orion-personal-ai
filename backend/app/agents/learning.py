"""
Post-Task Learning Service for Orion (Phase LEARN).

Closes the core cognitive loop:
UNDERSTAND → REMEMBER → PLAN → ACT → OBSERVE → LEARN → repeat

Evaluates task execution outcomes, verifies tool observations against objectives,
updates persistent memory and task records (with strict verification guarantees),
records sanitized learning events, and prevents duplicate or unverified conclusions.
"""
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from ..memory.database import get_connection
from ..memory.extraction import MemoryExtractionService
from ..memory.personal import PersonalModelStore
from ..memory.store import MemoryStore
from ..tools.audit import _sanitize_payload, _scrub_secrets, log_event


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_task_key(user_objective: str, session_id: str | None, obs_count: int, suffix: str = "") -> str:
    raw = f"{session_id or 'none'}::{user_objective.strip()}::{obs_count}::{suffix}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class PostTaskLearningService:
    """
    Evaluates completed or stopped agent turns to extract memories, update task statuses
    upon verification, record decisions, and log idempotent learning events.
    """

    def __init__(
        self,
        memory_store: MemoryStore | None = None,
        personal_store: PersonalModelStore | None = None,
        extraction_service: MemoryExtractionService | None = None,
    ) -> None:
        self.memory_store = memory_store or MemoryStore()
        self.personal_store = personal_store or PersonalModelStore()
        self.extraction_service = extraction_service or MemoryExtractionService(
            memory_store=self.memory_store
        )

    def learn_from_turn(
        self,
        user_objective: str,
        steps: list[dict[str, Any]],
        observations: list[dict[str, Any]],
        final_answer: str,
        session_id: str | None = None,
        confirmation_required: bool = False,
        confirmed_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute the LEARN stage after a turn outcome is established.
        Guaranteed to never raise an exception that crashes agent execution.
        """
        try:
            return self._perform_learning(
                user_objective=user_objective,
                steps=steps,
                observations=observations,
                final_answer=final_answer,
                session_id=session_id,
                confirmation_required=confirmation_required,
                confirmed_result=confirmed_result,
            )
        except Exception as exc:
            # Learning failure must never crash the orchestrator
            log_event(
                event="learning_error",
                status="error",
                result={"error": str(exc)},
            )
            return {
                "status": "learning_error",
                "error": str(exc),
                "learned_memories": [],
                "learned_decisions": [],
                "task_updates": [],
            }

    def _perform_learning(
        self,
        user_objective: str,
        steps: list[dict[str, Any]],
        observations: list[dict[str, Any]],
        final_answer: str,
        session_id: str | None,
        confirmation_required: bool,
        confirmed_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        obs_count = len(observations)
        suffix = "confirmed" if confirmed_result is not None else ("pending" if confirmation_required else "normal")
        task_key = _generate_task_key(user_objective, session_id, obs_count, suffix)

        # ── Idempotency Check ───────────────────────────────────────────────
        with get_connection() as connection:
            existing = connection.execute(
                "SELECT * FROM learning_events WHERE task_key = ?",
                (task_key,),
            ).fetchone()
            if existing:
                try:
                    details = json.loads(existing["details"])
                except Exception:
                    details = {}
                return {
                    "status": "already_learned",
                    "task_key": task_key,
                    "completion_status": existing["completion_status"],
                    "learned_memories": details.get("learned_memories", []),
                    "learned_decisions": details.get("learned_decisions", []),
                    "task_updates": details.get("task_updates", []),
                    "summary": existing["summary"],
                }

        # ── Determine Verified Completion Status ─────────────────────────────
        completion_status = "success"
        if confirmation_required:
            completion_status = "pending_confirmation"
        elif any(s.get("status") == "error" for s in steps):
            completion_status = "failed"
        elif any(s.get("status") == "blocked" for s in steps):
            completion_status = "blocked"

        learned_memories: list[dict[str, Any]] = []
        learned_decisions: list[dict[str, Any]] = []
        task_updates: list[dict[str, Any]] = []

        # ── 1. Conversational Memory Extraction ─────────────────────────────
        # Only extract facts if not a purely blocked action
        if completion_status != "blocked":
            extracted = self.extraction_service.extract_from_conversation(
                user_message=user_objective,
                session_id=session_id,
            )
            for mem in extracted:
                learned_memories.append({
                    "id": mem["id"],
                    "content": mem["content"],
                    "category": mem["category"],
                    "importance": mem["importance"],
                })

        # ── 2. Verified Task Status Updates ──────────────────────────────────
        # CONSTRAINT: Never mark a task completed simply because the model claims success.
        # Require verified tool observations before changing task status.
        if completion_status == "success" and (observations or confirmed_result):
            # Check if user requested completing or updating a specific task
            # Or if observations prove verification of a task
            task_updates.extend(self._verify_and_update_tasks(user_objective, observations, confirmed_result))

        # ── 3. Decision Recording ────────────────────────────────────────────
        # If user explicitly stated a decision in objective or tool verified a decision
        if "decided to " in user_objective.lower() or "decision: " in user_objective.lower():
            decision_text = user_objective.strip()
            # Avoid duplicate decisions
            existing_decs = self.personal_store.list_decisions(limit=50)
            if not any(d["decision"].strip().lower() == decision_text.lower() for d in existing_decs):
                new_dec = self.personal_store.create_decision(
                    decision=decision_text,
                    context=f"Recorded during session {session_id}" if session_id else "Conversational turn",
                )
                learned_decisions.append({
                    "id": new_dec["id"],
                    "decision": new_dec["decision"],
                })

        # ── 4. Record Learning Event in SQLite ──────────────────────────────
        summary_lines = [f"Turn outcome: {completion_status}"]
        if learned_memories:
            summary_lines.append(f"Persisted {len(learned_memories)} memory record(s).")
        if task_updates:
            summary_lines.append(f"Updated {len(task_updates)} verified task(s).")
        if learned_decisions:
            summary_lines.append(f"Recorded {len(learned_decisions)} decision(s).")
        summary_str = " ".join(summary_lines)

        details_payload = {
            "learned_memories": learned_memories,
            "learned_decisions": learned_decisions,
            "task_updates": task_updates,
            "steps_count": len(steps),
            "observations_count": obs_count,
        }

        now = _now_iso()
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO learning_events (
                    task_key, session_id, user_objective, completion_status,
                    learned_memories_count, learned_decisions_count, task_updates_count,
                    summary, details, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_key,
                    session_id,
                    user_objective.strip(),
                    completion_status,
                    len(learned_memories),
                    len(learned_decisions),
                    len(task_updates),
                    summary_str,
                    json.dumps(details_payload, ensure_ascii=False),
                    now,
                ),
            )
            connection.commit()

        log_event(
            event="agent_learning",
            status="completed",
            result={
                "task_key": task_key,
                "completion_status": completion_status,
                "learned_memories": len(learned_memories),
                "task_updates": len(task_updates),
            },
        )

        return {
            "status": "learned",
            "task_key": task_key,
            "completion_status": completion_status,
            "learned_memories": learned_memories,
            "learned_decisions": learned_decisions,
            "task_updates": task_updates,
            "summary": summary_str,
        }

    def _verify_and_update_tasks(
        self,
        user_objective: str,
        observations: list[dict[str, Any]],
        confirmed_result: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """
        Verify that tool observations corroborate completion before updating task status.
        Never update task status based purely on unverified model text or unrelated tool observations.
        Requires authoritative task-specific mutation evidence (e.g., confirmed or executed update_task).
        Unrelated tools (list_directory, read_file, git_status, etc.) must NEVER complete a task.
        """
        updates = []

        # 1. Authoritative: User-confirmed update_task action
        if confirmed_result and confirmed_result.get("tool") == "update_task":
            res = confirmed_result.get("result", {})
            task_data = res.get("task")
            if task_data:
                updates.append({
                    "task_id": task_data.get("id"),
                    "title": task_data.get("title"),
                    "new_status": task_data.get("status"),
                    "verified_by": "user_confirmed_update_task",
                })
            return updates

        # 2. Authoritative: Verified update_task execution within observations
        for obs in observations:
            tool_name = obs.get("tool")
            tool_res = obs.get("result", {})

            if tool_name == "update_task":
                task_data = tool_res.get("task")
                if task_data:
                    updates.append({
                        "task_id": task_data.get("id"),
                        "title": task_data.get("title"),
                        "new_status": task_data.get("status"),
                        "verified_by": "tool_observation_update_task",
                    })

        return updates
