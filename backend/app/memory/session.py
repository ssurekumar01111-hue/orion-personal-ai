import uuid
from typing import Any

from .database import get_connection


class SessionStore:

    def create(self, title: str = "New conversation") -> dict[str, Any]:
        session_id = str(uuid.uuid4())

        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO sessions (id, title)
                VALUES (?, ?)
                """,
                (session_id, title),
            )

            connection.commit()

            row = connection.execute(
                """
                SELECT *
                FROM sessions
                WHERE id = ?
                """,
                (session_id,),
            ).fetchone()

        return dict(row)

    def get(self, session_id: str) -> dict[str, Any] | None:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM sessions
                WHERE id = ?
                """,
                (session_id,),
            ).fetchone()

        return dict(row) if row else None

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM sessions
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [dict(row) for row in rows]

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
    ) -> dict[str, Any]:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO messages (
                    session_id,
                    role,
                    content
                )
                VALUES (?, ?, ?)
                """,
                (session_id, role, content),
            )

            connection.execute(
                """
                UPDATE sessions
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (session_id,),
            )

            connection.commit()

            row = connection.execute(
                """
                SELECT *
                FROM messages
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()

        return dict(row)

    def get_messages(
        self,
        session_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM messages
                WHERE session_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()

        messages = [dict(row) for row in rows]
        messages.reverse()

        return messages

    def delete(self, session_id: str) -> bool:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM sessions
                WHERE id = ?
                """,
                (session_id,),
            )

            connection.commit()

            return cursor.rowcount > 0
