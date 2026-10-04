import atexit
import os
import sqlite3
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
_DEFAULT_DATABASE_PATH = DATA_DIR / "orion.db"
_DEFAULT_TEST_DATABASE_PATH = DATA_DIR / "orion_test.db"

_test_db_cleaned = False


def _is_test_environment() -> bool:
    if os.environ.get("ORION_TEST_MODE") == "1":
        return True
    if "pytest" in sys.modules:
        return True
    if "unittest" in sys.modules and any("test" in arg.lower() for arg in sys.argv):
        return True
    return False


def _ensure_test_db_fresh(test_db_path: Path) -> None:
    global _test_db_cleaned
    if not _test_db_cleaned:
        _test_db_cleaned = True
        test_db_path.parent.mkdir(parents=True, exist_ok=True)
        if test_db_path.exists():
            try:
                test_db_path.unlink()
            except Exception:
                pass

        def _cleanup():
            if test_db_path.exists():
                try:
                    test_db_path.unlink()
                except Exception:
                    pass

        atexit.register(_cleanup)


def get_database_path() -> Path:
    env_override = os.environ.get("ORION_DATABASE_PATH")
    if env_override:
        return Path(env_override)
    if _is_test_environment():
        _ensure_test_db_fresh(_DEFAULT_TEST_DATABASE_PATH)
        return _DEFAULT_TEST_DATABASE_PATH
    return _DEFAULT_DATABASE_PATH


DATABASE_PATH = get_database_path()


def set_database_path(path: Path | str | None) -> None:
    """Override database path (primarily for test isolation)."""
    global DATABASE_PATH
    if path is None:
        os.environ.pop("ORION_DATABASE_PATH", None)
        DATABASE_PATH = _DEFAULT_DATABASE_PATH
    else:
        resolved = Path(path)
        os.environ["ORION_DATABASE_PATH"] = str(resolved)
        DATABASE_PATH = resolved


def get_connection() -> sqlite3.Connection:
    db_path = get_database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    connection.execute("PRAGMA foreign_keys = ON")

    return connection


def initialize_database() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                importance INTEGER NOT NULL DEFAULT 3,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT 'New conversation',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id)
                    REFERENCES sessions(id)
                    ON DELETE CASCADE
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id, created_at)
            """
        )

        # ── Personal Model Tables ───────────────────────────────────────────
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                path TEXT,
                repository TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                project_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id)
                    REFERENCES projects(id)
                    ON DELETE SET NULL
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'todo',
                priority TEXT NOT NULL DEFAULT 'medium',
                project_id INTEGER,
                goal_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id)
                    REFERENCES projects(id)
                    ON DELETE SET NULL,
                FOREIGN KEY (goal_id)
                    REFERENCES goals(id)
                    ON DELETE SET NULL
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision TEXT NOT NULL,
                context TEXT NOT NULL DEFAULT '',
                project_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id)
                    REFERENCES projects(id)
                    ON DELETE SET NULL
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                workflow TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # ── Personal Model Indexes ──────────────────────────────────────────
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_goals_project
            ON goals(project_id)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tasks_project
            ON tasks(project_id)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tasks_goal
            ON tasks(goal_id)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_decisions_project
            ON decisions(project_id)
            """
        )

        connection.commit()

