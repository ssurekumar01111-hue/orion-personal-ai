"""
Focused tests for workspace tools:
- read_file
- git_status
- write_file
- Audit log sanitization
- Agent end-to-end integration for read_file
"""
import json
import sys
import unittest
import warnings
from pathlib import Path

# Suppress starlette deprecation warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

sys.path.insert(0, str(Path(__file__).parents[1]))

from starlette.testclient import TestClient
from app.config import get_settings
from app.main import app
from app.tools.filesystem import DeleteFileTool, ReadFileTool, WriteFileTool
from app.tools.git import GitStatusTool
from app.tools.permissions import Permission
from app.tools.registry import create_default_registry
from app.tools.workspace import WORKSPACE_ROOT, is_protected_file, safe_path

client = TestClient(app, raise_server_exceptions=True)
settings = get_settings()
AUDIT_LOG = WORKSPACE_ROOT / "data" / "audit.log"


class TestReadFileTool(unittest.IsolatedAsyncioTestCase):
    """Tests for ReadFileTool functionality and security boundaries."""

    async def asyncSetUp(self):
        self.tool = ReadFileTool()
        self.test_file = WORKSPACE_ROOT / "data" / "_test_read.txt"
        self.test_file.parent.mkdir(parents=True, exist_ok=True)
        self.test_file.write_text("Hello from Orion ReadFileTool test.", encoding="utf-8")

    async def asyncTearDown(self):
        if self.test_file.exists():
            self.test_file.unlink()

    async def test_read_file_success(self):
        result = await self.tool.execute("data/_test_read.txt")
        self.assertEqual(result["path"], "data/_test_read.txt")
        self.assertEqual(result["content"], "Hello from Orion ReadFileTool test.")

    async def test_read_file_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            await self.tool.execute("data/_nonexistent_file_999.txt")

    async def test_read_file_directory_rejection(self):
        with self.assertRaises(IsADirectoryError):
            await self.tool.execute("backend")

    async def test_read_file_traversal_rejection(self):
        with self.assertRaises(PermissionError):
            await self.tool.execute("../../etc/passwd")

    async def test_read_file_absolute_path_rejection(self):
        with self.assertRaises(PermissionError):
            await self.tool.execute("/etc/passwd")

    async def test_read_file_secret_file_rejection(self):
        # Must refuse .env and variations
        for secret_name in [".env", ".env.local", ".env.backup", "secret.key", "credentials.json"]:
            with self.subTest(secret=secret_name):
                with self.assertRaises(PermissionError) as ctx:
                    await self.tool.execute(secret_name)
                self.assertIn("forbidden", str(ctx.exception).lower())


class TestGitStatusTool(unittest.IsolatedAsyncioTestCase):
    """Tests for GitStatusTool safe subprocess execution in workspace."""

    async def asyncSetUp(self):
        self.tool = GitStatusTool()

    async def test_git_status_success(self):
        result = await self.tool.execute()
        self.assertIn("is_repo", result)
        self.assertTrue(result["is_repo"])
        self.assertIn("branch", result)
        self.assertIsNotNone(result["branch"])
        self.assertIn("clean", result)
        self.assertIn("untracked", result)

    async def test_git_status_executes_in_orion_workspace(self):
        result = await self.tool.execute()
        # Verify the raw status mentions files in orion workspace
        raw = result.get("raw", "")
        self.assertIsInstance(raw, str)
        # Untracked or tracked items should include workspace items like backend
        all_items = result.get("untracked", []) + result.get("staged", []) + result.get("unstaged", [])
        self.assertTrue(any("backend" in item or ".gitignore" in item for item in all_items) or result.get("clean"))

    async def test_git_status_does_not_leak_environment_secrets(self):
        result = await self.tool.execute()
        raw_output = json.dumps(result)
        if settings.nebius_api_key:
            self.assertNotIn(settings.nebius_api_key, raw_output)
        if settings.hermes_gateway_token:
            self.assertNotIn(settings.hermes_gateway_token, raw_output)


class TestWriteFileTool(unittest.IsolatedAsyncioTestCase):
    """Tests for WriteFileTool and confirmation enforcement."""

    async def asyncSetUp(self):
        self.tool = WriteFileTool()
        self.registry = create_default_registry()
        self.test_file = WORKSPACE_ROOT / "data" / "_test_write.txt"
        if self.test_file.exists():
            self.test_file.unlink()

    async def asyncTearDown(self):
        if self.test_file.exists():
            self.test_file.unlink()

    async def test_write_file_is_registered(self):
        tool = self.registry.get("write_file")
        self.assertIsNotNone(tool)
        self.assertEqual(tool.name, "write_file")

    async def test_write_file_has_confirmation_required_permission(self):
        tools_list = self.registry.list_tools()
        wf_meta = next((t for t in tools_list if t["name"] == "write_file"), None)
        self.assertIsNotNone(wf_meta)
        self.assertEqual(wf_meta["permission"], "confirmation_required")

    async def test_write_file_cannot_execute_without_confirmation(self):
        # Direct execution through registry without confirmed=True must fail
        with self.assertRaises(PermissionError) as ctx:
            await self.registry.execute(
                "write_file",
                path="data/_test_write.txt",
                content="unconfirmed content",
            )
        self.assertIn("requires user confirmation", str(ctx.exception))
        self.assertFalse(self.test_file.exists())

    async def test_write_file_executes_with_confirmation(self):
        # Execution through registry with confirmed=True must succeed
        result = await self.registry.execute(
            "write_file",
            confirmed=True,
            path="data/_test_write.txt",
            content="confirmed write content",
        )
        self.assertEqual(result["status"], "written")
        self.assertTrue(self.test_file.exists())
        self.assertEqual(self.test_file.read_text(encoding="utf-8"), "confirmed write content")

    async def test_write_file_traversal_rejection(self):
        with self.assertRaises(PermissionError):
            await self.tool.execute("../../escape.txt", content="malicious")

    async def test_write_file_secret_file_rejection(self):
        for secret_name in [".env", ".env.local", "secret.key", "credentials.json"]:
            with self.subTest(secret=secret_name):
                with self.assertRaises(PermissionError) as ctx:
                    await self.tool.execute(secret_name, content="bad data")
                self.assertIn("forbidden", str(ctx.exception).lower())


class TestAuditLogSanitization(unittest.IsolatedAsyncioTestCase):
    """Verify that file contents and secrets are never stored in audit.log."""

    async def test_audit_log_contains_no_file_contents_or_secrets(self):
        registry = create_default_registry()
        secret_content_marker = "SUPER_UNIQUE_TEST_PAYLOAD_TOKEN_77777"
        target_path = "data/_audit_test.txt"
        target_file = WORKSPACE_ROOT / target_path

        try:
            # 1. Write file with secret marker via confirmed execution
            await registry.execute(
                "write_file",
                confirmed=True,
                path=target_path,
                content=secret_content_marker,
            )

            # 2. Read file with secret marker
            read_res = await registry.execute(
                "read_file",
                path=target_path,
            )
            self.assertEqual(read_res["content"], secret_content_marker)

            # 3. Read audit log text
            self.assertTrue(AUDIT_LOG.exists())
            audit_text = AUDIT_LOG.read_text(encoding="utf-8")

            # 4. Marker content must NOT appear in audit.log
            self.assertNotIn(
                secret_content_marker,
                audit_text,
                "File content must never appear in data/audit.log",
            )

            # 5. Secrets must not appear in audit.log
            if settings.nebius_api_key:
                self.assertNotIn(settings.nebius_api_key, audit_text)
            if settings.hermes_gateway_token:
                self.assertNotIn(settings.hermes_gateway_token, audit_text)

        finally:
            if target_file.exists():
                target_file.unlink()


class TestAgentReadIntegration(unittest.TestCase):
    """
    End-to-end integration test:
    Read a known safe file -> planner chooses read_file -> agent executes it -> final response produced.
    """

    def setUp(self):
        self.test_file = WORKSPACE_ROOT / "data" / "_agent_note.txt"
        self.test_file.parent.mkdir(parents=True, exist_ok=True)
        self.test_file.write_text(
            "Project Orion: Safe agent loop and workspace tool milestone verified.",
            encoding="utf-8",
        )

    def tearDown(self):
        if self.test_file.exists():
            self.test_file.unlink()

    def test_agent_reads_known_safe_file(self):
        response = client.post(
            "/api/agent/run",
            json={"message": "Read the contents of data/_agent_note.txt and summarize it."},
        )
        self.assertEqual(response.status_code, 200, msg=response.text)
        data = response.json()

        # Planner chose read_file
        self.assertEqual(data["planner_decision"]["action"], "tool")
        self.assertEqual(data["tool_used"], "read_file")

        # Permission was automatic
        self.assertEqual(data["permission_status"], "automatic")

        # Tool result contains the content
        self.assertIsNotNone(data["tool_result"])
        self.assertEqual(data["tool_result"]["path"], "data/_agent_note.txt")
        self.assertIn("Project Orion", data["tool_result"]["content"])

        # Agent produced a final response
        self.assertIsInstance(data["response"], str)
        self.assertGreater(len(data["response"].strip()), 10)


class TestDeleteFileTool(unittest.IsolatedAsyncioTestCase):
    """Focused tests for DeleteFileTool and confirmation/security boundaries."""

    async def asyncSetUp(self):
        self.tool = DeleteFileTool()
        self.registry = create_default_registry()
        self.test_file = WORKSPACE_ROOT / "data" / "_test_delete.txt"
        self.test_file.parent.mkdir(parents=True, exist_ok=True)
        self.test_file.write_text("file to be deleted", encoding="utf-8")

    async def asyncTearDown(self):
        if self.test_file.exists():
            self.test_file.unlink()

    async def test_1_delete_file_is_registered(self):
        tool = self.registry.get("delete_file")
        self.assertIsNotNone(tool)
        self.assertEqual(tool.name, "delete_file")

    async def test_2_permission_is_confirmation_required(self):
        tools_list = self.registry.list_tools()
        df_meta = next((t for t in tools_list if t["name"] == "delete_file"), None)
        self.assertIsNotNone(df_meta)
        self.assertEqual(df_meta["permission"], "confirmation_required")

    async def test_3_deletion_without_confirmation_is_blocked(self):
        with self.assertRaises(PermissionError) as ctx:
            await self.registry.execute("delete_file", path="data/_test_delete.txt")
        self.assertIn("requires user confirmation", str(ctx.exception))

    async def test_4_blocked_deletion_leaves_file_intact(self):
        try:
            await self.registry.execute("delete_file", path="data/_test_delete.txt")
        except PermissionError:
            pass
        self.assertTrue(self.test_file.exists())
        self.assertEqual(self.test_file.read_text(encoding="utf-8"), "file to be deleted")

    async def test_5_confirmed_deletion_succeeds(self):
        result = await self.registry.execute(
            "delete_file",
            confirmed=True,
            path="data/_test_delete.txt",
        )
        self.assertEqual(result["status"], "deleted")
        self.assertFalse(self.test_file.exists())

    async def test_6_traversal_is_rejected(self):
        with self.assertRaises(PermissionError):
            await self.tool.execute("../../etc/passwd")

    async def test_7_absolute_outside_workspace_path_is_rejected(self):
        with self.assertRaises(PermissionError):
            await self.tool.execute("/etc/passwd")

    async def test_8_workspace_root_cannot_be_deleted(self):
        with self.assertRaises((PermissionError, IsADirectoryError)):
            await self.tool.execute(".")

    async def test_9_directory_deletion_is_rejected(self):
        with self.assertRaises(IsADirectoryError):
            await self.tool.execute("data")

    async def test_10_protected_env_deletion_is_rejected(self):
        for secret_name in [".env", ".env.local", ".env.backup", ".env.production"]:
            with self.subTest(secret=secret_name):
                with self.assertRaises(PermissionError) as ctx:
                    await self.tool.execute(secret_name)
                self.assertIn("forbidden", str(ctx.exception).lower())

    async def test_11_protected_credential_private_key_deletion_is_rejected(self):
        for secret_name in ["credentials.json", "secrets.json", "id_rsa", "secret.key", "cert.pem"]:
            with self.subTest(secret=secret_name):
                with self.assertRaises(PermissionError) as ctx:
                    await self.tool.execute(secret_name)
                self.assertIn("forbidden", str(ctx.exception).lower())

    async def test_12_missing_file_is_handled_correctly(self):
        with self.assertRaises(FileNotFoundError):
            await self.tool.execute("data/_nonexistent_file_xyz_999.txt")

    async def test_13_symlink_path_boundary_cannot_delete_outside_workspace(self):
        symlink_path = WORKSPACE_ROOT / "data" / "_symlink_to_outside"
        try:
            if symlink_path.is_symlink() or symlink_path.exists():
                symlink_path.unlink()
            symlink_path.symlink_to("/etc/passwd")

            with self.assertRaises(PermissionError):
                await self.tool.execute("data/_symlink_to_outside")
        finally:
            if symlink_path.is_symlink() or symlink_path.exists():
                symlink_path.unlink()

    async def test_14_audit_log_records_confirmation_required_and_success(self):
        temp_file = WORKSPACE_ROOT / "data" / "_audit_del_test.txt"
        temp_file.write_text("delete me", encoding="utf-8")
        try:
            # 1. Unconfirmed attempt
            with self.assertRaises(PermissionError):
                await self.registry.execute("delete_file", path="data/_audit_del_test.txt")

            # 2. Confirmed attempt
            await self.registry.execute("delete_file", confirmed=True, path="data/_audit_del_test.txt")

            # Verify audit log contains both events
            self.assertTrue(AUDIT_LOG.exists())
            entries = [
                json.loads(line)
                for line in AUDIT_LOG.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            del_entries = [e for e in entries if e.get("tool") == "delete_file"]
            self.assertTrue(any(e.get("status") == "confirmation_required" for e in del_entries))
            self.assertTrue(any(e.get("status") == "success" for e in del_entries))
        finally:
            if temp_file.exists():
                temp_file.unlink()

    async def test_15_audit_log_contains_no_secrets(self):
        self.assertTrue(AUDIT_LOG.exists())
        audit_text = AUDIT_LOG.read_text(encoding="utf-8")
        if settings.nebius_api_key:
            self.assertNotIn(settings.nebius_api_key, audit_text)
        if settings.hermes_gateway_token:
            self.assertNotIn(settings.hermes_gateway_token, audit_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
