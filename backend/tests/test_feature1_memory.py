"""
Tests for Feature 1 — Automatic Conversational Memory Extraction and Recall.
"""
import unittest
from unittest.mock import AsyncMock, patch

from app.memory.database import initialize_database
from app.memory.extraction import MemoryExtractionService
from app.memory.session import SessionStore
from app.memory.store import MemoryStore
from app.memory.context import ContextEngine
from app.main import app
from starlette.testclient import TestClient


class TestMemoryExtraction(unittest.TestCase):
    def setUp(self):
        initialize_database()
        self.store = MemoryStore()
        self.service = MemoryExtractionService(memory_store=self.store)

    def tearDown(self):
        from app.memory.database import get_connection
        with get_connection() as conn:
            conn.execute("DELETE FROM memories")
            conn.commit()

    def test_explicit_memory_extraction(self):
        """User: 'For this project, our internal codename is BLUE ORBIT 47. Remember it.'"""
        extracted = self.service.extract_from_conversation(
            "For this project, our internal codename is BLUE ORBIT 47. Remember it.",
            session_id="session-alpha",
        )
        self.assertEqual(len(extracted), 1)
        mem = extracted[0]
        self.assertIn("BLUE ORBIT 47", mem["content"])
        self.assertEqual(mem["importance"], 5)
        self.assertEqual(mem["category"], "project")
        self.assertEqual(mem["source_session"], "session-alpha")

    def test_explicit_memory_remember_that(self):
        """User: 'Remember that our deployment region is us-east-1.'"""
        extracted = self.service.extract_from_conversation(
            "Remember that our deployment region is us-east-1.",
            session_id="session-1",
        )
        self.assertEqual(len(extracted), 1)
        self.assertIn("deployment region is us-east-1", extracted[0]["content"])

    def test_automatic_candidate_extraction_preference(self):
        """User states preference without explicit 'remember' keyword."""
        extracted = self.service.extract_from_conversation(
            "I prefer tabs over spaces for Python indentation.",
            session_id="session-pref",
        )
        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0]["category"], "preference")
        self.assertIn("tabs over spaces", extracted[0]["content"])

    def test_transient_command_not_saved_as_memory(self):
        """Transient commands and questions should not be saved automatically."""
        extracted = self.service.extract_from_conversation(
            "What was the internal project codename?",
            session_id="session-q",
        )
        self.assertEqual(len(extracted), 0)

        extracted2 = self.service.extract_from_conversation(
            "Please list the files in the backend directory.",
            session_id="session-cmd",
        )
        self.assertEqual(len(extracted2), 0)

    def test_secret_filtering(self):
        """Secrets like API keys and passwords must never be extracted or stored."""
        # Attempt via extraction service
        extracted = self.service.extract_from_conversation(
            "Remember that api_key=sk-1234567890abcdef1234567890abcdef",
        )
        self.assertEqual(len(extracted), 0)

        # Attempt directly on store
        with self.assertRaises(ValueError):
            self.store.remember("The database password: password=supersecretpass123")

    def test_duplicate_detection_and_update(self):
        """Near identical memories update rather than creating duplicates."""
        mem1 = self.store.remember(
            "Internal codename is BLUE ORBIT 47",
            category="project",
            importance=3,
            source_session="s1",
        )
        mem2 = self.store.remember(
            "internal codename is BLUE ORBIT 47",
            category="project",
            importance=5,
            source_session="s2",
        )
        self.assertEqual(mem1["id"], mem2["id"])
        self.assertEqual(mem2["importance"], 5)
        self.assertEqual(mem2["source_session"], "s2")

    def test_conflict_and_outdated_memory_updating(self):
        """Updating conflicting project facts (e.g., changed codename)."""
        mem1 = self.store.remember(
            "Our internal codename is BLUE ORBIT 47",
            category="project",
        )
        # Update codename in subsequent interaction
        mem2 = self.store.remember(
            "Our internal codename is RED NOVA 99",
            category="project",
        )
        self.assertEqual(mem1["id"], mem2["id"])
        self.assertEqual(mem2["content"], "Our internal codename is RED NOVA 99")

    def test_cross_session_semantic_recall(self):
        """Session A stores fact; Session B recalls it with different wording."""
        self.store.remember(
            "For this project, our internal codename is BLUE ORBIT 47",
            category="project",
            importance=5,
            source_session="session-a",
        )

        # Query in session B
        results = self.store.recall("What was the internal project codename?")
        self.assertTrue(len(results) > 0)
        self.assertIn("BLUE ORBIT 47", results[0]["content"])

    def test_user_memory_deletion(self):
        """Users can delete a stored memory."""
        mem = self.store.remember("Temporary note to be forgotten", category="temp")
        self.assertTrue(self.store.delete(mem["id"]))
        self.assertIsNone(self.store.get(mem["id"]))

    def test_memory_api_endpoints(self):
        """Test API endpoints /api/memory, recall, delete."""
        client = TestClient(app)

        # Create
        res = client.post("/api/memory", json={"content": "Important architecture note: SQLite WAL mode", "category": "architecture", "importance": 4})
        self.assertEqual(res.status_code, 200)
        mem_id = res.json()["id"]

        # Recall
        recall_res = client.post("/api/memory/recall", json={"query": "architecture SQLite"})
        self.assertEqual(recall_res.status_code, 200)
        self.assertTrue(any(m["id"] == mem_id for m in recall_res.json()["memories"]))

        # Delete
        del_res = client.delete(f"/api/memory/{mem_id}")
        self.assertEqual(del_res.status_code, 200)
        self.assertTrue(del_res.json()["deleted"])

    def test_automatic_extraction_rejects_sensitive_health_and_medical(self):
        """Health, medical, and prescription info must NOT be automatically persisted without explicit instruction."""
        res1 = self.service.extract_from_conversation(
            "I prefer taking my insulin medication after dinner.",
            session_id="sess-health-1",
        )
        self.assertEqual(len(res1), 0)

        res2 = self.service.extract_from_conversation(
            "My preference is to manage my depression and hypertension with regular exercise.",
            session_id="sess-health-2",
        )
        self.assertEqual(len(res2), 0)

    def test_automatic_extraction_rejects_financial_accounts_and_identity(self):
        """Financial accounts, SSN, and identity details must NOT be automatically persisted."""
        res1 = self.service.extract_from_conversation(
            "My preference is checking bank account routing number 987654321.",
            session_id="sess-fin-1",
        )
        self.assertEqual(len(res1), 0)

        res2 = self.service.extract_from_conversation(
            "Our primary goal is to verify ssn 000-12-3456.",
            session_id="sess-fin-2",
        )
        self.assertEqual(len(res2), 0)

    def test_explicit_opt_in_allows_sensitive_personal_facts(self):
        """Explicit instruction allows remembering personal or health details."""
        res = self.service.extract_from_conversation(
            "Remember that my doctor is Dr. Smith and my clinic visit is on Friday.",
            session_id="sess-optin",
        )
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["category"], "personal")
        self.assertIn("Dr. Smith", res[0]["content"])

    def test_explicit_instruction_still_strictly_rejects_credentials(self):
        """Explicit instruction must NEVER bypass credential or password rejection."""
        res = self.service.extract_from_conversation(
            "Remember that password=SuperSecretPassword99!",
            session_id="sess-cred",
        )
        self.assertEqual(len(res), 0)

        with self.assertRaises(ValueError):
            self.store.remember(
                "My secret token is auth_token=abcdef1234567890",
                is_explicit=True,
            )

    def test_ordinary_work_preferences_and_project_facts_still_auto_extracted(self):
        """Non-sensitive project facts and coding preferences remain automatically extracted."""
        res1 = self.service.extract_from_conversation(
            "I prefer dark mode in VSCode with Fira Code font.",
            session_id="sess-pref",
        )
        self.assertEqual(len(res1), 1)
        self.assertEqual(res1[0]["category"], "preference")

        res2 = self.service.extract_from_conversation(
            "Our internal codename is BLUE ORBIT 47 for this project.",
            session_id="sess-code",
        )
        self.assertEqual(len(res2), 1)
        self.assertEqual(res2[0]["category"], "project")

    def test_exact_blue_orbit_47_extraction_without_preamble(self):
        """Test exact wording: 'Remember this for future conversations: My project codename is BLUE ORBIT 47. It is a personal AI research project.'"""
        extracted = self.service.extract_from_conversation(
            "Remember this for future conversations: My project codename is BLUE ORBIT 47. It is a personal AI research project.",
            session_id="session-blue-orbit",
        )
        self.assertEqual(len(extracted), 1)
        mem = extracted[0]
        self.assertEqual(
            mem["content"],
            "My project codename is BLUE ORBIT 47. It is a personal AI research project",
        )
        self.assertNotIn("for future conversations", mem["content"].lower())
        self.assertEqual(mem["category"], "project")
        self.assertEqual(mem["importance"], 5)
        self.assertEqual(mem["source_session"], "session-blue-orbit")

    def test_future_session_qualifier_removal(self):
        """Test: 'Please remember for future sessions: I prefer concise technical explanations.'"""
        extracted = self.service.extract_from_conversation(
            "Please remember for future sessions: I prefer concise technical explanations.",
            session_id="session-concise",
        )
        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0]["content"], "I prefer concise technical explanations")
        self.assertNotIn("future sessions", extracted[0]["content"].lower())
        self.assertEqual(extracted[0]["category"], "preference")

    def test_going_forward_remember_removal(self):
        """Test: 'Going forward, remember that I prefer written updates.'"""
        extracted = self.service.extract_from_conversation(
            "Going forward, remember that I prefer written updates.",
            session_id="session-updates",
        )
        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0]["content"], "I prefer written updates")
        self.assertNotIn("going forward", extracted[0]["content"].lower())

    def test_relevance_scoring_excludes_unrelated_high_importance_memories(self):
        """Fix D: Unrelated high-importance memories must NOT be retrieved merely because of importance."""
        self.store.remember(
            "Orion utilizes Nebius Token Factory for Nemotron LLM inference with bounded multi-step tool execution.",
            category="architecture",
            importance=5,
        )
        self.store.remember(
            "Workspace operations are strictly confined to the dedicated workspace directory.",
            category="security",
            importance=5,
        )

        # Completely unrelated query
        results = self.store.recall("What is your favorite recipe for homemade pasta?")
        self.assertEqual(len(results), 0)

    def test_relevance_scoring_retrieves_matching_high_and_lower_importance_memories(self):
        """Fix D: Directly matching memories remain eligible regardless of importance, and ranked sensibly."""
        mem_high = self.store.remember(
            "My project codename is BLUE ORBIT 47",
            category="project",
            importance=5,
        )
        mem_low = self.store.remember(
            "User prefers dark console interface",
            category="preference",
            importance=1,
        )

        # High-importance match
        results_high = self.store.recall("What is my project codename?")
        self.assertTrue(len(results_high) > 0)
        self.assertEqual(results_high[0]["id"], mem_high["id"])

        # Low-importance match
        results_low = self.store.recall("User preference for terminal console")
        self.assertTrue(len(results_low) > 0)
        self.assertEqual(results_low[0]["id"], mem_low["id"])

    def test_cross_session_retrieval_across_distinct_sessions(self):
        """Cross-session retrieval: Session 1 stores memory; Session 2 context engine recalls it."""
        session_store = SessionStore()
        s1 = session_store.create("Session 1")
        s2 = session_store.create("Session 2")

        # Session 1 extracts memory
        self.service.extract_from_conversation(
            "Remember this for future conversations: My project codename is BLUE ORBIT 47. It is a personal AI research project.",
            session_id=s1["id"],
        )

        # Session 2 context retrieval
        engine = ContextEngine(memory_store=self.store, session_store=session_store)
        ctx = engine.build_context("What was my project codename?", session_id=s2["id"])

        self.assertTrue(len(ctx["memories"]) > 0)
        self.assertIn("BLUE ORBIT 47", ctx["memories"][0]["content"])

    def test_system_prompt_accurately_describes_episodic_memory(self):
        """Fix B: System prompt must describe cross-session episodic memory and forbid disclaiming memory."""
        engine = ContextEngine(memory_store=self.store, session_store=SessionStore())
        prompt = engine.build_system_prompt(memories=[])

        self.assertIn("structured episodic memory that can be retrieved across separate conversation sessions", prompt)
        self.assertIn("Do not claim that you cannot remember or retain information across separate conversations", prompt)
        self.assertNotIn("session-only", prompt.lower())

    @patch("app.main.router.chat")
    def test_chat_acknowledgement_synchronization_on_successful_persistence(self, mock_chat):
        """Fix B: When memory is persisted, chat response accurately acknowledges it and strips disclaimers."""
        mock_chat.return_value = {
            "choices": [{
                "message": {
                    "content": "I've noted your project codename as BLUE ORBIT 47 for our current conversation. Per my operational constraints, I don't have persistent long-term memory across separate conversations—I can only retain and reference information provided within the active session or defined in my initial context (personal model/episodic memory)."
                }
            }],
            "model": "test-model",
        }

        client = TestClient(app)
        res = client.post(
            "/api/chat",
            json={
                "message": "Remember this for future conversations: My project codename is BLUE ORBIT 47. It is a personal AI research project."
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()

        # Memory was extracted
        self.assertTrue(len(data["extracted_memories"]) > 0)
        self.assertEqual(
            data["extracted_memories"][0]["content"],
            "My project codename is BLUE ORBIT 47. It is a personal AI research project",
        )

        # Response contains accurate acknowledgement and stripped disclaimer
        self.assertIn("saved this to persistent episodic memory", data["response"])
        self.assertNotIn("don't have persistent long-term memory", data["response"])

    @patch("app.main.router.chat")
    def test_chat_no_acknowledgement_when_no_persistence(self, mock_chat):
        """Fix B: When no memory is extracted, response does not invent a saved confirmation."""
        mock_chat.return_value = {
            "choices": [{"message": {"content": "Paris is the capital of France."}}],
            "model": "test-model",
        }

        client = TestClient(app)
        res = client.post(
            "/api/chat",
            json={"message": "What is the capital of France?"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertEqual(len(data["extracted_memories"]), 0)
        self.assertNotIn("saved this to persistent episodic memory", data["response"])
        self.assertIn("Paris is the capital of France.", data["response"])

    @patch("app.main.router.chat")
    def test_regression_false_save_acknowledgement_stripped_when_no_persistence(self, mock_chat):
        """Regression: False save acknowledgement must be stripped when no memory was persisted while preserving unrelated sentences."""
        mock_chat.return_value = {
            "choices": [{"message": {"content": "I have saved this to your persistent memory. Paris is the capital of France."}}],
            "model": "test-model",
        }

        client = TestClient(app)
        res = client.post(
            "/api/chat",
            json={"message": "What is the capital of France?"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertEqual(len(data["extracted_memories"]), 0)
        self.assertNotIn("saved this to", data["response"].lower())
        self.assertEqual(data["response"], "Paris is the capital of France.")

    @patch("app.main.router.chat")
    def test_false_save_acknowledgement_variations_stripped(self, mock_chat):
        """Verify 'I have saved', 'I\'ve saved', and 'I saved' are all stripped when no memory was persisted."""
        client = TestClient(app)
        variations = [
            ("I have saved this to your persistent memory. Paris is the capital of France.", "Paris is the capital of France."),
            ("I've saved this to your persistent memory. Paris is the capital of France.", "Paris is the capital of France."),
            ("I saved this to your persistent memory. Paris is the capital of France.", "Paris is the capital of France."),
        ]
        for mock_content, expected_content in variations:
            mock_chat.return_value = {
                "choices": [{"message": {"content": mock_content}}],
                "model": "test-model",
            }
            res = client.post(
                "/api/chat",
                json={"message": "What is the capital of France?"},
            )
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(len(data["extracted_memories"]), 0)
            self.assertEqual(data["response"], expected_content)

    def test_category_matching_exact_token_only(self):
        """Confirm category matching does not match 'go' against 'goal', 'pro' against 'project', or 'act' against 'architecture', but exact matches work."""
        self.store.remember("Achieve high performance milestones.", category="goal")
        self.store.remember("Manage the new enterprise rollout.", category="project")
        self.store.remember("Design microservices with clear boundaries.", category="architecture")

        # Inexact substrings must not match
        self.assertEqual(self.store.recall("go"), [])
        self.assertEqual(self.store.recall("pro"), [])
        self.assertEqual(self.store.recall("act"), [])

        # Valid exact category matches must work
        goal_matches = self.store.recall("goal")
        self.assertEqual(len(goal_matches), 1)
        self.assertEqual(goal_matches[0]["category"], "goal")

        project_matches = self.store.recall("project")
        self.assertEqual(len(project_matches), 1)
        self.assertEqual(project_matches[0]["category"], "project")

        arch_matches = self.store.recall("architecture")
        self.assertEqual(len(arch_matches), 1)
        self.assertEqual(arch_matches[0]["category"], "architecture")
