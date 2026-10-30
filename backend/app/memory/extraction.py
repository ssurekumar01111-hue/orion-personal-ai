"""
Memory Extraction Service for Orion.

Extracts persistent, structured conversational memories from user interactions:
- Explicit instructions (e.g., "Remember that...", "Our codename is BLUE ORBIT 47. Remember it.")
- User preferences, long-term goals, active project facts, constraints, and repeated working patterns.
- Conservative filtering (rejects chatter, transient task instructions, speculative text).
- Secret filtering (strictly rejects passwords, API keys, tokens, credentials).
- Integrates directly with MemoryStore for deduplication, conflict updates, and audit logging.
"""
import re
from typing import Any

from ..tools.audit import log_event
from .store import MemoryStore, _contains_secret, _contains_sensitive_personal_info

EXPLICIT_PATTERNS = [
    # "For this project, our internal codename is BLUE ORBIT 47. Remember it."
    re.compile(r"^(.*?)[,;.]?\s*(?:please\s+)?remember\s+(?:it|this|that)[.!]?$", re.IGNORECASE),
    # "Remember that our internal codename is BLUE ORBIT 47"
    re.compile(r"^(?:please\s+)?remember(?:\s+that|\s*:|\s+this)?\s*[:,-]?\s*(.+)$", re.IGNORECASE),
    # "Don't forget that ..."
    re.compile(r"^(?:don't|do not)\s+forget(?:\s+that)?\s*[:,-]?\s*(.+)$", re.IGNORECASE),
    # "Note that ..." / "Keep in mind that ..."
    re.compile(r"^(?:note\s+that|keep in mind\s+that)\s*[:,-]?\s*(.+)$", re.IGNORECASE),
]

# Patterns for automatic candidate extraction (conservative)
PREFERENCE_PATTERN = re.compile(
    r"\b(?:i\s+prefer|my\s+preference\s+is|i\s+always\s+use|always\s+format\s+with|my\s+favorite\s+editor\s+is)\b\s*(.+?)(?:\.|$)",
    re.IGNORECASE,
)
PROJECT_FACT_PATTERN = re.compile(
    r"\b(?:(?:internal\s+)?codename\s+is|project\s+name\s+is|repository\s+url\s+is)\b\s*([A-Za-z0-9_\-\s]{2,40})",
    re.IGNORECASE,
)
GOAL_PATTERN = re.compile(
    r"\b(?:our\s+(?:primary\s+)?goal\s+is\s+to|long-term\s+objective\s+is\s+to)\b\s*(.+?)(?:\.|$)",
    re.IGNORECASE,
)
CONSTRAINT_PATTERN = re.compile(
    r"\b(?:our\s+convention\s+is|the\s+hard\s+constraint\s+is|working\s+pattern\s+is)\b\s*(.+?)(?:\.|$)",
    re.IGNORECASE,
)

# Reject questions and transient commands from becoming permanent memories
TRANSIENT_PREFIXES = (
    "what ", "where ", "when ", "why ", "how ", "who ", "can you ",
    "could you ", "please list ", "list ", "show ", "read ", "write ",
    "delete ", "run ", "execute ", "check ", "find ",
)


class MemoryExtractionService:
    """
    Analyzes conversation inputs and task outcomes to conservatively
    extract and persist useful long-term memories.
    """

    def __init__(self, memory_store: MemoryStore | None = None) -> None:
        self.memory_store = memory_store or MemoryStore()

    def _determine_category(self, content: str) -> str:
        lower = content.lower()
        if _contains_sensitive_personal_info(content):
            return "personal"
        if any(term in lower for term in ("codename", "project", "repo", "architecture", "orbit")):
            return "project"
        if any(term in lower for term in ("prefer", "like", "style", "favorite", "editor")):
            return "preference"
        if any(term in lower for term in ("goal", "objective", "target", "milestone")):
            return "goal"
        if any(term in lower for term in ("constraint", "convention", "rule", "standard", "never", "always")):
            return "constraint"
        return "fact"

    def extract_from_conversation(
        self,
        user_message: str,
        session_id: str | None = None,
        project_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Extract memories from a conversation turn:
        1. Check explicit user instructions ("Remember that ...", "... Remember it.")
        2. Check conservative candidates (preferences, codenames, project constraints).
        3. Reject secrets and transient commands.
        4. Persist to MemoryStore.
        """
        if not user_message or not isinstance(user_message, str) or not user_message.strip():
            return []

        text = user_message.strip()

        # Reject secrets immediately
        if _contains_secret(text):
            return []

        extracted_records: list[dict[str, Any]] = []

        # ── 1. Explicit user instructions ──────────────────────────────────
        explicit_match = None
        for pattern in EXPLICIT_PATTERNS:
            m = pattern.match(text)
            if m:
                explicit_match = m.group(1).strip()
                break

        if explicit_match:
            # Clean trailing punctuation
            clean_fact = explicit_match.rstrip(".!? ")
            if len(clean_fact) >= 3 and not _contains_secret(clean_fact):
                category = self._determine_category(clean_fact)
                record = self.memory_store.remember(
                    content=clean_fact,
                    category=category,
                    importance=5,  # Explicit instructions have highest importance
                    source_session=session_id,
                    project_id=project_id,
                    allow_update=True,
                    is_explicit=True,
                )
                log_event(
                    event="memory_extracted_explicit",
                    status="success",
                    result={"memory_id": record["id"], "category": category},
                )
                extracted_records.append(record)
                return extracted_records

        # ── 2. Conservative Automatic Inferences ───────────────────────────
        # Reject questions, transient commands, and sensitive personal/health/financial info
        lower_text = text.lower()
        if (
            text.endswith("?")
            or any(lower_text.startswith(p) for p in TRANSIENT_PREFIXES)
            or _contains_sensitive_personal_info(text)
        ):
            return []

        # A) Project codename / fact
        proj_match = PROJECT_FACT_PATTERN.search(text)
        if proj_match:
            fact_body = proj_match.group(0).strip()
            # If part of a larger sentence, capture full clause
            record = self.memory_store.remember(
                content=text,
                category="project",
                importance=4,
                source_session=session_id,
                project_id=project_id,
                allow_update=True,
                is_explicit=False,
            )
            log_event(
                event="memory_extracted_auto",
                status="success",
                result={"memory_id": record["id"], "category": "project"},
            )
            extracted_records.append(record)
            return extracted_records

        # B) Preference
        pref_match = PREFERENCE_PATTERN.search(text)
        if pref_match:
            pref_content = pref_match.group(0).strip()
            record = self.memory_store.remember(
                content=pref_content,
                category="preference",
                importance=4,
                source_session=session_id,
                project_id=project_id,
                allow_update=True,
                is_explicit=False,
            )
            log_event(
                event="memory_extracted_auto",
                status="success",
                result={"memory_id": record["id"], "category": "preference"},
            )
            extracted_records.append(record)
            return extracted_records

        # C) Goal
        goal_match = GOAL_PATTERN.search(text)
        if goal_match:
            goal_content = goal_match.group(0).strip()
            record = self.memory_store.remember(
                content=goal_content,
                category="goal",
                importance=4,
                source_session=session_id,
                project_id=project_id,
                allow_update=True,
                is_explicit=False,
            )
            log_event(
                event="memory_extracted_auto",
                status="success",
                result={"memory_id": record["id"], "category": "goal"},
            )
            extracted_records.append(record)
            return extracted_records

        # D) Constraint / pattern
        const_match = CONSTRAINT_PATTERN.search(text)
        if const_match:
            const_content = const_match.group(0).strip()
            record = self.memory_store.remember(
                content=const_content,
                category="constraint",
                importance=4,
                source_session=session_id,
                project_id=project_id,
                allow_update=True,
                is_explicit=False,
            )
            log_event(
                event="memory_extracted_auto",
                status="success",
                result={"memory_id": record["id"], "category": "constraint"},
            )
            extracted_records.append(record)
            return extracted_records

        return extracted_records
