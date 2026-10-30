"""
Tests for Feature 3 — Automated Post-Task Learning & Core Loop Integration.
"""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from app.agents.learning import PostTaskLearningService
from app.agents.orchestrator import AgentOrchestrator
from app.memory.context import ContextEngine
from app.memory.database import initialize_database
from app.memory.extraction import MemoryExtractionService
from app.memory.personal import PersonalModelStore
from app.memory.session import SessionStore
from app.memory.store import MemoryStore
from app.tools.confirmation import ConfirmationStore
from app.tools.planner import ToolPlanner
from app.tools.registry import create_default_registry


def run(coro):
    return asyncio.run(coro)


class TestPostTaskLearning(unittest.TestCase):
    def setUp(self):
        initialize_database()
        self.memory = MemoryStore()
        self.sessions = SessionStore()
        self.personal_store = PersonalModelStore()
        self.extraction = MemoryExtractionService(memory_store=self.memory)
        self.learning_service = PostTaskLearningService(
            memory_store=self.memory,
            personal_store=self.personal_store,
            extraction_service=self.extraction,
        )

    def tearDown(self):
        from app.memory.database import get_connection
        with get_connection() as conn:
            conn.execute("DELETE FROM learning_events")
            conn.execute("DELETE FROM tasks")
            conn.execute("DELETE FROM decisions")
            conn.execute("DELETE FROM memories")
            conn.commit()

    def test_learning_after_successful_task_completion(self):
        """Learning captures verified memories and decisions upon task success."""
        task = self.personal_store.create_task(
            title="Deploy worker node",
            status="todo",
        )

        outcome = self.learning_service.learn_from_turn(
            user_objective="For this project, our internal codename is BLUE ORBIT 47. Remember it.",
            steps=[{"step": 1, "action": "respond", "status": "completed"}],
            observations=[],
            final_answer="Understood. The internal codename is BLUE ORBIT 47.",
            session_id="sess-success",
        )

        self.assertEqual(outcome["status"], "learned")
        self.assertEqual(outcome["completion_status"], "success")
        self.assertTrue(len(outcome["learned_memories"]) > 0)
        self.assertIn("BLUE ORBIT 47", outcome["learned_memories"][0]["content"])

        # Check memory in DB
        recalled = self.memory.recall("BLUE ORBIT 47")
        self.assertTrue(len(recalled) > 0)

    def test_no_false_completion_without_verified_tool_observation(self):
        """Task status is NOT updated merely because user objective or model claims completion."""
        task = self.personal_store.create_task(
            title="Configure SSL certificate",
            status="todo",
        )

        # Objective says complete task, but observations are empty (no tool verified it)
        outcome = self.learning_service.learn_from_turn(
            user_objective=f"Complete task #{task['id']}",
            steps=[{"step": 1, "action": "respond", "status": "completed"}],
            observations=[],  # No tool observations
            final_answer="I have completed the task.",
            session_id="sess-claim",
        )

        # Task in DB must remain 'todo' because no tool verified the completion
        current_task = self.personal_store.get_task(task["id"])
        self.assertEqual(current_task["status"], "todo")
        self.assertEqual(len(outcome["task_updates"]), 0)

    def test_verified_task_update_with_successful_tool_observation(self):
        """Task status is updated when corroborated by authoritative update_task tool observation."""
        task = self.personal_store.create_task(
            title="Generate audit report",
            status="todo",
        )

        outcome = self.learning_service.learn_from_turn(
            user_objective=f"Complete task #{task['id']}",
            steps=[{"step": 1, "action": "tool", "tool": "update_task", "status": "executed"}],
            observations=[{"tool": "update_task", "result": {"task": {"id": task["id"], "title": task["title"], "status": "completed"}}}],
            final_answer="Task marked as completed.",
            session_id="sess-verified",
        )

        self.assertEqual(len(outcome["task_updates"]), 1)
        self.assertEqual(outcome["task_updates"][0]["new_status"], "completed")

    def test_unrelated_successful_list_directory_does_not_complete_task(self):
        """Executing list_directory must NEVER mark a task completed even if user prompt says complete task."""
        task = self.personal_store.create_task(
            title="Inspect project directory and complete task",
            status="todo",
        )

        outcome = self.learning_service.learn_from_turn(
            user_objective=f"Inspect the directory and complete task #{task['id']}",
            steps=[{"step": 1, "action": "tool", "tool": "list_directory", "status": "executed"}],
            observations=[{"tool": "list_directory", "result": {"entries": [{"name": "README.md", "type": "file"}]}}],
            final_answer="Directory inspected.",
            session_id="sess-unrelated-list",
        )

        self.assertEqual(len(outcome["task_updates"]), 0)
        current = self.personal_store.get_task(task["id"])
        self.assertEqual(current["status"], "todo")

    def test_unrelated_successful_git_status_does_not_complete_task(self):
        """Executing git_status must NEVER mark a task completed."""
        task = self.personal_store.create_task(
            title="Check git repo status",
            status="todo",
        )

        outcome = self.learning_service.learn_from_turn(
            user_objective=f"Check git status and complete task #{task['id']}",
            steps=[{"step": 1, "action": "tool", "tool": "git_status", "status": "executed"}],
            observations=[{"tool": "git_status", "result": {"clean": True}}],
            final_answer="Git status is clean.",
            session_id="sess-unrelated-git",
        )

        self.assertEqual(len(outcome["task_updates"]), 0)
        current = self.personal_store.get_task(task["id"])
        self.assertEqual(current["status"], "todo")

    def test_unrelated_successful_read_file_does_not_complete_task(self):
        """Executing read_file must NEVER mark a task completed."""
        task = self.personal_store.create_task(
            title="Read specification notes",
            status="todo",
        )

        outcome = self.learning_service.learn_from_turn(
            user_objective=f"Read notes.txt and complete task #{task['id']}",
            steps=[{"step": 1, "action": "tool", "tool": "read_file", "status": "executed"}],
            observations=[{"tool": "read_file", "result": {"content": "spec notes"}}],
            final_answer="Read notes.",
            session_id="sess-unrelated-read",
        )

        self.assertEqual(len(outcome["task_updates"]), 0)
        current = self.personal_store.get_task(task["id"])
        self.assertEqual(current["status"], "todo")

    def test_task_id_mentioned_in_unrelated_conversation_does_not_cause_mutation(self):
        """Mentioning a task ID in passing conversation without authoritative execution does not mutate task."""
        task = self.personal_store.create_task(
            title="Review database architecture",
            status="todo",
        )

        outcome = self.learning_service.learn_from_turn(
            user_objective=f"I was looking at task #{task['id']} earlier today, what do you think?",
            steps=[{"step": 1, "action": "respond", "status": "completed"}],
            observations=[],
            final_answer="It looks like a solid task.",
            session_id="sess-chatter",
        )

        self.assertEqual(len(outcome["task_updates"]), 0)
        current = self.personal_store.get_task(task["id"])
        self.assertEqual(current["status"], "todo")

    def test_verified_confirmed_update_task_completes_task(self):
        """Confirmed update_task action is authoritatively learned as a task update."""
        task = self.personal_store.create_task(
            title="Deploy release v1.0",
            status="todo",
        )

        outcome = self.learning_service.learn_from_turn(
            user_objective=f"Confirmed action for task #{task['id']}",
            steps=[{"step": 1, "action": "tool", "tool": "update_task", "status": "executed"}],
            observations=[],
            final_answer="Confirmed update executed.",
            session_id="sess-confirm-exec",
            confirmation_required=False,
            confirmed_result={"tool": "update_task", "result": {"task": {"id": task["id"], "title": task["title"], "status": "completed"}}},
        )

        self.assertEqual(len(outcome["task_updates"]), 1)
        self.assertEqual(outcome["task_updates"][0]["task_id"], task["id"])
        self.assertEqual(outcome["task_updates"][0]["new_status"], "completed")
        self.assertEqual(outcome["task_updates"][0]["verified_by"], "user_confirmed_update_task")

    def test_learning_after_failed_task_completion(self):
        """Failed tasks record failure status and diagnostic information without marking completed."""
        task = self.personal_store.create_task(
            title="Read sensitive configuration",
            status="todo",
        )

        outcome = self.learning_service.learn_from_turn(
            user_objective=f"Read sensitive configuration and complete task #{task['id']}",
            steps=[{"step": 1, "action": "tool", "tool": "read_file", "status": "error"}],
            observations=[{"tool": "read_file", "result": {"error": "FileNotFoundError"}}],
            final_answer="File not found.",
            session_id="sess-fail",
        )

        self.assertEqual(outcome["completion_status"], "failed")
        # Task remains todo
        current_task = self.personal_store.get_task(task["id"])
        self.assertEqual(current_task["status"], "todo")

    def test_confirmation_required_is_not_learned_as_success_before_approval(self):
        """Confirmation-required operations are pending and not learned as executed mutations."""
        outcome = self.learning_service.learn_from_turn(
            user_objective="Delete old log file",
            steps=[{"step": 1, "action": "tool", "tool": "delete_file", "status": "confirmation_required"}],
            observations=[],
            final_answer="Confirmation required to delete file.",
            session_id="sess-confirm",
            confirmation_required=True,
        )

        self.assertEqual(outcome["completion_status"], "pending_confirmation")
        self.assertEqual(len(outcome["task_updates"]), 0)

    def test_idempotent_learning_no_duplicate_records(self):
        """Calling learn on the same turn multiple times returns cached event without duplicates."""
        outcome1 = self.learning_service.learn_from_turn(
            user_objective="Our internal codename is BLUE ORBIT 47. Remember it.",
            steps=[{"step": 1, "action": "respond", "status": "completed"}],
            observations=[],
            final_answer="Stored.",
            session_id="sess-idem",
        )
        self.assertEqual(outcome1["status"], "learned")

        outcome2 = self.learning_service.learn_from_turn(
            user_objective="Our internal codename is BLUE ORBIT 47. Remember it.",
            steps=[{"step": 1, "action": "respond", "status": "completed"}],
            observations=[],
            final_answer="Stored.",
            session_id="sess-idem",
        )
        self.assertEqual(outcome2["status"], "already_learned")

    def test_learning_errors_do_not_crash_orchestrator(self):
        """Exceptions during learning are caught safely and returned as an error outcome."""
        # Intentionally break memory_store to test isolation
        broken_learning = PostTaskLearningService(
            memory_store=None,
            personal_store=None,
            extraction_service=None,
        )
        with patch.object(broken_learning, "_perform_learning", side_effect=RuntimeError("Simulated DB failure")):
            res = broken_learning.learn_from_turn(
                user_objective="Do something",
                steps=[],
                observations=[],
                final_answer="Done",
            )
            self.assertEqual(res["status"], "learning_error")
            self.assertIn("Simulated DB failure", res["error"])

    def test_orchestrator_core_loop_learn_stage(self):
        """Orchestrator runs the 6-stage core loop: UNDERSTAND -> REMEMBER -> PLAN -> ACT -> OBSERVE -> LEARN."""
        router = AsyncMock()
        router.chat.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "I remembered BLUE ORBIT 47."}}],
            "model": "nvidia/nemotron",
        }
        planner = AsyncMock()
        planner.plan.return_value = {"action": "respond", "reason": "Conversational memory input"}

        registry = create_default_registry(personal_store=self.personal_store)
        context_engine = ContextEngine(
            memory_store=self.memory,
            session_store=self.sessions,
        )

        orchestrator = AgentOrchestrator(
            router=router,
            registry=registry,
            context_engine=context_engine,
            planner=planner,
            learning_service=self.learning_service,
        )

        turn_result = run(orchestrator.run(
            user_message="For this project, our internal codename is BLUE ORBIT 47. Remember it.",
            session_id="sess-full-loop",
        ))

        self.assertIn("learning", turn_result)
        self.assertEqual(turn_result["learning"]["completion_status"], "success")

        # In a new session, query for the memory
        memories = self.memory.recall("internal project codename")
        self.assertTrue(len(memories) > 0)
        self.assertIn("BLUE ORBIT 47", memories[0]["content"])
