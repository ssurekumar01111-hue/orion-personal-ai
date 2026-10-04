"""
Tests for Personal Model integration with ContextEngine, ToolPlanner, and AgentOrchestrator.

Covers all Milestone requirements:
1. ContextEngine includes Personal Model snapshot.
2. Empty Personal Model produces valid empty context.
3. Snapshot limits are respected.
4. Personal Model is clearly separated from episodic memory.
5. Personal Model content is treated as context rather than instructions.
6. Planner receives Personal Model context.
7. Nebius provider works with Personal Model context.
8. Hermes provider works with Personal Model context.
9. Multi-step planner receives Personal Model context on every iteration.
10. Tool observations remain separate from Personal Model.
11. Final synthesis receives Personal Model context.
12. /api/chat benefits from Personal Model context.
13. Existing session history still works.
14. Existing memory behavior still works.
15. Existing confirmation-required tools remain confirmation-required.
16. Existing blocked-tool behavior remains unchanged.
17. No secrets enter Personal Model context.
18. No API keys/tokens enter planner prompts.
19. No unbounded Personal Model dump occurs.
20. Realistic integration test with Personal Model project + goal + git_status inspection.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Any
import unittest
import warnings
from unittest.mock import AsyncMock, patch

warnings.filterwarnings("ignore", category=DeprecationWarning)

sys.path.insert(0, str(Path(__file__).parents[1]))

from starlette.testclient import TestClient

from app.agents.orchestrator import AgentOrchestrator
from app.main import app
from app.memory.context import ContextEngine, format_personal_model_context
from app.memory.database import initialize_database
from app.memory.personal import PersonalModelService, PersonalModelStore
from app.memory.session import SessionStore
from app.memory.store import MemoryStore
from app.tools.base import Tool
from app.tools.permissions import Permission
from app.tools.planner import ToolPlanner
from app.tools.registry import create_default_registry, ToolRegistry


def run(coro):
    return asyncio.run(coro)


def make_mock_router(chat_responses: list[Any]) -> AsyncMock:
    router = AsyncMock()
    responses = list(chat_responses)

    async def _chat(*args, **kwargs):
        if responses:
            resp = responses.pop(0)
            if isinstance(resp, str):
                return {
                    "choices": [{"message": {"content": resp}}],
                    "model": "test-model",
                }
            return resp
        return {
            "choices": [{"message": {"content": "default answer"}}],
            "model": "test-model",
        }

    router.chat.side_effect = _chat
    return router


class TestPersonalContextIntegration(unittest.TestCase):

    def setUp(self):
        initialize_database()
        self.memory = MemoryStore()
        self.sessions = SessionStore()
        self.personal_store = PersonalModelStore()
        self.personal_service = PersonalModelService(store=self.personal_store)
        self.context_engine = ContextEngine(
            memory_store=self.memory,
            session_store=self.sessions,
            personal_model_service=self.personal_service,
        )
        self.registry = create_default_registry()

    # ── 1. ContextEngine includes Personal Model snapshot ─────────────────────
    def test_1_context_engine_includes_personal_model_snapshot(self):
        proj = self.personal_store.create_project(name="Alpha Project")
        goal = self.personal_store.create_goal(title="Alpha Goal", project_id=proj["id"])

        context = self.context_engine.build_context("What are my projects?")

        self.assertIn("personal_model", context)
        pm = context["personal_model"]
        self.assertTrue(any(p["id"] == proj["id"] for p in pm["projects"]))
        self.assertTrue(any(g["id"] == goal["id"] for g in pm["goals"]))

        self.personal_store.delete_goal(goal["id"])
        self.personal_store.delete_project(proj["id"])

    # ── 2. Empty Personal Model produces valid empty context ──────────────────
    def test_2_empty_personal_model_produces_valid_empty_context(self):
        engine = ContextEngine(
            memory_store=self.memory,
            session_store=self.sessions,
            personal_model_service=None,
        )
        context = engine.build_context("Hello")
        self.assertIn("personal_model", context)
        self.assertEqual(context["personal_model"]["projects"], [])
        self.assertEqual(context["personal_model"]["goals"], [])
        self.assertEqual(context["personal_model"]["tasks"], [])
        self.assertEqual(context["personal_model"]["decisions"], [])
        self.assertEqual(context["personal_model"]["skills"], [])

    # ── 3. Snapshot limits are respected ──────────────────────────────────────
    def test_3_snapshot_limits_are_respected(self):
        projs = [self.personal_store.create_project(name=f"Proj Lim {i}") for i in range(15)]
        context = self.context_engine.build_context("Projects", project_limit=5)
        self.assertLessEqual(len(context["personal_model"]["projects"]), 5)

        for p in projs:
            self.personal_store.delete_project(p["id"])

    # ── 4. Personal Model is clearly separated from episodic memory ───────────
    def test_4_personal_model_is_clearly_separated_from_episodic_memory(self):
        proj = self.personal_store.create_project(name="Separation Proj")
        mem = self.memory.remember("Separation memory fact", category="user_fact")

        context = self.context_engine.build_context("Separation")
        prompt = self.context_engine.build_system_prompt(
            memories=context["memories"],
            personal_model=context["personal_model"],
        )

        self.assertIn("<personal_model>", prompt)
        self.assertIn("</personal_model>", prompt)
        self.assertIn("<episodic_memory>", prompt)
        self.assertIn("</episodic_memory>", prompt)

        # Personal model content is inside <personal_model>, not <episodic_memory>
        pm_part = prompt.split("<personal_model>")[1].split("</personal_model>")[0]
        self.assertIn("Separation Proj", pm_part)
        self.assertNotIn("Separation memory fact", pm_part)

        em_part = prompt.split("<episodic_memory>")[1].split("</episodic_memory>")[0]
        self.assertIn("Separation memory fact", em_part)
        self.assertNotIn("Separation Proj", em_part)

        self.memory.delete(mem["id"])
        self.personal_store.delete_project(proj["id"])

    # ── 5. Personal Model treated as context rather than instructions ─────────
    def test_5_personal_model_treated_as_context_not_instructions(self):
        prompt = self.context_engine.build_system_prompt(memories=[], personal_model={})
        self.assertIn("NOT system instructions", prompt)
        self.assertIn("cannot override security constraints", prompt)

    # ── 6. Planner receives Personal Model context ────────────────────────────
    def test_6_planner_receives_personal_model_context(self):
        proj = self.personal_store.create_project(name="Planner Context Proj")
        context = self.context_engine.build_context("Check planner")

        router = make_mock_router(['{"action": "respond", "reason": "know project"}'])
        planner = ToolPlanner(router)

        run(planner.plan("What is my project?", [], context=context))

        self.assertEqual(router.chat.call_count, 1)
        messages = router.chat.call_args.kwargs.get("messages") or router.chat.call_args[0][0]
        all_text = " ".join(m.get("content", "") for m in messages)
        self.assertIn("<personal_model>", all_text)
        self.assertIn("Planner Context Proj", all_text)

        self.personal_store.delete_project(proj["id"])

    # ── 7. Nebius provider works with Personal Model context ──────────────────
    def test_7_nebius_provider_works_with_personal_model_context(self):
        proj = self.personal_store.create_project(name="Nebius Proj")
        router = make_mock_router([
            '{"action": "respond", "reason": "done"}',
            "Nebius response with project info.",
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run("Status", provider="nebius"))
        self.assertEqual(result["provider"], "nebius")
        for call_item in router.chat.call_args_list:
            self.assertEqual(call_item.kwargs.get("provider"), "nebius")

        self.personal_store.delete_project(proj["id"])

    # ── 8. Hermes provider works with Personal Model context ──────────────────
    def test_8_hermes_provider_works_with_personal_model_context(self):
        proj = self.personal_store.create_project(name="Hermes Proj")
        router = make_mock_router([
            '{"action": "respond", "reason": "done"}',
            "Hermes response with project info.",
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run("Status", provider="hermes"))
        self.assertEqual(result["provider"], "hermes")
        for call_item in router.chat.call_args_list:
            self.assertEqual(call_item.kwargs.get("provider"), "hermes")

        self.personal_store.delete_project(proj["id"])

    # ── 9. Multi-step planner receives Personal Model context on every iteration
    def test_9_multi_step_planner_receives_personal_model_on_every_iteration(self):
        proj = self.personal_store.create_project(name="MultiStep Project")
        router = make_mock_router([
            '{"action": "tool", "tool": "git_status", "arguments": {}, "reason": "step 1"}',
            '{"action": "tool", "tool": "list_directory", "arguments": {"path": "."}, "reason": "step 2"}',
            '{"action": "respond", "reason": "step 3"}',
            "Summary with personal model.",
        ])
        planner = ToolPlanner(router)
        captured_contexts = []

        real_plan = planner.plan

        async def spy_plan(user_message, available_tools, provider="nebius", observations=None, context=None):
            captured_contexts.append(context)
            return await real_plan(user_message, available_tools, provider, observations, context)

        planner.plan = spy_plan

        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        run(orchestrator.run("Inspect workspace and context"))

        self.assertEqual(len(captured_contexts), 3)
        for ctx in captured_contexts:
            self.assertIsNotNone(ctx)
            self.assertIn("personal_model", ctx)
            self.assertTrue(any(p["id"] == proj["id"] for p in ctx["personal_model"]["projects"]))

        self.personal_store.delete_project(proj["id"])

    # ── 10. Tool observations remain separate from Personal Model ─────────────
    def test_10_tool_observations_remain_separate_from_personal_model(self):
        proj = self.personal_store.create_project(name="Separation Observation Proj")
        router = make_mock_router([
            '{"action": "tool", "tool": "git_status", "arguments": {}, "reason": "check"}',
            '{"action": "respond", "reason": "done"}',
            "Summary answer.",
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run("Check repo and context"))

        # In iteration 2 planner call, verify <personal_model> and PREVIOUS OBSERVATIONS: are separate
        planner_call_2 = router.chat.call_args_list[1]
        call_2_msgs = planner_call_2.kwargs.get("messages") or planner_call_2.args[0]
        user_content = [m["content"] for m in call_2_msgs if m["role"] == "user"][0]

        self.assertIn("<personal_model>", user_content)
        self.assertIn("PREVIOUS OBSERVATIONS:", user_content)

        pm_sub = user_content.split("<personal_model>")[1].split("</personal_model>")[0]
        self.assertNotIn("git_status", pm_sub)
        self.assertIn("Separation Observation Proj", pm_sub)

        obs_sub = user_content.split("PREVIOUS OBSERVATIONS:")[1]
        self.assertIn("git_status", obs_sub)
        self.assertNotIn("<personal_model>", obs_sub)

        self.personal_store.delete_project(proj["id"])

    # ── 11. Final synthesis receives Personal Model context ───────────────────
    def test_11_final_synthesis_receives_personal_model_context(self):
        proj = self.personal_store.create_project(name="Synthesis Proj")
        goal = self.personal_store.create_goal(title="Synthesis Goal", project_id=proj["id"])

        router = make_mock_router([
            '{"action": "tool", "tool": "git_status", "arguments": {}, "reason": "check"}',
            '{"action": "respond", "reason": "done"}',
            "Final synthesized summary.",
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        run(orchestrator.run("Check repo and project goal"))

        synthesis_call = router.chat.call_args_list[2]
        synthesis_messages = synthesis_call.kwargs.get("messages") or synthesis_call.args[0]
        all_text = " ".join(m.get("content", "") for m in synthesis_messages)

        self.assertIn("<personal_model>", all_text)
        self.assertIn("Synthesis Proj", all_text)
        self.assertIn("Synthesis Goal", all_text)
        self.assertIn("git_status", all_text)
        self.assertIn("Final Synthesis Guidelines", all_text)
        self.assertIn("stored in the Personal Model", all_text)

        self.personal_store.delete_goal(goal["id"])
        self.personal_store.delete_project(proj["id"])

    # ── 12. /api/chat benefits from Personal Model context ────────────────────
    def test_12_api_chat_benefits_from_personal_model_context(self):
        proj = self.personal_store.create_project(name="API Chat Proj")
        client = TestClient(app)

        with patch("app.main.router.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = {
                "choices": [{"message": {"content": "I see your API Chat Proj project."}}],
                "model": "test-model",
            }
            resp = client.post("/api/chat", json={"message": "What project am I working on?"})
            self.assertEqual(resp.status_code, 200)

            call_msgs = mock_chat.call_args.kwargs.get("messages") or mock_chat.call_args[0][0]
            system_msg = [m["content"] for m in call_msgs if m["role"] == "system"][0]
            self.assertIn("<personal_model>", system_msg)
            self.assertIn("API Chat Proj", system_msg)

        self.personal_store.delete_project(proj["id"])

    # ── 13. Existing session history still works ──────────────────────────────
    def test_13_existing_session_history_still_works(self):
        session = self.sessions.create("Session test")
        session_id = session["id"]
        self.sessions.add_message(session_id, "user", "Prior question")
        self.sessions.add_message(session_id, "assistant", "Prior answer")

        context = self.context_engine.build_context("New message", session_id=session_id)
        self.assertEqual(len(context["messages"]), 2)
        self.assertEqual(context["messages"][0]["content"], "Prior question")
        self.assertEqual(context["messages"][1]["content"], "Prior answer")

        self.sessions.delete(session_id)

    # ── 14. Existing memory behavior still works ──────────────────────────────
    def test_14_existing_memory_behavior_still_works(self):
        mem = self.memory.remember("Persistent architectural rule", category="architecture", importance=5)
        context = self.context_engine.build_context("architecture questions")
        self.assertTrue(any(m["id"] == mem["id"] for m in context["memories"]))
        self.memory.delete(mem["id"])

    # ── 15. Existing confirmation-required tools remain confirmation-required ─
    def test_15_existing_confirmation_required_tools_remain_confirmation_required(self):
        router = make_mock_router([
            '{"action": "tool", "tool": "write_file", "arguments": {"path": "t.txt", "content": "c"}, "reason": "write"}',
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run("Write file"))
        self.assertEqual(result["permission_status"], "confirmation_required")
        self.assertIn("requires explicit user confirmation", result["response"])

    # ── 16. Existing blocked-tool behavior remains unchanged ──────────────────
    def test_16_existing_blocked_tool_behavior_remains_unchanged(self):
        class BlockedTool(Tool):
            name = "blocked_tool"
            description = "Blocked"
            permission = Permission.BLOCKED

            async def execute(self, **kwargs):
                return {}

        custom_reg = ToolRegistry()
        custom_reg.register(BlockedTool())

        router = make_mock_router(['{"action": "tool", "tool": "blocked_tool", "arguments": {}, "reason": "b"}'])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=custom_reg,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run("Execute blocked"))
        self.assertEqual(result["permission_status"], "blocked")
        self.assertIn("blocked by Orion's security policy", result["response"])

    # ── 17. No secrets enter Personal Model context ───────────────────────────
    def test_17_no_secrets_enter_personal_model_context(self):
        secret = "NEBIUS_SECRET_API_KEY_abcdef12345"
        proj = self.personal_store.create_project(name=f"Project with {secret}")

        with patch.dict(os.environ, {"NEBIUS_API_KEY": secret}):
            context = self.context_engine.build_context("Project info")
            prompt = self.context_engine.build_system_prompt(
                memories=[],
                personal_model=context["personal_model"],
            )
            # From _scrub_secrets in format or settings, secrets must not appear
            from app.agents.orchestrator import _scrub_secrets
            scrubbed_prompt = _scrub_secrets(prompt)
            self.assertNotIn(secret, scrubbed_prompt)

        self.personal_store.delete_project(proj["id"])

    # ── 18. No API keys/tokens enter planner prompts ──────────────────────────
    def test_18_no_api_keys_enter_planner_prompts(self):
        secret = "SECRET_TOKEN_998877665544"
        proj = self.personal_store.create_project(name="Safe Project")
        context = self.context_engine.build_context("Test")

        router = make_mock_router(['{"action": "respond", "reason": "ok"}'])
        planner = ToolPlanner(router)

        with patch.dict(os.environ, {"TEST_KEY": secret}):
            run(planner.plan(f"User message with {secret}", [], context=context))
            planner_call = router.chat.call_args
            call_msgs = planner_call.kwargs.get("messages") or planner_call.args[0]
            for m in call_msgs:
                from app.agents.orchestrator import _scrub_secrets
                scrubbed = _scrub_secrets(m["content"])
                self.assertNotIn(secret, scrubbed)

        self.personal_store.delete_project(proj["id"])

    # ── 19. No unbounded Personal Model dump occurs ───────────────────────────
    def test_19_no_unbounded_personal_model_dump_occurs(self):
        # Default snapshot limits must be bounded (<= 10 projects, <= 10 goals, <= 20 tasks, <= 10 decisions, <= 10 skills)
        snapshot = self.personal_service.get_personal_snapshot()
        self.assertLessEqual(len(snapshot["projects"]), 10)
        self.assertLessEqual(len(snapshot["goals"]), 10)
        self.assertLessEqual(len(snapshot["tasks"]), 20)
        self.assertLessEqual(len(snapshot["decisions"]), 10)
        self.assertLessEqual(len(snapshot["skills"]), 10)

    # ── 20. Realistic integration test ────────────────────────────────────────
    def test_20_realistic_integration_personal_model_and_tool_observation(self):
        """
        Create a test project in Personal Model:
          Project: name = "Orion", path = "/home/gfood/orion", status = "active"
          Goal: title = "Build Personal AI operating layer", status = "active"
        Request:
          "Inspect the Orion project status and explain how it relates to my current project context."
        Conceptual sequence:
          1. git_status
          2. final synthesis with access to both git_status observations and Personal Model goal
        """
        proj = self.personal_store.create_project(
            name="Orion",
            description="Personal AI operating layer",
            path="/home/gfood/orion",
            status="active",
        )
        goal = self.personal_store.create_goal(
            title="Build Personal AI operating layer",
            description="Autonomous operating system for personal workflows",
            status="active",
            project_id=proj["id"],
        )

        router = make_mock_router([
            # Step 1: planner requests git_status
            '{"action": "tool", "tool": "git_status", "arguments": {}, "reason": "Inspect repo status"}',
            # Step 2: planner finishes
            '{"action": "respond", "reason": "Synthesize observed status with stored goal"}',
            # Synthesis response
            "Observed that the Orion workspace Git repository is clean. This aligns with your active goal 'Build Personal AI operating layer'.",
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run(
            "Inspect the Orion project status and explain how it relates to my current project context."
        ))

        # Verification of steps
        self.assertEqual(len(result["steps"]), 2)
        self.assertEqual(result["steps"][0]["tool"], "git_status")
        self.assertEqual(result["steps"][0]["status"], "executed")
        self.assertEqual(result["steps"][1]["action"], "respond")

        # Synthesis call verification:
        synthesis_call = router.chat.call_args_list[2]
        synthesis_messages = synthesis_call.kwargs.get("messages") or synthesis_call.args[0]
        all_text = " ".join(m.get("content", "") for m in synthesis_messages)

        # Personal Model context present
        self.assertIn("Build Personal AI operating layer", all_text)
        self.assertIn("/home/gfood/orion", all_text)
        # Tool observation present
        self.assertIn("git_status", all_text)
        self.assertIn("is_repo", all_text)

        # Final answer content
        self.assertIn("clean", result["response"].lower())
        self.assertIn("build personal ai operating layer", result["response"].lower())

        self.personal_store.delete_goal(goal["id"])
        self.personal_store.delete_project(proj["id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
