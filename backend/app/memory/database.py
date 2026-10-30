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


_is_initializing = False


def get_connection() -> sqlite3.Connection:
    global _is_initializing
    db_path = get_database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    connection.execute("PRAGMA foreign_keys = ON")

    if not _is_initializing:
        try:
            has_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories'"
            ).fetchone()
            if not has_table:
                _is_initializing = True
                try:
                    initialize_database()
                finally:
                    _is_initializing = False
        except Exception:
            pass

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
                source_session TEXT,
                project_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id)
                    REFERENCES projects(id)
                    ON DELETE SET NULL
            )
            """
        )

        # Safe additive migrations for existing memories table
        existing_mem_cols = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(memories)").fetchall()
        }
        if "source_session" not in existing_mem_cols:
            connection.execute("ALTER TABLE memories ADD COLUMN source_session TEXT")
        if "project_id" not in existing_mem_cols:
            connection.execute(
                "ALTER TABLE memories ADD COLUMN project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL"
            )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_memories_category_importance
            ON memories(category, importance)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_memories_project
            ON memories(project_id)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_memories_session
            ON memories(source_session)
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

        # ── Skill Learning & Versioning Tables (LEARN Stage) ────────────────
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS skill_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_id INTEGER NOT NULL,
                session_id TEXT,
                status TEXT NOT NULL,
                step_results TEXT NOT NULL DEFAULT '[]',
                failure_reason TEXT,
                duration_ms REAL DEFAULT 0.0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (skill_id)
                    REFERENCES skills(id)
                    ON DELETE CASCADE
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_skill_executions_skill
            ON skill_executions(skill_id, created_at)
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS skill_proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                proposed_workflow TEXT NOT NULL,
                rationale TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                applied_at TEXT,
                FOREIGN KEY (skill_id)
                    REFERENCES skills(id)
                    ON DELETE CASCADE
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_skill_proposals_skill
            ON skill_proposals(skill_id, status)
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS skill_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_id INTEGER NOT NULL,
                version_number INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                workflow TEXT NOT NULL,
                change_summary TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (skill_id)
                    REFERENCES skills(id)
                    ON DELETE CASCADE,
                UNIQUE (skill_id, version_number)
            )
            """
        )

        # Safe migration: if existing records contain duplicate versions, renumber sequentially
        # to ensure no data is lost before enforcing unique index
        dup_rows = connection.execute(
            """
            SELECT skill_id, version_number, COUNT(*) as cnt
            FROM skill_versions
            GROUP BY skill_id, version_number
            HAVING cnt > 1
            """
        ).fetchall()
        if dup_rows:
            for dup in dup_rows:
                s_id = dup["skill_id"]
                all_v = connection.execute(
                    "SELECT id FROM skill_versions WHERE skill_id = ? ORDER BY id ASC",
                    (s_id,),
                ).fetchall()
                for idx, v_row in enumerate(all_v, start=1):
                    connection.execute(
                        "UPDATE skill_versions SET version_number = ? WHERE id = ?",
                        (idx, v_row["id"]),
                    )

        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_skill_versions_skill_version
            ON skill_versions(skill_id, version_number)
            """
        )

        # ── Automated Post-Task Learning Events Table ───────────────────────
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_key TEXT NOT NULL UNIQUE,
                session_id TEXT,
                user_objective TEXT NOT NULL,
                completion_status TEXT NOT NULL,
                learned_memories_count INTEGER DEFAULT 0,
                learned_decisions_count INTEGER DEFAULT 0,
                task_updates_count INTEGER DEFAULT 0,
                summary TEXT NOT NULL DEFAULT '',
                details TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_learning_events_session
            ON learning_events(session_id)
            """
        )

        connection.commit()

