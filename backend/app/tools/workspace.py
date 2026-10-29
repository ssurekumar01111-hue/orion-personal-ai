"""
workspace.py — Orion R3 dedicated workspace with canonical path enforcement.

Key design decisions:
* WORKSPACE_ROOT is a configurable, dedicated directory under Orion's writable
  data area (PROJECT_ROOT / "data" / "workspace" by default), NOT the source repository.
* The application source tree (backend, frontend, .git, .env, root files),
  the SQLite databases (data/orion.db), and audit logs (data/audit.log) are protected
  and cannot be read, written, or deleted through workspace tools.
* safe_path() resolves all symlinks canonically before containment check, preventing
  directory traversal and symlink escapes outside the workspace.
* is_protected_file() rejects secret/environment files, SQLite DBs, audit logs,
  and Git metadata.
* is_source_path() provides defence-in-depth protection for application source.
* A synthetic demo workspace with safe sample files is automatically populated.

Isolation caveat:
Workspace path restrictions and environment sanitisation are process-level controls,
NOT an OS-level sandbox. Render Free cannot be assumed to provide container or VM
sandboxing. For public-demo deployment, command execution fails closed.
"""

import os
from pathlib import Path


PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]

_WORKSPACE_ROOT_CACHE: Path | None = None


def _get_workspace_root() -> Path:
    """
    Return the canonical, resolved workspace root directory.
    Resolution order:
      1. Cached path (if set, e.g. for testing)
      2. ORION_WORKSPACE_ROOT env var or settings
      3. Default: PROJECT_ROOT / "data" / "workspace"
    """
    global _WORKSPACE_ROOT_CACHE, WORKSPACE_ROOT
    if _WORKSPACE_ROOT_CACHE is not None:
        return _WORKSPACE_ROOT_CACHE

    raw = os.environ.get("ORION_WORKSPACE_ROOT", "").strip()
    if not raw:
        try:
            from ..config import get_settings
            raw = get_settings().orion_workspace_root.strip()
        except Exception:
            raw = ""

    if raw:
        candidate = Path(raw)
    else:
        candidate = PROJECT_ROOT / "data" / "workspace"

    resolved = candidate.resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    _WORKSPACE_ROOT_CACHE = resolved
    WORKSPACE_ROOT = resolved
    return resolved


# Module-level alias for backward compatibility
WORKSPACE_ROOT: Path = PROJECT_ROOT / "data" / "workspace"


def _reset_workspace_root_for_testing(new_root: Path | None = None) -> None:
    """Reset workspace root cache for testing purposes."""
    global _WORKSPACE_ROOT_CACHE, WORKSPACE_ROOT
    if new_root is not None:
        resolved = new_root.resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        _WORKSPACE_ROOT_CACHE = resolved
        WORKSPACE_ROOT = resolved
    else:
        _WORKSPACE_ROOT_CACHE = None
        WORKSPACE_ROOT = _get_workspace_root()


def is_protected_file(path: Path) -> bool:
    """
    Check whether a path refers to sensitive configuration, secrets,
    environment files, SQLite databases, audit logs, or Git metadata.
    """
    name = path.name.lower()

    # Exact or prefixed .env patterns (.env, .env.local, .env.prod, etc.)
    if name == ".env" or name.startswith(".env.") or name.startswith(".env"):
        return True

    # Common credential and secret file patterns
    if name in {
        "credentials",
        "credentials.json",
        "secrets.json",
        "token",
        "tokens.json",
        "id_rsa",
        "id_ed25519",
        "id_dsa",
        "id_ecdsa",
        "authorized_keys",
        "known_hosts",
    }:
        return True

    # Secret and private key extensions
    if path.suffix.lower() in {".key", ".pem", ".pfx", ".p12", ".pkcs12"}:
        return True

    # Database and audit log files
    if name in {"orion.db", "orion_test.db", "audit.log"} or name.startswith("audit."):
        return True
    if path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
        return True

    # Git metadata
    if name == ".git" or any(part.lower() == ".git" for part in path.parts):
        return True

    return False


def is_source_path(path: Path) -> bool:
    """
    Return True if path (resolved) falls inside the Orion application source tree,
    Git metadata, or data root files (databases, audit log), but NOT within
    the dedicated workspace.
    """
    resolved = path.resolve()
    ws = _get_workspace_root()

    # If the path is inside the workspace, it's a workspace path, not application source
    try:
        resolved.relative_to(ws)
        return False
    except ValueError:
        pass

    # Blocked application source directories and files
    blocked_targets = [
        PROJECT_ROOT / "backend",
        PROJECT_ROOT / "frontend",
        PROJECT_ROOT / ".git",
        PROJECT_ROOT / ".venv",
        PROJECT_ROOT / ".env",
        PROJECT_ROOT / "data" / "orion.db",
        PROJECT_ROOT / "data" / "orion_test.db",
        PROJECT_ROOT / "data" / "audit.log",
    ]

    for target in blocked_targets:
        target_resolved = target.resolve()
        if resolved == target_resolved:
            return True
        try:
            resolved.relative_to(target_resolved)
            return True
        except ValueError:
            continue

    # Files directly in PROJECT_ROOT (like package.json, vite.config.ts, etc.)
    if resolved.parent == PROJECT_ROOT or resolved == PROJECT_ROOT:
        return True

    return False


def safe_path(relative_path: str = ".") -> Path:
    """
    Resolve relative_path relative to WORKSPACE_ROOT, enforce canonical containment,
    and reject symlink escapes, traversal, and access to application source / secrets.
    """
    workspace = _get_workspace_root()
    candidate = (workspace / relative_path).resolve()

    # 1. Workspace containment check (prevents traversal and symlink escape)
    try:
        candidate.relative_to(workspace)
    except ValueError as exc:
        raise PermissionError(
            "Path is outside the Orion workspace."
        ) from exc

    # 2. Application source protection
    if is_source_path(candidate):
        raise PermissionError(
            "Path resolves into the application source tree, which is protected."
        )

    # 3. Protected files check
    if is_protected_file(candidate):
        raise PermissionError(
            "Access to secret or environment files is forbidden."
        )

    return candidate


def _ensure_demo_workspace() -> None:
    """
    Create a small, synthetic demo workspace with safe sample files.
    Idempotent and safe to run on startup.
    """
    ws = _get_workspace_root()

    readme = ws / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Orion Demo Workspace\n\n"
            "This directory is the dedicated sandbox for Orion AI tool operations.\n"
            "It is intentionally separate from the Orion application source tree.\n\n"
            "## Structure\n\n"
            "```\n"
            "workspace/\n"
            "├── README.md                 — Demo workspace overview\n"
            "├── backend/requirements.txt   — Sample backend dependencies\n"
            "├── frontend/package.json      — Sample frontend package configuration\n"
            "├── notes/welcome.txt         — Sample notes\n"
            "└── projects/demo_project/    — Sample project plan\n"
            "```\n",
            encoding="utf-8",
        )

    # Synthetic demo backend requirements
    backend_dir = ws / "backend"
    backend_dir.mkdir(parents=True, exist_ok=True)
    requirements = backend_dir / "requirements.txt"
    if not requirements.exists():
        requirements.write_text(
            "# Demo project backend dependencies\n"
            "fastapi>=0.115.0\n"
            "uvicorn>=0.30.0\n"
            "pydantic>=2.0.0\n",
            encoding="utf-8",
        )

    # Synthetic demo frontend package.json
    frontend_dir = ws / "frontend"
    frontend_dir.mkdir(parents=True, exist_ok=True)
    pkg_json = frontend_dir / "package.json"
    if not pkg_json.exists():
        pkg_json.write_text(
            '{\n  "name": "demo-frontend",\n  "version": "0.1.0",\n  "scripts": {\n    "dev": "vite",\n    "build": "tsc && vite build"\n  }\n}\n',
            encoding="utf-8",
        )

    # Sample notes
    notes_dir = ws / "notes"
    notes_dir.mkdir(exist_ok=True)
    welcome = notes_dir / "welcome.txt"
    if not welcome.exists():
        welcome.write_text(
            "Welcome to the Orion demo workspace.\n\n"
            "This workspace is a safe sandbox for AI-assisted file operations.\n"
            "All reads and writes are restricted to this directory.\n",
            encoding="utf-8",
        )

    # Sample project plan
    projects_dir = ws / "projects" / "demo_project"
    projects_dir.mkdir(parents=True, exist_ok=True)
    plan = projects_dir / "plan.md"
    if not plan.exists():
        plan.write_text(
            "# Demo Project Plan\n\n"
            "## Goals\n\n"
            "- [ ] Explore Orion workspace tools\n"
            "- [ ] Create and read files safely\n"
            "- [ ] Verify permission boundaries\n",
            encoding="utf-8",
        )

    data_dir = ws / "data"
    data_dir.mkdir(exist_ok=True)
