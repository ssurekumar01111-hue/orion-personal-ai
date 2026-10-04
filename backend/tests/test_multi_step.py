"""
Unit and integration tests for the Orion Bounded Multi-Step Agent Loop.

Tests cover all 22 required specifications:
  1. Single respond still works.
  2. One automatic tool still works.
  3. Two sequential automatic tools work.
  4. Three sequential automatic tools work.
  5. Planner receives previous observations.
  6. Maximum 5 iterations is enforced.
  7. Sixth iteration is never executed.
  8. Repeated identical tool call terminates safely.
  9. Confirmation-required tool stops the loop.
  10. Confirmation-required tool is never executed automatically.
  11. Blocked tool stops the loop.
  12. Blocked tool is never executed.
  13. Tool execution error terminates safely.
  14. Final synthesis receives tool observations.
  15. Nebius provider propagation works.
  16. Hermes provider propagation works.
  17. Secrets never enter planner context.
  18. Secrets never enter final response through audit/context paths.
  19. Existing session behavior remains correct.
  20. Existing tool permission behavior remains unchanged.
  21. Orchestrator stores decision reason in observations (5C-3A loop fix).
  22. Observations without reason are backward compatible.
  + Real integration test with read-only tools ("Inspect the project README and git status...").
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
import unittest
import warnings
from unittest.mock import AsyncMock, MagicMock, patch

warnings.filterwarnings("ignore", category=DeprecationWarning)

sys.path.insert(0, str(Path(__file__).parents[1]))

from starlette.testclient import TestClient

from app.agents.orchestrator import AgentOrchestrator, _sanitize_data, _scrub_secrets
from app.main import app
from app.memory.context import ContextEngine
from app.memory.session import SessionStore
from app.memory.store import MemoryStore
from app.tools.base import Tool
from app.tools.permissions import DEFAULT_TOOL_PERMISSIONS, Permission
from app.tools.planner import ToolPlanner
from app.tools.registry import create_default_registry, ToolRegistry


def run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


def make_mock_router(chat_responses: list[dict[str, Any]]) -> AsyncMock:
    """Return a mock ModelRouter that yields from chat_responses sequentially."""
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
            "choices": [{"message": {"content": "default response"}}],
            "model": "test-model",
        }

    router.chat.side_effect = _chat
    return router


class TestBoundedMultiStepLoop(unittest.TestCase):
    """Unit tests for the bounded multi-step agent loop in AgentOrchestrator."""

    def setUp(self):
        self.memory = MemoryStore()
        self.sessions = SessionStore()
        self.context_engine = ContextEngine(
            memory_store=self.memory,
            session_store=self.sessions,
        )
        self.registry = create_default_registry()

    # ── 1. Single respond still works ─────────────────────────────────────────
    def test_1_single_respond_still_works(self):
        """Planner immediately returns 'respond' → direct conversational answer, 1 step."""
        router = make_mock_router([
            '{"action": "respond", "reason": "General question"}',
            "Hello! How can I help you today?",
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run("Hello there"))

        self.assertEqual(result["response"], "Hello! How can I help you today?")
        self.assertEqual(result["planner_decision"]["action"], "respond")
        self.assertIsNone(result["tool_used"])
        self.assertIsNone(result["tool_result"])
        self.assertEqual(len(result["steps"]), 1)
        self.assertEqual(result["steps"][0]["action"], "respond")
        self.assertEqual(result["steps"][0]["status"], "completed")

    # ── 2. One automatic tool still works ──────────────────────────────────────
    def test_2_one_automatic_tool_still_works(self):
        """Step 1: list_directory → Step 2: respond → 2 steps, final synthesis."""
        router = make_mock_router([
            '{"action": "tool", "tool": "list_directory", "arguments": {"path": "."}, "reason": "List files"}',
            '{"action": "respond", "reason": "Now I can describe the files"}',
            "The workspace contains several directories.",
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run("List my files"))

        self.assertEqual(result["response"], "The workspace contains several directories.")
        self.assertEqual(result["planner_decision"]["action"], "tool")
        self.assertEqual(result["tool_used"], "list_directory")
        self.assertIsNotNone(result["tool_result"])
        self.assertEqual(result["permission_status"], "automatic")
        self.assertEqual(len(result["steps"]), 2)
        self.assertEqual(result["steps"][0]["tool"], "list_directory")
        self.assertEqual(result["steps"][0]["status"], "executed")
        self.assertEqual(result["steps"][1]["action"], "respond")
        self.assertEqual(result["steps"][1]["status"], "completed")

    # ── 3. Two sequential automatic tools work ────────────────────────────────
    def test_3_two_sequential_automatic_tools_work(self):
        """Step 1: git_status → Step 2: list_directory → Step 3: respond."""
        router = make_mock_router([
            '{"action": "tool", "tool": "git_status", "arguments": {}, "reason": "Check git"}',
            '{"action": "tool", "tool": "list_directory", "arguments": {"path": "."}, "reason": "Check files"}',
            '{"action": "respond", "reason": "Done"}',
            "Git is clean and workspace files are present.",
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run("Check repo and files"))

        self.assertEqual(len(result["steps"]), 3)
        self.assertEqual(result["steps"][0]["tool"], "git_status")
        self.assertEqual(result["steps"][0]["status"], "executed")
        self.assertEqual(result["steps"][1]["tool"], "list_directory")
        self.assertEqual(result["steps"][1]["status"], "executed")
        self.assertEqual(result["steps"][2]["action"], "respond")
        self.assertEqual(result["steps"][2]["status"], "completed")
        self.assertEqual(result["response"], "Git is clean and workspace files are present.")

    # ── 4. Three sequential automatic tools work ──────────────────────────────
    def test_4_three_sequential_automatic_tools_work(self):
        """Step 1: git_status → Step 2: list_directory → Step 3: read_file → Step 4: respond."""
        router = make_mock_router([
            '{"action": "tool", "tool": "git_status", "arguments": {}, "reason": "Check git"}',
            '{"action": "tool", "tool": "list_directory", "arguments": {"path": "backend"}, "reason": "List backend"}',
            '{"action": "tool", "tool": "read_file", "arguments": {"path": "backend/requirements.txt"}, "reason": "Read requirements"}',
            '{"action": "respond", "reason": "Summary ready"}',
            "Repository status, files, and requirements summarized.",
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run("Inspect backend dependencies and git status"))

        self.assertEqual(len(result["steps"]), 4)
        self.assertEqual(result["steps"][0]["tool"], "git_status")
        self.assertEqual(result["steps"][1]["tool"], "list_directory")
        self.assertEqual(result["steps"][2]["tool"], "read_file")
        self.assertEqual(result["steps"][3]["action"], "respond")
        self.assertEqual(result["steps"][0]["status"], "executed")
        self.assertEqual(result["steps"][1]["status"], "executed")
        self.assertEqual(result["steps"][2]["status"], "executed")
        self.assertEqual(result["steps"][3]["status"], "completed")

    # ── 5. Planner receives previous observations ─────────────────────────────
    def test_5_planner_receives_previous_observations(self):
        """Planner receives accumulated observations from prior steps."""
        router = make_mock_router([
            '{"action": "tool", "tool": "git_status", "arguments": {}, "reason": "Check git"}',
            '{"action": "tool", "tool": "list_directory", "arguments": {"path": "."}, "reason": "Check files"}',
            '{"action": "respond", "reason": "Done"}',
            "Final summary.",
        ])
        planner = ToolPlanner(router)
        recorded_observations = []

        real_plan = planner.plan

        async def spy_plan(user_message, available_tools, provider="nebius", observations=None):
            recorded_observations.append(list(observations) if observations else None)
            return await real_plan(user_message, available_tools, provider, observations)

        planner.plan = spy_plan

        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        run(orchestrator.run("Check repo and files"))

        self.assertEqual(len(recorded_observations), 3)
        # Iteration 1: no previous observations
        self.assertIsNone(recorded_observations[0])
        # Iteration 2: 1 observation from git_status
        self.assertIsNotNone(recorded_observations[1])
        self.assertEqual(len(recorded_observations[1]), 1)
        self.assertEqual(recorded_observations[1][0]["tool"], "git_status")
        # Iteration 3: 2 observations (git_status + list_directory)
        self.assertIsNotNone(recorded_observations[2])
        self.assertEqual(len(recorded_observations[2]), 2)
        self.assertEqual(recorded_observations[2][0]["tool"], "git_status")
        self.assertEqual(recorded_observations[2][1]["tool"], "list_directory")

    # ── 6. Maximum 5 iterations is enforced ───────────────────────────────────
    def test_6_maximum_5_iterations_is_enforced(self):
        """When planner keeps requesting tools, loop terminates at 5 iterations."""
        router = make_mock_router([
            '{"action": "tool", "tool": "git_status", "arguments": {}, "reason": "step 1"}',
            '{"action": "tool", "tool": "list_directory", "arguments": {"path": "."}, "reason": "step 2"}',
            '{"action": "tool", "tool": "list_directory", "arguments": {"path": "backend"}, "reason": "step 3"}',
            '{"action": "tool", "tool": "list_directory", "arguments": {"path": "data"}, "reason": "step 4"}',
            '{"action": "tool", "tool": "read_file", "arguments": {"path": "backend/requirements.txt"}, "reason": "step 5"}',
            '{"action": "tool", "tool": "read_file", "arguments": {"path": "README.md"}, "reason": "step 6 should not run"}',
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run("Do 6 things"))

        self.assertEqual(len(result["steps"]), 5)
        self.assertIn("Bounded execution limit of 5 iterations was reached", result["response"])
        self.assertIn("incomplete", result["response"].lower())

    # ── 7. Sixth iteration is never executed ──────────────────────────────────
    def test_7_sixth_iteration_is_never_executed(self):
        """Planner and registry are called at most 5 times."""
        router = make_mock_router([
            '{"action": "tool", "tool": "git_status", "arguments": {}, "reason": "step 1"}',
            '{"action": "tool", "tool": "list_directory", "arguments": {"path": "."}, "reason": "step 2"}',
            '{"action": "tool", "tool": "list_directory", "arguments": {"path": "backend"}, "reason": "step 3"}',
            '{"action": "tool", "tool": "list_directory", "arguments": {"path": "data"}, "reason": "step 4"}',
            '{"action": "tool", "tool": "read_file", "arguments": {"path": "backend/requirements.txt"}, "reason": "step 5"}',
            '{"action": "tool", "tool": "read_file", "arguments": {"path": "README.md"}, "reason": "step 6"}',
        ])
        planner = ToolPlanner(router)
        plan_spy = AsyncMock(wraps=planner.plan)
        planner.plan = plan_spy

        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        run(orchestrator.run("Do 6 things"))

        self.assertEqual(plan_spy.call_count, 5)

    # ── 8. Repeated identical tool call terminates safely ─────────────────────
    def test_8_repeated_identical_tool_call_terminates_safely(self):
        """Selecting the exact same tool and arguments consecutively terminates safely."""
        router = make_mock_router([
            '{"action": "tool", "tool": "git_status", "arguments": {}, "reason": "Check git"}',
            '{"action": "tool", "tool": "git_status", "arguments": {}, "reason": "Check git again"}',
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run("Check git repeatedly"))

        self.assertEqual(len(result["steps"]), 2)
        self.assertEqual(result["steps"][0]["status"], "executed")
        self.assertEqual(result["steps"][1]["status"], "repeated_call")
        self.assertIn("Repeated identical tool call", result["response"])

    # ── 9. Confirmation-required tool stops the loop ──────────────────────────
    def test_9_confirmation_required_tool_stops_the_loop(self):
        """Selecting a confirmation_required tool terminates loop with confirmation prompt."""
        router = make_mock_router([
            '{"action": "tool", "tool": "write_file", "arguments": {"path": "test.txt", "content": "hello"}, "reason": "Write file"}',
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run("Write to file"))

        self.assertEqual(len(result["steps"]), 1)
        self.assertEqual(result["steps"][0]["status"], "confirmation_required")
        self.assertEqual(result["permission_status"], "confirmation_required")
        self.assertIn("requires explicit user confirmation", result["response"])

    # ── 10. Confirmation-required tool is never executed automatically ────────
    def test_10_confirmation_required_tool_is_never_executed_automatically(self):
        """ToolRegistry.execute is never invoked when tool requires confirmation."""
        router = make_mock_router([
            '{"action": "tool", "tool": "write_file", "arguments": {"path": "test.txt", "content": "hello"}, "reason": "Write"}',
        ])
        planner = ToolPlanner(router)
        mock_registry = MagicMock(wraps=self.registry)
        mock_registry.execute = AsyncMock()

        orchestrator = AgentOrchestrator(
            router=router,
            registry=mock_registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run("Write file"))

        mock_registry.execute.assert_not_called()
        self.assertIsNone(result["tool_result"])

    # ── 11. Blocked tool stops the loop ───────────────────────────────────────
    def test_11_blocked_tool_stops_the_loop(self):
        """Selecting a blocked tool stops the loop with a policy error response."""
        class DummyBlockedTool(Tool):
            name = "blocked_danger_tool"
            description = "Dangerous operation"
            permission = Permission.BLOCKED

            async def execute(self, **kwargs):
                return {"status": "danger"}

        custom_registry = ToolRegistry()
        custom_registry.register(DummyBlockedTool())

        router = make_mock_router([
            '{"action": "tool", "tool": "blocked_danger_tool", "arguments": {}, "reason": "dangerous"}',
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=custom_registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run("Run danger"))

        self.assertEqual(len(result["steps"]), 1)
        self.assertEqual(result["steps"][0]["status"], "blocked")
        self.assertEqual(result["permission_status"], "blocked")
        self.assertIn("blocked by Orion's security policy", result["response"])

    # ── 12. Blocked tool is never executed ────────────────────────────────────
    def test_12_blocked_tool_is_never_executed(self):
        """Verify blocked tool execute method is never called."""
        tool_executed = False

        class DummyBlockedTool(Tool):
            name = "blocked_danger_tool"
            description = "Dangerous operation"
            permission = Permission.BLOCKED

            async def execute(self, **kwargs):
                nonlocal tool_executed
                tool_executed = True
                return {"status": "danger"}

        custom_registry = ToolRegistry()
        custom_registry.register(DummyBlockedTool())

        router = make_mock_router([
            '{"action": "tool", "tool": "blocked_danger_tool", "arguments": {}, "reason": "dangerous"}',
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=custom_registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run("Run danger"))

        self.assertFalse(tool_executed)
        self.assertIsNone(result["tool_result"])

    # ── 13. Tool execution error terminates safely ────────────────────────────
    def test_13_tool_execution_error_terminates_safely(self):
        """Tool execution raising an error terminates the loop safely without crashing."""
        router = make_mock_router([
            '{"action": "tool", "tool": "read_file", "arguments": {"path": "nonexistent_file_12345.txt"}, "reason": "Read missing"}',
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run("Read missing file"))

        self.assertEqual(len(result["steps"]), 1)
        self.assertEqual(result["steps"][0]["status"], "error")
        self.assertIn("execution failed", result["response"])

    # ── 14. Final synthesis receives tool observations ────────────────────────
    def test_14_final_synthesis_receives_tool_observations(self):
        """Final synthesis prompt includes previous tool observations."""
        router = make_mock_router([
            '{"action": "tool", "tool": "git_status", "arguments": {}, "reason": "check"}',
            '{"action": "respond", "reason": "ready"}',
            "Synthesized summary of git status.",
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run("Check repo status"))

        self.assertEqual(router.chat.call_count, 3)
        # Call 3 is the final synthesis call
        synthesis_call = router.chat.call_args_list[2]
        synthesis_messages = synthesis_call.kwargs.get("messages") or synthesis_call.args[0]

        all_text = " ".join(m.get("content", "") for m in synthesis_messages)
        self.assertIn("git_status", all_text)
        self.assertIn("is_repo", all_text)
        self.assertIn("Final Synthesis Guidelines", all_text)
        self.assertEqual(result["response"], "Synthesized summary of git status.")

    # ── 15. Nebius provider propagation works ─────────────────────────────────
    def test_15_nebius_provider_propagation_works(self):
        """Provider 'nebius' is passed to planner and router."""
        router = make_mock_router([
            '{"action": "respond", "reason": "ok"}',
            "Hello from Nebius",
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run("Hi", provider="nebius"))

        self.assertEqual(result["provider"], "nebius")
        for call_item in router.chat.call_args_list:
            _, kwargs = call_item
            self.assertEqual(kwargs.get("provider"), "nebius")

    # ── 16. Hermes provider propagation works ─────────────────────────────────
    def test_16_hermes_provider_propagation_works(self):
        """Provider 'hermes' is passed to planner and router."""
        router = make_mock_router([
            '{"action": "respond", "reason": "ok"}',
            "Hello from Hermes",
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run("Hi", provider="hermes"))

        self.assertEqual(result["provider"], "hermes")
        for call_item in router.chat.call_args_list:
            _, kwargs = call_item
            self.assertEqual(kwargs.get("provider"), "hermes")

    # ── 17. Secrets never enter planner context ───────────────────────────────
    def test_17_secrets_never_enter_planner_context(self):
        """Mock tool returning secrets is scrubbed before passing to planner."""
        secret_value = "SECRET_API_KEY_xyz9876543210"

        class LeakyTool(Tool):
            name = "leaky_tool"
            description = "Tool that returns sensitive token"
            permission = Permission.AUTOMATIC

            async def execute(self, **kwargs):
                return {"token": secret_value, "safe_data": "ok"}

        custom_registry = ToolRegistry()
        custom_registry.register(LeakyTool())

        captured_planner_prompts = []
        router = AsyncMock()

        async def _chat(messages, provider="nebius", **kwargs):
            for m in messages:
                captured_planner_prompts.append(m.get("content", ""))
            if len(captured_planner_prompts) <= 2:
                return {
                    "choices": [{
                        "message": {
                            "content": '{"action": "tool", "tool": "leaky_tool", "arguments": {}, "reason": "leak"}'
                        }
                    }],
                    "model": "test-model",
                }
            return {
                "choices": [{
                    "message": {
                        "content": '{"action": "respond", "reason": "done"}'
                    }
                }],
                "model": "test-model",
            }

        router.chat.side_effect = _chat
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=custom_registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        with patch.dict(os.environ, {"TEST_SECRET_KEY": secret_value}):
            run(orchestrator.run("Run leaky tool"))

        for prompt in captured_planner_prompts:
            self.assertNotIn(secret_value, prompt, "Secret leaked into planner prompt context!")

    # ── 18. Secrets never enter final response through audit/context paths ─────
    def test_18_secrets_never_enter_final_response_through_audit_context_paths(self):
        """Secret scrubbers remove keys and tokens from data structures and strings."""
        secret = "secret-token-123456789"
        raw_data = {
            "api_key": secret,
            "normal": f"Text with {secret}",
            "sub": [{"nested_token": secret}],
        }
        with patch.dict(os.environ, {"MY_SECRET_TOKEN": secret}):
            sanitized = _sanitize_data(raw_data)
            self.assertEqual(sanitized["api_key"], "<REDACTED>")
            self.assertNotIn(secret, sanitized["normal"])
            self.assertIn("<REDACTED>", sanitized["normal"])
            self.assertEqual(sanitized["sub"][0]["nested_token"], "<REDACTED>")

    # ── 19. Existing session behavior remains correct ─────────────────────────
    def test_19_existing_session_behavior_remains_correct(self):
        """Session records user and assistant messages without unnecessary duplication."""
        session = self.sessions.create("Test conversation")
        session_id = session["id"]

        router = make_mock_router([
            '{"action": "respond", "reason": "Answer directly"}',
            "Orion personal AI core.",
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        self.sessions.add_message(session_id, "user", "What is Orion?")
        result = run(orchestrator.run("What is Orion?", session_id=session_id))
        self.sessions.add_message(session_id, "assistant", result["response"])

        messages = self.sessions.get_messages(session_id)
        # Should have exactly 1 user message and 1 assistant message
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[0]["content"], "What is Orion?")
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(messages[1]["content"], "Orion personal AI core.")

    # ── 20. Existing tool permission behavior remains unchanged ───────────────
    def test_20_existing_tool_permission_behavior_remains_unchanged(self):
        """All 6 default tools maintain their original permission levels."""
        expected_permissions = {
            "list_directory": Permission.AUTOMATIC,
            "read_file": Permission.AUTOMATIC,
            "git_status": Permission.AUTOMATIC,
            "write_file": Permission.CONFIRMATION_REQUIRED,
            "delete_file": Permission.CONFIRMATION_REQUIRED,
            "run_command": Permission.CONFIRMATION_REQUIRED,
        }
        self.assertEqual(DEFAULT_TOOL_PERMISSIONS, expected_permissions)

    # ── 21. Orchestrator stores decision reason in observations ───────────────
    def test_21_orchestrator_stores_reason_in_observations(self):
        """
        After each automatic tool execution the observation entry must carry
        the planner's 'reason' field from the decision that selected it.
        This is the orchestrator half of the 5C-3A decision-history fix.
        """
        recorded_observations: list[list[dict]] = []

        router = make_mock_router([
            '{"action": "tool", "tool": "git_status", "arguments": {}, "reason": "Check repo state"}',
            '{"action": "tool", "tool": "list_directory", "arguments": {"path": "."}, "reason": "List workspace files"}',
            '{"action": "respond", "reason": "Done"}',
            "Summary here.",
        ])
        planner = ToolPlanner(router)
        real_plan = planner.plan

        async def spy_plan(user_message, available_tools, provider="nebius",
                           observations=None, **kwargs):
            recorded_observations.append(
                [dict(o) for o in observations] if observations else None
            )
            return await real_plan(
                user_message, available_tools, provider, observations, **kwargs
            )

        planner.plan = spy_plan
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        run(orchestrator.run("Check repo and list workspace"))

        # Iteration 2 receives 1 observation (from git_status at iter 1)
        obs_iter2 = recorded_observations[1]
        self.assertIsNotNone(obs_iter2)
        self.assertEqual(len(obs_iter2), 1)
        self.assertEqual(obs_iter2[0]["tool"], "git_status")
        self.assertIn("reason", obs_iter2[0], "obs_entry must have 'reason' key")
        self.assertEqual(obs_iter2[0]["reason"], "Check repo state")

        # Iteration 3 receives 2 observations
        obs_iter3 = recorded_observations[2]
        self.assertIsNotNone(obs_iter3)
        self.assertEqual(len(obs_iter3), 2)
        self.assertEqual(obs_iter3[1]["tool"], "list_directory")
        self.assertEqual(obs_iter3[1]["reason"], "List workspace files")

    # ── 22. Observations without reason are backward compatible ───────────────
    def test_22_observations_without_reason_backward_compatible(self):
        """
        If an observation lacks a 'reason' key (e.g. from older code paths or
        tests that don't supply one), the planner must still work correctly.
        The missing reason must default to an empty string and must not appear
        in the observation block as 'Planned because: …'.
        """
        captured_messages: list[str] = []
        router = AsyncMock()
        call_count = 0

        async def _chat(messages, provider="nebius", **kwargs):
            nonlocal call_count
            call_count += 1
            for m in messages:
                captured_messages.append(m.get("content", ""))
            if call_count == 1:
                # First call: select a tool (no reason)
                return {
                    "choices": [{"message": {"content":
                        '{"action": "tool", "tool": "git_status", "arguments": {}, "reason": ""}'
                    }}],
                    "model": "test-model",
                }
            # Second call: respond
            return {
                "choices": [{"message": {"content":
                    '{"action": "respond", "reason": "done"}'
                }}],
                "model": "test-model",
            }

        router.chat.side_effect = _chat
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run("Check git"))

        # Must complete successfully
        self.assertNotIn("error", result.get("response", "").lower())
        # No 'Planned because' line should appear for empty-reason obs
        obs_messages = [m for m in captured_messages if "PREVIOUS OBSERVATIONS" in m]
        for msg in obs_messages:
            self.assertNotIn(
                "Planned because:",
                msg,
                "Empty reason must not emit 'Planned because:' line",
            )



class TestMultiStepIntegration(unittest.TestCase):
    """Integration test using safe read-only tools."""

    def setUp(self):
        self.memory = MemoryStore()
        self.sessions = SessionStore()
        self.context_engine = ContextEngine(
            memory_store=self.memory,
            session_store=self.sessions,
        )
        self.registry = create_default_registry()

    def test_mock_multi_step_read_only_integration(self):
        """
        Multi-step read-only scenario:
        User: 'Inspect the project README and git status, then summarize what you find.'
        Sequence:
          1. git_status (automatic, executed)
          2. read_file (automatic, executed)
          3. respond (completed)
        """
        router = make_mock_router([
            '{"action": "tool", "tool": "git_status", "arguments": {}, "reason": "Check repo"}',
            '{"action": "tool", "tool": "read_file", "arguments": {"path": "README.md"}, "reason": "Read README"}',
            '{"action": "respond", "reason": "Summarize"}',
            "The repository is in a clean state and README outlines the Orion project.",
        ])
        memory = MemoryStore()
        sessions = SessionStore()
        context_engine = ContextEngine(memory_store=memory, session_store=sessions)
        registry = create_default_registry()
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=registry,
            context_engine=context_engine,
            planner=planner,
        )

        result = run(orchestrator.run(
            "Inspect the project README and git status, then summarize what you find."
        ))

        self.assertEqual(len(result["steps"]), 3)
        self.assertEqual(result["steps"][0]["tool"], "git_status")
        self.assertEqual(result["steps"][0]["permission"], "automatic")
        self.assertEqual(result["steps"][0]["status"], "executed")

        self.assertEqual(result["steps"][1]["tool"], "read_file")
        self.assertEqual(result["steps"][1]["permission"], "automatic")
        self.assertEqual(result["steps"][1]["status"], "executed")

        self.assertEqual(result["steps"][2]["action"], "respond")
        self.assertEqual(result["steps"][2]["status"], "completed")

        self.assertIn("clean", result["response"])

    # ── 5C-3 Convergence and Bounded Inspection Regression Tests ─────────────

    def test_5c3_all_three_files_and_structure_forced_completion(self):
        """
        All three files + backend + frontend structure → forced completion.
        After the 5 required targets are observed, orchestrator synthesizes
        response rather than hitting bounded execution limit or requesting more tools.
        """
        user_msg = (
            "Verify the setup instructions in my current README against the actual Orion workspace. "
            "Inspect README.md, backend/requirements.txt, frontend/package.json, and the relevant "
            "backend/frontend project structure. Determine whether documented commands correspond."
        )
        router = make_mock_router([
            '{"action": "tool", "tool": "read_file", "arguments": {"path": "README.md"}, "reason": "read readme"}',
            '{"action": "tool", "tool": "read_file", "arguments": {"path": "backend/requirements.txt"}, "reason": "read requirements"}',
            '{"action": "tool", "tool": "read_file", "arguments": {"path": "frontend/package.json"}, "reason": "read package json"}',
            '{"action": "tool", "tool": "list_directory", "arguments": {"path": "backend"}, "reason": "list backend"}',
            '{"action": "tool", "tool": "list_directory", "arguments": {"path": "frontend"}, "reason": "list frontend"}',
            # Synthesis response (called after 5th observation):
            "Verified README instructions against backend and frontend project structure.",
        ])
        planner = ToolPlanner(router)
        plan_spy = AsyncMock(wraps=planner.plan)
        planner.plan = plan_spy

        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run(user_msg))

        # Exactly 5 tool steps were executed
        self.assertEqual(len(result["steps"]), 5)
        for s in result["steps"]:
            self.assertEqual(s["status"], "executed")

        # Planner was called exactly 5 times, never a 6th time
        self.assertEqual(plan_spy.call_count, 5)

        # Response is the synthesized answer, not bounded limit reached
        self.assertIn("Verified README instructions", result["response"])
        self.assertNotIn("Bounded execution limit", result["response"])
        self.assertEqual(result["tool_used"], "list_directory")

    def test_5c3_backend_cannot_be_listed_twice(self):
        """Directory inspection is bounded: backend cannot be listed twice."""
        router = make_mock_router([
            '{"action": "tool", "tool": "list_directory", "arguments": {"path": "backend"}, "reason": "first list"}',
            '{"action": "tool", "tool": "list_directory", "arguments": {"path": "backend/"}, "reason": "second list"}',
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run("Inspect backend and frontend structure"))

        # Step 1 was executed, Step 2 was rejected as repeated_call
        self.assertEqual(len(result["steps"]), 2)
        self.assertEqual(result["steps"][0]["status"], "executed")
        self.assertEqual(result["steps"][1]["status"], "repeated_call")
        self.assertIn("Repeated directory inspection for 'backend' is not permitted", result["response"])

        # backend was executed exactly once
        executed_backend_calls = [
            s for s in result["steps"]
            if s.get("status") == "executed" and s.get("tool") == "list_directory"
        ]
        self.assertEqual(len(executed_backend_calls), 1)

    def test_5c3_frontend_cannot_be_listed_twice(self):
        """Directory inspection is bounded: frontend cannot be listed twice (normalized path)."""
        router = make_mock_router([
            '{"action": "tool", "tool": "list_directory", "arguments": {"path": "frontend"}, "reason": "first list"}',
            '{"action": "tool", "tool": "list_directory", "arguments": {"path": "./frontend/"}, "reason": "second list"}',
        ])
        planner = ToolPlanner(router)
        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run("Inspect backend and frontend structure"))

        # Step 1 was executed, Step 2 was rejected as repeated_call
        self.assertEqual(len(result["steps"]), 2)
        self.assertEqual(result["steps"][0]["status"], "executed")
        self.assertEqual(result["steps"][1]["status"], "repeated_call")
        self.assertIn("Repeated directory inspection for 'frontend' is not permitted", result["response"])

        executed_frontend_calls = [
            s for s in result["steps"]
            if s.get("status") == "executed" and s.get("tool") == "list_directory"
        ]
        self.assertEqual(len(executed_frontend_calls), 1)

    def test_5c3_unrelated_exploratory_directories_do_not_become_unlimited_targets(self):
        """
        Unrelated subdirectories (such as backend/app, backend/app/tools)
        discovered in directory listings are NOT treated as required targets.
        """
        user_msg = "Inspect backend/frontend project structure and verify commands."
        from app.tools.planner import InspectionCompletionState
        state = InspectionCompletionState(user_msg)

        # Only backend and frontend are extracted as structural targets
        self.assertEqual(state.structural_targets, ["backend", "frontend"])

        # Simulated observation returning subdirectories
        obs = [
            {
                "tool": "list_directory",
                "arguments": {"path": "backend"},
                "result": {
                    "path": "backend",
                    "entries": [
                        {"name": "app", "type": "directory"},
                        {"name": "tests", "type": "directory"},
                        {"name": "requirements.txt", "type": "file"},
                    ],
                },
            },
            {
                "tool": "list_directory",
                "arguments": {"path": "frontend"},
                "result": {
                    "path": "frontend",
                    "entries": [
                        {"name": "src", "type": "directory"},
                        {"name": "package.json", "type": "file"},
                    ],
                },
            },
        ]
        # State considers targets resolved once backend and frontend are observed
        self.assertTrue(state.is_complete(obs))
        self.assertNotIn("backend/app", state.structural_targets)
        self.assertNotIn("backend/tests", state.structural_targets)
        self.assertNotIn("frontend/src", state.structural_targets)

    def test_5c3_live_simulation_reads_files_then_structure_and_synthesizes(self):
        """
        Live/integration simulation of:
          1. read_file README.md
          2. read_file backend/requirements.txt
          3. read_file frontend/package.json
          4. list_directory backend
          5. list_directory frontend
        Verifies orchestrator chooses/responds after the final observation
        without requesting a sixth tool call.
        """
        user_msg = (
            "Verify the setup instructions in my current README against the actual Orion workspace. "
            "Inspect README.md, backend/requirements.txt, frontend/package.json, and the relevant "
            "backend/frontend project structure. Determine whether the documented backend and "
            "frontend start commands correspond to the actual project structure. Run only safe, "
            "non-mutating validation that Orion's available tools permit. Do not install packages, "
            "modify files, start long-running services, or change project data. Report each "
            "documented command as verified, inconsistent, or unverified, and explain why."
        )
        router = make_mock_router([
            '{"action": "tool", "tool": "read_file", "arguments": {"path": "README.md"}, "reason": "step 1: read README"}',
            '{"action": "tool", "tool": "read_file", "arguments": {"path": "backend/requirements.txt"}, "reason": "step 2: read requirements"}',
            '{"action": "tool", "tool": "read_file", "arguments": {"path": "frontend/package.json"}, "reason": "step 3: read package.json"}',
            '{"action": "tool", "tool": "list_directory", "arguments": {"path": "backend"}, "reason": "step 4: list backend"}',
            '{"action": "tool", "tool": "list_directory", "arguments": {"path": "frontend"}, "reason": "step 5: list frontend"}',
            # Final synthesis response:
            "Documented commands verification complete: backend command verified, frontend start command verified.",
        ])
        planner = ToolPlanner(router)
        plan_spy = AsyncMock(wraps=planner.plan)
        planner.plan = plan_spy

        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
        )

        result = run(orchestrator.run(user_msg))

        # Verify exactly 5 steps run
        self.assertEqual(len(result["steps"]), 5)
        self.assertEqual(result["steps"][0]["tool"], "read_file")
        self.assertEqual(result["steps"][1]["tool"], "read_file")
        self.assertEqual(result["steps"][2]["tool"], "read_file")
        self.assertEqual(result["steps"][3]["tool"], "list_directory")
        self.assertEqual(result["steps"][4]["tool"], "list_directory")

        # Planner was called exactly 5 times, never a 6th time
        self.assertEqual(plan_spy.call_count, 5)

        # Response is synthesized final answer
        self.assertIn("Documented commands verification complete", result["response"])
        self.assertNotIn("Bounded execution limit of 5 iterations was reached", result["response"])
        self.assertEqual(result["tool_used"], "list_directory")


if __name__ == "__main__":
    unittest.main(verbosity=2)
