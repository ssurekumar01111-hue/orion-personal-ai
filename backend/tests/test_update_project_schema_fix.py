"""
Tests for Phase 5B-8A Fix: update_project canonical argument schema and confirmation flow.

Covers:
A. Valid update:
   {"operation": "update", "project_id": 68, "description": "..."}
   -> confirmation -> approve -> successful database update.
B. Valid create:
   {"operation": "create", "name": "...", "description": "...", "status": "active"}
   -> confirmation -> approve -> project created in database.
C. Malformed update using:
   {"id": 68, "description": "..."}
   -> must NOT reach successful execution.
D. Missing operation:
   {"project_id": 68, "description": "..."}
   -> must be rejected with ValueError / HTTP 400.
E. Unknown fields:
   {"operation": "update", "project_id": 68, "foo": "bar"}
   -> must be rejected with ValueError / HTTP 400.
F. Planner schema test:
   A request to update an existing project instructs the canonical
   operation="update", project_id=<id>, and orchestrator formats the summary correctly.
G. Confirmation flow:
   The canonical update request survives immutable confirmation arguments and
   executes successfully only after approval, and cannot be reused.
"""
import asyncio
import json
import sys
import unittest
import warnings
from pathlib import Path
from unittest.mock import AsyncMock

warnings.filterwarnings("ignore", category=DeprecationWarning)

sys.path.insert(0, str(Path(__file__).parents[1]))

from starlette.testclient import TestClient

from app.agents.orchestrator import AgentOrchestrator
from app.agents.planner import ToolPlanner
from app.main import app, confirmation_store, personal_store, tools
from app.memory.context import ContextEngine
from app.memory.database import get_connection, initialize_database
from app.memory.personal import PersonalModelService
from app.memory.session import SessionStore
from app.memory.store import MemoryStore
from app.tools.personal_tools import UpdateProjectTool


def run(coro):
    return asyncio.run(coro)


class TestUpdateProjectSchemaFix(unittest.TestCase):
    def setUp(self):
        initialize_database()
        self.client = TestClient(app, raise_server_exceptions=True)
        self.created_project_ids = []

        # Ensure project 68 exists for tests referencing it
        with get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO projects (id, name, description, status) VALUES (68, 'Separation Proj', 'Original desc', 'active')"
            )
            conn.commit()

    def tearDown(self):
        for pid in self.created_project_ids:
            try:
                personal_store.delete_project(pid)
            except Exception:
                pass

    def test_a_valid_update_confirmation_and_db_update(self):
        """A. Valid update: operation='update', project_id=68, description='...' -> confirmation -> approve -> successful DB update."""
        new_desc = "Orion Personal AI security validation project - Updated"
        args = {
            "operation": "update",
            "project_id": 68,
            "description": new_desc,
        }

        # Step 1: Create pending confirmation
        pending = confirmation_store.create(
            tool="update_project",
            arguments=args,
        )
        conf_id = pending.confirmation_id

        # Database should NOT be updated yet
        proj_before = personal_store.get_project(68)
        self.assertIsNotNone(proj_before)

        # Step 2: User approves via /api/agent/confirm
        resp = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": conf_id, "approved": True},
        )
        self.assertEqual(resp.status_code, 200, msg=resp.text)
        data = resp.json()

        self.assertEqual(data["status"], "executed")
        self.assertTrue(data["executed"])
        self.assertEqual(data["tool"], "update_project")
        self.assertEqual(data["result"]["status"], "updated")
        self.assertEqual(data["result"]["project"]["description"], new_desc)

        # Verify DB is actually updated
        proj_after = personal_store.get_project(68)
        self.assertEqual(proj_after["description"], new_desc)

    def test_b_valid_create_confirmation_and_project_created(self):
        """B. Valid create: operation='create', name='...' -> confirmation -> approve -> project created."""
        args = {
            "operation": "create",
            "name": "Phase 5B-8A Validation Project",
            "description": "Testing project creation through confirmation",
            "status": "active",
        }

        pending = confirmation_store.create(
            tool="update_project",
            arguments=args,
        )
        conf_id = pending.confirmation_id

        resp = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": conf_id, "approved": True},
        )
        self.assertEqual(resp.status_code, 200, msg=resp.text)
        data = resp.json()

        self.assertEqual(data["status"], "executed")
        self.assertTrue(data["executed"])
        self.assertEqual(data["result"]["status"], "created")
        created_proj = data["result"]["project"]
        self.created_project_ids.append(created_proj["id"])
        self.assertEqual(created_proj["name"], "Phase 5B-8A Validation Project")

        # Verify DB persistence
        stored = personal_store.get_project(created_proj["id"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored["name"], "Phase 5B-8A Validation Project")

    def test_c_malformed_update_using_id_rejected(self):
        """C. Malformed update using id=68 without operation must NOT reach successful execution."""
        tool = UpdateProjectTool(store=personal_store)

        # Direct execution must raise ValueError
        with self.assertRaises(ValueError) as ctx:
            run(tool.execute(id=68, description="Should fail"))
        self.assertIn("Missing required field: 'operation'", str(ctx.exception))

        # Even with operation='update', passing 'id' instead of 'project_id' must fail
        with self.assertRaises(ValueError) as ctx:
            run(tool.execute(operation="update", id=68, description="Should fail"))
        self.assertIn("Unexpected fields for update project", str(ctx.exception))

        # Confirmation endpoint must return 400 Bad Request
        pending = confirmation_store.create(
            tool="update_project",
            arguments={"id": 68, "description": "Should fail via API"},
        )
        resp = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": pending.confirmation_id, "approved": True},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Missing required field: 'operation'", resp.json()["detail"])

    def test_d_missing_operation_rejected(self):
        """D. Missing operation: {"project_id": 68, "description": "..."} must be rejected."""
        tool = UpdateProjectTool(store=personal_store)

        with self.assertRaises(ValueError) as ctx:
            run(tool.execute(project_id=68, description="Missing operation"))
        self.assertIn("Missing required field: 'operation'", str(ctx.exception))

        pending = confirmation_store.create(
            tool="update_project",
            arguments={"project_id": 68, "description": "Missing operation"},
        )
        resp = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": pending.confirmation_id, "approved": True},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Missing required field: 'operation'", resp.json()["detail"])

    def test_e_unknown_fields_rejected(self):
        """E. Unknown fields: {"operation": "update", "project_id": 68, "foo": "bar"} must be rejected."""
        tool = UpdateProjectTool(store=personal_store)

        with self.assertRaises(ValueError) as ctx:
            run(tool.execute(operation="update", project_id=68, foo="bar"))
        self.assertIn("Unexpected fields for update project", str(ctx.exception))

        pending = confirmation_store.create(
            tool="update_project",
            arguments={"operation": "update", "project_id": 68, "foo": "bar"},
        )
        resp = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": pending.confirmation_id, "approved": True},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Unexpected fields for update project", resp.json()["detail"])

    def test_f_planner_schema_and_summary_contract(self):
        """F. Planner schema test: system prompt instructs canonical update_project contract and summary formatting."""
        mock_router = AsyncMock()
        mock_router.chat.return_value = {
            "choices": [{"message": {"content": json.dumps({"action": "respond", "reason": "test"})}}],
            "model": "test-model",
        }

        planner = ToolPlanner(mock_router)
        run(planner.plan("test message", tools.list_tools()))

        call_args = mock_router.chat.call_args
        messages = call_args.kwargs.get("messages", call_args.args[0] if call_args.args else [])
        system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")

        self.assertIn("update_project", system_msg)
        self.assertIn('"operation": "update"', system_msg)
        self.assertIn('"project_id":', system_msg)
        self.assertIn('NEVER use "id" for update_project', system_msg)
        self.assertIn('Never omit operation', system_msg)

        # Check confirmation summary formatting
        summary_update = AgentOrchestrator._format_confirmation_summary(
            "update_project",
            {"operation": "update", "project_id": 68, "description": "New description"},
        )
        self.assertIn("Update project 68:", summary_update)
        self.assertNotIn("Create project", summary_update)

        summary_create = AgentOrchestrator._format_confirmation_summary(
            "update_project",
            {"operation": "create", "name": "Brand New"},
        )
        self.assertIn("Create project:", summary_create)

        summary_missing = AgentOrchestrator._format_confirmation_summary(
            "update_project",
            {"id": 68, "description": "Missing op"},
        )
        self.assertIn("unspecified or invalid", summary_missing)
        self.assertNotIn("Create project", summary_missing)

    def test_g_confirmation_flow_immutability_and_lifecycle(self):
        """G. Confirmation flow: canonical update survives immutable confirmation and executes only after approval."""
        target_desc = "Lifecycle Verified Description 5B-8A"
        canonical_args = {
            "operation": "update",
            "project_id": 68,
            "description": target_desc,
        }

        planner_decision = {
            "action": "tool",
            "tool": "update_project",
            "arguments": canonical_args,
            "reason": "User requested project update.",
        }

        mock_router = AsyncMock()
        mock_router.chat.return_value = {
            "choices": [{"message": {"content": json.dumps(planner_decision)}}],
            "model": "test-model",
        }

        planner = ToolPlanner(mock_router)
        memory = MemoryStore()
        sessions = SessionStore()
        personal_service = PersonalModelService(store=personal_store)
        context_engine = ContextEngine(
            memory_store=memory,
            session_store=sessions,
            personal_model_service=personal_service,
        )

        orchestrator = AgentOrchestrator(
            router=mock_router,
            registry=tools,
            context_engine=context_engine,
            planner=planner,
            confirmation_store=confirmation_store,
        )

        # Run agent: must request confirmation
        res = run(orchestrator.run("Update project 68 description"))
        self.assertTrue(res["confirmation_required"])
        self.assertEqual(res["tool_used"], "update_project")
        conf_id = res["confirmation_id"]
        self.assertIsNotNone(conf_id)

        # Check pending arguments are preserved immutably
        pending = confirmation_store.get(conf_id)
        self.assertEqual(pending.arguments, canonical_args)
        self.assertEqual(pending.status, "pending")

        # Confirm via endpoint
        resp = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": conf_id, "approved": True},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["executed"])

        # Check DB updated
        proj = personal_store.get_project(68)
        self.assertEqual(proj["description"], target_desc)

        # Confirmation cannot be reused
        reuse_resp = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": conf_id, "approved": True},
        )
        self.assertEqual(reuse_resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
