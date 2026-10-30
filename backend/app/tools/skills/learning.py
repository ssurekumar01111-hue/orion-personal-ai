"""
Skill Learning Service for Orion (Phase LEARN).

Provides:
- Persistent execution history for reusable skills (executions, durations, step outcomes).
- Pattern analysis identifying repeated failures, blocked tools, and optimization opportunities.
- Generation of safe, structured skill improvement proposals validated by SkillValidator.
- Strict requirement that executable changes must be explicitly approved by the user.
- Version tracking and rollback support for skills.
- Zero permission escalation: proposals cannot introduce blocked tools or bypass safety constraints.
"""
from datetime import datetime, timezone
import json
import time
from typing import Any

from ...memory.database import get_connection
from ...memory.personal import PersonalModelStore
from ..audit import _sanitize_payload, _scrub_secrets, log_event
from ..permissions import DEFAULT_TOOL_PERMISSIONS, Permission
from .validator import SkillValidator


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SkillLearningService:
    """
    Evaluates skill executions and manages improvement proposals, versions, and rollbacks.
    """

    def __init__(
        self,
        personal_store: PersonalModelStore | None = None,
        registry: Any | None = None,
    ) -> None:
        self.personal_store = personal_store or PersonalModelStore()
        self.registry = registry

    # ── 1. Execution History ──────────────────────────────────────────────────

    def record_execution(
        self,
        skill_id: int,
        status: str,
        step_results: list[dict[str, Any]],
        failure_reason: str | None = None,
        duration_ms: float = 0.0,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Record a skill execution outcome into persistent SQLite storage.
        Triggers evaluation and potential improvement proposal generation.
        """
        now = _now_iso()
        safe_steps = _sanitize_payload(step_results or [])
        steps_json = json.dumps(safe_steps, ensure_ascii=False)
        safe_failure = _scrub_secrets(failure_reason) if failure_reason else None

        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO skill_executions (
                    skill_id, session_id, status, step_results, failure_reason, duration_ms, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (skill_id, session_id, status, steps_json, safe_failure, float(duration_ms), now),
            )
            connection.commit()
            exec_id = cursor.lastrowid

            row = connection.execute(
                "SELECT * FROM skill_executions WHERE id = ?",
                (exec_id,),
            ).fetchone()

        exec_record = dict(row)

        log_event(
            event="skill_execution_recorded",
            tool="use_skill",
            arguments={"skill_id": skill_id, "status": status},
            status=status,
            result={"execution_id": exec_id, "duration_ms": duration_ms},
        )

        # Trigger automatic evaluation if failure or repeated pattern occurs
        self.evaluate_skill_performance(skill_id)

        return exec_record

    def get_execution_history(self, skill_id: int, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(100, limit))
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM skill_executions
                WHERE skill_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (skill_id, limit),
            ).fetchall()

        results = []
        for r in rows:
            d = dict(r)
            try:
                d["step_results"] = json.loads(d["step_results"])
            except Exception:
                d["step_results"] = []
            results.append(d)
        return results

    # ── 2. Performance Evaluation & Improvement Proposals ─────────────────────

    def evaluate_skill_performance(self, skill_id: int) -> dict[str, Any] | None:
        """
        Analyze recent execution history for the given skill to identify:
        - Repeated failures at a specific step
        - Blocked tools attempted in steps
        - Opportunities to improve or optimize the workflow
        Generates a pending proposal if an improvement opportunity is detected.
        """
        skill = self.personal_store.get_skill(skill_id)
        if not skill:
            return None

        history = self.get_execution_history(skill_id, limit=10)
        if not history:
            return None

        # Check existing pending proposals to avoid duplicate proposals
        existing_proposals = self.list_proposals(skill_id, status="pending")
        if existing_proposals:
            return existing_proposals[0]

        recent = history[0]
        recent_status = recent.get("status")

        # Case A: Execution failed with error
        if recent_status in ("error", "failed"):
            failure_reason = recent.get("failure_reason") or "Unknown execution failure"
            raw_wf = skill.get("workflow", "")
            try:
                parsed_wf = json.loads(raw_wf) if isinstance(raw_wf, str) else raw_wf
            except Exception:
                return None

            steps = parsed_wf.get("steps", []) if isinstance(parsed_wf, dict) else []
            if not steps:
                return None

            # Check if failure was caused by missing file inspection before file action
            # e.g., read_file on non-existent file -> propose adding list_directory check
            failed_tool = None
            step_results = recent.get("step_results", [])
            for s in step_results:
                if s.get("status") in ("error", "failed") or "error" in s:
                    failed_tool = s.get("tool")
                    break

            # Synthesize improvement proposal
            revised_steps = []
            for step in steps:
                revised_steps.append(dict(step))

            # If failed_tool was read_file or read_file in failure_reason, propose checking directory first
            is_read_file_failure = (
                failed_tool == "read_file"
                or "read_file" in str(failure_reason).lower()
                or "filenotfound" in str(failure_reason).lower()
            )
            if is_read_file_failure and not any(s.get("tool") == "list_directory" for s in revised_steps):
                revised_steps.insert(0, {
                    "tool": "list_directory",
                    "arguments": {"path": "."},
                })
                proposal_title = f"Add directory inspection before read_file in {skill['name']}"
                proposal_rationale = (
                    f"Execution #{recent['id']} failed with error: '{failure_reason}'. "
                    "Adding list_directory ensures files exist before attempting to read them."
                )
            else:
                proposal_title = f"Improve step robustness for {skill['name']}"
                proposal_rationale = (
                    f"Execution #{recent['id']} encountered failure: '{failure_reason}'. "
                    "Reviewing arguments and step sequence to prevent repeated failures."
                )

            proposed_wf = {"steps": revised_steps}
            try:
                return self.create_proposal(
                    skill_id=skill_id,
                    title=proposal_title,
                    description=f"Automated improvement suggestion following failure in execution #{recent['id']}",
                    proposed_workflow=proposed_wf,
                    rationale=proposal_rationale,
                )
            except Exception:
                return None

        # Case B: Check for optimization (e.g. repeated redundant steps)
        raw_wf = skill.get("workflow", "")
        try:
            parsed_wf = json.loads(raw_wf) if isinstance(raw_wf, str) else raw_wf
            steps = parsed_wf.get("steps", []) if isinstance(parsed_wf, dict) else []
            # Check for adjacent identical tools with same arguments
            cleaned_steps = []
            has_redundancy = False
            for s in steps:
                if cleaned_steps and s == cleaned_steps[-1]:
                    has_redundancy = True
                    continue
                cleaned_steps.append(s)

            if has_redundancy and len(cleaned_steps) < len(steps):
                return self.create_proposal(
                    skill_id=skill_id,
                    title=f"Deduplicate redundant workflow steps in {skill['name']}",
                    description="Remove identical consecutive tool invocations to improve execution speed.",
                    proposed_workflow={"steps": cleaned_steps},
                    rationale="Observed identical consecutive steps in skill workflow.",
                )
        except Exception:
            pass

        return None

    def create_proposal(
        self,
        skill_id: int,
        title: str,
        description: str,
        proposed_workflow: dict[str, Any] | str,
        rationale: str,
    ) -> dict[str, Any]:
        """
        Create an improvement proposal.
        Strictly validates the proposed workflow through SkillValidator.
        Validates that no permissions are escalated (no BLOCKED tools).
        Never overwrites the active skill without user approval.
        """
        skill = self.personal_store.get_skill(skill_id)
        if not skill:
            raise ValueError(f"Skill with ID {skill_id} does not exist.")

        # 1. Structural & security validation via SkillValidator
        validated_wf = SkillValidator.validate_workflow(
            proposed_workflow,
            registry=self.registry,
        )

        # 2. Permission check: verify no proposed step uses a BLOCKED tool
        for idx, step in enumerate(validated_wf["steps"], start=1):
            tool_name = step["tool"]
            perm = DEFAULT_TOOL_PERMISSIONS.get(tool_name)
            if perm == Permission.BLOCKED:
                raise PermissionError(
                    f"Proposed improvement attempts to introduce blocked tool '{tool_name}' (step {idx})."
                )

        wf_json = json.dumps(validated_wf, ensure_ascii=False)
        now = _now_iso()

        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO skill_proposals (
                    skill_id, title, description, proposed_workflow, rationale, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (skill_id, title.strip(), description.strip(), wf_json, rationale.strip(), now),
            )
            connection.commit()
            prop_id = cursor.lastrowid

            row = connection.execute(
                "SELECT * FROM skill_proposals WHERE id = ?",
                (prop_id,),
            ).fetchone()

        log_event(
            event="skill_proposal_created",
            tool="create_proposal",
            arguments={"skill_id": skill_id, "proposal_id": prop_id, "title": title},
            status="pending_approval",
        )

        return dict(row)

    def list_proposals(self, skill_id: int, status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM skill_proposals WHERE skill_id = ?"
        params: list[Any] = [skill_id]
        if status:
            query += " AND status = ?"
            params.append(status.strip().lower())
        query += " ORDER BY created_at DESC, id DESC"

        with get_connection() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()

        proposals = []
        for r in rows:
            d = dict(r)
            try:
                d["proposed_workflow"] = json.loads(d["proposed_workflow"])
            except Exception:
                pass
            proposals.append(d)
        return proposals

    def get_proposal(self, proposal_id: int) -> dict[str, Any] | None:
        with get_connection() as connection:
            row = connection.execute(
                "SELECT * FROM skill_proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["proposed_workflow"] = json.loads(d["proposed_workflow"])
        except Exception:
            pass
        return d

    # ── 3. User Approval & Version Control ────────────────────────────────────

    def approve_proposal(
        self,
        skill_id: int,
        proposal_id: int,
        change_summary: str = "Applied user-approved improvement proposal",
    ) -> dict[str, Any]:
        """
        Explicitly approve and apply a skill proposal inside a single atomic SQLite transaction.
        Requires explicit user authorization.
        Snapshots current skill to skill_versions before applying changes.
        """
        now = _now_iso()

        with get_connection() as connection:
            # 1. Fetch proposal within transaction
            prop_row = connection.execute(
                "SELECT * FROM skill_proposals WHERE id = ? AND skill_id = ?",
                (proposal_id, skill_id),
            ).fetchone()
            if not prop_row:
                raise ValueError(f"Proposal with ID {proposal_id} does not exist for skill {skill_id}.")

            if prop_row["status"] != "pending":
                raise ValueError(
                    f"Proposal {proposal_id} cannot be approved (current status: {prop_row['status']})."
                )

            # 2. Fetch skill within transaction
            skill_row = connection.execute(
                "SELECT * FROM skills WHERE id = ?",
                (skill_id,),
            ).fetchone()
            if not skill_row:
                raise ValueError(f"Skill with ID {skill_id} does not exist.")

            # 3. Validate proposed workflow via SkillValidator
            raw_wf = prop_row["proposed_workflow"]
            try:
                parsed_wf = json.loads(raw_wf) if isinstance(raw_wf, str) else raw_wf
            except Exception:
                parsed_wf = raw_wf

            validated_wf = SkillValidator.validate_workflow(
                parsed_wf,
                registry=self.registry,
            )
            wf_json = json.dumps(validated_wf, ensure_ascii=False)

            # 4. Atomic conditional transition:
            # UPDATE skill_proposals SET status = 'approved', applied_at = ?
            # WHERE id = ? AND skill_id = ? AND status = 'pending'
            cursor = connection.execute(
                """
                UPDATE skill_proposals
                SET status = 'approved', applied_at = ?
                WHERE id = ? AND skill_id = ? AND status = 'pending'
                """,
                (now, proposal_id, skill_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    f"Proposal {proposal_id} could not be approved (already approved, rejected, or concurrent modification)."
                )

            # 5. Snapshot current version for rollback (inside transaction)
            self.save_version_snapshot(
                skill_id=skill_id,
                change_summary=f"Pre-update snapshot before applying proposal #{proposal_id}",
                connection=connection,
            )

            # 6. Update active skill workflow (inside transaction)
            connection.execute(
                """
                UPDATE skills
                SET workflow = ?, updated_at = ?
                WHERE id = ?
                """,
                (wf_json, now, skill_id),
            )

            # 7. Snapshot new approved version (inside transaction)
            self.save_version_snapshot(
                skill_id=skill_id,
                change_summary=change_summary or f"Applied proposal #{proposal_id}: {prop_row['title']}",
                connection=connection,
            )

            connection.commit()

        # Fetch updated skill for response
        updated_skill = self.personal_store.get_skill(skill_id)

        log_event(
            event="skill_proposal_approved",
            tool="approve_proposal",
            arguments={"skill_id": skill_id, "proposal_id": proposal_id},
            status="approved",
            result={"skill_id": skill_id, "updated": True},
        )

        return {
            "status": "approved",
            "skill_id": skill_id,
            "proposal_id": proposal_id,
            "skill": updated_skill,
        }

    def reject_proposal(self, skill_id: int, proposal_id: int) -> dict[str, Any]:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                UPDATE skill_proposals
                SET status = 'rejected'
                WHERE id = ? AND skill_id = ? AND status = 'pending'
                """,
                (proposal_id, skill_id),
            )
            if cursor.rowcount != 1:
                row = connection.execute(
                    "SELECT * FROM skill_proposals WHERE id = ? AND skill_id = ?",
                    (proposal_id, skill_id),
                ).fetchone()
                if not row:
                    raise ValueError(f"Proposal with ID {proposal_id} does not exist.")
                raise ValueError(f"Proposal {proposal_id} is not pending (status: {row['status']}).")
            connection.commit()

        log_event(
            event="skill_proposal_rejected",
            tool="reject_proposal",
            arguments={"skill_id": skill_id, "proposal_id": proposal_id},
            status="rejected",
        )

        return {
            "status": "rejected",
            "skill_id": skill_id,
            "proposal_id": proposal_id,
        }

    # ── 4. Version Management & Rollback ──────────────────────────────────────

    def save_version_snapshot(
        self,
        skill_id: int,
        change_summary: str = "",
        connection: Any | None = None,
    ) -> dict[str, Any]:
        now = _now_iso()

        def _do_snapshot(conn):
            skill_row = conn.execute(
                "SELECT * FROM skills WHERE id = ?",
                (skill_id,),
            ).fetchone()
            if not skill_row:
                raise ValueError(f"Skill with ID {skill_id} does not exist.")

            last_v = conn.execute(
                "SELECT COALESCE(MAX(version_number), 0) as max_v FROM skill_versions WHERE skill_id = ?",
                (skill_id,),
            ).fetchone()
            next_v = (last_v["max_v"] or 0) + 1

            cursor = conn.execute(
                """
                INSERT INTO skill_versions (
                    skill_id, version_number, name, description, workflow, change_summary, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    skill_id,
                    next_v,
                    skill_row["name"],
                    skill_row["description"] or "",
                    skill_row["workflow"] or "",
                    change_summary,
                    now,
                ),
            )
            v_id = cursor.lastrowid
            row = conn.execute(
                "SELECT * FROM skill_versions WHERE id = ?", (v_id,)
            ).fetchone()
            return dict(row)

        if connection is not None:
            return _do_snapshot(connection)

        with get_connection() as conn:
            res = _do_snapshot(conn)
            conn.commit()
            return res

    def list_versions(self, skill_id: int) -> list[dict[str, Any]]:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM skill_versions
                WHERE skill_id = ?
                ORDER BY version_number DESC
                """,
                (skill_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def rollback_to_version(self, skill_id: int, version_number: int) -> dict[str, Any]:
        """
        Rollback a skill to a specific previous version inside a single transaction.
        Validates target workflow with SkillValidator before restoring.
        """
        now = _now_iso()
        with get_connection() as connection:
            target_v = connection.execute(
                """
                SELECT * FROM skill_versions
                WHERE skill_id = ? AND version_number = ?
                """,
                (skill_id, version_number),
            ).fetchone()

            if not target_v:
                raise ValueError(f"Version {version_number} does not exist for skill {skill_id}.")

            target_dict = dict(target_v)

            # Validate workflow of target version before applying
            validated_wf = SkillValidator.validate_workflow(
                target_dict["workflow"],
                registry=self.registry,
            )
            wf_json = json.dumps(validated_wf, ensure_ascii=False)

            # Snapshot current state before rolling back (inside transaction)
            self.save_version_snapshot(
                skill_id=skill_id,
                change_summary=f"Snapshot before rollback to version {version_number}",
                connection=connection,
            )

            # Restore skill in database (inside transaction)
            connection.execute(
                """
                UPDATE skills
                SET name = ?, description = ?, workflow = ?, updated_at = ?
                WHERE id = ?
                """,
                (target_dict["name"], target_dict["description"], wf_json, now, skill_id),
            )

            # Snapshot restored state (inside transaction)
            restored_snapshot = self.save_version_snapshot(
                skill_id=skill_id,
                change_summary=f"Rolled back to version {version_number}",
                connection=connection,
            )

            connection.commit()

        updated_skill = self.personal_store.get_skill(skill_id)

        log_event(
            event="skill_rollback",
            tool="rollback_to_version",
            arguments={"skill_id": skill_id, "target_version": version_number},
            status="success",
            result={"restored_version": version_number},
        )

        return {
            "status": "rolled_back",
            "skill_id": skill_id,
            "restored_version": version_number,
            "skill": updated_skill,
            "version_snapshot": restored_snapshot,
        }
