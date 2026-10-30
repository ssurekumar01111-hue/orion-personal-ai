import re
from datetime import datetime, timezone
from typing import Any

from ..tools.audit import _scrub_secrets
from .database import get_connection

STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "of", "with",
    "by", "is", "was", "are", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "what", "which", "who", "whom", "this", "that", "these",
    "those", "our", "my", "your", "his", "her", "its", "their", "please", "can",
    "could", "would", "should", "it", "about", "tell", "me", "how", "why", "when",
    "where", "remember",
})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(text: str) -> str:
    return " ".join(text.strip().lower().split())


SENSITIVE_PERSONAL_PATTERNS = [
    # Medical & Health conditions, medications, providers
    r"(?i)\b(?:doctor|physician|psychiatrist|therapist|cardiologist|oncologist|pediatrician|hospital|clinic)\b",
    r"(?i)\b(?:diagnos(?:ed|is)|prescription|prescribed|medication|dosage|insulin|metformin|adderall|lexapro|prozac|lipitor|lisinopril|chemotherapy|radiation|biopsy|surgery)\b",
    r"(?i)\b(?:diabetes|cancer|tumor|hypertension|blood\s+pressure|heart\s+attack|stroke|asthma|depression|bipolar|schizophrenia|anxiety\s+disorder|epilepsy|hiv|aids)\b",
    r"(?i)\b(?:medical\s+record|health\s+insurance|patient\s+id|blood\s+type)\b",
    # Financial accounts & national identity
    r"(?i)\b(?:bank\s+account|checking\s+account|savings\s+account|routing\s+number|account\s+number|iban|swift\s+code)\b",
    r"(?i)\b(?:social\s+security(?:\s+number)?|ssn|tax\s+id|national\s+insurance(?:\s+number)?)\b",
    r"(?i)\b(?:passport\s+number|driver'?s\s+license(?:\s+number)?)\b",
    r"(?i)\b\d{3}-\d{2}-\d{4}\b",  # SSN format
]


def _contains_sensitive_personal_info(text: str) -> bool:
    """
    Check if text contains sensitive personal information: health, medical,
    financial account numbers, or government identity details.
    """
    if not text:
        return False
    for pat in SENSITIVE_PERSONAL_PATTERNS:
        if re.search(pat, text):
            return True
    return False


def _contains_secret(text: str) -> bool:
    """Check if text contains passwords, API keys, tokens, or credentials."""
    if not text:
        return False
    patterns = [
        r"(?i)\b(?:password|passwd|secret|api[_-]?key|auth[_-]?token)\s*[:=]\s*\S+",
        r"(?i)\bBearer\s+[A-Za-z0-9_\-\.]{8,}",
        r"(?i)\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}",
        r"(?i)\bsk-[A-Za-z0-9]{20,}",
        r"-----BEGIN (?:RSA )?PRIVATE KEY-----",
        r"\b(?:\d[ -]*?){13,16}\b",
    ]
    for pat in patterns:
        if re.search(pat, text):
            return True
    return False


def _extract_topic_key(content: str) -> str | None:
    """
    Extract a normalized topic key to detect conflicting or outdated memories.
    e.g., 'internal codename is BLUE ORBIT 47' -> 'internal codename'
    'preferred python version is 3.12' -> 'preferred python version'
    """
    norm = _normalize_text(content)
    match = re.match(
        r"^(?:for this project,?\s*)?(?:our\s+|the\s+|user\s+|my\s+)?([a-z0-9_\-\s]+?)\s+(?:is|was|are|should be|must be)\b",
        norm,
    )
    if match:
        key = match.group(1).strip()
        # Ensure key is meaningful
        if len(key) >= 3 and key not in STOPWORDS:
            return key
    return None


class MemoryStore:
    """
    Episodic memory store with secret filtering, duplicate detection,
    outdated memory updating, and multi-word semantic recall scoring.
    """

    def remember(
        self,
        content: str,
        category: str = "general",
        importance: int = 3,
        source_session: str | None = None,
        project_id: int | None = None,
        allow_update: bool = True,
        is_explicit: bool = True,
    ) -> dict[str, Any]:
        if not content or not isinstance(content, str) or not content.strip():
            raise ValueError("Memory content cannot be empty.")

        if _contains_secret(content):
            raise ValueError("Cannot store memory containing sensitive credentials or secrets.")

        if not is_explicit and _contains_sensitive_personal_info(content):
            raise ValueError(
                "Cannot automatically persist sensitive personal or medical information without explicit user instruction."
            )

        safe_content = _scrub_secrets(content.strip())
        importance = max(1, min(5, int(importance)))
        norm_content = _normalize_text(safe_content)
        now = _now_iso()

        with get_connection() as connection:
            # 1. Exact or near-duplicate detection
            existing_rows = connection.execute(
                """
                SELECT id, content, category, importance, source_session, project_id, created_at
                FROM memories
                WHERE category = ?
                   OR project_id = ?
                   OR project_id IS NULL
                """,
                (category, project_id),
            ).fetchall()

            for row in existing_rows:
                row_norm = _normalize_text(row["content"])
                if row_norm == norm_content:
                    # Duplicate detected: update recency, importance, session, project
                    new_importance = max(row["importance"], importance)
                    new_session = source_session or row["source_session"]
                    new_project = project_id if project_id is not None else row["project_id"]
                    connection.execute(
                        """
                        UPDATE memories
                        SET importance = ?, source_session = ?, project_id = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (new_importance, new_session, new_project, now, row["id"]),
                    )
                    connection.commit()
                    updated = connection.execute(
                        "SELECT * FROM memories WHERE id = ?", (row["id"],)
                    ).fetchone()
                    return dict(updated)

            # 2. Topic-based conflict detection (updating outdated memory)
            if allow_update:
                topic_key = _extract_topic_key(safe_content)
                if topic_key:
                    for row in existing_rows:
                        row_topic = _extract_topic_key(row["content"])
                        if row_topic and row_topic == topic_key:
                            # Conflicting/outdated memory found: update existing record
                            connection.execute(
                                """
                                UPDATE memories
                                SET content = ?, category = ?, importance = ?,
                                    source_session = ?, project_id = ?, updated_at = ?
                                WHERE id = ?
                                """,
                                (
                                    safe_content,
                                    category,
                                    importance,
                                    source_session or row["source_session"],
                                    project_id if project_id is not None else row["project_id"],
                                    now,
                                    row["id"],
                                ),
                            )
                            connection.commit()
                            updated = connection.execute(
                                "SELECT * FROM memories WHERE id = ?", (row["id"],)
                            ).fetchone()
                            return dict(updated)

            # 3. Insert new memory
            cursor = connection.execute(
                """
                INSERT INTO memories (content, category, importance, source_session, project_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (safe_content, category, importance, source_session, project_id, now, now),
            )
            connection.commit()
            memory_id = cursor.lastrowid

            row = connection.execute(
                "SELECT * FROM memories WHERE id = ?",
                (memory_id,),
            ).fetchone()

        return dict(row)

    def get(self, memory_id: int) -> dict[str, Any] | None:
        with get_connection() as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE id = ?",
                (memory_id,),
            ).fetchone()
        return dict(row) if row else None

    def update(
        self,
        memory_id: int,
        content: str | None = None,
        category: str | None = None,
        importance: int | None = None,
        project_id: int | None = None,
    ) -> dict[str, Any] | None:
        with get_connection() as connection:
            existing = connection.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
            if not existing:
                return None

            updates = []
            params = []
            if content is not None:
                if not content.strip():
                    raise ValueError("Memory content cannot be empty.")
                if _contains_secret(content):
                    raise ValueError("Cannot store memory containing sensitive credentials or secrets.")
                updates.append("content = ?")
                params.append(_scrub_secrets(content.strip()))
            if category is not None:
                updates.append("category = ?")
                params.append(category.strip())
            if importance is not None:
                updates.append("importance = ?")
                params.append(max(1, min(5, int(importance))))
            if project_id is not None:
                updates.append("project_id = ?")
                params.append(project_id)

            if not updates:
                return dict(existing)

            updates.append("updated_at = ?")
            params.append(_now_iso())
            params.append(memory_id)

            connection.execute(
                f"UPDATE memories SET {', '.join(updates)} WHERE id = ?",
                tuple(params),
            )
            connection.commit()

            row = connection.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
        return dict(row) if row else None

    def recall(
        self,
        query: str,
        limit: int = 10,
        project_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Recall relevant memories beyond crude keyword matching using
        token overlap, importance weighting, project matching, and phrase detection.
        """
        if not query or not query.strip():
            return []

        limit = max(1, min(50, limit))
        clean_query = query.strip()
        norm_query = _normalize_text(clean_query)
        raw_tokens = re.findall(r"[a-z0-9_\-]+", norm_query)
        query_keywords = [t for t in raw_tokens if t not in STOPWORDS and len(t) >= 2]

        with get_connection() as connection:
            # Fetch all candidate memories (bounded limit for speed & prompt safety)
            rows = connection.execute(
                """
                SELECT * FROM memories
                ORDER BY updated_at DESC
                LIMIT 200
                """
            ).fetchall()

        if not rows:
            return []

        scored_candidates: list[tuple[float, dict[str, Any]]] = []

        for row in rows:
            mem_dict = dict(row)
            content_norm = _normalize_text(mem_dict["content"])
            cat_norm = _normalize_text(mem_dict.get("category", ""))
            content_tokens = set(re.findall(r"[a-z0-9_\-]+", content_norm))

            score = 0.0

            # 1. Exact substring match in content
            if norm_query in content_norm:
                score += 10.0
            elif clean_query.lower() in content_norm:
                score += 8.0

            # 2. Token overlap
            matched_keywords = [kw for kw in query_keywords if kw in content_tokens or kw in content_norm]
            if matched_keywords:
                score += len(matched_keywords) * 3.0

            # 3. Category match
            if any(kw in cat_norm for kw in query_keywords):
                score += 2.0

            # 4. Importance weighting
            score += mem_dict.get("importance", 3) * 0.5

            # 5. Project alignment
            if project_id is not None and mem_dict.get("project_id") == project_id:
                score += 3.0

            if score > 1.5:  # meaningful relevance threshold
                scored_candidates.append((score, mem_dict))

        if scored_candidates:
            scored_candidates.sort(
                key=lambda item: (item[0], item[1].get("importance", 3), item[1].get("updated_at", "")),
                reverse=True,
            )
            return [item[1] for item in scored_candidates[:limit]]

        # Fallback to direct LIKE matching for backward compatibility
        pattern = f"%{clean_query}%"
        with get_connection() as connection:
            fallback_rows = connection.execute(
                """
                SELECT *
                FROM memories
                WHERE content LIKE ?
                   OR category LIKE ?
                ORDER BY importance DESC, updated_at DESC
                LIMIT ?
                """,
                (pattern, pattern, limit),
            ).fetchall()
        return [dict(r) for r in fallback_rows]

    def list_recent(
        self,
        limit: int = 10,
        category: str | None = None,
        project_id: int | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(100, limit))
        query = "SELECT * FROM memories"
        params: list[Any] = []
        conditions: list[str] = []

        if category:
            conditions.append("category = ?")
            params.append(category.strip())
        if project_id is not None:
            conditions.append("project_id = ?")
            params.append(project_id)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)

        with get_connection() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()

        return [dict(row) for row in rows]

    def delete(self, memory_id: int) -> bool:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM memories
                WHERE id = ?
                """,
                (memory_id,),
            )
            connection.commit()
            return cursor.rowcount > 0
