"""
Unit and integration tests for GET /api/personal/snapshot endpoint.

Requirements:
1. Endpoint returns 200.
2. Endpoint reflects the actual SQLite Personal Model.
3. Empty goals/tasks/skills are returned as empty arrays.
4. Endpoint does not return the frontend's old hardcoded Orion Personal AI demo data unless it actually exists in the database.
5. Parameter validation and bounded limits.
6. No secrets exposed.
"""
import os
import sys
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)

sys.path.insert(0, str(Path(__file__).parents[1]))

from starlette.testclient import TestClient
from app.main import app, personal_store


class TestPersonalSnapshotEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(
            app,
            headers={"Authorization": f"Bearer {os.environ.get('ORION_DEMO_KEY', 'test-demo-secret-key-12345-very-long')}"},
            raise_server_exceptions=True,
        )

    def test_snapshot_endpoint_returns_200(self):
        """1. Endpoint returns 200."""
        response = self.client.get("/api/personal/snapshot")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, dict)
        self.assertIn("projects", data)
        self.assertIn("goals", data)
        self.assertIn("tasks", data)
        self.assertIn("decisions", data)
        self.assertIn("skills", data)

    def test_snapshot_reflects_actual_sqlite_model(self):
        """2. Endpoint reflects the actual SQLite Personal Model."""
        response = self.client.get("/api/personal/snapshot")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Database currently has 'Separation Proj' with id 68
        db_projects = personal_store.list_projects(status="active", limit=10)
        self.assertEqual(len(data["projects"]), len(db_projects))
        if db_projects:
            self.assertEqual(data["projects"][0]["name"], db_projects[0]["name"])
            self.assertEqual(data["projects"][0]["id"], db_projects[0]["id"])

    def test_empty_goals_tasks_skills_are_empty_arrays(self):
        """3. Empty goals/tasks/skills are returned as empty arrays."""
        response = self.client.get("/api/personal/snapshot")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # If DB currently has 0 goals, 0 tasks, 0 skills, they must be empty lists []
        self.assertIsInstance(data["goals"], list)
        self.assertIsInstance(data["tasks"], list)
        self.assertIsInstance(data["skills"], list)
        self.assertIsInstance(data["decisions"], list)

        active_statuses = {"todo", "pending", "in_progress", "blocked"}
        db_goals = personal_store.list_goals(status="active", limit=10)
        db_tasks = [t for t in personal_store.list_tasks(limit=40) if t.get("status") in active_statuses][:20]
        db_skills = personal_store.list_skills(limit=10)

        self.assertEqual(len(data["goals"]), len(db_goals))
        self.assertEqual(len(data["tasks"]), len(db_tasks))
        self.assertEqual(len(data["skills"]), len(db_skills))

    def test_no_fabricated_orion_demo_data(self):
        """4. Endpoint does not return the frontend's old hardcoded Orion Personal AI demo data unless it actually exists in the database."""
        response = self.client.get("/api/personal/snapshot")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        project_names = [p["name"] for p in data["projects"]]
        goal_titles = [g["title"] for g in data["goals"]]
        task_titles = [t["title"] for t in data["tasks"]]

        db_project_names = [p["name"] for p in personal_store.list_projects()]
        if "Orion Personal AI" not in db_project_names:
            self.assertNotIn("Orion Personal AI", project_names)

        db_goal_titles = [g["title"] for g in personal_store.list_goals()]
        if "Phase 5A UI Shell" not in db_goal_titles:
            self.assertNotIn("Phase 5A UI Shell", goal_titles)

        db_task_titles = [t["title"] for t in personal_store.list_tasks()]
        if "Implement 3-region responsive layout" not in db_task_titles:
            self.assertNotIn("Implement 3-region responsive layout", task_titles)

    def test_query_parameters_and_bounds(self):
        """Validate bounded limits and rejection of out-of-range params."""
        # Valid custom limits
        response = self.client.get(
            "/api/personal/snapshot?project_limit=1&goal_limit=1&task_limit=1&decision_limit=1&skill_limit=1"
        )
        self.assertEqual(response.status_code, 200)

        # Negative limit rejected
        response = self.client.get("/api/personal/snapshot?project_limit=-1")
        self.assertEqual(response.status_code, 400)

        # Excessive limit rejected
        response = self.client.get("/api/personal/snapshot?task_limit=101")
        self.assertEqual(response.status_code, 400)

    def test_no_secrets_in_snapshot(self):
        """Ensure no secret keys or credentials leaked in the snapshot."""
        response = self.client.get("/api/personal/snapshot")
        self.assertEqual(response.status_code, 200)
        text = response.text.lower()
        self.assertNotIn("api_key", text)
        self.assertNotIn("secret", text)
        self.assertNotIn("password", text)
        self.assertNotIn("nebius_api_key", text)


if __name__ == "__main__":
    unittest.main()
