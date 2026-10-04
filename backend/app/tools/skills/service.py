"""
Skill Service (Phase 4B).

Provides skill management and discovery:
- Listing and fetching skills.
- Bounded keyword discovery (SkillMatcher) returning at most 3 candidates.
- Safe creation and updates using SkillValidator.
"""
import json
import re
from typing import Any

from ...memory.personal import PersonalModelStore
from .validator import SkillValidator


class SkillService:
    """
    Service layer for skill discovery and persistence.
    """

    def __init__(self, store: PersonalModelStore | None = None) -> None:
        self.store = store or PersonalModelStore()

    def list_skills(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.list_skills(limit=limit)

    def get_skill(self, skill_id: int) -> dict[str, Any] | None:
        return self.store.get_skill(skill_id)

    def get_skill_by_name(self, name: str) -> dict[str, Any] | None:
        if not name or not isinstance(name, str):
            return None
        norm_name = name.strip().lower()
        skills = self.store.list_skills(limit=100)
        for s in skills:
            if (s.get("name") or "").strip().lower() == norm_name:
                return s
        return None

    def match_skills(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        """
        Identify relevant skills for a user query using bounded keyword matching.
        Returns at most `min(limit, 3)` candidate skills.
        """
        if not query or not query.strip():
            return []

        max_limit = min(limit, 3)
        skills = self.store.list_skills(limit=50)
        if not skills:
            return []

        stopwords = {
            "the", "and", "for", "with", "this", "that", "from", "are",
            "was", "were", "what", "how", "can", "you", "please", "could",
            "about", "have", "been", "will", "would", "shall", "should",
        }
        query_words = set(re.findall(r"[a-z0-9_\-]+", query.lower())) - stopwords
        if not query_words:
            return []

        scored: list[tuple[float, dict[str, Any]]] = []
        for s in skills:
            name_words = set(re.findall(r"[a-z0-9_\-]+", (s.get("name") or "").lower()))
            desc_words = set(re.findall(r"[a-z0-9_\-]+", (s.get("description") or "").lower()))

            name_overlap = len(query_words & name_words)
            desc_overlap = len(query_words & desc_words)

            score = (name_overlap * 3.0) + (desc_overlap * 1.0)
            if score > 0:
                scored.append((score, s))

        # Sort by score DESC, then updated_at DESC
        scored.sort(key=lambda item: (item[0], item[1].get("updated_at", "")), reverse=True)
        return [item[1] for item in scored[:max_limit]]
