"""
Tests for Feature 2 — Reusable Skill Evaluation and Improvement.
"""
import json
import unittest
from unittest.mock import patch

from app.memory.database import initialize_database
from app.memory.personal import PersonalModelStore
from app.tools.registry import create_default_registry
from app.tools.skills.learning import SkillLearningService
from app.tools.skills.tools import UseSkillTool
from app.tools.skills.validator import SkillValidator
from app.main import app
from starlette.testclient import TestClient


class TestSkillLearning(unittest.TestCase):
    def setUp(self):
        initialize_database()
        self.store = PersonalModelStore()
        self.registry = create_default_registry(personal_store=self.store)
        self.learning_service = SkillLearningService(
            personal_store=self.store,
            registry=self.registry,
        )

    def tearDown(self):
        from app.memory.database import get_connection
        with get_connection() as conn:
            conn.execute("DELETE FROM skill_executions")
            conn.execute("DELETE FROM skill_proposals")
            conn.execute("DELETE FROM skill_versions")
            conn.execute("DELETE FROM skills")
            conn.commit()

    def test_successful_execution_history_recorded(self):
        """Skill execution history is recorded with step results and duration."""
        wf = {"steps": [{"tool": "git_status", "arguments": {}}]}
        skill = self.store.create_skill(
            name="Git Check",
            description="Check git status",
            workflow=json.dumps(wf),
        )

        exec_rec = self.learning_service.record_execution(
            skill_id=skill["id"],
            status="completed",
            step_results=[{"step": 1, "tool": "git_status", "result": {"clean": True}}],
            duration_ms=12.5,
            session_id="sess-100",
        )
        self.assertIsNotNone(exec_rec["id"])
        self.assertEqual(exec_rec["status"], "completed")

        history = self.learning_service.get_execution_history(skill["id"])
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["id"], exec_rec["id"])
        self.assertEqual(history[0]["duration_ms"], 12.5)

    def test_failed_execution_triggers_improvement_proposal(self):
        """Failure during execution generates an improvement proposal."""
        wf = {
            "steps": [
                {"tool": "read_file", "arguments": {"path": "missing_config.json"}},
            ]
        }
        skill = self.store.create_skill(
            name="Read Config Skill",
            description="Reads config file",
            workflow=json.dumps(wf),
        )

        # Record failure
        self.learning_service.record_execution(
            skill_id=skill["id"],
            status="error",
            step_results=[{"step": 1, "tool": "read_file", "error": "FileNotFoundError: missing_config.json"}],
            failure_reason="FileNotFoundError: missing_config.json",
            duration_ms=5.0,
        )

        proposals = self.learning_service.list_proposals(skill["id"], status="pending")
        self.assertTrue(len(proposals) > 0)
        prop = proposals[0]
        self.assertEqual(prop["status"], "pending")
        # Proposes list_directory before read_file
        proposed_steps = prop["proposed_workflow"]["steps"]
        self.assertTrue(any(s["tool"] == "list_directory" for s in proposed_steps))

    def test_skill_validator_enforced_on_revised_workflow(self):
        """SkillValidator strictly validates all proposed improvements."""
        skill = self.store.create_skill(
            name="Valid Skill",
            description="Valid",
            workflow=json.dumps({"steps": [{"tool": "git_status", "arguments": {}}]}),
        )

        # Invalid tool in proposal must be rejected
        with self.assertRaises(ValueError):
            self.learning_service.create_proposal(
                skill_id=skill["id"],
                title="Bad Tool Proposal",
                description="Adds invalid tool",
                proposed_workflow={"steps": [{"tool": "non_existent_tool_123", "arguments": {}}]},
                rationale="Testing validation rejection",
            )

    def test_permission_escalation_rejected(self):
        """Proposals cannot introduce BLOCKED tools."""
        skill = self.store.create_skill(
            name="Safe Skill",
            description="Safe",
            workflow=json.dumps({"steps": [{"tool": "git_status", "arguments": {}}]}),
        )

        # Proposing run_command without permissions or malicious tool
        with patch.dict("app.tools.permissions.DEFAULT_TOOL_PERMISSIONS", {"blocked_tool": "blocked"}):
            with self.assertRaises(Exception):
                self.learning_service.create_proposal(
                    skill_id=skill["id"],
                    title="Escalation Proposal",
                    description="Tries to escalate",
                    proposed_workflow={"steps": [{"tool": "blocked_tool", "arguments": {}}]},
                    rationale="Testing escalation prevention",
                )

    def test_approval_required_for_executable_changes(self):
        """Active skill workflow is unchanged until proposal is explicitly approved."""
        orig_wf = {"steps": [{"tool": "git_status", "arguments": {}}]}
        skill = self.store.create_skill(
            name="Review Skill",
            description="Requires approval",
            workflow=json.dumps(orig_wf),
        )

        new_wf = {
            "steps": [
                {"tool": "list_directory", "arguments": {"path": "."}},
                {"tool": "git_status", "arguments": {}},
            ]
        }
        prop = self.learning_service.create_proposal(
            skill_id=skill["id"],
            title="Add directory check",
            description="Proposal",
            proposed_workflow=new_wf,
            rationale="Pre-check directory",
        )

        # Check skill in DB: still has original workflow
        current_skill = self.store.get_skill(skill["id"])
        self.assertEqual(json.loads(current_skill["workflow"]), orig_wf)

        # Explicit approval applies the change
        res = self.learning_service.approve_proposal(skill_id=skill["id"], proposal_id=prop["id"])
        self.assertEqual(res["status"], "approved")

        # Now active skill has updated workflow
        updated_skill = self.store.get_skill(skill["id"])
        self.assertEqual(json.loads(updated_skill["workflow"]), new_wf)

    def test_version_history_and_rollback(self):
        """Version history tracks changes and allows rollback to previous version."""
        v1_wf = {"steps": [{"tool": "git_status", "arguments": {}}]}
        skill = self.store.create_skill(
            name="Versioned Skill",
            description="Testing versions",
            workflow=json.dumps(v1_wf),
        )
        snap1 = self.learning_service.save_version_snapshot(skill["id"], "v1")

        # Apply update
        v2_wf = {"steps": [{"tool": "list_directory", "arguments": {"path": "."}}]}
        self.store.update_skill(skill["id"], workflow=json.dumps(v2_wf))
        snap2 = self.learning_service.save_version_snapshot(skill["id"], "v2")

        versions = self.learning_service.list_versions(skill["id"])
        self.assertTrue(len(versions) >= 2)

        # Rollback to v1
        rb_res = self.learning_service.rollback_to_version(skill["id"], snap1["version_number"])
        self.assertEqual(rb_res["status"], "rolled_back")

        # Verify restored workflow
        restored_skill = self.store.get_skill(skill["id"])
        self.assertEqual(json.loads(restored_skill["workflow"]), v1_wf)

    def test_skill_learning_api_endpoints(self):
        """Test API endpoints for executions, proposals, approval, rollback."""
        client = TestClient(app)
        wf = {"steps": [{"tool": "git_status", "arguments": {}}]}
        skill = self.store.create_skill(
            name="API Test Skill",
            description="API test",
            workflow=json.dumps(wf),
        )

        # 1. Record execution
        self.learning_service.record_execution(
            skill_id=skill["id"],
            status="completed",
            step_results=[{"step": 1, "tool": "git_status"}],
            duration_ms=10.0,
        )

        # 2. Get executions
        res = client.get(f"/api/skills/{skill['id']}/executions")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.json()["executions"]), 1)

        # 3. Create proposal
        prop = self.learning_service.create_proposal(
            skill_id=skill["id"],
            title="API Proposal",
            description="Test API",
            proposed_workflow={"steps": [{"tool": "list_directory", "arguments": {}}]},
            rationale="API test rationale",
        )

        # 4. List proposals
        prop_res = client.get(f"/api/skills/{skill['id']}/proposals")
        self.assertEqual(prop_res.status_code, 200)
        self.assertEqual(len(prop_res.json()["proposals"]), 1)

        # 5. Approve proposal
        appr_res = client.post(f"/api/skills/{skill['id']}/proposals/{prop['id']}/approve")
        self.assertEqual(appr_res.status_code, 200)
        self.assertEqual(appr_res.json()["status"], "approved")

        # 6. List versions
        ver_res = client.get(f"/api/skills/{skill['id']}/versions")
        self.assertEqual(ver_res.status_code, 200)
        self.assertTrue(len(ver_res.json()["versions"]) > 0)

    def test_repeated_approval_fails(self):
        """Once approved, a proposal cannot be approved again."""
        wf = {"steps": [{"tool": "git_status", "arguments": {}}]}
        skill = self.store.create_skill(name="Idem Skill", workflow=json.dumps(wf))
        prop = self.learning_service.create_proposal(
            skill_id=skill["id"],
            title="Idem Test",
            description="desc",
            proposed_workflow={"steps": [{"tool": "list_directory", "arguments": {}}]},
            rationale="test",
        )

        res1 = self.learning_service.approve_proposal(skill["id"], prop["id"])
        self.assertEqual(res1["status"], "approved")

        with self.assertRaises(ValueError):
            self.learning_service.approve_proposal(skill["id"], prop["id"])

    def test_rejected_proposal_cannot_be_approved(self):
        """A rejected proposal cannot be approved."""
        wf = {"steps": [{"tool": "git_status", "arguments": {}}]}
        skill = self.store.create_skill(name="Reject Skill", workflow=json.dumps(wf))
        prop = self.learning_service.create_proposal(
            skill_id=skill["id"],
            title="Reject Test",
            description="desc",
            proposed_workflow={"steps": [{"tool": "list_directory", "arguments": {}}]},
            rationale="test",
        )

        rej = self.learning_service.reject_proposal(skill["id"], prop["id"])
        self.assertEqual(rej["status"], "rejected")

        with self.assertRaises(ValueError):
            self.learning_service.approve_proposal(skill["id"], prop["id"])

    def test_competing_approval_attempts(self):
        """Only one approval attempt can succeed for a pending proposal."""
        import concurrent.futures
        wf = {"steps": [{"tool": "git_status", "arguments": {}}]}
        skill = self.store.create_skill(name="Race Skill", workflow=json.dumps(wf))
        prop = self.learning_service.create_proposal(
            skill_id=skill["id"],
            title="Race Test",
            description="desc",
            proposed_workflow={"steps": [{"tool": "list_directory", "arguments": {}}]},
            rationale="test",
        )

        results = []
        errors = []

        def attempt_approval():
            try:
                res = self.learning_service.approve_proposal(skill["id"], prop["id"])
                results.append(res)
            except Exception as e:
                errors.append(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(attempt_approval)
            f2 = executor.submit(attempt_approval)
            f1.result()
            f2.result()

        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ValueError)

    def test_failure_during_approval_rolls_back_atomically(self):
        """If an error occurs during approval, skill and proposal remain unchanged."""
        wf = {"steps": [{"tool": "git_status", "arguments": {}}]}
        skill = self.store.create_skill(name="Rollback Skill", workflow=json.dumps(wf))
        prop = self.learning_service.create_proposal(
            skill_id=skill["id"],
            title="Fail Test",
            description="desc",
            proposed_workflow={"steps": [{"tool": "list_directory", "arguments": {}}]},
            rationale="test",
        )

        # Force an error inside SkillValidator during approval
        with patch.object(SkillValidator, "validate_workflow", side_effect=RuntimeError("Simulated validation crash")):
            with self.assertRaises(RuntimeError):
                self.learning_service.approve_proposal(skill["id"], prop["id"])

        # Verify proposal remains pending
        current_prop = self.learning_service.get_proposal(prop["id"])
        self.assertEqual(current_prop["status"], "pending")

        # Verify skill workflow is unchanged
        current_skill = self.store.get_skill(skill["id"])
        self.assertEqual(json.loads(current_skill["workflow"]), wf)

    def test_version_numbers_remain_unique(self):
        """Database enforces UNIQUE(skill_id, version_number) constraint on skill_versions."""
        import sqlite3
        from app.memory.database import get_connection
        wf = {"steps": [{"tool": "git_status", "arguments": {}}]}
        skill = self.store.create_skill(name="Uniq Skill", workflow=json.dumps(wf))

        snap = self.learning_service.save_version_snapshot(skill["id"], "v1")
        v_num = snap["version_number"]

        # Attempt to insert a duplicate version number directly into SQLite
        with self.assertRaises(sqlite3.IntegrityError):
            with get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO skill_versions (skill_id, version_number, name, description, workflow, change_summary)
                    VALUES (?, ?, 'dup', '', '{}', '')
                    """,
                    (skill["id"], v_num),
                )
                conn.commit()
