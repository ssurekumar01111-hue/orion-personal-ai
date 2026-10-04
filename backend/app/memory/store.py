from typing import Any

from .database import get_connection


class MemoryStore:

    def remember(
        self,
        content: str,
        category: str = "general",
        importance: int = 3,
    ) -> dict[str, Any]:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO memories (content, category, importance)
                VALUES (?, ?, ?)
                """,
                (content, category, importance),
            )

            connection.commit()

            memory_id = cursor.lastrowid

            row = connection.execute(
                """
                SELECT *
                FROM memories
                WHERE id = ?
                """,
                (memory_id,),
            ).fetchone()

        return dict(row)

    def recall(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        pattern = f"%{query}%"

        with get_connection() as connection:
            rows = connection.execute(
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

        return [dict(row) for row in rows]

    def list_recent(
        self,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM memories
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

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
