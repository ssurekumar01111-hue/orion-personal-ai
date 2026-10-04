"""
Personal Model Store and Service for Orion.

Provides a structured, explicit knowledge layer for:
- Projects
- Goals
- Tasks
- Decisions
- Skills

All operations use parameterized SQL, application-level UTC timestamps,
controlled status/priority validation, and strict foreign-key integrity.
"""
from datetime import datetime, timezone
import sqlite3
from typing import Any

from .database import get_connection

PROJECT_STATUSES = frozenset({"active", "paused", "completed", "archived"})
GOAL_STATUSES = frozenset({"active", "paused", "completed", "abandoned"})
TASK_STATUSES = frozenset({"todo", "pending", "in_progress", "blocked", "completed", "cancelled"})
TASK_PRIORITIES = frozenset({"low", "medium", "high", "urgent"})


def _now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _validate_id(item_id: Any, name: str = "id") -> int:
    """Ensure item_id is a positive integer."""
    if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return item_id


def _validate_non_empty_str(val: Any, name: str) -> str:
    """Ensure val is a non-empty string."""
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f"{name} cannot be empty.")
    return val.strip()


def _check_project_exists(connection: sqlite3.Connection, project_id: int) -> None:
    """Verify that project_id exists in the projects table."""
    row = connection.execute(
        "SELECT id FROM projects WHERE id = ?",
        (project_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"Project with id {project_id} does not exist.")


def _check_goal_exists(connection: sqlite3.Connection, goal_id: int) -> None:
    """Verify that goal_id exists in the goals table."""
    row = connection.execute(
        "SELECT id FROM goals WHERE id = ?",
        (goal_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"Goal with id {goal_id} does not exist.")


class PersonalModelStore:
    """
    Repository layer for the Orion structured Personal Model.
    All database access uses parameterized queries.
    """

    # ── Projects ─────────────────────────────────────────────────────────────

    def create_project(
        self,
        name: str,
        description: str = "",
        path: str | None = None,
        repository: str | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        valid_name = _validate_non_empty_str(name, "Project name")
        norm_status = status.strip().lower()
        if norm_status not in PROJECT_STATUSES:
            raise ValueError(
                f"Invalid project status '{status}'. Must be one of: {sorted(PROJECT_STATUSES)}"
            )

        now = _now_iso()

        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO projects (
                    name, description, path, repository, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (valid_name, description.strip(), path, repository, norm_status, now, now),
            )
            connection.commit()
            project_id = cursor.lastrowid

            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()

        return dict(row)

    def get_project(self, project_id: int) -> dict[str, Any] | None:
        valid_id = _validate_id(project_id, "project_id")
        with get_connection() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?",
                (valid_id,),
            ).fetchone()

        return dict(row) if row else None

    def list_projects(
        self,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        limit = min(limit, 200)
        query = "SELECT * FROM projects"
        params: list[Any] = []

        if status:
            norm_status = status.strip().lower()
            query += " WHERE status = ?"
            params.append(norm_status)

        query += " ORDER BY updated_at DESC, id DESC LIMIT ?"
        params.append(limit)

        with get_connection() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()

        return [dict(row) for row in rows]

    def update_project(
        self,
        project_id: int,
        **fields: Any,
    ) -> dict[str, Any] | None:
        valid_id = _validate_id(project_id, "project_id")
        allowed_fields = {"name", "description", "path", "repository", "status"}
        update_keys = [k for k in fields if k in allowed_fields]

        if not update_keys:
            return self.get_project(valid_id)

        values: list[Any] = []
        set_clauses: list[str] = []

        for key in update_keys:
            val = fields[key]
            if key == "name":
                val = _validate_non_empty_str(val, "Project name")
            elif key == "status":
                val = val.strip().lower()
                if val not in PROJECT_STATUSES:
                    raise ValueError(
                        f"Invalid project status '{val}'. Must be one of: {sorted(PROJECT_STATUSES)}"
                    )
            elif key == "description":
                val = val.strip() if isinstance(val, str) else ""

            set_clauses.append(f"{key} = ?")
            values.append(val)

        now = _now_iso()
        set_clauses.append("updated_at = ?")
        values.append(now)
        values.append(valid_id)

        with get_connection() as connection:
            # Check existence first
            existing = connection.execute(
                "SELECT id FROM projects WHERE id = ?",
                (valid_id,),
            ).fetchone()
            if not existing:
                return None

            sql = f"UPDATE projects SET {', '.join(set_clauses)} WHERE id = ?"
            connection.execute(sql, tuple(values))
            connection.commit()

            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?",
                (valid_id,),
            ).fetchone()

        return dict(row) if row else None

    def delete_project(self, project_id: int) -> bool:
        valid_id = _validate_id(project_id, "project_id")
        with get_connection() as connection:
            cursor = connection.execute(
                "DELETE FROM projects WHERE id = ?",
                (valid_id,),
            )
            connection.commit()
            return cursor.rowcount > 0

    # ── Goals ────────────────────────────────────────────────────────────────

    def create_goal(
        self,
        title: str,
        description: str = "",
        status: str = "active",
        project_id: int | None = None,
    ) -> dict[str, Any]:
        valid_title = _validate_non_empty_str(title, "Goal title")
        norm_status = status.strip().lower()
        if norm_status not in GOAL_STATUSES:
            raise ValueError(
                f"Invalid goal status '{status}'. Must be one of: {sorted(GOAL_STATUSES)}"
            )

        now = _now_iso()

        with get_connection() as connection:
            if project_id is not None:
                valid_proj_id = _validate_id(project_id, "project_id")
                _check_project_exists(connection, valid_proj_id)
            else:
                valid_proj_id = None

            cursor = connection.execute(
                """
                INSERT INTO goals (
                    title, description, status, project_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (valid_title, description.strip(), norm_status, valid_proj_id, now, now),
            )
            connection.commit()
            goal_id = cursor.lastrowid

            row = connection.execute(
                "SELECT * FROM goals WHERE id = ?",
                (goal_id,),
            ).fetchone()

        return dict(row)

    def get_goal(self, goal_id: int) -> dict[str, Any] | None:
        valid_id = _validate_id(goal_id, "goal_id")
        with get_connection() as connection:
            row = connection.execute(
                "SELECT * FROM goals WHERE id = ?",
                (valid_id,),
            ).fetchone()

        return dict(row) if row else None

    def list_goals(
        self,
        project_id: int | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        limit = min(limit, 200)
        query = "SELECT * FROM goals"
        conditions: list[str] = []
        params: list[Any] = []

        if project_id is not None:
            valid_proj_id = _validate_id(project_id, "project_id")
            conditions.append("project_id = ?")
            params.append(valid_proj_id)

        if status:
            norm_status = status.strip().lower()
            conditions.append("status = ?")
            params.append(norm_status)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY updated_at DESC, id DESC LIMIT ?"
        params.append(limit)

        with get_connection() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()

        return [dict(row) for row in rows]

    def update_goal(
        self,
        goal_id: int,
        **fields: Any,
    ) -> dict[str, Any] | None:
        valid_id = _validate_id(goal_id, "goal_id")
        allowed_fields = {"title", "description", "status", "project_id"}
        update_keys = [k for k in fields if k in allowed_fields]

        if not update_keys:
            return self.get_goal(valid_id)

        values: list[Any] = []
        set_clauses: list[str] = []

        with get_connection() as connection:
            existing = connection.execute(
                "SELECT id FROM goals WHERE id = ?",
                (valid_id,),
            ).fetchone()
            if not existing:
                return None

            for key in update_keys:
                val = fields[key]
                if key == "title":
                    val = _validate_non_empty_str(val, "Goal title")
                elif key == "status":
                    val = val.strip().lower()
                    if val not in GOAL_STATUSES:
                        raise ValueError(
                            f"Invalid goal status '{val}'. Must be one of: {sorted(GOAL_STATUSES)}"
                        )
                elif key == "project_id":
                    if val is not None:
                        val = _validate_id(val, "project_id")
                        _check_project_exists(connection, val)
                elif key == "description":
                    val = val.strip() if isinstance(val, str) else ""

                set_clauses.append(f"{key} = ?")
                values.append(val)

            now = _now_iso()
            set_clauses.append("updated_at = ?")
            values.append(now)
            values.append(valid_id)

            sql = f"UPDATE goals SET {', '.join(set_clauses)} WHERE id = ?"
            connection.execute(sql, tuple(values))
            connection.commit()

            row = connection.execute(
                "SELECT * FROM goals WHERE id = ?",
                (valid_id,),
            ).fetchone()

        return dict(row) if row else None

    def delete_goal(self, goal_id: int) -> bool:
        valid_id = _validate_id(goal_id, "goal_id")
        with get_connection() as connection:
            cursor = connection.execute(
                "DELETE FROM goals WHERE id = ?",
                (valid_id,),
            )
            connection.commit()
            return cursor.rowcount > 0

    # ── Tasks ────────────────────────────────────────────────────────────────

    def create_task(
        self,
        title: str,
        description: str = "",
        status: str = "todo",
        priority: str = "medium",
        project_id: int | None = None,
        goal_id: int | None = None,
    ) -> dict[str, Any]:
        valid_title = _validate_non_empty_str(title, "Task title")
        norm_status = status.strip().lower()
        if norm_status not in TASK_STATUSES:
            raise ValueError(
                f"Invalid task status '{status}'. Must be one of: {sorted(TASK_STATUSES)}"
            )

        norm_priority = priority.strip().lower()
        if norm_priority not in TASK_PRIORITIES:
            raise ValueError(
                f"Invalid task priority '{priority}'. Must be one of: {sorted(TASK_PRIORITIES)}"
            )

        now = _now_iso()

        with get_connection() as connection:
            if project_id is not None:
                valid_proj_id = _validate_id(project_id, "project_id")
                _check_project_exists(connection, valid_proj_id)
            else:
                valid_proj_id = None

            if goal_id is not None:
                valid_goal_id = _validate_id(goal_id, "goal_id")
                _check_goal_exists(connection, valid_goal_id)
            else:
                valid_goal_id = None

            cursor = connection.execute(
                """
                INSERT INTO tasks (
                    title, description, status, priority, project_id, goal_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (valid_title, description.strip(), norm_status, norm_priority, valid_proj_id, valid_goal_id, now, now),
            )
            connection.commit()
            task_id = cursor.lastrowid

            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()

        return dict(row)

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        valid_id = _validate_id(task_id, "task_id")
        with get_connection() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (valid_id,),
            ).fetchone()

        return dict(row) if row else None

    def list_tasks(
        self,
        project_id: int | None = None,
        goal_id: int | None = None,
        status: str | None = None,
        priority: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        limit = min(limit, 200)
        query = "SELECT * FROM tasks"
        conditions: list[str] = []
        params: list[Any] = []

        if project_id is not None:
            valid_proj_id = _validate_id(project_id, "project_id")
            conditions.append("project_id = ?")
            params.append(valid_proj_id)

        if goal_id is not None:
            valid_goal_id = _validate_id(goal_id, "goal_id")
            conditions.append("goal_id = ?")
            params.append(valid_goal_id)

        if status:
            norm_status = status.strip().lower()
            conditions.append("status = ?")
            params.append(norm_status)

        if priority:
            norm_priority = priority.strip().lower()
            conditions.append("priority = ?")
            params.append(norm_priority)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY updated_at DESC, id DESC LIMIT ?"
        params.append(limit)

        with get_connection() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()

        return [dict(row) for row in rows]

    def update_task(
        self,
        task_id: int,
        **fields: Any,
    ) -> dict[str, Any] | None:
        valid_id = _validate_id(task_id, "task_id")
        allowed_fields = {"title", "description", "status", "priority", "project_id", "goal_id"}
        update_keys = [k for k in fields if k in allowed_fields]

        if not update_keys:
            return self.get_task(valid_id)

        values: list[Any] = []
        set_clauses: list[str] = []

        with get_connection() as connection:
            existing = connection.execute(
                "SELECT id FROM tasks WHERE id = ?",
                (valid_id,),
            ).fetchone()
            if not existing:
                return None

            for key in update_keys:
                val = fields[key]
                if key == "title":
                    val = _validate_non_empty_str(val, "Task title")
                elif key == "status":
                    val = val.strip().lower()
                    if val not in TASK_STATUSES:
                        raise ValueError(
                            f"Invalid task status '{val}'. Must be one of: {sorted(TASK_STATUSES)}"
                        )
                elif key == "priority":
                    val = val.strip().lower()
                    if val not in TASK_PRIORITIES:
                        raise ValueError(
                            f"Invalid task priority '{val}'. Must be one of: {sorted(TASK_PRIORITIES)}"
                        )
                elif key == "project_id":
                    if val is not None:
                        val = _validate_id(val, "project_id")
                        _check_project_exists(connection, val)
                elif key == "goal_id":
                    if val is not None:
                        val = _validate_id(val, "goal_id")
                        _check_goal_exists(connection, val)
                elif key == "description":
                    val = val.strip() if isinstance(val, str) else ""

                set_clauses.append(f"{key} = ?")
                values.append(val)

            now = _now_iso()
            set_clauses.append("updated_at = ?")
            values.append(now)
            values.append(valid_id)

            sql = f"UPDATE tasks SET {', '.join(set_clauses)} WHERE id = ?"
            connection.execute(sql, tuple(values))
            connection.commit()

            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (valid_id,),
            ).fetchone()

        return dict(row) if row else None

    def delete_task(self, task_id: int) -> bool:
        valid_id = _validate_id(task_id, "task_id")
        with get_connection() as connection:
            cursor = connection.execute(
                "DELETE FROM tasks WHERE id = ?",
                (valid_id,),
            )
            connection.commit()
            return cursor.rowcount > 0

    # ── Decisions ────────────────────────────────────────────────────────────

    def create_decision(
        self,
        decision: str,
        context: str = "",
        project_id: int | None = None,
    ) -> dict[str, Any]:
        valid_decision = _validate_non_empty_str(decision, "Decision")
        now = _now_iso()

        with get_connection() as connection:
            if project_id is not None:
                valid_proj_id = _validate_id(project_id, "project_id")
                _check_project_exists(connection, valid_proj_id)
            else:
                valid_proj_id = None

            cursor = connection.execute(
                """
                INSERT INTO decisions (decision, context, project_id, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (valid_decision, context.strip(), valid_proj_id, now),
            )
            connection.commit()
            decision_id = cursor.lastrowid

            row = connection.execute(
                "SELECT * FROM decisions WHERE id = ?",
                (decision_id,),
            ).fetchone()

        return dict(row)

    def get_decision(self, decision_id: int) -> dict[str, Any] | None:
        valid_id = _validate_id(decision_id, "decision_id")
        with get_connection() as connection:
            row = connection.execute(
                "SELECT * FROM decisions WHERE id = ?",
                (valid_id,),
            ).fetchone()

        return dict(row) if row else None

    def list_decisions(
        self,
        project_id: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        limit = min(limit, 200)
        query = "SELECT * FROM decisions"
        params: list[Any] = []

        if project_id is not None:
            valid_proj_id = _validate_id(project_id, "project_id")
            query += " WHERE project_id = ?"
            params.append(valid_proj_id)

        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)

        with get_connection() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()

        return [dict(row) for row in rows]

    def delete_decision(self, decision_id: int) -> bool:
        valid_id = _validate_id(decision_id, "decision_id")
        with get_connection() as connection:
            cursor = connection.execute(
                "DELETE FROM decisions WHERE id = ?",
                (valid_id,),
            )
            connection.commit()
            return cursor.rowcount > 0

    # ── Skills ───────────────────────────────────────────────────────────────

    def create_skill(
        self,
        name: str,
        description: str = "",
        workflow: str = "",
    ) -> dict[str, Any]:
        valid_name = _validate_non_empty_str(name, "Skill name")
        now = _now_iso()

        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO skills (name, description, workflow, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (valid_name, description.strip(), workflow.strip(), now, now),
            )
            connection.commit()
            skill_id = cursor.lastrowid

            row = connection.execute(
                "SELECT * FROM skills WHERE id = ?",
                (skill_id,),
            ).fetchone()

        return dict(row)

    def get_skill(self, skill_id: int) -> dict[str, Any] | None:
        valid_id = _validate_id(skill_id, "skill_id")
        with get_connection() as connection:
            row = connection.execute(
                "SELECT * FROM skills WHERE id = ?",
                (valid_id,),
            ).fetchone()

        return dict(row) if row else None

    def list_skills(
        self,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        limit = min(limit, 200)
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM skills
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [dict(row) for row in rows]

    def update_skill(
        self,
        skill_id: int,
        **fields: Any,
    ) -> dict[str, Any] | None:
        valid_id = _validate_id(skill_id, "skill_id")
        allowed_fields = {"name", "description", "workflow"}
        update_keys = [k for k in fields if k in allowed_fields]

        if not update_keys:
            return self.get_skill(valid_id)

        values: list[Any] = []
        set_clauses: list[str] = []

        with get_connection() as connection:
            existing = connection.execute(
                "SELECT id FROM skills WHERE id = ?",
                (valid_id,),
            ).fetchone()
            if not existing:
                return None

            for key in update_keys:
                val = fields[key]
                if key == "name":
                    val = _validate_non_empty_str(val, "Skill name")
                elif isinstance(val, str):
                    val = val.strip()
                set_clauses.append(f"{key} = ?")
                values.append(val)

            now = _now_iso()
            set_clauses.append("updated_at = ?")
            values.append(now)
            values.append(valid_id)

            sql = f"UPDATE skills SET {', '.join(set_clauses)} WHERE id = ?"
            connection.execute(sql, tuple(values))
            connection.commit()

            row = connection.execute(
                "SELECT * FROM skills WHERE id = ?",
                (valid_id,),
            ).fetchone()

        return dict(row) if row else None

    def delete_skill(self, skill_id: int) -> bool:
        valid_id = _validate_id(skill_id, "skill_id")
        with get_connection() as connection:
            cursor = connection.execute(
                "DELETE FROM skills WHERE id = ?",
                (valid_id,),
            )
            connection.commit()
            return cursor.rowcount > 0


class PersonalModelService:
    """
    Service layer providing structured snapshots and deterministic views
    over the Personal Model for future context injection.
    """

    def __init__(self, store: PersonalModelStore | None = None) -> None:
        self.store = store or PersonalModelStore()

    def get_personal_snapshot(
        self,
        project_limit: int = 10,
        goal_limit: int = 10,
        task_limit: int = 20,
        decision_limit: int = 10,
        skill_limit: int = 10,
        active_only: bool = True,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Return a deterministic, structured snapshot of the user's personal model:
        {
          "projects": [...],
          "goals": [...],
          "tasks": [...],
          "decisions": [...],
          "skills": [...]
        }

        Bounded limits prevent unbounded prompt flooding.
        """
        if project_limit <= 0:
            projects = []
        elif active_only:
            projects = self.store.list_projects(status="active", limit=project_limit)
        else:
            projects = self.store.list_projects(limit=project_limit)

        if goal_limit <= 0:
            goals = []
        elif active_only:
            goals = self.store.list_goals(status="active", limit=goal_limit)
        else:
            goals = self.store.list_goals(limit=goal_limit)

        if task_limit <= 0:
            tasks = []
        elif active_only:
            all_tasks = self.store.list_tasks(limit=task_limit * 2)
            active_statuses = {"todo", "pending", "in_progress", "blocked"}
            tasks = [t for t in all_tasks if t.get("status") in active_statuses][:task_limit]
        else:
            tasks = self.store.list_tasks(limit=task_limit)

        decisions = self.store.list_decisions(limit=decision_limit) if decision_limit > 0 else []
        skills = self.store.list_skills(limit=skill_limit) if skill_limit > 0 else []

        return {
            "projects": projects,
            "goals": goals,
            "tasks": tasks,
            "decisions": decisions,
            "skills": skills,
        }
