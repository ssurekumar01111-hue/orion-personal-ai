"""
Focused security and functional tests for RunCommandTool:
- Registration and confirmation policy
- Command allowlist and argument policy validation
- Shell wrapper and metacharacter rejection
- Workspace boundary and cwd pinning (now points to dedicated workspace)
- Timeout enforcement and output bounds
- Secret redaction in output and audit log
- Secret exclusion from subprocess environment
- Agent loop integration (confirmation required without execution)
"""
import json
import os
import sys
import unittest
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

import subprocess

# Suppress starlette deprecation warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

sys.path.insert(0, str(Path(__file__).parents[1]))

from starlette.testclient import TestClient
from app.config import get_settings
from app.main import app
from app.tools.command import RunCommandTool, _get_safe_env
from app.tools.registry import create_default_registry
from app.tools.workspace import _get_workspace_root, PROJECT_ROOT

client = TestClient(app, raise_server_exceptions=True)
settings = get_settings()


AUDIT_LOG = PROJECT_ROOT / "data" / "audit.log"


def _audit_log() -> Path:
    """Return the audit log path in Orion's writable data area."""
    return AUDIT_LOG


class TestRunCommandTool(unittest.IsolatedAsyncioTestCase):
    """Security and functional unit tests for RunCommandTool."""

    async def asyncSetUp(self):
        self.tool = RunCommandTool()
        self.registry = create_default_registry()

    # 1. run_command is registered
    async def test_1_run_command_is_registered(self):
        tool = self.registry.get("run_command")
        self.assertIsNotNone(tool)
        self.assertEqual(tool.name, "run_command")

    # 2. permission is confirmation_required
    async def test_2_permission_is_confirmation_required(self):
        tools_list = self.registry.list_tools()
        rc_meta = next((t for t in tools_list if t["name"] == "run_command"), None)
        self.assertIsNotNone(rc_meta)
        self.assertEqual(rc_meta["permission"], "confirmation_required")

    # 3. execution without confirmation is blocked
    async def test_3_execution_without_confirmation_is_blocked(self):
        with self.assertRaises(PermissionError) as ctx:
            await self.registry.execute("run_command", command="git", arguments=["status"])
        self.assertIn("requires user confirmation", str(ctx.exception))

    # 4. blocked execution does not execute
    async def test_4_blocked_execution_does_not_execute(self):
        with patch("subprocess.run") as mock_run:
            try:
                await self.registry.execute("run_command", command="git", arguments=["status"])
            except PermissionError:
                pass
            mock_run.assert_not_called()

    # 5. git status runs without policy rejection when confirmed
    async def test_5_git_status_executes_when_confirmed(self):
        result = await self.registry.execute(
            "run_command",
            confirmed=True,
            command="git",
            arguments=["status"],
        )
        # The workspace may not be a git repo; non-zero exit is acceptable.
        # We verify the tool ran without policy rejection (no ValueError raised).
        self.assertIn(result["status"], ("completed", "timeout"))
        self.assertEqual(result["command"], "git")

    # 5b. python --version executes successfully when confirmed
    async def test_5b_python_version_executes_successfully_when_confirmed(self):
        result = await self.registry.execute(
            "run_command",
            confirmed=True,
            command="python3",
            arguments=["--version"],
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["return_code"], 0)

    # 6. cwd is exactly the dedicated workspace root (NOT the source tree)
    async def test_6_cwd_is_dedicated_workspace_not_source_tree(self):
        workspace = _get_workspace_root()
        source_root = PROJECT_ROOT

        # Workspace must not be the source tree
        self.assertNotEqual(str(workspace), str(source_root))
        # Workspace must not be inside application source code
        for src_dir in (source_root / "backend", source_root / "frontend", source_root / ".git"):
            with self.subTest(src_dir=src_dir):
                self.assertFalse(str(workspace).startswith(str(src_dir)))

        mock_proc = MagicMock(returncode=0, stdout="clean", stderr="")
        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            await self.tool.execute("git", ["status"])
            mock_run.assert_called_once()
            _, kwargs = mock_run.call_args
            actual_cwd = kwargs.get("cwd")
            self.assertEqual(actual_cwd, str(workspace))
            # Double-check: cwd must NOT be the source repo
            self.assertNotEqual(actual_cwd, str(source_root))

    # 7. shell=True is never used
    async def test_7_shell_false_is_always_used(self):
        mock_proc = MagicMock(returncode=0, stdout="clean", stderr="")
        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            await self.tool.execute("git", ["status"])
            mock_run.assert_called_once()
            _, kwargs = mock_run.call_args
            self.assertIs(kwargs.get("shell"), False)

    # 8. arbitrary shell string is rejected
    async def test_8_arbitrary_shell_string_is_rejected(self):
        with self.assertRaises(ValueError):
            await self.tool.execute("git status", [])
        with self.assertRaises(ValueError):
            await self.tool.execute("ls -la", [])

    # 9. bash is rejected
    async def test_9_bash_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            await self.tool.execute("bash", ["-c", "echo pwned"])
        self.assertIn("prohibited", str(ctx.exception).lower())

    # 10. sh is rejected
    async def test_10_sh_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            await self.tool.execute("sh", ["-c", "echo pwned"])
        self.assertIn("prohibited", str(ctx.exception).lower())

    # 11. powershell is rejected
    async def test_11_powershell_is_rejected(self):
        with self.assertRaises(ValueError):
            await self.tool.execute("powershell", ["-Command", "dir"])
        with self.assertRaises(ValueError):
            await self.tool.execute("pwsh", ["-Command", "dir"])

    # 12. unsupported executable is rejected
    async def test_12_unsupported_executable_is_rejected(self):
        for exe in ["curl", "wget", "rm", "cat", "node", "ruby", "nc"]:
            with self.subTest(exe=exe):
                with self.assertRaises(ValueError) as ctx:
                    await self.tool.execute(exe, ["--help"])
                self.assertIn("not in orion's allowed command policy", str(ctx.exception).lower())

    # 13. unsupported git subcommand is rejected
    async def test_13_unsupported_git_subcommand_is_rejected(self):
        for sub in ["checkout", "commit", "clone", "fetch", "pull", "merge", "rebase", "tag", "stash"]:
            with self.subTest(sub=sub):
                with self.assertRaises(ValueError) as ctx:
                    await self.tool.execute("git", [sub])
                self.assertIn("not permitted", str(ctx.exception).lower())

    # 14. git push is rejected
    async def test_14_git_push_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            await self.tool.execute("git", ["push", "origin", "main"])
        self.assertIn("not permitted", str(ctx.exception).lower())

    # 15. git reset is rejected
    async def test_15_git_reset_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            await self.tool.execute("git", ["reset", "--hard", "HEAD"])
        self.assertIn("not permitted", str(ctx.exception).lower())

    # 16. git clean is rejected
    async def test_16_git_clean_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            await self.tool.execute("git", ["clean", "-fd"])
        self.assertIn("not permitted", str(ctx.exception).lower())

    # 17. python -c is rejected
    async def test_17_python_c_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            await self.tool.execute("python", ["-c", "import os; print('bad')"])
        self.assertIn("prohibited", str(ctx.exception).lower())

        with self.assertRaises(ValueError) as ctx:
            await self.tool.execute("python3", ["-c", "import os; print('bad')"])
        self.assertIn("prohibited", str(ctx.exception).lower())

    # 18. shell metacharacter attempts are rejected
    async def test_18_shell_metacharacters_are_rejected(self):
        metacharacters = [";", "&&", "||", "|", ">", ">>", "<", "$(", "`", "\n", "\r"]
        for meta in metacharacters:
            with self.subTest(meta=meta):
                with self.assertRaises(ValueError) as ctx:
                    await self.tool.execute("git", ["status", f"--flag{meta}extra"])
                self.assertIn("prohibited shell character", str(ctx.exception).lower())

    # 19. caller cannot specify cwd
    async def test_19_caller_cannot_specify_cwd(self):
        with self.assertRaises(ValueError) as ctx:
            await self.tool.execute("git", ["status"], cwd="/tmp")
        self.assertIn("custom working directory is not permitted", str(ctx.exception).lower())

    # 20. timeout is enforced
    async def test_20_timeout_is_enforced(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["git"], timeout=30.0)):
            result = await self.tool.execute("git", ["status"])
            self.assertEqual(result["status"], "timeout")
            self.assertEqual(result["return_code"], -1)
            self.assertIn("timed out", result["stderr"])

    # 21. stdout/stderr are bounded
    async def test_21_stdout_stderr_are_bounded(self):
        large_text = "A" * 25_000
        mock_proc = MagicMock(returncode=0, stdout=large_text, stderr=large_text)
        with patch("subprocess.run", return_value=mock_proc):
            result = await self.tool.execute("git", ["status"])
            self.assertLessEqual(len(result["stdout"]), 11_000)
            self.assertIn("[output truncated]", result["stdout"])
            self.assertLessEqual(len(result["stderr"]), 11_000)
            self.assertIn("[output truncated]", result["stderr"])

    # 22. API secrets do not appear in output
    async def test_22_api_secrets_do_not_appear_in_output(self):
        if not settings.nebius_api_key:
            self.skipTest("NEBIUS_API_KEY not configured")
        leaky_text = f"Traceback with secret: {settings.nebius_api_key}"
        mock_proc = MagicMock(returncode=1, stdout="", stderr=leaky_text)
        with patch("subprocess.run", return_value=mock_proc):
            result = await self.tool.execute("git", ["status"])
            self.assertNotIn(settings.nebius_api_key, result["stderr"])
            self.assertIn("<REDACTED>", result["stderr"])

    # 23. API secrets do not appear in audit.log
    async def test_23_api_secrets_do_not_appear_in_audit_log(self):
        if not settings.nebius_api_key:
            self.skipTest("NEBIUS_API_KEY not configured")
        leaky_text = f"Leaked Nebius key: {settings.nebius_api_key}"
        mock_proc = MagicMock(returncode=0, stdout=leaky_text, stderr="")
        with patch("subprocess.run", return_value=mock_proc):
            await self.registry.execute("run_command", confirmed=True, command="git", arguments=["status"])
        audit_text = _audit_log().read_text(encoding="utf-8")
        self.assertNotIn(settings.nebius_api_key, audit_text)

    # 24. Hermes token does not appear in output
    async def test_24_hermes_token_does_not_appear_in_output(self):
        if not settings.hermes_gateway_token:
            self.skipTest("HERMES_GATEWAY_TOKEN not configured")
        leaky_text = f"Traceback with token: {settings.hermes_gateway_token}"
        mock_proc = MagicMock(returncode=1, stdout="", stderr=leaky_text)
        with patch("subprocess.run", return_value=mock_proc):
            result = await self.tool.execute("git", ["status"])
            self.assertNotIn(settings.hermes_gateway_token, result["stderr"])
            self.assertIn("<REDACTED>", result["stderr"])

    # 25. Hermes token does not appear in audit.log
    async def test_25_hermes_token_does_not_appear_in_audit_log(self):
        if not settings.hermes_gateway_token:
            self.skipTest("HERMES_GATEWAY_TOKEN not configured")
        leaky_text = f"Leaked Hermes token: {settings.hermes_gateway_token}"
        mock_proc = MagicMock(returncode=0, stdout=leaky_text, stderr="")
        with patch("subprocess.run", return_value=mock_proc):
            await self.registry.execute("run_command", confirmed=True, command="git", arguments=["status"])
        audit_text = _audit_log().read_text(encoding="utf-8")
        self.assertNotIn(settings.hermes_gateway_token, audit_text)

    # 26. Command execution fails closed in production / public-demo mode
    async def test_26_command_execution_fails_closed_in_production_mode(self):
        mock_settings = MagicMock(environment="production")
        with patch("app.config.get_settings", return_value=mock_settings):
            with self.assertRaises(PermissionError) as ctx:
                await self.tool.execute("git", ["status"])
            self.assertIn("disabled in public-demo / production mode", str(ctx.exception))


class TestSafeEnvSecretExclusion(unittest.TestCase):
    """
    Verify that _get_safe_env() excludes deployment secrets from the
    child process environment.
    """

    def test_nebius_api_key_excluded_from_env(self):
        """NEBIUS_API_KEY must not appear in the sanitised environment."""
        original = os.environ.get("NEBIUS_API_KEY")
        try:
            os.environ["NEBIUS_API_KEY"] = "super-secret-nebius-key-12345"
            safe = _get_safe_env()
            self.assertNotIn("NEBIUS_API_KEY", safe)
        finally:
            if original is not None:
                os.environ["NEBIUS_API_KEY"] = original
            else:
                os.environ.pop("NEBIUS_API_KEY", None)

    def test_orion_demo_key_excluded_from_env(self):
        """ORION_DEMO_KEY must not appear in the sanitised environment."""
        original = os.environ.get("ORION_DEMO_KEY")
        try:
            os.environ["ORION_DEMO_KEY"] = "demo-secret-key-abcdef123456789"
            safe = _get_safe_env()
            self.assertNotIn("ORION_DEMO_KEY", safe)
        finally:
            if original is not None:
                os.environ["ORION_DEMO_KEY"] = original
            else:
                os.environ.pop("ORION_DEMO_KEY", None)

    def test_hermes_gateway_token_excluded_from_env(self):
        """HERMES_GATEWAY_TOKEN must not appear in the sanitised environment."""
        original = os.environ.get("HERMES_GATEWAY_TOKEN")
        try:
            os.environ["HERMES_GATEWAY_TOKEN"] = "hermes-token-xyz-987654"
            safe = _get_safe_env()
            self.assertNotIn("HERMES_GATEWAY_TOKEN", safe)
        finally:
            if original is not None:
                os.environ["HERMES_GATEWAY_TOKEN"] = original
            else:
                os.environ.pop("HERMES_GATEWAY_TOKEN", None)

    def test_path_is_preserved_in_safe_env(self):
        """PATH must be preserved in the sanitised environment."""
        safe = _get_safe_env()
        self.assertIn("PATH", safe)

    def test_generic_token_variable_excluded(self):
        """Any variable with TOKEN in the name must be excluded."""
        original = os.environ.get("MY_CUSTOM_TOKEN")
        try:
            os.environ["MY_CUSTOM_TOKEN"] = "custom-token-value-abc"
            safe = _get_safe_env()
            self.assertNotIn("MY_CUSTOM_TOKEN", safe)
        finally:
            if original is not None:
                os.environ["MY_CUSTOM_TOKEN"] = original
            else:
                os.environ.pop("MY_CUSTOM_TOKEN", None)

    def test_child_process_cannot_read_nebius_key(self):
        """
        Run a real subprocess via python3 and verify that NEBIUS_API_KEY
        does not appear in the child's environment.
        """
        sentinel = "SENTINEL_NEBIUS_KEY_VALUE_UNIQUE_99887766"
        original = os.environ.get("NEBIUS_API_KEY")
        try:
            os.environ["NEBIUS_API_KEY"] = sentinel
            safe = _get_safe_env()
            proc = subprocess.run(
                ["python3", "-c", "import os, json; print(json.dumps(dict(os.environ)))"],
                capture_output=True,
                text=True,
                env=safe,
                shell=False,
                timeout=10,
            )
            child_env_text = proc.stdout
            self.assertNotIn(sentinel, child_env_text,
                             "NEBIUS_API_KEY value must not appear in child process environment")
        finally:
            if original is not None:
                os.environ["NEBIUS_API_KEY"] = original
            else:
                os.environ.pop("NEBIUS_API_KEY", None)

    def test_child_process_cannot_read_orion_demo_key(self):
        """
        Run a real subprocess and verify ORION_DEMO_KEY is absent in child env.
        """
        sentinel = "SENTINEL_DEMO_KEY_UNIQUE_55443322"
        original = os.environ.get("ORION_DEMO_KEY")
        try:
            os.environ["ORION_DEMO_KEY"] = sentinel
            safe = _get_safe_env()
            proc = subprocess.run(
                ["python3", "-c", "import os, json; print(json.dumps(dict(os.environ)))"],
                capture_output=True,
                text=True,
                env=safe,
                shell=False,
                timeout=10,
            )
            self.assertNotIn(sentinel, proc.stdout,
                             "ORION_DEMO_KEY value must not appear in child process environment")
        finally:
            if original is not None:
                os.environ["ORION_DEMO_KEY"] = original
            else:
                os.environ.pop("ORION_DEMO_KEY", None)


class TestAgentRunCommandIntegration(unittest.TestCase):
    """
    Integration test:
    user request -> ToolPlanner selects run_command -> orchestrator sees confirmation_required
    -> command is NOT executed -> response asks for confirmation.
    """

    def test_agent_run_command_requires_confirmation(self):
        # We test that a request intending to run a command stops at confirmation.
        # Uses a retry loop to tolerate transient remote LLM provider timeouts.
        response = None
        for attempt in range(3):
            response = client.post(
                "/api/agent/run",
                json={"message": "Run git log on this repository to inspect the commit history."},
            )
            if response.status_code == 200:
                break

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 200, msg=response.text)
        data = response.json()

        # Planner chose run_command
        self.assertEqual(data["planner_decision"]["action"], "tool")
        self.assertEqual(data["tool_used"], "run_command")

        # Permission is confirmation_required
        self.assertEqual(data["permission_status"], "confirmation_required")

        # Command was NOT executed (tool_result is None)
        self.assertIsNone(data["tool_result"])

        # Agent response explicitly requests user confirmation/approval
        self.assertIn("confirmation", data["response"].lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
