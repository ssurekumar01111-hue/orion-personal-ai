"""
Unit tests for ToolPlanner — no real API calls; the ModelRouter is mocked.

Tests:
  A  Valid raw JSON response → valid decision returned.
  B  JSON wrapped in ```json...``` fence → fence stripped, valid decision.
  C  Planner returns an unknown tool name → controlled ValueError, no execution.
  D  Planner returns invalid JSON → controlled ValueError, no execution.
  E  Reasoning-model token budget regression (5C-3A fix):
       - ToolPlanner passes max_tokens=4096 (not the old 800) to the router.
       - Reasoning-model response with content populated parses correctly.
       - content=None (token exhaustion) still raises the empty-content guard.
  F  Decision-history regression (5C-3A loop fix):
       - Observation with reason → planner prompt includes "Planned because: …".
       - Observation without reason → prompt is unchanged (backward compatible).
       - Planner message carries reason text verbatim.
  G  Explicit target tracking and prompt guidance (5C-3A convergence fix):
       - Explicitly named files are extracted as required targets.
       - Successful read_file marks the exact target observed.
       - Directory listings do not mark a required file observed.
       - All targets observed produces deterministic completion signal.
       - Missing targets remain marked unresolved.
       - Requests without explicit file targets omit block.
       - Planner prompt contains explicit-target rules.
  I  Provider propagation regression:
       - ToolPlanner.plan() default provider is "nebius".
       - AgentOrchestrator.run() default provider is "nebius".
       - Explicit provider is forwarded to ModelRouter.chat().
"""
import asyncio
import inspect
import sys
import unittest
import warnings
from unittest.mock import AsyncMock, call

# Suppress the starlette/httpx deprecation warning that appears on import.
warnings.filterwarnings("ignore", category=DeprecationWarning)

sys.path.insert(0, __file__.replace("/tests/test_planner.py", ""))

from app.tools.planner import (
    InspectionCompletionState,
    ToolPlanner,
    _build_target_progress_block,
    _extract_requested_file_targets,
    _extract_requested_structural_targets,
    _normalize_dir_path,
    _strip_code_fence,
)
from app.agents.orchestrator import AgentOrchestrator


# ── helpers ──────────────────────────────────────────────────────────────────

SAMPLE_TOOLS = [
    {
        "name": "list_directory",
        "description": "List files and directories inside the Orion workspace.",
        "permission": "automatic",
    }
]


def make_router(content: str) -> AsyncMock:
    """Return a mocked ModelRouter whose chat() returns a single choice."""
    router = AsyncMock()
    router.chat.return_value = {
        "choices": [{"message": {"content": content}}],
        "model": "test-model",
    }
    return router


def run(coro):
    """Run an async coroutine synchronously (stdlib only, no pytest-asyncio)."""
    return asyncio.run(coro)


# ── Test A: valid raw JSON ────────────────────────────────────────────────────

class TestPlannerValidRawJSON(unittest.TestCase):
    """A: ToolPlanner receives valid raw JSON → returns valid decision."""

    def test_respond_action(self):
        router = make_router('{"action": "respond", "reason": "No tool needed"}')
        planner = ToolPlanner(router)

        result = run(planner.plan("Hello", SAMPLE_TOOLS))

        self.assertEqual(result["action"], "respond")
        self.assertIn("reason", result)

    def test_tool_action(self):
        router = make_router(
            '{"action": "tool", "tool": "list_directory",'
            ' "arguments": {}, "reason": "User wants files"}'
        )
        planner = ToolPlanner(router)

        result = run(planner.plan("List my files", SAMPLE_TOOLS))

        self.assertEqual(result["action"], "tool")
        self.assertEqual(result["tool"], "list_directory")
        self.assertIsInstance(result["arguments"], dict)


# ── Test B: fenced JSON ───────────────────────────────────────────────────────

class TestPlannerFencedJSON(unittest.TestCase):
    """B: ToolPlanner receives JSON wrapped in ```json...``` → valid decision."""

    def _fence(self, lang: str, payload: str) -> str:
        return f"```{lang}\n{payload}\n```"

    def test_json_fence(self):
        payload = '{"action": "respond", "reason": "test"}'
        router = make_router(self._fence("json", payload))
        planner = ToolPlanner(router)

        result = run(planner.plan("Hello", SAMPLE_TOOLS))
        self.assertEqual(result["action"], "respond")

    def test_plain_fence(self):
        payload = (
            '{"action": "tool", "tool": "list_directory",'
            ' "arguments": {}, "reason": "list files"}'
        )
        router = make_router(self._fence("", payload))
        planner = ToolPlanner(router)

        result = run(planner.plan("List files", SAMPLE_TOOLS))
        self.assertEqual(result["action"], "tool")
        self.assertEqual(result["tool"], "list_directory")

    def test_strip_code_fence_function_directly(self):
        """_strip_code_fence must handle all expected variations."""
        cases = [
            # (input, expected_output)
            ('{"a":1}',                          '{"a":1}'),
            ('```json\n{"a":1}\n```',             '{"a":1}'),
            ('```\n{"a":1}\n```',                 '{"a":1}'),
            ('  ```json\n{"a":1}\n```  ',         '{"a":1}'),
            ('  {"no":"fence"}  ',                '{"no":"fence"}'),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw[:30]):
                self.assertEqual(_strip_code_fence(raw), expected)


# ── Test C: unknown tool ──────────────────────────────────────────────────────

class TestPlannerUnknownTool(unittest.TestCase):
    """C: Planner returns unknown tool → controlled ValueError, no execution."""

    def test_unknown_tool_raises(self):
        bad_json = (
            '{"action": "tool", "tool": "rm_rf_root",'
            ' "arguments": {}, "reason": "malicious"}'
        )
        router = make_router(bad_json)
        planner = ToolPlanner(router)

        with self.assertRaises(ValueError) as ctx:
            run(planner.plan("do something dangerous", SAMPLE_TOOLS))

        self.assertIn("unavailable tool", str(ctx.exception))
        # router.chat was called (planning happened), but we never touch a
        # ToolRegistry — callers must not execute when ValueError is raised.

    def test_no_execution_on_unknown_tool(self):
        """Verify the exception is raised before any registry interaction."""
        router = make_router(
            '{"action": "tool", "tool": "nonexistent_tool",'
            ' "arguments": {}, "reason": "test"}'
        )
        planner = ToolPlanner(router)
        raised = False
        try:
            run(planner.plan("do something", SAMPLE_TOOLS))
        except ValueError:
            raised = True
        self.assertTrue(raised, "ValueError must be raised for unknown tools")


# ── Test D: invalid JSON ──────────────────────────────────────────────────────

class TestPlannerInvalidJSON(unittest.TestCase):
    """D: Planner returns invalid JSON → controlled ValueError, no execution."""

    def test_plain_text_raises(self):
        router = make_router("Sure, I will list your files for you!")
        planner = ToolPlanner(router)

        with self.assertRaises(ValueError) as ctx:
            run(planner.plan("list files", SAMPLE_TOOLS))

        self.assertIn("invalid JSON", str(ctx.exception))

    def test_partial_json_raises(self):
        router = make_router('{"action": "tool", ')
        planner = ToolPlanner(router)

        with self.assertRaises(ValueError) as ctx:
            run(planner.plan("list files", SAMPLE_TOOLS))

        self.assertIn("invalid JSON", str(ctx.exception))

    def test_empty_content_raises(self):
        router = make_router("")
        planner = ToolPlanner(router)

        with self.assertRaises(ValueError) as ctx:
            run(planner.plan("list files", SAMPLE_TOOLS))

        # Empty string hits the "empty content" guard before json.loads
        self.assertIn("empty", str(ctx.exception).lower())

    def test_unexpected_structure_raises(self):
        """Provider returns structurally wrong response (no 'choices' key)."""
        router = AsyncMock()
        router.chat.return_value = {"error": "service unavailable"}
        planner = ToolPlanner(router)

        with self.assertRaises(ValueError) as ctx:
            run(planner.plan("list files", SAMPLE_TOOLS))

        self.assertIn("unexpected response structure", str(ctx.exception))

    def test_invalid_action_raises(self):
        router = make_router('{"action": "hack", "reason": "bad"}')
        planner = ToolPlanner(router)

        with self.assertRaises(ValueError) as ctx:
            run(planner.plan("list files", SAMPLE_TOOLS))

        self.assertIn("invalid action", str(ctx.exception).lower())

    def test_non_dict_arguments_raises(self):
        router = make_router(
            '{"action": "tool", "tool": "list_directory",'
            ' "arguments": ["bad", "args"], "reason": "test"}'
        )
        planner = ToolPlanner(router)

        with self.assertRaises(ValueError) as ctx:
            run(planner.plan("list files", SAMPLE_TOOLS))

        self.assertIn("invalid tool arguments", str(ctx.exception).lower())

    def test_no_secret_in_error_message(self):
        """Raw model content in error messages must not contain the API key."""
        import os
        from pathlib import Path
        # Load the key from .env without importing settings (avoid lru_cache side-effects)
        env_path = Path(__file__).parents[2] / ".env"
        api_key = ""
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.upper().startswith("NEBIUS_API_KEY"):
                    api_key = line.split("=", 1)[-1].strip().strip('"').strip("'")
                    break

        router = make_router("not json")
        planner = ToolPlanner(router)
        try:
            run(planner.plan("test", SAMPLE_TOOLS))
        except ValueError as exc:
            if api_key:
                self.assertNotIn(api_key, str(exc), "API key must not appear in error")


# ── Test F: decision-history regression (5C-3A loop fix) ─────────────────────

class TestDecisionHistoryInObservations(unittest.TestCase):
    """
    F: Regression guard for the 5C-3A iteration-limit loop failure.

    Root cause: ToolPlanner.plan() was called fresh at every orchestrator
    iteration and only saw tool *results*, not the planner's own prior
    decisions.  The model therefore re-reasoned from scratch, picked a new
    tool it believed was needed, and the orchestrator executed a different
    one — causing the planner to re-derive the same intent on the next call
    (e.g. re-requesting README.md three times).

    Fix: the orchestrator now stores decision["reason"] in each obs_entry,
    and ToolPlanner emits it as "Planned because: …" in the observation
    header so the model at iteration N+1 knows what was already decided and
    executed.

    These tests verify:
      F1  An observation that carries a reason → the planner prompt message
          contains "Planned because: <reason>".
      F2  An observation without a reason (legacy / empty string) → the
          prompt is *identical* to the pre-fix format (backward compatible).
      F3  The reason text is included verbatim — no truncation or mutation.
    """
    def _capture_planner_messages(self, observations: list[dict]) -> list[dict]:
        """
        Run plan() with the given observations and return the list of message
        dicts that the mocked router received.
        """
        captured: list[list[dict]] = []
        router = AsyncMock()

        async def _chat(messages, **kwargs):
            captured.append(list(messages))
            return {
                "choices": [{"message": {"content": '{"action": "respond", "reason": "ok"}'}}],
                "model": "test-model",
            }

        router.chat.side_effect = _chat
        planner = ToolPlanner(router)
        run(planner.plan(
            user_message="What changed?",
            available_tools=SAMPLE_TOOLS,
            observations=observations,
        ))
        return captured[0]

    # F1 ── reason is injected into the planner prompt ────────────────────────

    def test_observation_with_reason_appears_in_planner_prompt(self):
        """
        When an obs_entry carries a non-empty reason, the user message sent
        to the router must contain 'Planned because: <reason>'.
        """
        obs = [{
            "step": 1,
            "tool": "list_directory",
            "arguments": {"path": "."},
            "result": {"path": ".", "entries": []},
            "reason": "Need workspace layout first",
        }]
        messages = self._capture_planner_messages(obs)
        user_msg = next(m["content"] for m in messages if m.get("role") == "user")
        self.assertIn(
            "Planned because: Need workspace layout first",
            user_msg,
            "Planner prompt must include 'Planned because: …' when reason is set",
        )
        self.assertIn("Tool: list_directory", user_msg)

    # F2 ── no-reason obs produces backward-compatible format ─────────────────

    def test_observation_without_reason_produces_legacy_format(self):
        """
        When obs_entry has no 'reason' key (or reason=''), the emitted
        observation block is identical to the pre-fix format:
        '[Step N]\\nTool: …\\nResult:\\n…' with no 'Planned because' line.
        """
        obs_no_reason = [{
            "step": 1,
            "tool": "git_status",
            "arguments": {},
            "result": {"is_repo": True},
            # no 'reason' key at all
        }]
        obs_empty_reason = [{
            "step": 1,
            "tool": "git_status",
            "arguments": {},
            "result": {"is_repo": True},
            "reason": "",   # explicitly empty
        }]

        msgs_no = self._capture_planner_messages(obs_no_reason)
        msgs_empty = self._capture_planner_messages(obs_empty_reason)

        user_no = next(m["content"] for m in msgs_no if m.get("role") == "user")
        user_empty = next(m["content"] for m in msgs_empty if m.get("role") == "user")

        self.assertNotIn(
            "Planned because",
            user_no,
            "No 'Planned because' line when reason is absent",
        )
        self.assertNotIn(
            "Planned because",
            user_empty,
            "No 'Planned because' line when reason is empty string",
        )
        # Both formats should be identical
        self.assertEqual(
            user_no, user_empty,
            "Missing-reason and empty-reason observations must produce identical output",
        )

    # F3 ── reason text is verbatim ───────────────────────────────────────────

    def test_reason_text_is_included_verbatim(self):
        """
        The full reason string is included without truncation or mutation.
        """
        long_reason = (
            "User explicitly asked for backend/requirements.txt and frontend/package.json "
            "to be read and cross-referenced with README setup instructions — "
            "this is step 3 of that multi-file inspection plan."
        )
        obs = [{
            "step": 3,
            "tool": "read_file",
            "arguments": {"path": "backend/requirements.txt"},
            "result": {"path": "backend/requirements.txt", "content": "fastapi\nhttpx\n"},
            "reason": long_reason,
        }]
        messages = self._capture_planner_messages(obs)
        user_msg = next(m["content"] for m in messages if m.get("role") == "user")
        self.assertIn(long_reason, user_msg)

    # F4 ── multiple observations: each reason is in the correct step block ───

    def test_multiple_observations_each_reason_correct(self):
        """
        With two observations each having distinct reasons, both appear in
        the correct step block and do not bleed into each other.
        """
        obs = [
            {
                "step": 1,
                "tool": "git_status",
                "arguments": {},
                "result": {"is_repo": True},
                "reason": "Reason for step ONE",
            },
            {
                "step": 2,
                "tool": "list_directory",
                "arguments": {"path": "."},
                "result": {"path": ".", "entries": []},
                "reason": "Reason for step TWO",
            },
        ]
        messages = self._capture_planner_messages(obs)
        user_msg = next(m["content"] for m in messages if m.get("role") == "user")

        self.assertIn("Planned because: Reason for step ONE", user_msg)
        self.assertIn("Planned because: Reason for step TWO", user_msg)
        # Each reason appears exactly once
        self.assertEqual(user_msg.count("Reason for step ONE"), 1)
        self.assertEqual(user_msg.count("Reason for step TWO"), 1)


# ── Test E: reasoning-model token budget regression (5C-3A fix) ───────────────

class TestReasoningModelTokenBudget(unittest.TestCase):
    """
    E: Regression guard for the 5C-3A failure.

    Root cause: nvidia/nemotron-3-super-120b-a12b is a reasoning model that
    consumes its token budget in an internal chain-of-thought phase before
    emitting content.  At max_tokens=800 the reasoning phase can exhaust the
    entire budget, causing the API to return {"content": null,
    "finish_reason": "length"}.  ToolPlanner then raised
    "Planner model returned empty content."

    Fix A raises max_tokens to 4096 so the reasoning phase has room to
    complete and the model can still emit its JSON reply.

    These tests verify:
      E1  ToolPlanner.plan() passes max_tokens=4096 (not 800) to the router.
      E2  A response where content IS populated after a larger token budget
          (simulating a successful reasoning-model completion) is parsed
          correctly — i.e. the fix does not regress existing happy-path logic.
      E3  A response where content=None and reasoning_content is non-empty
          (simulating token exhaustion at the old 800-token budget) raises
          the expected ValueError — confirming the empty-content guard is
          still in place and that Fix A's purpose is to prevent this scenario
          rather than silently swallow it.
    """

    def _make_reasoning_router(self, content, reasoning_content="I thought about it."):
        """
        Return a mocked router whose response mimics the Nebius reasoning-model
        wire format: message has both 'content' and 'reasoning_content'.
        """
        router = AsyncMock()
        router.chat.return_value = {
            "choices": [{
                "finish_reason": "stop" if content else "length",
                "message": {
                    "role": "assistant",
                    "content": content,
                    "reasoning_content": reasoning_content,
                    "refusal": None,
                    "tool_calls": None,
                },
            }],
            "model": "nvidia/nemotron-3-super-120b-a12b",
        }
        return router

    # E1 ── max_tokens passed to router is 4096 ───────────────────────────────

    def test_planner_uses_4096_max_tokens(self):
        """Fix A: ToolPlanner must pass max_tokens=4096 to the router."""
        router = make_router('{"action": "respond", "reason": "ok"}')
        planner = ToolPlanner(router)

        run(planner.plan("Hello", SAMPLE_TOOLS))

        router.chat.assert_called_once()
        _, kwargs = router.chat.call_args
        self.assertEqual(
            kwargs.get("max_tokens"),
            4096,
            "max_tokens must be 4096 after Fix A (was 800 before the fix)",
        )

    def test_planner_does_not_use_old_800_max_tokens(self):
        """Ensure the old 800 budget is not passed — prevents regression."""
        router = make_router('{"action": "respond", "reason": "ok"}')
        planner = ToolPlanner(router)

        run(planner.plan("Hello", SAMPLE_TOOLS))

        _, kwargs = router.chat.call_args
        self.assertNotEqual(
            kwargs.get("max_tokens"),
            800,
            "max_tokens must NOT be 800 after Fix A",
        )

    # E2 ── reasoning model with content populated succeeds ───────────────────

    def test_reasoning_model_with_content_succeeds(self):
        """
        Simulates a reasoning-model response where the larger token budget
        (4096) allowed the model to finish its chain-of-thought and emit
        valid JSON content.  The planner must parse and return the decision.
        """
        json_payload = '{"action": "respond", "reason": "Reasoned and answered."}'
        router = self._make_reasoning_router(
            content=json_payload,
            reasoning_content=(
                "The user said hello. No tool is required. "
                "I will respond directly. " * 50  # simulate long reasoning
            ),
        )
        planner = ToolPlanner(router)

        result = run(planner.plan("Hello", SAMPLE_TOOLS))

        self.assertEqual(result["action"], "respond")
        self.assertIn("reason", result)

    def test_reasoning_model_tool_decision_succeeds(self):
        """
        Reasoning-model response that selects a tool — parsed correctly
        despite the presence of reasoning_content in the message.
        """
        json_payload = (
            '{"action": "tool", "tool": "list_directory",'
            ' "arguments": {}, "reason": "User wants files."}'
        )
        router = self._make_reasoning_router(
            content=json_payload,
            reasoning_content=(
                "The user wants to list files. I should use list_directory."
            ),
        )
        planner = ToolPlanner(router)

        result = run(planner.plan("List my files", SAMPLE_TOOLS))

        self.assertEqual(result["action"], "tool")
        self.assertEqual(result["tool"], "list_directory")
        self.assertIsInstance(result["arguments"], dict)

    # E3 ── token-exhausted response (content=None) still raises correctly ────

    def test_null_content_with_reasoning_raises_empty_content_error(self):
        """
        Simulates the exact 5C-3A failure scenario: the model returned
        content=None and finish_reason=length (token budget exhausted during
        reasoning).  Fix A prevents this by raising max_tokens; but if it
        ever occurs again the existing empty-content guard must still fire
        with a clear error rather than a KeyError or AttributeError.
        """
        router = self._make_reasoning_router(
            content=None,   # ← the failure mode: content is null
            reasoning_content="Okay I am thinking about this carefully...",
        )
        planner = ToolPlanner(router)

        with self.assertRaises(ValueError) as ctx:
            run(planner.plan("Complex 5C-3A request", SAMPLE_TOOLS))

        self.assertIn(
            "empty",
            str(ctx.exception).lower(),
            "Empty-content guard must raise a clear ValueError",
        )


# ── Test G: explicit target tracking and prompt guidance (5C-3A convergence fix)

class TestExplicitTargetTracking(unittest.TestCase):
    """
    G: Regression guard for 5C-3A convergence fix (Option A and Option B).
    """

    def test_extract_explicitly_named_file_targets(self):
        msg = (
            "Verify the setup instructions in my current README against the actual "
            "Orion workspace. Inspect README.md, backend/requirements.txt, "
            "frontend/package.json, and the relevant backend/frontend project structure. "
            "Cross-reference with the actual files in the workspace. Report any discrepancies."
        )
        targets = _extract_requested_file_targets(msg)
        self.assertEqual(
            targets,
            ["README.md", "backend/requirements.txt", "frontend/package.json"],
        )
        # Verify arbitrary words and slashes are NOT extracted
        self.assertNotIn("backend/frontend", targets)
        self.assertNotIn("workspace", targets)
        self.assertNotIn("README", targets)

    def test_arbitrary_words_and_urls_not_extracted(self):
        msg = "Can you check either/or and backend/frontend and http://example.com/test.py and /abs/path.py or v1.0.0?"
        targets = _extract_requested_file_targets(msg)
        self.assertEqual(targets, [])

    def test_successful_read_file_marks_target_observed(self):
        targets = ["README.md", "backend/requirements.txt"]
        obs = [
            {
                "tool": "read_file",
                "arguments": {"path": "README.md"},
                "result": {"path": "README.md", "content": "# Orion"},
            }
        ]
        block = _build_target_progress_block(targets, obs)
        self.assertIn("- README.md [✓ observed]", block)
        self.assertIn("- backend/requirements.txt [unresolved]", block)

    def test_directory_listings_do_not_mark_target_observed(self):
        targets = ["README.md"]
        obs = [
            {
                "tool": "list_directory",
                "arguments": {"path": "."},
                "result": {"entries": [{"name": "README.md", "type": "file"}]},
            }
        ]
        block = _build_target_progress_block(targets, obs)
        self.assertIn("- README.md [unresolved]", block)
        self.assertNotIn("[✓ observed]", block)

    def test_read_file_error_does_not_mark_target_observed(self):
        targets = ["README.md"]
        obs = [
            {
                "tool": "read_file",
                "arguments": {"path": "README.md"},
                "result": {"error": "File not found"},
            }
        ]
        block = _build_target_progress_block(targets, obs)
        self.assertIn("- README.md [unresolved]", block)
        self.assertNotIn("[✓ observed]", block)

    def test_all_targets_observed_produces_completion_signal(self):
        targets = ["README.md", "backend/requirements.txt"]
        obs = [
            {
                "tool": "read_file",
                "arguments": {"path": "README.md"},
                "result": {"path": "README.md", "content": "# Orion"},
            },
            {
                "tool": "read_file",
                "arguments": {"path": "backend/requirements.txt"},
                "result": {"path": "backend/requirements.txt", "content": "fastapi"},
            },
        ]
        block = _build_target_progress_block(targets, obs)
        self.assertIn("- README.md [✓ observed]", block)
        self.assertIn("- backend/requirements.txt [✓ observed]", block)
        self.assertIn(
            "All required targets have been observed. Select respond unless another specific tool is clearly needed.",
            block,
        )

    def test_missing_targets_remain_marked_unresolved(self):
        targets = ["README.md", "backend/requirements.txt", "frontend/package.json"]
        obs = [
            {
                "tool": "read_file",
                "arguments": {"path": "README.md"},
                "result": {"content": "ok"},
            }
        ]
        block = _build_target_progress_block(targets, obs)
        self.assertIn("- backend/requirements.txt [unresolved]", block)
        self.assertIn("- frontend/package.json [unresolved]", block)
        self.assertIn("Unresolved targets: backend/requirements.txt, frontend/package.json", block)

    def test_requests_without_explicit_file_targets_omit_block(self):
        msg = "Hello, can you list my files and tell me the status?"
        targets = _extract_requested_file_targets(msg)
        self.assertEqual(targets, [])
        block = _build_target_progress_block(targets, [])
        self.assertEqual(block, "")

        # Verify planner call with no targets does not include REQUIRED FILES
        captured_messages = []
        router = AsyncMock()

        async def _chat(messages, **kwargs):
            captured_messages.extend(messages)
            return {
                "choices": [{"message": {"content": '{"action": "respond", "reason": "ok"}'}}],
                "model": "test-model",
            }

        router.chat.side_effect = _chat
        planner = ToolPlanner(router)
        run(planner.plan(msg, SAMPLE_TOOLS))

        user_msg = next(m["content"] for m in captured_messages if m["role"] == "user")
        self.assertNotIn("REQUIRED FILES", user_msg)

    def test_planner_prompt_contains_explicit_target_rules(self):
        captured_messages = []
        router = AsyncMock()

        async def _chat(messages, **kwargs):
            captured_messages.extend(messages)
            return {
                "choices": [{"message": {"content": '{"action": "respond", "reason": "ok"}'}}],
                "model": "test-model",
            }

        router.chat.side_effect = _chat
        planner = ToolPlanner(router)
        run(planner.plan("Verify README.md", SAMPLE_TOOLS))

        system_msg = next(m["content"] for m in captured_messages if m["role"] == "system")
        self.assertIn("treat each named path as a required inspection target", system_msg)
        self.assertIn("Do not select list_directory to verify the existence of a file path", system_msg)
        self.assertIn("Exploratory directory listings should not displace unresolved explicitly requested files", system_msg)
        self.assertIn("Once all explicitly named file targets have appeared in successful read_file observations", system_msg)

    def test_target_tracking_coexists_with_decision_history(self):
        captured_messages = []
        router = AsyncMock()

        async def _chat(messages, **kwargs):
            captured_messages.extend(messages)
            return {
                "choices": [{"message": {"content": '{"action": "respond", "reason": "ok"}'}}],
                "model": "test-model",
            }

        router.chat.side_effect = _chat
        planner = ToolPlanner(router)
        obs = [
            {
                "step": 1,
                "tool": "read_file",
                "arguments": {"path": "README.md"},
                "result": {"path": "README.md", "content": "hello"},
                "reason": "Inspect README first",
            }
        ]
        run(planner.plan(
            user_message="Inspect README.md and backend/requirements.txt",
            available_tools=SAMPLE_TOOLS,
            observations=obs,
        ))

        user_msg = next(m["content"] for m in captured_messages if m["role"] == "user")
        # Decision history is present
        self.assertIn("Planned because: Inspect README first", user_msg)
        # Target progress is present
        self.assertIn("REQUIRED FILES (named in the user request):", user_msg)
        self.assertIn("- README.md [✓ observed]", user_msg)
        self.assertIn("- backend/requirements.txt [unresolved]", user_msg)


# ── Test I: provider propagation regression ───────────────────────────────────

class TestProviderPropagation(unittest.TestCase):
    """I: Provider default remains "nebius"; explicit provider propagates."""

    def test_planner_plan_default_provider(self):
        sig = inspect.signature(ToolPlanner.plan)
        self.assertIn("provider", sig.parameters)
        self.assertEqual(sig.parameters["provider"].default, "nebius")

    def test_orchestrator_run_default_provider(self):
        sig = inspect.signature(AgentOrchestrator.run)
        self.assertIn("provider", sig.parameters)
        self.assertEqual(sig.parameters["provider"].default, "nebius")

    def test_explicit_provider_forwarded_to_router(self):
        """Explicit provider must be passed to ModelRouter.chat()."""
        router = make_router('{"action": "respond", "reason": "ok"}')
        planner = ToolPlanner(router)

        run(planner.plan("hello", SAMPLE_TOOLS, provider="nebius"))

        router.chat.assert_called_once()
        _, kwargs = router.chat.call_args
        self.assertEqual(kwargs.get("provider"), "nebius")

    def test_tools_plan_endpoint_uses_request_provider(self):
        """
        /api/tools/plan must propagate request.provider → planner.plan().
        We verify this by checking main.py source rather than running the server,
        keeping this test fast and dependency-free.
        """
        from pathlib import Path
        main_src = (Path(__file__).parents[1] / "app" / "main.py").read_text()
        # The plan_tool handler must pass provider=request.provider
        self.assertIn("provider=request.provider", main_src)


# ── Test J: structural target tracking and deterministic completion ──────────

class TestStructuralTargetTrackingAndBoundedCompletion(unittest.TestCase):
    """
    J: Regression guard for structural target tracking, directory normalization,
    and deterministic completion when all requested targets are resolved.
    """

    def test_extract_requested_structural_targets(self):
        msg = (
            "Verify the setup instructions in my current README against the actual "
            "Orion workspace. Inspect README.md, backend/requirements.txt, "
            "frontend/package.json, and the relevant backend/frontend project structure."
        )
        targets = _extract_requested_structural_targets(msg)
        self.assertEqual(targets, ["backend", "frontend"])

        # Single structural target
        self.assertEqual(_extract_requested_structural_targets("Inspect backend project structure"), ["backend"])
        self.assertEqual(_extract_requested_structural_targets("Check frontend directory structure"), ["frontend"])

        # No structural targets
        self.assertEqual(_extract_requested_structural_targets("Inspect README.md and run git_status"), [])

    def test_unrelated_exploratory_directories_not_targets(self):
        """Arbitrary exploratory directories like backend/app are not targets."""
        msg = "Inspect README.md and backend/frontend project structure."
        targets = _extract_requested_structural_targets(msg)
        self.assertEqual(targets, ["backend", "frontend"])
        self.assertNotIn("backend/app", targets)
        self.assertNotIn("backend/app/tools", targets)

    def test_normalize_dir_path(self):
        self.assertEqual(_normalize_dir_path("backend"), "backend")
        self.assertEqual(_normalize_dir_path("backend/"), "backend")
        self.assertEqual(_normalize_dir_path("./backend"), "backend")
        self.assertEqual(_normalize_dir_path("./backend/"), "backend")
        self.assertEqual(_normalize_dir_path("frontend"), "frontend")
        self.assertEqual(_normalize_dir_path("frontend/"), "frontend")
        self.assertEqual(_normalize_dir_path("./frontend"), "frontend")
        self.assertEqual(_normalize_dir_path("./frontend/"), "frontend")
        self.assertEqual(_normalize_dir_path("."), ".")
        self.assertEqual(_normalize_dir_path("./"), ".")
        self.assertEqual(_normalize_dir_path(""), ".")
        self.assertEqual(_normalize_dir_path(None), ".")

    def test_inspection_completion_state_all_resolved(self):
        msg = "Inspect README.md, backend/requirements.txt, frontend/package.json, and backend/frontend structure."
        state = InspectionCompletionState(msg)
        self.assertEqual(state.file_targets, ["README.md", "backend/requirements.txt", "frontend/package.json"])
        self.assertEqual(state.structural_targets, ["backend", "frontend"])
        self.assertTrue(state.has_targets)

        obs = [
            {"tool": "read_file", "arguments": {"path": "README.md"}, "result": {"content": "ok"}},
            {"tool": "read_file", "arguments": {"path": "backend/requirements.txt"}, "result": {"content": "ok"}},
            {"tool": "read_file", "arguments": {"path": "frontend/package.json"}, "result": {"content": "ok"}},
        ]
        # Only files observed so far
        self.assertFalse(state.is_complete(obs))

        # Add backend structure
        obs.append({"tool": "list_directory", "arguments": {"path": "backend"}, "result": {"entries": [], "path": "backend"}})
        self.assertFalse(state.is_complete(obs))
        self.assertTrue(state.is_dir_observed("backend", obs))
        self.assertTrue(state.is_dir_observed("backend/", obs))
        self.assertFalse(state.is_dir_observed("frontend", obs))

        # Add frontend structure
        obs.append({"tool": "list_directory", "arguments": {"path": "frontend/"}, "result": {"entries": [], "path": "frontend"}})
        self.assertTrue(state.is_complete(obs))
        self.assertTrue(state.is_dir_observed("frontend", obs))

    def test_build_target_progress_block_with_structure(self):
        msg = "Inspect README.md and backend/frontend structure."
        file_targets = ["README.md"]
        struct_targets = ["backend", "frontend"]
        obs = [
            {"tool": "read_file", "arguments": {"path": "README.md"}, "result": {"content": "ok"}},
            {"tool": "list_directory", "arguments": {"path": "backend"}, "result": {"entries": [], "path": "backend"}},
        ]
        block = _build_target_progress_block(file_targets, obs, structural_targets=struct_targets)
        self.assertIn("REQUIRED FILES (named in the user request):", block)
        self.assertIn("- README.md [✓ observed]", block)
        self.assertIn("REQUIRED STRUCTURE (named in the user request):", block)
        self.assertIn("- backend/ [✓ observed]", block)
        self.assertIn("- frontend/ [unresolved]", block)
        self.assertNotIn("ALL REQUESTED INSPECTION TARGETS RESOLVED", block)

        # Complete frontend as well
        obs.append({"tool": "list_directory", "arguments": {"path": "frontend"}, "result": {"entries": [], "path": "frontend"}})
        block_complete = _build_target_progress_block(file_targets, obs, structural_targets=struct_targets)
        self.assertIn("ALL REQUESTED INSPECTION TARGETS RESOLVED", block_complete)

    def test_planner_plan_deterministic_completion_without_llm_call(self):
        msg = "Inspect README.md and backend/frontend project structure."
        obs = [
            {"tool": "read_file", "arguments": {"path": "README.md"}, "result": {"content": "ok"}},
            {"tool": "list_directory", "arguments": {"path": "backend"}, "result": {"entries": [], "path": "backend"}},
            {"tool": "list_directory", "arguments": {"path": "frontend"}, "result": {"entries": [], "path": "frontend"}},
        ]
        router = AsyncMock()
        planner = ToolPlanner(router)
        decision = run(planner.plan(msg, SAMPLE_TOOLS, observations=obs))
        self.assertEqual(decision["action"], "respond")
        self.assertEqual(decision["reason"], "All requested inspection targets resolved")
        # Router was never invoked because completion was deterministic
        router.chat.assert_not_called()

    def test_inspection_state_is_dir_observed_normalized(self):
        msg = "Inspect files and folders"
        state = InspectionCompletionState(msg)
        obs = [
            {"tool": "list_directory", "arguments": {"path": "backend"}, "result": {"entries": [], "path": "backend"}},
        ]
        self.assertTrue(state.is_dir_observed("backend", obs))
        self.assertTrue(state.is_dir_observed("backend/", obs))
        self.assertTrue(state.is_dir_observed("./backend/", obs))
        self.assertFalse(state.is_dir_observed("frontend", obs))
        self.assertFalse(state.is_dir_observed("./frontend/", obs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
