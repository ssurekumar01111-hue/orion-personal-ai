"""
Tests for Phase 5B-7 Fix: create_skill argument schema mismatch and confirmation flow.

Covers:
1. CreateSkillTool.execute() with correct structured workflow creates the skill.
2. CreateSkillTool.execute() with old malformed top-level steps is rejected with ValueError.
3. CreateSkillTool.execute() without workflow is rejected with ValueError.
4. End-to-end confirmation flow:
   - Agent requests create_skill
   - Confirmation is created (status=pending, skill not yet created)
   - User approves via /api/agent/confirm
   - Exact stored operation executed with confirmed=True
   - Skill is actually persisted in SQLite
   - No second confirmation requested
   - Confirmation cannot be reused (HTTP 400)
5. Planner system prompt explicitly specifies the create_skill schema and rules.
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
from app.memory.personal import PersonalModelService
from app.memory.session import SessionStore
from app.memory.store import MemoryStore
from app.tools.skills import CreateSkillTool, SkillValidator


def run(coro):
    return asyncio.run(coro)


class TestCreateSkillSchemaFix(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=True)
        self.created_skill_ids = []

    def tearDown(self):
        for sid in self.created_skill_ids:
            try:
                personal_store.delete_skill(sid)
            except Exception:
                pass

    def test_create_skill_tool_valid_structured_workflow(self):
        """CreateSkillTool accepts the exact structured workflow schema."""
        tool = CreateSkillTool(store=personal_store, registry=tools)
        res = run(
            tool.execute(
                name="Git Status Check",
                description="Checks the current git status of the Orion workspace.",
                workflow={
                    "steps": [
                        {
                            "tool": "git_status",
                            "arguments": {},
                        }
                    ]
                },
            )
        )
        self.assertEqual(res["status"], "created")
        self.assertEqual(res["source"], "user_confirmed_agent_action")
        skill = res["skill"]
        self.created_skill_ids.append(skill["id"])

        self.assertEqual(skill["name"], "Git Status Check")
        self.assertEqual(skill["description"], "Checks the current git status of the Orion workspace.")

        stored = personal_store.get_skill(skill["id"])
        self.assertIsNotNone(stored)
        parsed_wf = json.loads(stored["workflow"])
        self.assertEqual(
            parsed_wf,
            {
                "steps": [
                    {
                        "tool": "git_status",
                        "arguments": {},
                    }
                ]
            },
        )

    def test_create_skill_tool_rejects_old_malformed_steps_format(self):
        """CreateSkillTool rejects old format with top-level 'steps'."""
        tool = CreateSkillTool(store=personal_store, registry=tools)
        with self.assertRaises(ValueError) as ctx:
            run(
                tool.execute(
                    name="Git Status Check",
                    description="Checks the current git status of the Orion workspace.",
                    steps=["git_status"],
                )
            )
        self.assertIn("steps", str(ctx.exception).lower())

    def test_create_skill_tool_rejects_missing_workflow(self):
        """CreateSkillTool rejects missing 'workflow'."""
        tool = CreateSkillTool(store=personal_store, registry=tools)
        with self.assertRaises(ValueError) as ctx:
            run(
                tool.execute(
                    name="Git Status Check",
                    description="Checks the current git status of the Orion workspace.",
                )
            )
        self.assertIn("workflow", str(ctx.exception).lower())

    def test_end_to_end_create_skill_confirmation_flow(self):
        """Complete flow: agent requests create_skill -> confirmation -> approval -> persistence -> no reuse."""
        skill_name = "E2E Test Git Status Check"
        wf_payload = {
            "steps": [
                {
                    "tool": "git_status",
                    "arguments": {},
                }
            ]
        }

        # Step 1: Agent requests create_skill with the structured workflow
        planner_decision = {
            "action": "tool",
            "tool": "create_skill",
            "arguments": {
                "name": skill_name,
                "description": "Checks the current git status of the Orion workspace.",
                "workflow": wf_payload,
            },
            "reason": "User requested saving Git status check as a reusable skill.",
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

        # Step 2: Agent run triggers confirmation_required
        res = run(orchestrator.run("Save this workflow as a skill called E2E Test Git Status Check"))
        self.assertTrue(res["confirmation_required"])
        self.assertEqual(res["permission_status"], "confirmation_required")
        self.assertEqual(res["tool_used"], "create_skill")

        conf_id = res["confirmation_id"]
        self.assertIsNotNone(conf_id)

        # Skill must NOT be in DB yet
        all_skills = personal_store.list_skills()
        self.assertFalse(any(s["name"] == skill_name for s in all_skills))

        # Check pending confirmation in store
        pending = confirmation_store.get(conf_id)
        self.assertIsNotNone(pending)
        self.assertEqual(pending.status, "pending")
        self.assertEqual(pending.tool, "create_skill")
        self.assertEqual(pending.arguments["name"], skill_name)
        self.assertEqual(pending.arguments["workflow"], wf_payload)

        # Step 3 & 4: User approves through /api/agent/confirm
        confirm_resp = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": conf_id, "approved": True},
        )
        self.assertEqual(confirm_resp.status_code, 200, msg=confirm_resp.text)
        data = confirm_resp.json()

        # Step 5 & 6: Executed and persisted, no second confirmation
        self.assertEqual(data["status"], "executed")
        self.assertTrue(data["executed"])
        self.assertEqual(data["tool"], "create_skill")
        self.assertEqual(data["result"]["status"], "created")

        created_skill = data["result"]["skill"]
        self.created_skill_ids.append(created_skill["id"])
        self.assertEqual(created_skill["name"], skill_name)

        # Verify persisted in SQLite
        persisted = personal_store.get_skill(created_skill["id"])
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted["name"], skill_name)
        persisted_wf = json.loads(persisted["workflow"])
        self.assertEqual(persisted_wf, wf_payload)

        # Step 7: Confirmation cannot be reused
        reuse_resp = self.client.post(
            "/api/agent/confirm",
            json={"confirmation_id": conf_id, "approved": True},
        )
        self.assertEqual(reuse_resp.status_code, 400)
        self.assertIn("cannot be reused", reuse_resp.json()["detail"])

    def test_planner_prompt_instructs_structured_create_skill_contract(self):
        """Planner system prompt must instruct the exact create_skill arguments contract."""
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

        self.assertIn("create_skill", system_msg)
        self.assertIn('"workflow":', system_msg)
        self.assertIn('"steps":', system_msg)
        self.assertIn('"tool":', system_msg)
        self.assertIn("NEVER generate a top-level \"steps\" field", system_msg)


if __name__ == "__main__":
    unittest.main()
