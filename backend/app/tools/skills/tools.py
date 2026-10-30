"""
Skill Tools (Phase 4B).

Provides Orion tools for skill creation, updating, and execution:
- create_skill: Create a new reusable skill (confirmation_required).
- update_skill: Update an existing skill (confirmation_required).
- use_skill: Execute a reusable skill sequence through ToolRegistry (automatic,
  stopping if a step requires confirmation).
"""
import copy
import json
import time
from typing import Any

from ...memory.personal import PersonalModelStore
from ..audit import log_event
from ..base import Tool
from ..permissions import DEFAULT_TOOL_PERMISSIONS, Permission
from .learning import SkillLearningService
from .validator import SkillValidator


class CreateSkillTool(Tool):
    name = "create_skill"
    description = (
        "Create a reusable skill in Orion's Personal Model. Requires confirmation. "
        "Use ONLY when the user explicitly requests saving or creating a reusable skill. "
        "Arguments schema: {\"name\": string, \"description\": string, \"workflow\": {\"steps\": [{\"tool\": string, \"arguments\": {}}]}}. "
        "Never use top-level 'steps'."
    )
    permission = Permission.CONFIRMATION_REQUIRED

    def __init__(
        self,
        store: PersonalModelStore | None = None,
        registry: Any | None = None,
        learning_service: SkillLearningService | None = None,
    ) -> None:
        self.store = store or PersonalModelStore()
        self.registry = registry
        self.learning_service = learning_service or SkillLearningService(
            personal_store=self.store, registry=self.registry
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        allowed_keys = {"name", "description", "workflow"}
        extra = set(kwargs.keys()) - allowed_keys
        if extra:
            raise ValueError(f"Unexpected fields for create_skill: {sorted(extra)}")

        name = kwargs.get("name")
        if not name or not isinstance(name, str) or not name.strip():
            raise ValueError("Skill name cannot be empty.")

        description = kwargs.get("description", "")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("Skill description cannot be empty.")

        if "workflow" not in kwargs:
            raise ValueError("Missing required field: 'workflow'")

        workflow = kwargs["workflow"]
        validated_workflow = SkillValidator.validate_workflow(
            workflow,
            registry=self.registry,
        )

        workflow_json = json.dumps(validated_workflow, ensure_ascii=False)
        skill = self.store.create_skill(
            name=name.strip(),
            description=description.strip(),
            workflow=workflow_json,
        )

        # Snapshot initial version
        try:
            self.learning_service.save_version_snapshot(
                skill_id=skill["id"],
                change_summary="Initial creation of skill",
            )
        except Exception:
            pass

        return {
            "status": "created",
            "source": "user_confirmed_agent_action",
            "skill": skill,
        }


class UpdateSkillTool(Tool):
    name = "update_skill"
    description = (
        "Update an existing reusable skill in Orion's Personal Model. Requires confirmation. "
        "Use ONLY when the user explicitly requests updating a skill."
    )
    permission = Permission.CONFIRMATION_REQUIRED

    def __init__(
        self,
        store: PersonalModelStore | None = None,
        registry: Any | None = None,
        learning_service: SkillLearningService | None = None,
    ) -> None:
        self.store = store or PersonalModelStore()
        self.registry = registry
        self.learning_service = learning_service or SkillLearningService(
            personal_store=self.store, registry=self.registry
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        allowed_keys = {"skill_id", "name", "description", "workflow"}
        extra = set(kwargs.keys()) - allowed_keys
        if extra:
            raise ValueError(f"Unexpected fields for update_skill: {sorted(extra)}")

        if "skill_id" not in kwargs:
            raise ValueError("Missing required field: 'skill_id'")

        try:
            skill_id = int(kwargs["skill_id"])
            if skill_id <= 0:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("skill_id must be a positive integer.")

        update_fields: dict[str, Any] = {}
        if "name" in kwargs:
            name = kwargs["name"]
            if not name or not isinstance(name, str) or not name.strip():
                raise ValueError("Skill name cannot be empty.")
            update_fields["name"] = name.strip()

        if "description" in kwargs:
            desc = kwargs["description"]
            if not desc or not isinstance(desc, str) or not desc.strip():
                raise ValueError("Skill description cannot be empty.")
            update_fields["description"] = desc.strip()

        if "workflow" in kwargs:
            workflow = kwargs["workflow"]
            validated_wf = SkillValidator.validate_workflow(
                workflow,
                registry=self.registry,
            )
            update_fields["workflow"] = json.dumps(validated_wf, ensure_ascii=False)

        if not update_fields:
            skill = self.store.get_skill(skill_id)
            if skill is None:
                raise ValueError(f"Skill with ID {skill_id} not found.")
            return {
                "status": "unchanged",
                "source": "user_confirmed_agent_action",
                "skill": skill,
            }

        # Snapshot before update for rollback
        try:
            self.learning_service.save_version_snapshot(
                skill_id=skill_id,
                change_summary="Pre-update snapshot",
            )
        except Exception:
            pass

        skill = self.store.update_skill(skill_id, **update_fields)
        if skill is None:
            raise ValueError(f"Skill with ID {skill_id} not found.")

        # Snapshot post-update version
        try:
            self.learning_service.save_version_snapshot(
                skill_id=skill_id,
                change_summary="User confirmed skill update",
            )
        except Exception:
            pass

        return {
            "status": "updated",
            "source": "user_confirmed_agent_action",
            "skill": skill,
        }


class UseSkillTool(Tool):
    name = "use_skill"
    description = (
        "Execute a stored reusable skill workflow. Runs automatic tools immediately; "
        "halts and requests confirmation if any step requires user confirmation."
    )
    permission = Permission.AUTOMATIC

    def __init__(
        self,
        registry: Any,
        store: PersonalModelStore | None = None,
        learning_service: SkillLearningService | None = None,
    ) -> None:
        self.registry = registry
        self.store = store or PersonalModelStore()
        self.learning_service = learning_service or SkillLearningService(
            personal_store=self.store, registry=self.registry
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        start_time = time.perf_counter()
        session_id = kwargs.get("session_id")
        skill_id = kwargs.get("skill_id")
        skill_name = kwargs.get("skill_name")

        skill: dict[str, Any] | None = None
        if skill_id is not None:
            try:
                s_id = int(skill_id)
                skill = self.store.get_skill(s_id)
            except (ValueError, TypeError):
                raise ValueError("skill_id must be a positive integer.")
        elif skill_name is not None and isinstance(skill_name, str):
            norm_name = skill_name.strip().lower()
            all_skills = self.store.list_skills(limit=100)
            for s in all_skills:
                if (s.get("name") or "").strip().lower() == norm_name:
                    skill = s
                    break

        if skill is None:
            target = skill_id if skill_id is not None else skill_name
            raise ValueError(f"Skill '{target}' not found.")

        # Parse and validate workflow
        raw_wf = skill.get("workflow", "")
        validated_wf = SkillValidator.validate_workflow(raw_wf, registry=self.registry)
        steps = validated_wf["steps"]

        executed_steps: list[dict[str, Any]] = []

        log_event(
            event="skill_execution_started",
            tool=self.name,
            arguments={"skill_id": skill["id"], "skill_name": skill["name"]},
            status="started",
        )

        for idx, step in enumerate(steps, start=1):
            tool_name = step["tool"]
            tool_args = copy.deepcopy(step.get("arguments") or {})
            tool_args.pop("confirmed", None)

            # Inspect permission via registry
            tool_obj = self.registry.get(tool_name)
            perm = DEFAULT_TOOL_PERMISSIONS.get(tool_name, tool_obj.permission)

            # 1. BLOCKED
            if perm == Permission.BLOCKED:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                try:
                    self.learning_service.record_execution(
                        skill_id=skill["id"],
                        status="blocked",
                        step_results=executed_steps,
                        failure_reason=f"Blocked tool '{tool_name}' at step {idx}",
                        duration_ms=duration_ms,
                        session_id=session_id,
                    )
                except Exception:
                    pass

                log_event(
                    event="skill_execution_stopped",
                    tool=self.name,
                    arguments={"skill_id": skill["id"], "blocked_tool": tool_name},
                    status="blocked",
                )
                return {
                    "status": "blocked",
                    "skill_id": skill["id"],
                    "skill_name": skill["name"],
                    "stopped_at_step": idx,
                    "blocked_tool": tool_name,
                    "executed_steps": executed_steps,
                    "message": f"Skill execution stopped: Tool '{tool_name}' is blocked by Orion's security policy.",
                }

            # 2. CONFIRMATION_REQUIRED
            if perm == Permission.CONFIRMATION_REQUIRED:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                try:
                    self.learning_service.record_execution(
                        skill_id=skill["id"],
                        status="confirmation_required",
                        step_results=executed_steps,
                        failure_reason=f"Confirmation required for '{tool_name}' at step {idx}",
                        duration_ms=duration_ms,
                        session_id=session_id,
                    )
                except Exception:
                    pass

                log_event(
                    event="skill_execution_stopped",
                    tool=self.name,
                    arguments={
                        "skill_id": skill["id"],
                        "pending_tool": tool_name,
                        "pending_arguments": tool_args,
                    },
                    status="confirmation_required",
                )
                return {
                    "status": "confirmation_required",
                    "skill_id": skill["id"],
                    "skill_name": skill["name"],
                    "stopped_at_step": idx,
                    "pending_tool": tool_name,
                    "pending_arguments": tool_args,
                    "executed_steps": executed_steps,
                    "message": f"Skill execution stopped at step {idx}: Tool '{tool_name}' requires explicit user confirmation.",
                }

            # 3. AUTOMATIC — Execute via ToolRegistry.execute
            try:
                step_result = await self.registry.execute(tool_name, **tool_args)
                executed_steps.append({
                    "step": idx,
                    "tool": tool_name,
                    "result": step_result,
                })
            except Exception as exc:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                try:
                    self.learning_service.record_execution(
                        skill_id=skill["id"],
                        status="error",
                        step_results=executed_steps,
                        failure_reason=str(exc),
                        duration_ms=duration_ms,
                        session_id=session_id,
                    )
                except Exception:
                    pass

                log_event(
                    event="skill_execution_error",
                    tool=self.name,
                    arguments={"skill_id": skill["id"], "failed_tool": tool_name},
                    status="error",
                    result={"error": str(exc)},
                )
                return {
                    "status": "error",
                    "skill_id": skill["id"],
                    "skill_name": skill["name"],
                    "stopped_at_step": idx,
                    "error_tool": tool_name,
                    "error": str(exc),
                    "executed_steps": executed_steps,
                    "message": f"Skill execution failed at step {idx} ({tool_name}): {exc}",
                }

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        try:
            self.learning_service.record_execution(
                skill_id=skill["id"],
                status="completed",
                step_results=executed_steps,
                failure_reason=None,
                duration_ms=duration_ms,
                session_id=session_id,
            )
        except Exception:
            pass

        log_event(
            event="skill_execution_completed",
            tool=self.name,
            arguments={"skill_id": skill["id"], "skill_name": skill["name"]},
            status="success",
            result={"steps_executed": len(executed_steps), "duration_ms": duration_ms},
        )

        return {
            "status": "completed",
            "skill_id": skill["id"],
            "skill_name": skill["name"],
            "executed_steps": executed_steps,
            "duration_ms": duration_ms,
        }
