"""
demo_data.py — Deterministic synthetic demo records and seeding mechanism for Orion.

Ensures reliable, reproducible demo records for:
- Projects
- Goals
- Tasks
- Decisions
- Skills
- Episodic Memories

Safety rules:
1. No personal, sensitive, or external user data.
2. Deterministic: consistent across fresh instances and resets.
3. Safe: never blindly duplicates records; only seeds on fresh/empty DB or explicit reseed.
4. Reseed is gated behind authenticated demo access.
"""

from typing import Any
from .database import get_connection, _is_test_environment

SYNTHETIC_PROJECTS = [
    {
        "id": 1,
        "name": "Orion Personal AI",
        "description": "Personal AI operating layer and autonomous assistant powered by Nebius Token Factory and Nemotron.",
        "path": "data/workspace",
        "repository": "https://github.com/ssurekumar01111-hue/orion-personal-ai",
        "status": "active",
    },
    {
        "id": 2,
        "name": "Isolated Runner Sandbox",
        "description": "Evaluating microVM and containerized runner architectures for safe, sandboxed command execution.",
        "path": None,
        "repository": None,
        "status": "active",
    },
]

SYNTHETIC_GOALS = [
    {
        "id": 1,
        "title": "Deploy Hackathon Production Demo",
        "description": "Deliver a hardened, safe, single-service production deployment on Render free tier.",
        "status": "active",
        "project_id": 1,
    },
    {
        "id": 2,
        "title": "Enforce Subprocess Safety",
        "description": "Safely disable unconfined shell execution in public demo environments.",
        "status": "active",
        "project_id": 2,
    },
]

SYNTHETIC_TASKS = [
    {
        "id": 1,
        "title": "Configure production multi-stage Dockerfile",
        "description": "Bundle React frontend and FastAPI backend into unified container image with dynamic port binding.",
        "status": "done",
        "priority": "high",
        "project_id": 1,
        "goal_id": 1,
    },
    {
        "id": 2,
        "title": "Enforce server-side confirmation for mutating tools",
        "description": "Require explicit confirmation for file writes, deletions, and model mutations.",
        "status": "done",
        "priority": "high",
        "project_id": 1,
        "goal_id": 1,
    },
    {
        "id": 3,
        "title": "Audit process isolation on Render free tier",
        "description": "Verify host command execution fails closed in production mode.",
        "status": "in_progress",
        "priority": "medium",
        "project_id": 2,
        "goal_id": 2,
    },
]

SYNTHETIC_DECISIONS = [
    {
        "id": 1,
        "decision": "Fail closed for host command execution in production mode",
        "context": "Process-level controls on shared containers lack OS sandboxing. Disabling commands protects the host.",
        "project_id": 1,
    },
    {
        "id": 2,
        "decision": "Serve compiled React bundle directly through FastAPI",
        "context": "Single web service architecture eliminates multi-origin CORS friction and Render free tier limits.",
        "project_id": 1,
    },
]

SYNTHETIC_SKILLS = [
    {
        "id": 1,
        "name": "read_project_readme",
        "description": "Reads the project README documentation from the workspace.",
        "workflow": '{"steps": [{"tool": "read_file", "arguments": {"path": "README.md"}}]}',
    },
]

SYNTHETIC_MEMORIES = [
    {
        "content": "Orion utilizes Nebius Token Factory for Nemotron LLM inference with bounded multi-step tool execution.",
        "category": "architecture",
        "importance": 5,
    },
    {
        "content": "Workspace operations are strictly confined to the dedicated workspace directory; secrets and source code are protected.",
        "category": "security",
        "importance": 5,
    },
    {
        "content": "Mutating tools like write_file, delete_file, and run_command require explicit server-side confirmation.",
        "category": "policy",
        "importance": 4,
    },
]


def is_database_empty() -> bool:
    """Check whether the projects and memories tables are currently empty."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM projects")
        projects_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM memories")
        memories_count = cursor.fetchone()[0]
        return (projects_count == 0 and memories_count == 0)


def seed_demo_data(force: bool = False) -> dict[str, int]:
    """
    Seed deterministic synthetic demo records.
    If force is False, only seeds if the database is currently empty.
    """
    if not force and not is_database_empty():
        return {"status": "skipped", "message": "Database already contains records"}

    with get_connection() as conn:
        cursor = conn.cursor()

        if force:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("DELETE FROM messages")
            conn.execute("DELETE FROM sessions")
            conn.execute("DELETE FROM tasks")
            conn.execute("DELETE FROM goals")
            conn.execute("DELETE FROM decisions")
            conn.execute("DELETE FROM projects")
            conn.execute("DELETE FROM skills")
            conn.execute("DELETE FROM memories")
            conn.execute("PRAGMA foreign_keys = ON")

        # Insert Projects
        for p in SYNTHETIC_PROJECTS:
            cursor.execute(
                """
                INSERT OR REPLACE INTO projects (id, name, description, path, repository, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (p["id"], p["name"], p["description"], p["path"], p["repository"], p["status"]),
            )

        # Insert Goals
        for g in SYNTHETIC_GOALS:
            cursor.execute(
                """
                INSERT OR REPLACE INTO goals (id, title, description, status, project_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (g["id"], g["title"], g["description"], g["status"], g["project_id"]),
            )

        # Insert Tasks
        for t in SYNTHETIC_TASKS:
            cursor.execute(
                """
                INSERT OR REPLACE INTO tasks (id, title, description, status, priority, project_id, goal_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (t["id"], t["title"], t["description"], t["status"], t["priority"], t["project_id"], t["goal_id"]),
            )

        # Insert Decisions
        for d in SYNTHETIC_DECISIONS:
            cursor.execute(
                """
                INSERT OR REPLACE INTO decisions (id, decision, context, project_id)
                VALUES (?, ?, ?, ?)
                """,
                (d["id"], d["decision"], d["context"], d["project_id"]),
            )

        # Insert Skills
        for s in SYNTHETIC_SKILLS:
            cursor.execute(
                """
                INSERT OR REPLACE INTO skills (id, name, description, workflow)
                VALUES (?, ?, ?, ?)
                """,
                (s["id"], s["name"], s["description"], s["workflow"]),
            )

        # Insert Memories
        for m in SYNTHETIC_MEMORIES:
            cursor.execute(
                """
                INSERT INTO memories (content, category, importance)
                VALUES (?, ?, ?)
                """,
                (m["content"], m["category"], m["importance"]),
            )

        conn.commit()

    return {
        "projects": len(SYNTHETIC_PROJECTS),
        "goals": len(SYNTHETIC_GOALS),
        "tasks": len(SYNTHETIC_TASKS),
        "decisions": len(SYNTHETIC_DECISIONS),
        "skills": len(SYNTHETIC_SKILLS),
        "memories": len(SYNTHETIC_MEMORIES),
    }
