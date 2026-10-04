"""
Tests for Phase 5B-8C Planner Disambiguation Fix: record_decision vs remark vs query.

Covers:
A. Explicit recording request:
   "Record this decision in my Personal Model: Orion should require explicit confirmation before any operation that modifies files or structured personal data."
   -> tool = record_decision
   -> arguments = {"decision": "Orion should require explicit confirmation before any operation that modifies files or structured personal data."}
B. Explicit short form:
   "Record this decision: Never bypass confirmation for mutating tools."
   -> tool = record_decision
C. Save wording:
   "Save this as a decision: Skills must obey the same permission boundaries as direct tool calls."
   -> tool = record_decision
D. Declarative statement:
   "Orion should require explicit confirmation before any operation that modifies files."
   -> respond, NOT record_decision.
E. Existing-context question:
   "Do I already have a decision requiring confirmation for file modifications?"
   -> respond/read-only behavior, NOT record_decision.
F. Personal Model context populated:
   Repeat test A with an existing <personal_model> containing related information.
   -> record_decision still selected because explicit recording takes precedence over context inspection.
G. Verify generated record_decision arguments are canonical:
   {"decision": "<non-empty string>"}
"""
import asyncio
import sys
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.main import context_engine, planner, tools
from app.memory.personal import PersonalModelStore
from app.tools.personal_tools import RecordDecisionTool


def _load_nebius_api_key() -> str:
    env_path = Path(__file__).parents[2] / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text().splitlines():
        if line.upper().startswith("NEBIUS_API_KEY"):
            return line.split("=", 1)[-1].strip().strip('"').strip("'")
    return ""


def run(coro):
    return asyncio.run(coro)


class TestRecordDecisionDisambiguation(unittest.TestCase):
    def setUp(self):
        self.api_key = _load_nebius_api_key()
        self.available_tools = tools.list_tools()

    def test_prompt_contains_disambiguation_rules(self):
        """Verify the ToolPlanner prompt explicitly documents decision-recording disambiguation."""
        from unittest.mock import AsyncMock
        import json
        mock_router = AsyncMock()
        mock_router.chat.return_value = {
            "choices": [{"message": {"content": json.dumps({"action": "respond", "reason": "test"})}}],
            "model": "test-model",
        }
        from app.tools.planner import ToolPlanner
        p = ToolPlanner(mock_router)
        run(p.plan("test message", self.available_tools))

        call_args = mock_router.chat.call_args
        messages = call_args.kwargs.get("messages", call_args.args[0] if call_args.args else [])
        system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")

        # Verify explicit recording examples
        self.assertIn('"Record this decision: <decision text>"', system_msg)
        self.assertIn('"Record this decision in my Personal Model: <decision text>"', system_msg)
        self.assertIn('"Save this as a decision: <decision text>"', system_msg)

        # Verify declarative statements remain remarks
        self.assertIn("An ordinary declarative statement without an explicit recording instruction", system_msg)
        self.assertIn("must NOT be classified as a request to persist it", system_msg)

        # Verify precedence over context inspection
        self.assertIn("do NOT answer by inspecting whether the decision already exists in <personal_model>", system_msg)
        self.assertIn("the explicit recording instruction takes precedence over context inspection", system_msg)

        # Verify existing-context questions are treated as read-only queries
        self.assertIn("Do I already have a requirement for confirmation before file modifications?", system_msg)
        self.assertIn("use existing personal context/read-only reasoning and do not invoke record_decision", system_msg)

    def test_a_explicit_recording_request(self):
        """A. Explicit recording request selects record_decision with exact decision text."""
        if not self.api_key:
            self.skipTest("NEBIUS_API_KEY not configured")

        msg = (
            "Record this decision in my Personal Model: Orion should require explicit confirmation "
            "before any operation that modifies files or structured personal data."
        )
        ctx = context_engine.build_context(user_message=msg)
        res = run(planner.plan(
            user_message=msg,
            available_tools=self.available_tools,
            provider="nebius",
            context=ctx,
        ))

        self.assertEqual(res.get("action"), "tool")
        self.assertEqual(res.get("tool"), "record_decision")
        self.assertIsInstance(res.get("arguments"), dict)
        self.assertEqual(
            res["arguments"].get("decision"),
            "Orion should require explicit confirmation before any operation that modifies files or structured personal data.",
        )

    def test_b_explicit_short_form(self):
        """B. Explicit short form 'Record this decision: ...' selects record_decision."""
        if not self.api_key:
            self.skipTest("NEBIUS_API_KEY not configured")

        msg = "Record this decision: Never bypass confirmation for mutating tools."
        ctx = context_engine.build_context(user_message=msg)
        res = run(planner.plan(
            user_message=msg,
            available_tools=self.available_tools,
            provider="nebius",
            context=ctx,
        ))

        self.assertEqual(res.get("action"), "tool")
        self.assertEqual(res.get("tool"), "record_decision")
        self.assertIsInstance(res.get("arguments"), dict)
        self.assertEqual(
            res["arguments"].get("decision"),
            "Never bypass confirmation for mutating tools.",
        )

    def test_c_save_wording(self):
        """C. Save wording 'Save this as a decision: ...' selects record_decision."""
        if not self.api_key:
            self.skipTest("NEBIUS_API_KEY not configured")

        msg = "Save this as a decision: Skills must obey the same permission boundaries as direct tool calls."
        ctx = context_engine.build_context(user_message=msg)
        res = run(planner.plan(
            user_message=msg,
            available_tools=self.available_tools,
            provider="nebius",
            context=ctx,
        ))

        self.assertEqual(res.get("action"), "tool")
        self.assertEqual(res.get("tool"), "record_decision")
        self.assertIsInstance(res.get("arguments"), dict)
        self.assertEqual(
            res["arguments"].get("decision"),
            "Skills must obey the same permission boundaries as direct tool calls.",
        )

    def test_d_declarative_statement_responds_without_mutation(self):
        """D. Declarative statement without explicit recording directive returns respond, NOT record_decision."""
        if not self.api_key:
            self.skipTest("NEBIUS_API_KEY not configured")

        msg = "Orion should require explicit confirmation before any operation that modifies files."
        ctx = context_engine.build_context(user_message=msg)
        res = run(planner.plan(
            user_message=msg,
            available_tools=self.available_tools,
            provider="nebius",
            context=ctx,
        ))

        self.assertEqual(res.get("action"), "respond")
        self.assertNotEqual(res.get("tool"), "record_decision")

    def test_e_existing_context_question_responds_without_mutation(self):
        """E. Existing-context question returns respond (read-only behavior), NOT record_decision."""
        if not self.api_key:
            self.skipTest("NEBIUS_API_KEY not configured")

        msg = "Do I already have a decision requiring confirmation for file modifications?"
        ctx = context_engine.build_context(user_message=msg)
        res = run(planner.plan(
            user_message=msg,
            available_tools=self.available_tools,
            provider="nebius",
            context=ctx,
        ))

        self.assertEqual(res.get("action"), "respond")
        self.assertNotEqual(res.get("tool"), "record_decision")

    def test_f_personal_model_context_populated_takes_precedence(self):
        """F. Explicit recording request takes precedence over context inspection even when context is populated."""
        if not self.api_key:
            self.skipTest("NEBIUS_API_KEY not configured")

        msg = (
            "Record this decision in my Personal Model: Orion should require explicit confirmation "
            "before any operation that modifies files or structured personal data."
        )
        ctx = {
            "personal_model": {
                "projects": [{"id": 68, "name": "Separation Proj", "status": "active"}],
                "decisions": [
                    {
                        "id": 1,
                        "decision": "Orion requires explicit confirmation for destructive actions.",
                        "context": "security",
                    }
                ],
                "skills": [{"id": 10, "name": "write_file", "description": "Write files safely"}],
                "tasks": [],
            },
            "memories": [
                {"category": "governance", "content": "Orion follows least privilege policies."}
            ],
        }
        res = run(planner.plan(
            user_message=msg,
            available_tools=self.available_tools,
            provider="nebius",
            context=ctx,
        ))

        self.assertEqual(res.get("action"), "tool")
        self.assertEqual(res.get("tool"), "record_decision")
        self.assertIsInstance(res.get("arguments"), dict)
        self.assertEqual(
            res["arguments"].get("decision"),
            "Orion should require explicit confirmation before any operation that modifies files or structured personal data.",
        )

    def test_g_canonical_arguments_validation(self):
        """G. Verify generated record_decision arguments are canonical and pass RecordDecisionTool execution."""
        tool = RecordDecisionTool(store=PersonalModelStore())
        canonical_args = {
            "decision": "Orion should require explicit confirmation before any operation that modifies files or structured personal data."
        }

        # Check structure
        self.assertIn("decision", canonical_args)
        self.assertIsInstance(canonical_args["decision"], str)
        self.assertTrue(bool(canonical_args["decision"].strip()))
        self.assertNotIn("confirmed", canonical_args)

        # Verify tool execution accepts it
        res = run(tool.execute(**canonical_args))
        self.assertEqual(res["status"], "recorded")
        self.assertEqual(res["decision"]["decision"], canonical_args["decision"])

        # Cleanup
        tool.store.delete_decision(res["decision"]["id"])


if __name__ == "__main__":
    unittest.main()
