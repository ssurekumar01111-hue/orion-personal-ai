"""
Integration tests for the Orion agent loop.

Tests E–H use starlette.testclient.TestClient which runs the ASGI app
in-process. Tests E and F make real calls to the Nebius Nemotron API.

Tests:
  E  POST /api/agent/run with "Inspect the files in my Orion project."
       - planner selects list_directory
       - permission is automatic
       - tool executes, tool_result is populated
       - audit entry is created
       - Nemotron produces a final natural-language response

  F  POST /api/agent/run with "What is Orion?"
       - normal conversational branch (no tool)
       - tool_used, tool_result are null

  G  POST /api/tools/list_directory with {"path": "../../"}
       - HTTP 403
       - workspace boundary error message

  H  Audit log:
       - successful list_directory execution produces an audit entry
       - blocked/error tool attempts are recorded
       - no API key or authorization secret appears in the log
"""
import json
import os
import sys
import unittest
import warnings
from pathlib import Path

# Suppress the starlette/httpx deprecation warning that appears on import.
warnings.filterwarnings("ignore", category=DeprecationWarning)

sys.path.insert(0, str(Path(__file__).parents[1]))

from starlette.testclient import TestClient
from app.main import app

client = TestClient(
    app,
    headers={"Authorization": f"Bearer {os.environ.get('ORION_DEMO_KEY', 'test-demo-secret-key-12345-very-long')}"},
    raise_server_exceptions=True,
)

AUDIT_LOG = Path(__file__).parents[2] / "data" / "audit.log"


def _read_audit_entries() -> list[dict]:
    """Read all current audit log entries as parsed dicts."""
    if not AUDIT_LOG.exists():
        return []
    lines = [l.strip() for l in AUDIT_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [json.loads(l) for l in lines]


def _load_api_key() -> str:
    """Read NEBIUS_API_KEY from .env without importing settings."""
    env_path = Path(__file__).parents[2] / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text().splitlines():
        if line.upper().startswith("NEBIUS_API_KEY"):
            return line.split("=", 1)[-1].strip().strip('"').strip("'")
    return ""


# ── Test E: agent/run — tool branch ──────────────────────────────────────────

class TestAgentRunToolBranch(unittest.TestCase):
    """
    E: POST /api/agent/run with a file-inspection request.
    Makes a real Nebius API call. Requires NEBIUS_API_KEY in .env.
    """

    def test_tool_branch_full_loop(self):
        entries_before = _read_audit_entries()

        response = client.post(
            "/api/agent/run",
            json={"message": "Inspect the files in my Orion project."},
        )

        self.assertEqual(response.status_code, 200, msg=response.text)
        data = response.json()

        # Session created
        self.assertIn("session_id", data)
        self.assertIsNotNone(data["session_id"])

        # Planner chose list_directory
        self.assertEqual(data["planner_decision"]["action"], "tool")
        self.assertEqual(data["tool_used"], "list_directory")

        # Permission was automatic
        self.assertEqual(data["permission_status"], "automatic")

        # Tool produced a result
        self.assertIsNotNone(data["tool_result"])
        self.assertIn("entries", data["tool_result"])
        self.assertIsInstance(data["tool_result"]["entries"], list)

        # Nemotron produced a natural-language response
        self.assertIsInstance(data["response"], str)
        self.assertGreater(len(data["response"].strip()), 10)

        # Provider and model are populated
        self.assertEqual(data["provider"], "nebius")
        self.assertIsNotNone(data["model"])

        # Audit entry was created
        entries_after = _read_audit_entries()
        new_entries = entries_after[len(entries_before):]
        self.assertTrue(
            any(
                e["tool"] == "list_directory" and e["status"] == "success"
                for e in new_entries
            ),
            f"No successful list_directory audit entry found. New entries: {new_entries}",
        )


# ── Test F: agent/run — respond branch ───────────────────────────────────────

class TestAgentRunRespondBranch(unittest.TestCase):
    """
    F: POST /api/agent/run with a conversational request.
    Makes a real Nebius API call.
    """

    def test_respond_branch_no_tool(self):
        response = client.post(
            "/api/agent/run",
            json={"message": "What is Orion?"},
        )

        self.assertEqual(response.status_code, 200, msg=response.text)
        data = response.json()

        # Planner chose to respond directly
        self.assertEqual(data["planner_decision"]["action"], "respond")

        # No tool was used
        self.assertIsNone(data["tool_used"])
        self.assertIsNone(data["tool_result"])
        self.assertIsNone(data["tool_arguments"])

        # A natural-language response was produced
        self.assertIsInstance(data["response"], str)
        self.assertGreater(len(data["response"].strip()), 5)

        # Session was created
        self.assertIn("session_id", data)


# ── Test G: path traversal ────────────────────────────────────────────────────

class TestPathTraversal(unittest.TestCase):
    """G: Path traversal attempt via the direct tool endpoint → HTTP 403."""

    def test_parent_traversal_blocked(self):
        response = client.post(
            "/api/tools/list_directory",
            json={"path": "../../"},
        )
        self.assertEqual(response.status_code, 403)
        detail = response.json().get("detail", "")
        self.assertIn("workspace", detail.lower())

    def test_absolute_path_blocked(self):
        response = client.post(
            "/api/tools/list_directory",
            json={"path": "/etc"},
        )
        self.assertEqual(response.status_code, 403)

    def test_relative_path_inside_workspace_allowed(self):
        """A safe relative path inside the workspace must succeed."""
        response = client.post(
            "/api/tools/list_directory",
            json={"path": "."},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("result", data)
        self.assertIn("entries", data["result"])


# ── Test H: audit log ─────────────────────────────────────────────────────────

class TestAuditLog(unittest.TestCase):
    """H: Audit log correctness and secret-free content."""

    def test_successful_tool_execution_creates_audit_entry(self):
        entries_before = _read_audit_entries()

        response = client.post(
            "/api/tools/list_directory",
            json={"path": "."},
        )
        self.assertEqual(response.status_code, 200)

        entries_after = _read_audit_entries()
        self.assertGreater(len(entries_after), len(entries_before))

        new_entry = entries_after[len(entries_before)]
        self.assertEqual(new_entry["event"], "tool_execution")
        self.assertEqual(new_entry["tool"], "list_directory")
        self.assertEqual(new_entry["status"], "success")
        self.assertIn("result", new_entry)
        self.assertIn("timestamp", new_entry)

    def test_traversal_attempt_creates_error_audit_entry(self):
        entries_before = _read_audit_entries()

        client.post("/api/tools/list_directory", json={"path": "../../"})

        entries_after = _read_audit_entries()
        self.assertGreater(len(entries_after), len(entries_before))

        new_entry = entries_after[len(entries_before)]
        self.assertEqual(new_entry["status"], "error")
        self.assertIn("error", new_entry.get("result", {}))

    def test_audit_log_contains_no_api_key(self):
        api_key = _load_api_key()
        if not api_key:
            self.skipTest("NEBIUS_API_KEY not found in .env — skipping secret check")

        log_content = AUDIT_LOG.read_text(encoding="utf-8") if AUDIT_LOG.exists() else ""
        self.assertNotIn(
            api_key,
            log_content,
            "NEBIUS_API_KEY must never appear in the audit log",
        )

    def test_audit_log_contains_no_bearer_header(self):
        log_content = AUDIT_LOG.read_text(encoding="utf-8") if AUDIT_LOG.exists() else ""
        self.assertNotIn(
            "Authorization",
            log_content,
            "Authorization header must never appear in the audit log",
        )

    def test_audit_log_entries_are_valid_json(self):
        if not AUDIT_LOG.exists():
            self.skipTest("Audit log does not exist yet")
        lines = [l for l in AUDIT_LOG.read_text().splitlines() if l.strip()]
        self.assertGreater(len(lines), 0)
        for i, line in enumerate(lines):
            with self.subTest(line=i):
                entry = json.loads(line)          # raises if invalid JSON
                self.assertIn("timestamp", entry)
                self.assertIn("event", entry)
                self.assertIn("status", entry)

    def test_audit_entry_schema(self):
        """Every audit entry must have the required fields."""
        entries = _read_audit_entries()
        self.assertGreater(len(entries), 0)
        required_fields = {"timestamp", "event", "tool", "arguments", "result", "status"}
        for entry in entries:
            missing = required_fields - set(entry.keys())
            self.assertFalse(
                missing,
                f"Audit entry missing fields {missing}: {entry}",
            )


# ── Test J: multi-step agent loop integration ─────────────────────────────────

class TestAgentRunMultiStepLoop(unittest.TestCase):
    """
    J: POST /api/agent/run with a multi-step inspection request:
    "Inspect the project README and git status, then summarize what you find."
    Makes real Nebius API calls. Requires NEBIUS_API_KEY in .env.
    """

    def test_multi_step_read_only_loop(self):
        api_key = _load_api_key()
        if not api_key:
            self.skipTest("NEBIUS_API_KEY not found in .env — skipping live multi-step test")

        entries_before = _read_audit_entries()

        response = client.post(
            "/api/agent/run",
            json={"message": "Inspect the project README and git status, then summarize what you find."},
        )

        self.assertEqual(response.status_code, 200, msg=response.text)
        data = response.json()

        # Session created
        self.assertIn("session_id", data)
        self.assertIsNotNone(data["session_id"])

        # Steps recorded
        self.assertIn("steps", data)
        steps = data["steps"]
        self.assertGreaterEqual(len(steps), 2)

        # Tools executed must be automatic read-only tools only
        tool_steps = [s for s in steps if s["action"] == "tool"]
        self.assertTrue(len(tool_steps) >= 1)
        for s in tool_steps:
            self.assertIn(s["tool"], ("git_status", "read_file", "list_directory"))
            self.assertEqual(s["permission"], "automatic")
            self.assertEqual(s["status"], "executed")

        # Response produced
        self.assertIsInstance(data["response"], str)
        self.assertGreater(len(data["response"].strip()), 10)

        # Provider and model
        self.assertEqual(data["provider"], "nebius")
        self.assertIsNotNone(data["model"])

        # Audit log entries created for tools
        entries_after = _read_audit_entries()
        new_entries = entries_after[len(entries_before):]
        self.assertTrue(
            any(e["status"] == "success" for e in new_entries),
            f"No successful tool audit entry found in {new_entries}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

