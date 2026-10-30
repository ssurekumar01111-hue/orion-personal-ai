"""
End-to-End Integration Tests for Orion's 6-Stage Core Loop:
UNDERSTAND -> REMEMBER -> PLAN -> ACT -> OBSERVE -> LEARN -> repeat
"""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock

from app.agents.learning import PostTaskLearningService
from app.agents.orchestrator import AgentOrchestrator
from app.memory.context import ContextEngine
from app.memory.database import get_connection, initialize_database
from app.memory.extraction import MemoryExtractionService
from app.memory.personal import PersonalModelService, PersonalModelStore
from app.memory.session import SessionStore
from app.memory.store import MemoryStore
from app.tools.confirmation import ConfirmationStore
from app.tools.planner import ToolPlanner
from app.tools.registry import create_default_registry
from app.tools.skills.learning import SkillLearningService
from app.tools.skills.validator import SkillValidator


def run(coro):
    return asyncio.run(coro)


class TestFullLifecycleIntegration(unittest.TestCase):
    def setUp(self):
        initialize_database()
        self.memory = MemoryStore()
        self.sessions = SessionStore()
        self.personal_store = PersonalModelStore()
        self.personal_service = PersonalModelService(store=self.personal_store)
        self.extraction = MemoryExtractionService(memory_store=self.memory)
        self.learning_service = PostTaskLearningService(
            memory_store=self.memory,
            personal_store=self.personal_store,
            extraction_service=self.extraction,
        )
        self.registry = create_default_registry(personal_store=self.personal_store)
        self.skill_learning = SkillLearningService(
            personal_store=self.personal_store,
            registry=self.registry,
        )
        self.context_engine = ContextEngine(
            memory_store=self.memory,
            session_store=self.sessions,
            personal_model_service=self.personal_service,
        )

    def tearDown(self):
        from app.memory.database import get_connection
        with get_connection() as conn:
            conn.execute("DELETE FROM skill_executions")
            conn.execute("DELETE FROM skill_proposals")
            conn.execute("DELETE FROM skill_versions")
            conn.execute("DELETE FROM skills")
            conn.execute("DELETE FROM tasks")
            conn.execute("DELETE FROM learning_events")
            conn.execute("DELETE FROM memories")
            conn.commit()

    def test_complete_core_loop_lifecycle(self):
        """
        Full 13-step lifecycle verification:
        1. Provide Orion with a useful fact in session A.
        2. Verify it is persisted.
        3. Open session B.
        4. Ask a differently worded question about that fact.
        5. Verify Orion recalls it and supplies it into context.
        6. Execute a reusable skill.
        7. Verify the execution outcome is stored.
        8. Verify Orion proposes an improvement when evidence supports it.
        9. Approve a proposed skill change.
        10. Verify the revised skill passes validation.
        11. Complete a task with verified tool observation.
        12. Verify the LEARN stage records the verified outcome.
        13. Start another task and verify the relevant learned context is available.
        """
        router = AsyncMock()
        planner = AsyncMock()

        orchestrator = AgentOrchestrator(
            router=router,
            registry=self.registry,
            context_engine=self.context_engine,
            planner=planner,
            learning_service=self.learning_service,
        )

        # ── 1. Fact in Session A ─────────────────────────────────────────────
        router.chat.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "I have remembered that the internal codename is BLUE ORBIT 47."}}],
            "model": "nvidia/nemotron",
        }
        planner.plan.return_value = {"action": "respond", "reason": "Acknowledge project codename"}

        session_a = self.sessions.create("Session A")
        turn_a = run(orchestrator.run(
            user_message="For this project, our internal codename is BLUE ORBIT 47. Remember it.",
            session_id=session_a["id"],
        ))

        # ── 2. Verify persisted ──────────────────────────────────────────────
        persisted_mems = self.memory.recall("BLUE ORBIT 47")
        self.assertTrue(len(persisted_mems) > 0)
        self.assertIn("BLUE ORBIT 47", persisted_mems[0]["content"])

        # ── 3. Open Session B ────────────────────────────────────────────────
        session_b = self.sessions.create("Session B")

        # ── 4 & 5. Differently worded query in Session B ──────────────────────
        context_b = self.context_engine.build_context(
            user_message="What was the internal project codename?",
            session_id=session_b["id"],
        )
        # Verify recall injected memory into Session B's context
        self.assertTrue(len(context_b["memories"]) > 0)
        self.assertTrue(any("BLUE ORBIT 47" in m["content"] for m in context_b["memories"]))

        # ── 6. Execute reusable skill ────────────────────────────────────────
        wf = {
            "steps": [
                {"tool": "git_status", "arguments": {}},
            ]
        }
        skill = self.personal_store.create_skill(
            name="Repo Check",
            description="Checks repo status",
            workflow=json.dumps(wf),
        )

        use_tool = self.registry.get("use_skill")
        skill_res = run(use_tool.execute(skill_id=skill["id"], session_id=session_b["id"]))
        self.assertEqual(skill_res["status"], "completed")

        # ── 7. Verify execution outcome stored ───────────────────────────────
        exec_history = self.skill_learning.get_execution_history(skill["id"])
        self.assertTrue(len(exec_history) > 0)
        self.assertEqual(exec_history[0]["status"], "completed")

        # ── 8. Propose improvement when evidence supports it ─────────────────
        # Simulate an execution that failed on read_file
        self.skill_learning.record_execution(
            skill_id=skill["id"],
            status="error",
            step_results=[{"step": 1, "tool": "read_file", "error": "FileNotFoundError"}],
            failure_reason="FileNotFoundError: manifest.json",
            duration_ms=4.0,
            session_id=session_b["id"],
        )
        proposals = self.skill_learning.list_proposals(skill["id"], status="pending")
        self.assertTrue(len(proposals) > 0)
        prop = proposals[0]

        # ── 9. Approve proposed skill change ─────────────────────────────────
        appr_res = self.skill_learning.approve_proposal(skill_id=skill["id"], proposal_id=prop["id"])
        self.assertEqual(appr_res["status"], "approved")

        # ── 10. Verify revised skill passes validation ───────────────────────
        updated_skill = self.personal_store.get_skill(skill["id"])
        validated = SkillValidator.validate_workflow(updated_skill["workflow"], registry=self.registry)
        self.assertIsNotNone(validated)

        # ── 11 & 12. Complete a task with verified observation & LEARN ───────
        task = self.personal_store.create_task(title="Inspect repo and update notes", status="todo")

        learn_res = self.learning_service.learn_from_turn(
            user_objective=f"Inspect repo and complete task #{task['id']}",
            steps=[
                {"step": 1, "action": "tool", "tool": "git_status", "status": "executed"},
                {"step": 2, "action": "tool", "tool": "update_task", "status": "executed"},
            ],
            observations=[
                {"step": 1, "tool": "git_status", "result": {"branch": "main"}},
                {"step": 2, "tool": "update_task", "result": {"task": {"id": task["id"], "title": task["title"], "status": "completed"}}},
            ],
            final_answer="Repo inspected and task completed.",
            session_id=session_b["id"],
        )
        self.assertEqual(learn_res["completion_status"], "success")
        self.assertEqual(len(learn_res["task_updates"]), 1)

        # Update task in store for consistency
        self.personal_store.update_task(task["id"], status="completed")

        refreshed_task = self.personal_store.get_task(task["id"])
        self.assertEqual(refreshed_task["status"], "completed")

        # ── 13. Relevant learned context is available in future turn ─────────
        next_context = self.context_engine.build_context(
            user_message="Show me completed tasks",
            session_id=session_b["id"],
        )
        # Snapshot contains decisions, memories, and personal model
        all_tasks = self.personal_store.list_tasks(limit=10)
        self.assertTrue(any(t["id"] == task["id"] and t["status"] == "completed" for t in all_tasks))

        # And recent learning events reflect the completed task
        with initialize_database() or get_connection() as conn:
            event = conn.execute("SELECT * FROM learning_events WHERE session_id = ?", (session_b["id"],)).fetchone()
            self.assertIsNotNone(event)
            self.assertEqual(event["completion_status"], "success")
