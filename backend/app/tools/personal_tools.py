"""
Personal Model mutation tools (Phase 4A).

Provides controlled, confirmation-required tools for updating the structured
Personal Model:
- update_project: Create or update a project record.
- update_task: Create or update a task record.
- record_decision: Create a decision record.
"""
from typing import Any

from ..memory.personal import (
    PROJECT_STATUSES,
    TASK_PRIORITIES,
    TASK_STATUSES,
    PersonalModelStore,
)
from .base import Tool
from .permissions import Permission


class UpdateProjectTool(Tool):
    name = "update_project"
    description = (
        "Create or update a project in Orion's Personal Model. Requires confirmation. "
        "Use ONLY when the user explicitly requests creating or updating a project. "
        "Canonical schemas: "
        "CREATE: {\"operation\": \"create\", \"name\": \"<string>\", \"description\": \"<optional string>\", \"path\": \"<optional string>\", \"repository\": \"<optional string>\", \"status\": \"<active|paused|completed|archived>\"}. "
        "UPDATE: {\"operation\": \"update\", \"project_id\": <positive integer>, \"name\": \"<optional string>\", \"description\": \"<optional string>\", \"path\": \"<optional string>\", \"repository\": \"<optional string>\", \"status\": \"<optional active|paused|completed|archived>\"}. "
        "operation is required. Update uses project_id, NOT id. Do not accept arbitrary fields. Never add confirmed:true or shell/code. update_project remains confirmation_required."
    )
    permission = Permission.CONFIRMATION_REQUIRED

    def __init__(self, store: PersonalModelStore | None = None) -> None:
        self.store = store or PersonalModelStore()

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        if "operation" not in kwargs:
            raise ValueError("Missing required field: 'operation'")

        op = str(kwargs["operation"]).strip().lower()
        if op not in ("create", "update"):
            raise ValueError(
                f"Invalid operation '{op}'. Supported operations: 'create', 'update'"
            )

        if op == "create":
            allowed_fields = {"operation", "name", "description", "path", "repository", "status"}
            extra = set(kwargs.keys()) - allowed_fields
            if extra:
                raise ValueError(f"Unexpected fields for create project: {sorted(extra)}")

            name = kwargs.get("name")
            if not name or not isinstance(name, str) or not name.strip():
                raise ValueError("Project name cannot be empty.")

            status = kwargs.get("status", "active")
            if status is not None:
                norm_status = str(status).strip().lower()
                if norm_status not in PROJECT_STATUSES:
                    raise ValueError(
                        f"Invalid project status '{status}'. Must be one of: {sorted(PROJECT_STATUSES)}"
                    )
            else:
                norm_status = "active"

            proj = self.store.create_project(
                name=name.strip(),
                description=str(kwargs.get("description") or "").strip(),
                path=kwargs.get("path"),
                repository=kwargs.get("repository"),
                status=norm_status,
            )
            return {
                "status": "created",
                "source": "user_confirmed_agent_action",
                "project": proj,
            }

        else:  # update
            allowed_fields = {"operation", "project_id", "name", "description", "path", "repository", "status"}
            extra = set(kwargs.keys()) - allowed_fields
            if extra:
                raise ValueError(f"Unexpected fields for update project: {sorted(extra)}")

            if "project_id" not in kwargs:
                raise ValueError("Missing required field: 'project_id'")

            try:
                project_id = int(kwargs["project_id"])
                if project_id <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                raise ValueError("project_id must be a positive integer.")

            update_data: dict[str, Any] = {}
            for k in ("name", "description", "path", "repository", "status"):
                if k in kwargs:
                    update_data[k] = kwargs[k]

            if not update_data:
                proj = self.store.get_project(project_id)
                if proj is None:
                    raise ValueError(f"Project with ID {project_id} not found.")
                return {
                    "status": "unchanged",
                    "source": "user_confirmed_agent_action",
                    "project": proj,
                }

            proj = self.store.update_project(project_id, **update_data)
            if proj is None:
                raise ValueError(f"Project with ID {project_id} not found.")

            return {
                "status": "updated",
                "source": "user_confirmed_agent_action",
                "project": proj,
            }


class UpdateTaskTool(Tool):
    name = "update_task"
    description = (
        "Create or update a task in Orion's Personal Model. Requires confirmation. "
        "Use ONLY when the user explicitly requests creating or updating a task."
    )
    permission = Permission.CONFIRMATION_REQUIRED

    def __init__(self, store: PersonalModelStore | None = None) -> None:
        self.store = store or PersonalModelStore()

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        if "operation" not in kwargs:
            raise ValueError("Missing required field: 'operation'")

        op = str(kwargs["operation"]).strip().lower()
        if op not in ("create", "update"):
            raise ValueError(
                f"Invalid operation '{op}'. Supported operations: 'create', 'update'"
            )

        if op == "create":
            allowed_fields = {
                "operation",
                "title",
                "description",
                "status",
                "priority",
                "project_id",
                "goal_id",
            }
            extra = set(kwargs.keys()) - allowed_fields
            if extra:
                raise ValueError(f"Unexpected fields for create task: {sorted(extra)}")

            title = kwargs.get("title")
            if not title or not isinstance(title, str) or not title.strip():
                raise ValueError("Task title cannot be empty.")

            status = kwargs.get("status", "todo")
            if status is not None:
                norm_status = str(status).strip().lower()
                if norm_status not in TASK_STATUSES:
                    raise ValueError(
                        f"Invalid task status '{status}'. Must be one of: {sorted(TASK_STATUSES)}"
                    )
            else:
                norm_status = "todo"

            priority = kwargs.get("priority", "medium")
            if priority is not None:
                norm_priority = str(priority).strip().lower()
                if norm_priority not in TASK_PRIORITIES:
                    raise ValueError(
                        f"Invalid task priority '{priority}'. Must be one of: {sorted(TASK_PRIORITIES)}"
                    )
            else:
                norm_priority = "medium"

            project_id = kwargs.get("project_id")
            if project_id is not None:
                try:
                    project_id = int(project_id)
                    if project_id <= 0:
                        raise ValueError
                except (ValueError, TypeError):
                    raise ValueError("project_id must be a positive integer.")

            goal_id = kwargs.get("goal_id")
            if goal_id is not None:
                try:
                    goal_id = int(goal_id)
                    if goal_id <= 0:
                        raise ValueError
                except (ValueError, TypeError):
                    raise ValueError("goal_id must be a positive integer.")

            task = self.store.create_task(
                title=title.strip(),
                description=str(kwargs.get("description") or "").strip(),
                status=norm_status,
                priority=norm_priority,
                project_id=project_id,
                goal_id=goal_id,
            )
            return {
                "status": "created",
                "source": "user_confirmed_agent_action",
                "task": task,
            }

        else:  # update
            allowed_fields = {
                "operation",
                "task_id",
                "title",
                "description",
                "status",
                "priority",
                "project_id",
                "goal_id",
            }
            extra = set(kwargs.keys()) - allowed_fields
            if extra:
                raise ValueError(f"Unexpected fields for update task: {sorted(extra)}")

            if "task_id" not in kwargs:
                raise ValueError("Missing required field: 'task_id'")

            try:
                task_id = int(kwargs["task_id"])
                if task_id <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                raise ValueError("task_id must be a positive integer.")

            update_data: dict[str, Any] = {}
            for k in ("title", "description", "status", "priority", "project_id", "goal_id"):
                if k in kwargs:
                    update_data[k] = kwargs[k]

            if not update_data:
                task = self.store.get_task(task_id)
                if task is None:
                    raise ValueError(f"Task with ID {task_id} not found.")
                return {
                    "status": "unchanged",
                    "source": "user_confirmed_agent_action",
                    "task": task,
                }

            task = self.store.update_task(task_id, **update_data)
            if task is None:
                raise ValueError(f"Task with ID {task_id} not found.")

            return {
                "status": "updated",
                "source": "user_confirmed_agent_action",
                "task": task,
            }


class RecordDecisionTool(Tool):
    name = "record_decision"
    description = (
        "Record an architectural or project decision in Orion's Personal Model. Requires confirmation. "
        "Use ONLY when the user explicitly asks Orion to record a decision. "
        "Canonical schema: "
        "{\"decision\": \"<non-empty string>\", \"context\": \"<optional string>\", \"project_id\": \"<optional positive integer>\"}. "
        "Rules: "
        "- decision is required and must contain the actual decision text requested by the user. "
        "- context is optional. "
        "- project_id is optional and must be a positive integer referring to an existing project. "
        "- reject unknown fields. "
        "- do not include confirmed:true. "
        "- no shell/code/arbitrary execution. "
        "- record_decision remains confirmation-required. "
        "- only use record_decision when the user explicitly asks Orion to record a decision."
    )
    permission = Permission.CONFIRMATION_REQUIRED

    def __init__(self, store: PersonalModelStore | None = None) -> None:
        self.store = store or PersonalModelStore()

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        allowed_fields = {"decision", "context", "project_id"}
        extra = set(kwargs.keys()) - allowed_fields
        if extra:
            raise ValueError(f"Unexpected fields for record_decision: {sorted(extra)}")

        decision = kwargs.get("decision")
        if not decision or not isinstance(decision, str) or not decision.strip():
            raise ValueError("Decision text cannot be empty.")

        project_id = kwargs.get("project_id")
        if project_id is not None:
            try:
                project_id = int(project_id)
                if project_id <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                raise ValueError("project_id must be a positive integer.")

        dec = self.store.create_decision(
            decision=decision.strip(),
            context=str(kwargs.get("context") or "").strip(),
            project_id=project_id,
        )
        return {
            "status": "recorded",
            "source": "user_confirmed_agent_action",
            "decision": dec,
        }
