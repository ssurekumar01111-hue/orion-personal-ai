"""
Backend Test Package Initialization.

Configures an isolated test database so that tests run against a clean,
deterministic temporary/test database rather than the persistent development
database (data/orion.db).
"""
import atexit
import os
import sys
from pathlib import Path

# Ensure backend root is in sys.path
_backend_root = Path(__file__).resolve().parents[1]
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

# Set test-isolated database if not explicitly set
if "ORION_DATABASE_PATH" not in os.environ:
    _project_root = Path(__file__).resolve().parents[2]
    _test_db_dir = _project_root / "data"
    _test_db_path = _test_db_dir / "orion_test.db"

    # Start with a fresh deterministic database file
    if _test_db_path.exists():
        try:
            _test_db_path.unlink()
        except Exception:
            pass

    os.environ["ORION_DATABASE_PATH"] = str(_test_db_path)

    from app.memory.database import initialize_database, set_database_path
    set_database_path(_test_db_path)
    initialize_database()

    def _cleanup_test_db() -> None:
        if _test_db_path.exists():
            try:
                _test_db_path.unlink()
            except Exception:
                pass

    atexit.register(_cleanup_test_db)
else:
    from app.memory.database import initialize_database
    initialize_database()
