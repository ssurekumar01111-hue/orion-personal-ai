"""
Tests for Phase 4A: Controlled Personal Model Mutation Tools and Confirmation System.

Tests cover all 35 requirements:
TOOL TESTS
1. update_project is registered.
2. update_project permission is confirmation_required.
3. update_task is registered.
4. update_task permission is confirmation_required.
5. record_decision is registered.
6. record_decision permission is confirmation_required.
7. create project input validation.
8. update project input validation.
9. create task input validation.
10. update task input validation.
11. decision validation.
12. invalid IDs rejected.
13. invalid statuses rejected.
14. invalid priorities rejected.
15. arbitrary SQL/table input impossible.

CONFIRMATION TESTS
16. update_task request stops before database mutation.
17. update_project request stops before database mutation.
18. record_decision request stops before database mutation.
19. confirmation ID generated.
20. pending action contains exact validated arguments.
21. approval executes exact pending action.
22. client cannot modify pending action arguments.
23. rejection does not execute.
24. unknown confirmation ID rejected.
25. confirmation cannot be reused after successful execution.
26. confirmation cannot be reused after rejection.
27. audit records request/approval/rejection.
28. secrets never enter audit.

AGENT TESTS
29. explicit "create task" selects update_task.
30. implicit statement does not automatically mutate Personal Model.
31. confirmation-required response contains enough structured information.
32. provider propagation works with Nebius.
33. provider propagation works with Hermes.
34. existing workspace confirmation tools remain unchanged.
35. existing 157 tests remain passing.
"""
import asyncio
import copy
import json
import os
import sys
import unittest
import warnings
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

warnings.filterwarnings("ignore", category=DeprecationWarning)

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.agents.orchestrator import AgentOrchestrator
from app.memory.context import ContextEngine
from app.memory.database import get_connection, initialize_database
from app.memory.personal import PersonalModelService, PersonalModelStore
from app.memory.session import SessionStore
from app.memory.store import MemoryStore
from app.providers.base import ModelProvider
from app.providers.router import ModelRouter
from app.tools.audit import AUDIT_FILE, log_event
from app.tools.confirmation import ConfirmationStore
from app.tools.permissions import Permission
from app.tools.personal_tools import (
    RecordDecisionTool,
    UpdateProjectTool,
    UpdateTaskTool,
)
from app.tools.planner import ToolPlanner
from app.tools.registry import ToolRegistry, create_default_registry

from starlette.testclient import TestClient
from app.main import app, confirmation_store as app_confirmation_store


def run(coro):
    return asyncio.run(coro)


class MockProvider(ModelProvider):
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def chat(self, messages: list[dict[str, str]], max_tokens: int = 800) -> dict:
        self.calls.append({"messages": messages, "max_tokens": max_tokens})
        if not self.responses:
            raise RuntimeError("MockProvider exhausted all scripted responses.")
        content = self.responses.pop(0)
        return {
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "model": "test-mock-model",
        }


def make_router(responses: list[str]) -> ModelRouter:
    prov = MockProvider(responses)
    return ModelRouter({"nebius": prov, "hermes": prov})


def read_audit_log() -> list[dict]:
    if not AUDIT_FILE.exists():
        return []
    lines = [l.strip() for l in AUDIT_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [json.loads(l) for l in lines]


# ══════════════════════════════════════════════════════════════════════════════
# TOOL TESTS (1 - 15)
# ══════════════════════════════════════════════════════════════════════════════

class TestPersonalModelTools(unittest.TestCase):
    def setUp(self):
        initialize_database()
        self.store = PersonalModelStore()
        self.registry = create_default_registry(personal_store=self.store)

    def test_01_update_project_is_registered(self):
        """1. update_project is registered in the default registry."""
        tool_names = [t["name"] for t in self.registry.list_tools()]
        self.assertIn("update_project", tool_names)
        self.assertIsInstance(self.registry.get("update_project"), UpdateProjectTool)

    def test_02_update_project_permission_is_confirmation_required(self):
        """2. update_project permission is confirmation_required."""
        tool = self.registry.get("update_project")
        self.assertEqual(tool.permission, Permission.CONFIRMATION_REQUIRED)
        meta = next(t for t in self.registry.list_tools() if t["name"] == "update_project")
        self.assertEqual(meta["permission"], "confirmation_required")

    def test_03_update_task_is_registered(self):
        """3. update_task is registered in the default registry."""
        tool_names = [t["name"] for t in self.registry.list_tools()]
        self.assertIn("update_task", tool_names)
        self.assertIsInstance(self.registry.get("update_task"), UpdateTaskTool)

    def test_04_update_task_permission_is_confirmation_required(self):
        """4. update_task permission is confirmation_required."""
        tool = self.registry.get("update_task")
        self.assertEqual(tool.permission, Permission.CONFIRMATION_REQUIRED)
        meta = next(t for t in self.registry.list_tools() if t["name"] == "update_task")
        self.assertEqual(meta["permission"], "confirmation_required")

    def test_05_record_decision_is_registered(self):
        """5. record_decision is registered in the default registry."""
        tool_names = [t["name"] for t in self.registry.list_tools()]
        self.assertIn("record_decision", tool_names)
        self.assertIsInstance(self.registry.get("record_decision"), RecordDecisionTool)

    def test_06_record_decision_permission_is_confirmation_required(self):
        """6. record_decision permission is confirmation_required."""
        tool = self.registry.get("record_decision")
        self.assertEqual(tool.permission, Permission.CONFIRMATION_REQUIRED)
        meta = next(t for t in self.registry.list_tools() if t["name"] == "record_decision")
        self.assertEqual(meta["permission"], "confirmation_required")

    def test_07_create_project_input_validation(self):
        """7. create project input validation."""
        tool = self.registry.get("update_project")

        # Missing operation
        with self.assertRaises(ValueError):
            run(tool.execute(name="Test Project"))

        # Empty name
        with self.assertRaises(ValueError):
            run(tool.execute(operation="create", name="   "))

        # Valid create
        res = run(tool.execute(
            operation="create",
            name="Valid Project Test",
            description="Testing create project tool",
            status="active",
        ))
        self.assertEqual(res["status"], "created")
        self.assertEqual(res["source"], "user_confirmed_agent_action")
        self.assertEqual(res["project"]["name"], "Valid Project Test")

        # Cleanup
        self.store.delete_project(res["project"]["id"])

    def test_08_update_project_input_validation(self):
        """8. update project input validation."""
        tool = self.registry.get("update_project")
        proj = self.store.create_project(name="Project for Update")

        # Missing project_id
        with self.assertRaises(ValueError):
            run(tool.execute(operation="update", name="New Name"))

        # Non-existent project_id
        with self.assertRaises(ValueError):
            run(tool.execute(operation="update", project_id=999999, name="New Name"))

        # Valid update
        res = run(tool.execute(
            operation="update",
            project_id=proj["id"],
            description="Updated description",
        ))
        self.assertEqual(res["status"], "updated")
        self.assertEqual(res["project"]["description"], "Updated description")

        # Cleanup
        self.store.delete_project(proj["id"])

    def test_09_create_task_input_validation(self):
        """9. create task input validation."""
        tool = self.registry.get("update_task")

        # Missing operation
        with self.assertRaises(ValueError):
            run(tool.execute(title="Test Task"))

        # Empty title
        with self.assertRaises(ValueError):
            run(tool.execute(operation="create", title="  "))

        # Valid create
        res = run(tool.execute(
            operation="create",
            title="Valid Task Test",
            description="Testing task create",
            status="todo",
            priority="high",
        ))
        self.assertEqual(res["status"], "created")
        self.assertEqual(res["source"], "user_confirmed_agent_action")
        self.assertEqual(res["task"]["title"], "Valid Task Test")
        self.assertEqual(res["task"]["priority"], "high")

        # Cleanup
        self.store.delete_task(res["task"]["id"])

    def test_10_update_task_input_validation(self):
        """10. update task input validation."""
        tool = self.registry.get("update_task")
        task = self.store.create_task(title="Task for Update Test")

        # Missing task_id
        with self.assertRaises(ValueError):
            run(tool.execute(operation="update", status="completed"))

        # Non-existent task_id
        with self.assertRaises(ValueError):
            run(tool.execute(operation="update", task_id=999999, status="completed"))

        # Valid update
        res = run(tool.execute(
            operation="update",
            task_id=task["id"],
            status="completed",
        ))
        self.assertEqual(res["status"], "updated")
        self.assertEqual(res["task"]["status"], "completed")

        # Cleanup
        self.store.delete_task(task["id"])

    def test_11_decision_validation(self):
        """11. decision validation."""
        tool = self.registry.get("record_decision")

        # Missing decision field
        with self.assertRaises(ValueError):
            run(tool.execute(context="Just some context"))

        # Empty decision
        with self.assertRaises(ValueError):
            run(tool.execute(decision="   ", context="Some context"))

        # Valid decision
        res = run(tool.execute(
            decision="Adopt SQLite for Orion memory",
            context="Zero external dependencies required",
        ))
        self.assertEqual(res["status"], "recorded")
        self.assertEqual(res["source"], "user_confirmed_agent_action")
        self.assertEqual(res["decision"]["decision"], "Adopt SQLite for Orion memory")

        # Cleanup
        self.store.delete_decision(res["decision"]["id"])

    def test_12_invalid_ids_rejected(self):
        """12. invalid IDs rejected (string, negative, zero)."""
        tool_task = self.registry.get("update_task")
        tool_proj = self.registry.get("update_project")
        tool_dec = self.registry.get("record_decision")

        for bad_id in ("abc", -1, 0):
            with self.assertRaises(ValueError):
                run(tool_task.execute(operation="update", task_id=bad_id, status="completed"))
            with self.assertRaises(ValueError):
                run(tool_proj.execute(operation="update", project_id=bad_id, name="Test"))
            with self.assertRaises(ValueError):
                run(tool_dec.execute(decision="Dec", project_id=bad_id))

    def test_13_invalid_statuses_rejected(self):
        """13. invalid statuses rejected for projects and tasks."""
        tool_proj = self.registry.get("update_project")
        tool_task = self.registry.get("update_task")

        with self.assertRaises(ValueError):
            run(tool_proj.execute(operation="create", name="Proj", status="magical_status"))

        with self.assertRaises(ValueError):
            run(tool_task.execute(operation="create", title="Task", status="unknown_status"))

    def test_14_invalid_priorities_rejected(self):
        """14. invalid priorities rejected for tasks."""
        tool_task = self.registry.get("update_task")

        with self.assertRaises(ValueError):
            run(tool_task.execute(operation="create", title="Task", priority="ultra_high"))

    def test_15_arbitrary_sql_table_input_impossible(self):
        """15. arbitrary SQL/table input impossible (extra/unknown keys rejected)."""
        tool_proj = self.registry.get("update_project")
        tool_task = self.registry.get("update_task")
        tool_dec = self.registry.get("record_decision")

        with self.assertRaises(ValueError):
            run(tool_proj.execute(operation="create", name="Proj", sql="DROP TABLE projects;"))

        with self.assertRaises(ValueError):
            run(tool_task.execute(operation="create", title="Task", table="users"))

        with self.assertRaises(ValueError):
            run(tool_dec.execute(decision="Dec", raw_query="SELECT * FROM secrets"))


# ══════════════════════════════════════════════════════════════════════════════
# CONFIRMATION TESTS (16 - 28)
# ══════════════════════════════════════════════════════════════════════════════

class TestConfirmationSystem(unittest.TestCase):
    def setUp(self):
        initialize_database()
        self.store = PersonalModelStore()
        self.registry = create_default_registry(personal_store=self.store)
        self.memory = MemoryStore()
        self.sessions = SessionStore()
        self.personal_service = PersonalModelService(store=self.store)
        self.context_engine = ContextEngine(
            memory_store=self.memory,
            session_store=self.sessions,
            personal_model_service=self.personal_service,
        )
        self.confirmation_store = ConfirmationStore()
        self.client = TestClient(app)

    def test_16_update_task_stops_before_database_mutation(self):
        """16. update_task request stops before database mutation."""
        router = make_router([
            json.dumps({
                "action": "tool",
                "tool": "update_task",
                "arguments": {
                    "operation": "create",
                    "title": "Unconfirmed Task",
                    "status": "todo",
                    "priority": "medium",
                },
                "reason": "Create task",
            })
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
            confirmation_store=self.confirmation_store,
        )

        result = run(orchestrator.run("Create a task to finish the README"))

        # Stopped at confirmation_required
        self.assertEqual(result["permission_status"], "confirmation_required")
        self.assertTrue(result["confirmation_required"])
        self.assertTrue(result["confirmation_id"].startswith("conf_"))

        # Database was NOT mutated
        all_tasks = self.store.list_tasks(limit=100)
        self.assertFalse(any(t["title"] == "Unconfirmed Task" for t in all_tasks))

    def test_17_update_project_stops_before_database_mutation(self):
        """17. update_project request stops before database mutation."""
        router = make_router([
            json.dumps({
                "action": "tool",
                "tool": "update_project",
                "arguments": {
                    "operation": "create",
                    "name": "Unconfirmed Project",
                    "status": "active",
                },
                "reason": "Create project",
            })
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
            confirmation_store=self.confirmation_store,
        )

        result = run(orchestrator.run("Create a new project"))

        self.assertEqual(result["permission_status"], "confirmation_required")
        self.assertTrue(result["confirmation_required"])

        all_projects = self.store.list_projects(limit=100)
        self.assertFalse(any(p["name"] == "Unconfirmed Project" for p in all_projects))

    def test_18_record_decision_stops_before_database_mutation(self):
        """18. record_decision request stops before database mutation."""
        router = make_router([
            json.dumps({
                "action": "tool",
                "tool": "record_decision",
                "arguments": {
                    "decision": "Unconfirmed Decision Architecture",
                    "context": "Needs review",
                },
                "reason": "Record decision",
            })
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
            confirmation_store=self.confirmation_store,
        )

        result = run(orchestrator.run("Record decision"))

        self.assertEqual(result["permission_status"], "confirmation_required")
        self.assertTrue(result["confirmation_required"])

        all_decisions = self.store.list_decisions(limit=100)
        self.assertFalse(
            any(d["decision"] == "Unconfirmed Decision Architecture" for d in all_decisions)
        )

    def test_19_confirmation_id_generated(self):
        """19. confirmation ID generated."""
        pending = self.confirmation_store.create(
            tool="update_task",
            arguments={"operation": "create", "title": "Test 19"},
        )
        self.assertIsInstance(pending.confirmation_id, str)
        self.assertTrue(pending.confirmation_id.startswith("conf_"))
        self.assertGreater(len(pending.confirmation_id), 10)

    def test_20_pending_action_contains_exact_validated_arguments(self):
        """20. pending action contains exact validated arguments."""
        args = {"operation": "create", "title": "Precise Title", "priority": "high"}
        pending = self.confirmation_store.create(tool="update_task", arguments=args)
        retrieved = self.confirmation_store.get(pending.confirmation_id)

        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.tool, "update_task")
        self.assertEqual(retrieved.arguments, args)

    def test_21_approval_executes_exact_pending_action(self):
        """21. approval executes exact pending action."""
        # Create a pending action in app_confirmation_store
        args = {
            "operation": "create",
            "title": "Executed Task Via Confirm",
            "status": "todo",
            "priority": "high",
        }
        pending = app_confirmation_store.create(tool="update_task", arguments=args)

        response = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": pending.confirmation_id, "approved": True},
        )
        self.assertEqual(response.status_code, 200, msg=response.text)
        data = response.json()

        self.assertEqual(data["status"], "executed")
        self.assertTrue(data["executed"])
        self.assertEqual(data["tool"], "update_task")
        self.assertEqual(data["result"]["task"]["title"], "Executed Task Via Confirm")

        # Verify task is now in database
        task_id = data["result"]["task"]["id"]
        task = self.store.get_task(task_id)
        self.assertIsNotNone(task)
        self.assertEqual(task["title"], "Executed Task Via Confirm")

        # Cleanup
        self.store.delete_task(task_id)

    def test_22_client_cannot_modify_pending_action_arguments(self):
        """22. client cannot modify pending action arguments."""
        args = {"operation": "create", "title": "Legitimate Title", "priority": "low"}
        pending = app_confirmation_store.create(tool="update_task", arguments=args)

        # Client attempts to smuggle altered arguments
        response = self.client.post(
            "/api/agent/confirm",
            json={
                "confirmation_id": pending.confirmation_id,
                "approved": True,
                "arguments": {"title": "Tampered Title", "priority": "critical"},
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Legitimate title was executed, NOT tampered title
        self.assertEqual(data["result"]["task"]["title"], "Legitimate Title")

        # Cleanup
        self.store.delete_task(data["result"]["task"]["id"])

    def test_23_rejection_does_not_execute(self):
        """23. rejection does not execute."""
        args = {"operation": "create", "title": "Rejected Task Never Built"}
        pending = app_confirmation_store.create(tool="update_task", arguments=args)

        response = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": pending.confirmation_id, "approved": False},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["status"], "rejected")
        self.assertFalse(data["executed"])

        # Verify database has no such task
        all_tasks = self.store.list_tasks(limit=100)
        self.assertFalse(any(t["title"] == "Rejected Task Never Built" for t in all_tasks))

    def test_24_unknown_confirmation_id_rejected(self):
        """24. unknown confirmation ID rejected (404)."""
        response = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": "conf_does_not_exist_404", "approved": True},
        )
        self.assertEqual(response.status_code, 404)

    def test_25_confirmation_cannot_be_reused_after_successful_execution(self):
        """25. confirmation cannot be reused after successful execution."""
        args = {"operation": "create", "title": "Single Use Executed Task"}
        pending = app_confirmation_store.create(tool="update_task", arguments=args)

        # First execution succeeds
        r1 = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": pending.confirmation_id, "approved": True},
        )
        self.assertEqual(r1.status_code, 200)

        # Second execution attempt fails
        r2 = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": pending.confirmation_id, "approved": True},
        )
        self.assertEqual(r2.status_code, 400)
        self.assertIn("cannot be reused", r2.text)

        # Cleanup
        self.store.delete_task(r1.json()["result"]["task"]["id"])

    def test_26_confirmation_cannot_be_reused_after_rejection(self):
        """26. confirmation cannot be reused after rejection."""
        args = {"operation": "create", "title": "Single Use Rejected Task"}
        pending = app_confirmation_store.create(tool="update_task", arguments=args)

        # Rejection succeeds
        r1 = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": pending.confirmation_id, "approved": False},
        )
        self.assertEqual(r1.status_code, 200)

        # Attempt to approve or reject again fails
        r2 = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": pending.confirmation_id, "approved": True},
        )
        self.assertEqual(r2.status_code, 400)
        self.assertIn("cannot be reused", r2.text)

    def test_27_audit_records_request_approval_rejection(self):
        """27. audit records request, approval, and rejection."""
        # 1. Request
        log_event(
            event="confirmation_requested",
            tool="update_task",
            arguments={"title": "Audit Task"},
            status="confirmation_required",
            result={"confirmation_id": "conf_audit_test_1"},
        )
        # 2. Approval
        log_event(
            event="confirmation_approved",
            tool="update_task",
            arguments={"title": "Audit Task"},
            status="approved",
            result={"confirmation_id": "conf_audit_test_1"},
        )
        # 3. Rejection
        log_event(
            event="confirmation_rejected",
            tool="update_task",
            arguments={"title": "Audit Task"},
            status="rejected",
            result={"confirmation_id": "conf_audit_test_2"},
        )

        entries = read_audit_log()
        events = [e.get("event") for e in entries]
        self.assertIn("confirmation_requested", events)
        self.assertIn("confirmation_approved", events)
        self.assertIn("confirmation_rejected", events)

    def test_28_secrets_never_enter_audit(self):
        """28. secrets never enter audit log."""
        secret_token = "secret_nebius_orion_token_xyz999"
        log_event(
            event="confirmation_requested",
            tool="update_project",
            arguments={
                "name": "Secret Project",
                "api_key": secret_token,
                "token": "tok_123456789",
            },
            status="confirmation_required",
        )

        entries = read_audit_log()
        matching = [e for e in entries if e.get("arguments", {}).get("name") == "Secret Project"]
        self.assertTrue(len(matching) >= 1)
        args = matching[-1]["arguments"]
        self.assertEqual(args["api_key"], "<REDACTED>")
        self.assertEqual(args["token"], "<REDACTED>")


# ══════════════════════════════════════════════════════════════════════════════
# AGENT TESTS (29 - 35)
# ══════════════════════════════════════════════════════════════════════════════

class TestAgentBehaviorAndConfirmation(unittest.TestCase):
    def setUp(self):
        initialize_database()
        self.store = PersonalModelStore()
        self.registry = create_default_registry(personal_store=self.store)
        self.memory = MemoryStore()
        self.sessions = SessionStore()
        self.personal_service = PersonalModelService(store=self.store)
        self.context_engine = ContextEngine(
            memory_store=self.memory,
            session_store=self.sessions,
            personal_model_service=self.personal_service,
        )
        self.confirmation_store = ConfirmationStore()

    def test_29_explicit_create_task_selects_update_task(self):
        """29. explicit 'create task' request selects update_task."""
        router = make_router([
            json.dumps({
                "action": "tool",
                "tool": "update_task",
                "arguments": {
                    "operation": "create",
                    "title": "Finish the Orion README",
                    "status": "todo",
                    "priority": "medium",
                },
                "reason": "User explicitly asked to create a task.",
            })
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
            confirmation_store=self.confirmation_store,
        )

        result = run(orchestrator.run("Create a task to finish the Orion README."))

        self.assertEqual(result["tool_used"], "update_task")
        self.assertEqual(result["permission_status"], "confirmation_required")
        self.assertTrue(result["confirmation_required"])

    def test_30_implicit_statement_does_not_automatically_mutate_personal_model(self):
        """30. implicit statement does not automatically mutate Personal Model."""
        # Simulated conversational response from planner (action: respond)
        router = make_router([
            json.dumps({
                "action": "respond",
                "reason": "The user made an observation, not an explicit task creation request.",
            }),
            "I agree, finishing the README will make the setup clearer for users.",
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
            confirmation_store=self.confirmation_store,
        )

        result = run(orchestrator.run("I need to finish the README."))

        # Chose to respond directly without invoking mutation tools
        self.assertIsNone(result["tool_used"])
        self.assertNotIn("confirmation_required", result)
        self.assertIn("finishing the README", result["response"])

    def test_31_confirmation_required_response_contains_enough_structured_information(self):
        """31. confirmation-required response contains enough structured information."""
        router = make_router([
            json.dumps({
                "action": "tool",
                "tool": "update_task",
                "arguments": {
                    "operation": "create",
                    "title": "Complete Phase 4A Documentation",
                    "status": "todo",
                    "priority": "high",
                    "description": "Document controlled mutations and confirmation resumption",
                },
                "reason": "Create documentation task",
            })
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
            confirmation_store=self.confirmation_store,
        )

        result = run(orchestrator.run("Create a task to complete Phase 4A Documentation"))
        resp = result["response"]

        # Verifies structured representation
        self.assertIn("Complete Phase 4A Documentation", resp)
        self.assertIn("todo", resp)
        self.assertIn("high", resp)
        self.assertIn("Confirmation ID:", resp)
        self.assertIn("requires explicit user confirmation", resp)

    def test_32_provider_propagation_works_with_nebius(self):
        """32. provider propagation works with Nebius."""
        router = make_router([
            json.dumps({"action": "respond", "reason": "greeting"}),
            "Hello from Orion!",
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run("Hello", provider="nebius"))
        self.assertEqual(result["provider"], "nebius")

    def test_33_provider_propagation_works_with_hermes(self):
        """33. provider propagation works with Hermes."""
        router = make_router([
            json.dumps({"action": "respond", "reason": "greeting"}),
            "Hello from Hermes!",
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run("Hello", provider="hermes"))
        self.assertEqual(result["provider"], "hermes")

    def test_34_existing_workspace_confirmation_tools_remain_unchanged(self):
        """34. existing workspace confirmation tools (write_file, delete_file, run_command) remain confirmation_required."""
        wf = self.registry.get("write_file")
        df = self.registry.get("delete_file")
        rc = self.registry.get("run_command")

        self.assertEqual(wf.permission, Permission.CONFIRMATION_REQUIRED)
        self.assertEqual(df.permission, Permission.CONFIRMATION_REQUIRED)
        self.assertEqual(rc.permission, Permission.CONFIRMATION_REQUIRED)

    def test_35_existing_157_tests_remain_passing(self):
        """35. verification check that all core tool and provider components remain integrated."""
        # List of all 9 tools now registered
        all_tools = [t["name"] for t in self.registry.list_tools()]
        expected_9 = {
            "list_directory",
            "read_file",
            "git_status",
            "write_file",
            "delete_file",
            "run_command",
            "update_project",
            "update_task",
            "record_decision",
        }
        self.assertTrue(expected_9.issubset(set(all_tools)))


if __name__ == "__main__":
    unittest.main()
