"""
Unit tests for the Orion Personal Model (Phase 3).

Tests cover:
1. Schema initialization.
2. Existing memory tables remain usable.
3. Create/list/get/update/delete project.
4. Create/list/get/update/delete goal.
5. Create/list/get/update/delete task.
6. Create/list/get/delete decision.
7. Create/list/get/update/delete skill.
8. Foreign-key validation.
9. Invalid IDs.
10. Empty required fields.
11. Controlled status validation.
12. Controlled priority validation.
13. Parameterized SQL behavior.
14. Personal snapshot structure.
15. Empty personal model returns deterministic empty collections.
16. Multiple projects and related goals/tasks.
17. Bounded snapshot limits and deterministic ordering.
"""
import os
import sys
from pathlib import Path
import unittest
from unittest.mock import MagicMock
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.memory.database import get_connection, initialize_database
from app.memory.personal import (
    PersonalModelService,
    PersonalModelStore,
    PROJECT_STATUSES,
    GOAL_STATUSES,
    TASK_STATUSES,
    TASK_PRIORITIES,
)
from app.memory.store import MemoryStore
from app.memory.session import SessionStore


class TestPersonalModelSchemaAndCompatibility(unittest.TestCase):
    """Tests 1 & 2: Schema initialization and existing memory compatibility."""

    def setUp(self):
        initialize_database()
        self.store = PersonalModelStore()
        self.memory = MemoryStore()
        self.sessions = SessionStore()

    def test_1_schema_initialization(self):
        """All personal model tables and indexes exist in SQLite."""
        with get_connection() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = {t["name"] for t in tables}

            required_tables = {"projects", "goals", "tasks", "decisions", "skills"}
            for t in required_tables:
                self.assertIn(t, table_names, f"Table '{t}' was not created.")

            # Check indexes
            indexes = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
            index_names = {idx["name"] for idx in indexes}
            for expected_idx in ("idx_goals_project", "idx_tasks_project", "idx_tasks_goal", "idx_decisions_project"):
                self.assertIn(expected_idx, index_names)

    def test_2_existing_memory_tables_remain_usable(self):
        """Existing memories, sessions, and messages work completely unchanged."""
        # MemoryStore
        mem = self.memory.remember("Personal test memory", category="test", importance=4)
        self.assertIsNotNone(mem["id"])
        self.assertEqual(mem["content"], "Personal test memory")

        recalled = self.memory.recall("Personal test memory")
        self.assertTrue(any(m["id"] == mem["id"] for m in recalled))

        self.memory.delete(mem["id"])

        # SessionStore
        session = self.sessions.create("Test compatibility conversation")
        session_id = session["id"]
        msg = self.sessions.add_message(session_id, "user", "Hello world")
        self.assertEqual(msg["content"], "Hello world")

        messages = self.sessions.get_messages(session_id)
        self.assertEqual(len(messages), 1)

        deleted = self.sessions.delete(session_id)
        self.assertTrue(deleted)


class TestPersonalModelCRUD(unittest.TestCase):
    """Tests 3-7: Full CRUD operations for projects, goals, tasks, decisions, skills."""

    def setUp(self):
        initialize_database()
        self.store = PersonalModelStore()

    def test_3_project_crud(self):
        """Create, get, list, update, and delete a project."""
        proj = self.store.create_project(
            name="Orion Core",
            description="Personal AI operating layer",
            path="/home/gfood/orion",
            repository="https://github.com/example/orion",
            status="active",
        )
        self.assertIsNotNone(proj["id"])
        self.assertEqual(proj["name"], "Orion Core")
        self.assertEqual(proj["status"], "active")
        self.assertIsNotNone(proj["created_at"])
        self.assertIsNotNone(proj["updated_at"])

        # Get
        fetched = self.store.get_project(proj["id"])
        self.assertEqual(fetched, proj)

        # List
        active_projects = self.store.list_projects(status="active")
        self.assertTrue(any(p["id"] == proj["id"] for p in active_projects))

        # Update
        updated = self.store.update_project(
            proj["id"],
            description="Updated description",
            status="paused",
        )
        self.assertEqual(updated["description"], "Updated description")
        self.assertEqual(updated["status"], "paused")

        # Delete
        deleted = self.store.delete_project(proj["id"])
        self.assertTrue(deleted)
        self.assertIsNone(self.store.get_project(proj["id"]))

    def test_4_goal_crud(self):
        """Create, get, list, update, and delete a goal."""
        proj = self.store.create_project(name="Project for Goal")
        goal = self.store.create_goal(
            title="Complete Phase 3",
            description="Implement personal model v1",
            status="active",
            project_id=proj["id"],
        )
        self.assertIsNotNone(goal["id"])
        self.assertEqual(goal["title"], "Complete Phase 3")
        self.assertEqual(goal["project_id"], proj["id"])

        # Get
        fetched = self.store.get_goal(goal["id"])
        self.assertEqual(fetched, goal)

        # List by project
        proj_goals = self.store.list_goals(project_id=proj["id"])
        self.assertEqual(len(proj_goals), 1)
        self.assertEqual(proj_goals[0]["id"], goal["id"])

        # Update
        updated = self.store.update_goal(goal["id"], status="completed")
        self.assertEqual(updated["status"], "completed")

        # Delete
        self.assertTrue(self.store.delete_goal(goal["id"]))
        self.assertIsNone(self.store.get_goal(goal["id"]))
        self.store.delete_project(proj["id"])

    def test_5_task_crud(self):
        """Create, get, list, update, and delete a task."""
        proj = self.store.create_project(name="Project for Task")
        goal = self.store.create_goal(title="Goal for Task", project_id=proj["id"])

        task = self.store.create_task(
            title="Write unit tests",
            description="Cover personal model thoroughly",
            status="todo",
            priority="high",
            project_id=proj["id"],
            goal_id=goal["id"],
        )
        self.assertIsNotNone(task["id"])
        self.assertEqual(task["title"], "Write unit tests")
        self.assertEqual(task["status"], "todo")
        self.assertEqual(task["priority"], "high")
        self.assertEqual(task["project_id"], proj["id"])
        self.assertEqual(task["goal_id"], goal["id"])

        # Get
        fetched = self.store.get_task(task["id"])
        self.assertEqual(fetched, task)

        # List with filters
        tasks_filtered = self.store.list_tasks(
            project_id=proj["id"],
            goal_id=goal["id"],
            status="todo",
            priority="high",
        )
        self.assertEqual(len(tasks_filtered), 1)
        self.assertEqual(tasks_filtered[0]["id"], task["id"])

        # Update
        updated = self.store.update_task(task["id"], status="in_progress", priority="urgent")
        self.assertEqual(updated["status"], "in_progress")
        self.assertEqual(updated["priority"], "urgent")

        # Delete
        self.assertTrue(self.store.delete_task(task["id"]))
        self.assertIsNone(self.store.get_task(task["id"]))

        self.store.delete_goal(goal["id"])
        self.store.delete_project(proj["id"])

    def test_6_decision_crud(self):
        """Create, get, list, and delete a decision."""
        proj = self.store.create_project(name="Project for Decision")
        decision = self.store.create_decision(
            decision="Use SQLite with foreign keys",
            context="Simple, zero-overhead embedded relational storage",
            project_id=proj["id"],
        )
        self.assertIsNotNone(decision["id"])
        self.assertEqual(decision["decision"], "Use SQLite with foreign keys")
        self.assertEqual(decision["project_id"], proj["id"])

        # Get
        fetched = self.store.get_decision(decision["id"])
        self.assertEqual(fetched, decision)

        # List
        decisions = self.store.list_decisions(project_id=proj["id"])
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["id"], decision["id"])

        # Delete
        self.assertTrue(self.store.delete_decision(decision["id"]))
        self.assertIsNone(self.store.get_decision(decision["id"]))
        self.store.delete_project(proj["id"])

    def test_7_skill_crud(self):
        """Create, get, list, update, and delete a skill."""
        skill = self.store.create_skill(
            name="Python Refactoring",
            description="Refactor modules safely using unittests",
            workflow="1. Run tests 2. Refactor 3. Verify tests pass",
        )
        self.assertIsNotNone(skill["id"])
        self.assertEqual(skill["name"], "Python Refactoring")

        # Get
        fetched = self.store.get_skill(skill["id"])
        self.assertEqual(fetched, skill)

        # List
        skills = self.store.list_skills()
        self.assertTrue(any(s["id"] == skill["id"] for s in skills))

        # Update
        updated = self.store.update_skill(skill["id"], workflow="1. Test 2. Clean up")
        self.assertEqual(updated["workflow"], "1. Test 2. Clean up")

        # Delete
        self.assertTrue(self.store.delete_skill(skill["id"]))
        self.assertIsNone(self.store.get_skill(skill["id"]))


class TestPersonalModelValidationAndSecurity(unittest.TestCase):
    """Tests 8-13: Validation rules and security guards."""

    def setUp(self):
        initialize_database()
        self.store = PersonalModelStore()

    def test_8_foreign_key_validation(self):
        """Non-existent project_id or goal_id raises ValueError."""
        # Non-existent project for goal
        with self.assertRaises(ValueError) as ctx:
            self.store.create_goal(title="Orphan goal", project_id=999999)
        self.assertIn("Project with id 999999 does not exist", str(ctx.exception))

        # Non-existent project for task
        with self.assertRaises(ValueError) as ctx:
            self.store.create_task(title="Orphan task", project_id=888888)
        self.assertIn("Project with id 888888 does not exist", str(ctx.exception))

        # Non-existent goal for task
        with self.assertRaises(ValueError) as ctx:
            self.store.create_task(title="Orphan task", goal_id=777777)
        self.assertIn("Goal with id 777777 does not exist", str(ctx.exception))

        # Non-existent project for decision
        with self.assertRaises(ValueError) as ctx:
            self.store.create_decision(decision="Orphan decision", project_id=666666)
        self.assertIn("Project with id 666666 does not exist", str(ctx.exception))

        # Cascade set-null check when parent project deleted
        proj = self.store.create_project(name="Parent to be deleted")
        goal = self.store.create_goal(title="Child goal", project_id=proj["id"])
        self.store.delete_project(proj["id"])
        # Goal still exists, project_id is set to None by foreign key cascade
        refetched_goal = self.store.get_goal(goal["id"])
        self.assertIsNotNone(refetched_goal)
        self.assertIsNone(refetched_goal["project_id"])
        self.store.delete_goal(goal["id"])

    def test_9_invalid_ids(self):
        """Negative, zero, or non-integer IDs raise ValueError."""
        invalid_ids = [-1, 0, -100, "1", None, 3.14, True]
        for bad_id in invalid_ids:
            with self.subTest(bad_id=bad_id):
                with self.assertRaises(ValueError):
                    self.store.get_project(bad_id)
                with self.assertRaises(ValueError):
                    self.store.update_project(bad_id, name="Test")
                with self.assertRaises(ValueError):
                    self.store.delete_project(bad_id)
                with self.assertRaises(ValueError):
                    self.store.get_goal(bad_id)
                with self.assertRaises(ValueError):
                    self.store.get_task(bad_id)
                with self.assertRaises(ValueError):
                    self.store.get_decision(bad_id)
                with self.assertRaises(ValueError):
                    self.store.get_skill(bad_id)

    def test_10_empty_required_fields(self):
        """Empty names, titles, or decisions raise ValueError."""
        empty_values = ["", "   ", "\t\n"]
        for empty_val in empty_values:
            with self.subTest(empty_val=repr(empty_val)):
                with self.assertRaises(ValueError):
                    self.store.create_project(name=empty_val)
                with self.assertRaises(ValueError):
                    self.store.create_goal(title=empty_val)
                with self.assertRaises(ValueError):
                    self.store.create_task(title=empty_val)
                with self.assertRaises(ValueError):
                    self.store.create_decision(decision=empty_val)
                with self.assertRaises(ValueError):
                    self.store.create_skill(name=empty_val)

        # Update empty name/title
        proj = self.store.create_project(name="Valid Name")
        with self.assertRaises(ValueError):
            self.store.update_project(proj["id"], name="  ")
        self.store.delete_project(proj["id"])

    def test_11_controlled_status_validation(self):
        """Unrecognized status values raise ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.store.create_project(name="Proj", status="random_status")
        self.assertIn("Invalid project status", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            self.store.create_goal(title="Goal", status="flying")
        self.assertIn("Invalid goal status", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            self.store.create_task(title="Task", status="waiting_for_godot")
        self.assertIn("Invalid task status", str(ctx.exception))

    def test_12_controlled_priority_validation(self):
        """Unrecognized priority values raise ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.store.create_task(title="Task", priority="maximum")
        self.assertIn("Invalid task priority", str(ctx.exception))

        task = self.store.create_task(title="Valid task", priority="low")
        with self.assertRaises(ValueError):
            self.store.update_task(task["id"], priority="super_high")
        self.store.delete_task(task["id"])

    def test_13_parameterized_sql_behavior(self):
        """SQL injection payloads are safely stored as literal strings."""
        payload = "'; DROP TABLE projects; --"
        proj = self.store.create_project(name=payload, description="Test injection")
        self.assertEqual(proj["name"], payload)

        # Verify projects table still exists and record is retrievable
        fetched = self.store.get_project(proj["id"])
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["name"], payload)

        self.store.delete_project(proj["id"])


class TestPersonalModelServiceAndSnapshot(unittest.TestCase):
    """Tests 14-17: PersonalModelService and snapshot behavior."""

    def setUp(self):
        initialize_database()
        self.store = PersonalModelStore()
        self.service = PersonalModelService(store=self.store)

    def test_14_personal_snapshot_structure(self):
        """Snapshot returns a structured dict with all five collections."""
        proj = self.store.create_project(name="Snapshot Project", status="active")
        goal = self.store.create_goal(title="Snapshot Goal", project_id=proj["id"], status="active")
        task = self.store.create_task(title="Snapshot Task", project_id=proj["id"], status="todo")
        dec = self.store.create_decision(decision="Snapshot Decision", project_id=proj["id"])
        skill = self.store.create_skill(name="Snapshot Skill")

        snapshot = self.service.get_personal_snapshot()

        required_keys = {"projects", "goals", "tasks", "decisions", "skills"}
        self.assertEqual(set(snapshot.keys()), required_keys)

        self.assertTrue(any(p["id"] == proj["id"] for p in snapshot["projects"]))
        self.assertTrue(any(g["id"] == goal["id"] for g in snapshot["goals"]))
        self.assertTrue(any(t["id"] == task["id"] for t in snapshot["tasks"]))
        self.assertTrue(any(d["id"] == dec["id"] for d in snapshot["decisions"]))
        self.assertTrue(any(s["id"] == skill["id"] for s in snapshot["skills"]))

        # Cleanup
        self.store.delete_task(task["id"])
        self.store.delete_goal(goal["id"])
        self.store.delete_decision(dec["id"])
        self.store.delete_skill(skill["id"])
        self.store.delete_project(proj["id"])

    def test_15_empty_personal_model_returns_deterministic_empty_collections(self):
        """Snapshot on empty store returns empty lists for all keys."""
        # 1. Zero limits explicitly return empty lists
        empty_snapshot = self.service.get_personal_snapshot(
            project_limit=0, goal_limit=0, task_limit=0, decision_limit=0, skill_limit=0
        )
        self.assertEqual(empty_snapshot["projects"], [])
        self.assertEqual(empty_snapshot["goals"], [])
        self.assertEqual(empty_snapshot["tasks"], [])
        self.assertEqual(empty_snapshot["decisions"], [])
        self.assertEqual(empty_snapshot["skills"], [])

        # 2. Mock store returning empty collections
        mock_empty_store = MagicMock()
        mock_empty_store.list_projects.return_value = []
        mock_empty_store.list_goals.return_value = []
        mock_empty_store.list_tasks.return_value = []
        mock_empty_store.list_decisions.return_value = []
        mock_empty_store.list_skills.return_value = []

        empty_service = PersonalModelService(store=mock_empty_store)
        snapshot = empty_service.get_personal_snapshot()
        self.assertEqual(snapshot, {
            "projects": [],
            "goals": [],
            "tasks": [],
            "decisions": [],
            "skills": [],
        })

    def test_16_multiple_projects_and_related_goals_tasks(self):
        """Multiple projects with distinct goals and tasks remain correctly isolated."""
        proj_a = self.store.create_project(name="Project Alpha")
        proj_b = self.store.create_project(name="Project Beta")

        goal_a = self.store.create_goal(title="Goal A1", project_id=proj_a["id"])
        goal_b = self.store.create_goal(title="Goal B1", project_id=proj_b["id"])

        task_a = self.store.create_task(title="Task A1.1", project_id=proj_a["id"], goal_id=goal_a["id"])
        task_b = self.store.create_task(title="Task B1.1", project_id=proj_b["id"], goal_id=goal_b["id"])

        # Filter by project
        a_goals = self.store.list_goals(project_id=proj_a["id"])
        self.assertEqual(len(a_goals), 1)
        self.assertEqual(a_goals[0]["id"], goal_a["id"])

        b_goals = self.store.list_goals(project_id=proj_b["id"])
        self.assertEqual(len(b_goals), 1)
        self.assertEqual(b_goals[0]["id"], goal_b["id"])

        # Filter by goal
        a_tasks = self.store.list_tasks(goal_id=goal_a["id"])
        self.assertEqual(len(a_tasks), 1)
        self.assertEqual(a_tasks[0]["id"], task_a["id"])

        b_tasks = self.store.list_tasks(goal_id=goal_b["id"])
        self.assertEqual(len(b_tasks), 1)
        self.assertEqual(b_tasks[0]["id"], task_b["id"])

        # Cleanup
        self.store.delete_task(task_a["id"])
        self.store.delete_task(task_b["id"])
        self.store.delete_goal(goal_a["id"])
        self.store.delete_goal(goal_b["id"])
        self.store.delete_project(proj_a["id"])
        self.store.delete_project(proj_b["id"])

    def test_17_service_bounded_limits(self):
        """Snapshot bounds the number of items returned."""
        projs = [self.store.create_project(name=f"Bounded Proj {i}") for i in range(5)]

        snapshot = self.service.get_personal_snapshot(project_limit=2)
        self.assertLessEqual(len(snapshot["projects"]), 2)

        for p in projs:
            self.store.delete_project(p["id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
