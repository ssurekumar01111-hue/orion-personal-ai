"""
Tests for Phase 5B-8C Fix: record_decision argument schema and confirmation flow.

Covers:
A. Valid decision:
   {"decision": "Orion should require explicit confirmation before file or Personal Model mutations."}
   -> confirmation_required -> immutable arguments -> approval -> successful persistence.
B. Valid decision with context and project:
   {"decision": "...", "context": "...", "project_id": 68}
   -> confirmation_required -> approval -> successful persistence.
C. Empty decision:
   {"decision": ""} -> rejected.
D. Missing decision:
   {} -> rejected.
E. Unknown field:
   {"decision": "...", "notes": "..."} -> rejected.
F. Invalid project ID:
   {"decision": "...", "project_id": -1} -> rejected.
G. Planner schema test:
   Verify the ToolPlanner prompt explicitly contains the canonical record_decision contract and requires "decision".
H. Confirmation lifecycle:
   Verify canonical arguments survive immutable pending storage, execute after approval, persist successfully, and the confirmation cannot be reused.
I. Summary formatting:
   - valid decision shows the actual decision
   - missing/empty decision produces the neutral invalid summary.
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
from app.tools.personal_tools import RecordDecisionTool


def run(coro):
    return asyncio.run(coro)


class TestRecordDecisionSchemaFix(unittest.TestCase):
    def setUp(self):
        initialize_database()
        self.client = TestClient(app, raise_server_exceptions=True)
        self.created_decision_ids = []

        # Ensure project 68 exists for tests referencing it
        with get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO projects (id, name, description, status) VALUES (68, 'Separation Proj', 'Original desc', 'active')"
            )
            conn.commit()

    def tearDown(self):
        for did in self.created_decision_ids:
            try:
                personal_store.delete_decision(did)
            except Exception:
                pass

    def test_a_valid_decision_confirmation_and_persistence(self):
        """A. Valid decision:
        {"decision": "Orion should require explicit confirmation before file or Personal Model mutations."}
        -> confirmation_required -> immutable arguments -> approval -> successful persistence.
        """
        canonical_decision = (
            "Orion should require explicit confirmation before file or Personal Model mutations."
        )
        canonical_args = {
            "decision": canonical_decision,
        }

        # Step 1: Agent planner selects record_decision
        planner_decision = {
            "action": "tool",
            "tool": "record_decision",
            "arguments": canonical_args,
            "reason": "User requested recording an architectural governance decision.",
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

        # Agent run -> confirmation_required
        res = run(orchestrator.run("Record this decision: " + canonical_decision))
        self.assertTrue(res["confirmation_required"])
        self.assertEqual(res["permission_status"], "confirmation_required")
        self.assertEqual(res["tool_used"], "record_decision")

        conf_id = res["confirmation_id"]
        self.assertIsNotNone(conf_id)

        # Pending arguments survive immutably
        pending = confirmation_store.get(conf_id)
        self.assertIsNotNone(pending)
        self.assertEqual(pending.arguments, canonical_args)
        self.assertEqual(pending.status, "pending")

        # Database should NOT contain the decision yet
        decisions_before = personal_store.list_decisions(limit=100)
        self.assertFalse(any(d["decision"] == canonical_decision for d in decisions_before))

        # Step 2: User approves via /api/agent/confirm
        resp = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": conf_id, "approved": True},
        )
        self.assertEqual(resp.status_code, 200, msg=resp.text)
        data = resp.json()

        self.assertEqual(data["status"], "executed")
        self.assertTrue(data["executed"])
        self.assertEqual(data["tool"], "record_decision")
        self.assertEqual(data["result"]["status"], "recorded")
        self.assertEqual(data["result"]["decision"]["decision"], canonical_decision)

        did = data["result"]["decision"]["id"]
        self.created_decision_ids.append(did)

        # Step 3: Verify successful persistence in database
        decisions_after = personal_store.list_decisions(limit=100)
        matching = [d for d in decisions_after if d["id"] == did]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["decision"], canonical_decision)

    def test_b_valid_decision_with_context_and_project(self):
        """B. Valid decision with context and project:
        {"decision": "...", "context": "...", "project_id": 68}
        -> confirmation_required -> approval -> successful persistence.
        """
        canonical_args = {
            "decision": "Adopt strict schema verification for all agent tool executions.",
            "context": "Phase 5B architectural governance trace fix",
            "project_id": 68,
        }

        pending = confirmation_store.create(
            tool="record_decision",
            arguments=canonical_args,
        )
        conf_id = pending.confirmation_id
        self.assertEqual(pending.status, "pending")

        resp = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": conf_id, "approved": True},
        )
        self.assertEqual(resp.status_code, 200, msg=resp.text)
        data = resp.json()

        self.assertEqual(data["status"], "executed")
        self.assertTrue(data["executed"])
        self.assertEqual(data["tool"], "record_decision")
        self.assertEqual(data["result"]["status"], "recorded")

        stored_dec = data["result"]["decision"]
        self.created_decision_ids.append(stored_dec["id"])
        self.assertEqual(stored_dec["decision"], canonical_args["decision"])
        self.assertEqual(stored_dec["context"], canonical_args["context"])
        self.assertEqual(stored_dec["project_id"], 68)

        # Verify DB persistence under project 68
        proj_decisions = personal_store.list_decisions(project_id=68)
        self.assertTrue(any(d["id"] == stored_dec["id"] for d in proj_decisions))

    def test_c_empty_decision_rejected(self):
        """C. Empty decision: {"decision": ""} -> rejected."""
        tool = RecordDecisionTool(store=personal_store)

        # Direct execution must raise ValueError for empty string
        with self.assertRaises(ValueError) as ctx:
            run(tool.execute(decision=""))
        self.assertIn("Decision text cannot be empty", str(ctx.exception))

        # Direct execution must raise ValueError for whitespace-only string
        with self.assertRaises(ValueError) as ctx:
            run(tool.execute(decision="   "))
        self.assertIn("Decision text cannot be empty", str(ctx.exception))

        # Confirmation endpoint must reject empty decision with 400 Bad Request
        pending = confirmation_store.create(
            tool="record_decision",
            arguments={"decision": ""},
        )
        resp = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": pending.confirmation_id, "approved": True},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Decision text cannot be empty", resp.json()["detail"])

    def test_d_missing_decision_rejected(self):
        """D. Missing decision: {} -> rejected."""
        tool = RecordDecisionTool(store=personal_store)

        with self.assertRaises(ValueError) as ctx:
            run(tool.execute())
        self.assertIn("Decision text cannot be empty", str(ctx.exception))

        # Confirmation endpoint must reject empty arguments with 400 Bad Request
        pending = confirmation_store.create(
            tool="record_decision",
            arguments={},
        )
        resp = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": pending.confirmation_id, "approved": True},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Decision text cannot be empty", resp.json()["detail"])

    def test_e_unknown_field_rejected(self):
        """E. Unknown field: {"decision": "...", "notes": "..."} -> rejected."""
        tool = RecordDecisionTool(store=personal_store)

        with self.assertRaises(ValueError) as ctx:
            run(tool.execute(decision="Valid decision text", notes="Arbitrary note"))
        self.assertIn("Unexpected fields for record_decision", str(ctx.exception))

        pending = confirmation_store.create(
            tool="record_decision",
            arguments={"decision": "Valid decision text", "notes": "Arbitrary note"},
        )
        resp = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": pending.confirmation_id, "approved": True},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Unexpected fields for record_decision", resp.json()["detail"])

    def test_f_invalid_project_id_rejected(self):
        """F. Invalid project ID: {"decision": "...", "project_id": -1} -> rejected."""
        tool = RecordDecisionTool(store=personal_store)

        # Negative project_id
        with self.assertRaises(ValueError) as ctx:
            run(tool.execute(decision="Valid decision text", project_id=-1))
        self.assertIn("project_id must be a positive integer", str(ctx.exception))

        # Zero project_id
        with self.assertRaises(ValueError) as ctx:
            run(tool.execute(decision="Valid decision text", project_id=0))
        self.assertIn("project_id must be a positive integer", str(ctx.exception))

        # Non-numeric project_id
        with self.assertRaises(ValueError) as ctx:
            run(tool.execute(decision="Valid decision text", project_id="not_an_int"))
        self.assertIn("project_id must be a positive integer", str(ctx.exception))

        # Confirmation endpoint must reject invalid project_id with 400
        pending = confirmation_store.create(
            tool="record_decision",
            arguments={"decision": "Valid decision text", "project_id": -1},
        )
        resp = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": pending.confirmation_id, "approved": True},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("project_id must be a positive integer", resp.json()["detail"])

    def test_g_planner_schema_contract(self):
        """G. Planner schema test:
        Verify the ToolPlanner prompt explicitly contains the canonical record_decision contract and requires "decision".
        """
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

        # Verify prompt contains canonical contract and requirements
        self.assertIn("record_decision", system_msg)
        self.assertIn('"decision": "<actual decision text>"', system_msg)
        self.assertIn('"decision" is required and MUST be non-empty', system_msg)
        self.assertIn("Do not emit {}", system_msg)
        self.assertIn("Do not invent a decision that the user did not request.", system_msg)
        self.assertIn("Use project_id only when the request identifies an existing project.", system_msg)
        self.assertIn("Do not use arbitrary keys such as content/title/notes.", system_msg)
        self.assertIn("Do not include confirmed:true.", system_msg)
        self.assertIn("record_decision remains confirmation-required.", system_msg)

        # Verify RecordDecisionTool description also documents canonical schema and rules
        rec_tool = tools.get("record_decision")
        self.assertIsNotNone(rec_tool)
        self.assertIn('"decision": "<non-empty string>"', rec_tool.description)
        self.assertIn("decision is required and must contain the actual decision text", rec_tool.description)
        self.assertIn("reject unknown fields", rec_tool.description.lower())
        self.assertIn("do not include confirmed:true", rec_tool.description.lower())
        self.assertIn("record_decision remains confirmation-required", rec_tool.description.lower())

    def test_h_confirmation_lifecycle_immutability_and_no_reuse(self):
        """H. Confirmation lifecycle:
        Verify canonical arguments survive immutable pending storage, execute after approval,
        persist successfully, and the confirmation cannot be reused.
        """
        canonical_args = {
            "decision": "Orion confirmation lifecycle governance invariant",
            "context": "Verification of pending immutability and non-reuse",
            "project_id": 68,
        }

        pending = confirmation_store.create(
            tool="record_decision",
            arguments=canonical_args,
        )
        conf_id = pending.confirmation_id

        # Verify pending arguments are immutably preserved
        self.assertEqual(confirmation_store.get(conf_id).arguments, canonical_args)
        self.assertEqual(confirmation_store.get(conf_id).status, "pending")

        # Database does not have it yet
        decisions_before = personal_store.list_decisions(project_id=68)
        self.assertFalse(any(d["decision"] == canonical_args["decision"] for d in decisions_before))

        # Approve and execute
        resp = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": conf_id, "approved": True},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["executed"])
        did = data["result"]["decision"]["id"]
        self.created_decision_ids.append(did)

        # Verify persisted successfully in DB
        decisions_after = personal_store.list_decisions(project_id=68)
        stored = next((d for d in decisions_after if d["id"] == did), None)
        self.assertIsNotNone(stored)
        self.assertEqual(stored["decision"], canonical_args["decision"])
        self.assertEqual(stored["context"], canonical_args["context"])
        self.assertEqual(stored["project_id"], 68)

        # Attempt to reuse the confirmation ID: must fail with HTTP 400
        reuse_resp = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": conf_id, "approved": True},
        )
        self.assertEqual(reuse_resp.status_code, 400)
        self.assertIn("cannot be reused", reuse_resp.json()["detail"])

    def test_i_summary_formatting(self):
        """I. Summary formatting:
        - valid decision shows the actual decision
        - missing/empty decision produces the neutral invalid summary.
        """
        # Valid decision alone
        summary_valid = AgentOrchestrator._format_confirmation_summary(
            "record_decision",
            {"decision": "Orion must require explicit confirmation."},
        )
        self.assertIn("Orion wants to record this decision:", summary_valid)
        self.assertIn("Decision: Orion must require explicit confirmation.", summary_valid)

        # Valid decision with context and project_id
        summary_full = AgentOrchestrator._format_confirmation_summary(
            "record_decision",
            {
                "decision": "Orion must require explicit confirmation.",
                "context": "Phase 5B safety policy",
                "project_id": 68,
            },
        )
        self.assertIn("Decision: Orion must require explicit confirmation.", summary_full)
        self.assertIn("Context: Phase 5B safety policy", summary_full)
        self.assertIn("Project ID: 68", summary_full)

        # Empty string decision -> neutral invalid summary
        expected_invalid = "Orion wants to record a decision, but the decision text is missing or invalid."
        summary_empty = AgentOrchestrator._format_confirmation_summary(
            "record_decision",
            {"decision": ""},
        )
        self.assertEqual(summary_empty, expected_invalid)

        # Whitespace-only decision -> neutral invalid summary
        summary_ws = AgentOrchestrator._format_confirmation_summary(
            "record_decision",
            {"decision": "   \n\t  "},
        )
        self.assertEqual(summary_ws, expected_invalid)

        # Missing decision field ({}) -> neutral invalid summary
        summary_missing = AgentOrchestrator._format_confirmation_summary(
            "record_decision",
            {},
        )
        self.assertEqual(summary_missing, expected_invalid)

        # Missing decision with other keys (e.g. only context) -> neutral invalid summary
        summary_context_only = AgentOrchestrator._format_confirmation_summary(
            "record_decision",
            {"context": "some context without a decision"},
        )
        self.assertEqual(summary_context_only, expected_invalid)

        # None decision -> neutral invalid summary
        summary_none = AgentOrchestrator._format_confirmation_summary(
            "record_decision",
            {"decision": None},
        )
        self.assertEqual(summary_none, expected_invalid)

        # Non-string decision -> neutral invalid summary
        summary_non_str = AgentOrchestrator._format_confirmation_summary(
            "record_decision",
            {"decision": 12345},
        )
        self.assertEqual(summary_non_str, expected_invalid)

        # Verify summary never silently substitutes or invents a decision
        self.assertNotIn("substituted", summary_missing)
        self.assertNotIn("default", summary_empty)


if __name__ == "__main__":
    unittest.main()
