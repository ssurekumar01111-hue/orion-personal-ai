import os
from pathlib import Path
import pytest
from app.config import get_settings
from app.rate_limiter import limiter
from starlette.testclient import TestClient

TEST_DEMO_KEY = "test-demo-secret-key-12345-very-long"
os.environ["ORION_DEMO_KEY"] = TEST_DEMO_KEY

# Point tests at a dedicated workspace under Orion's writable data area
from app.tools.workspace import PROJECT_ROOT, _ensure_demo_workspace, _reset_workspace_root_for_testing

_TEST_WORKSPACE = PROJECT_ROOT / "data" / "workspace"
os.environ["ORION_WORKSPACE_ROOT"] = str(_TEST_WORKSPACE)

_reset_workspace_root_for_testing(_TEST_WORKSPACE)
_ensure_demo_workspace()

get_settings.cache_clear()

# Default TestClient to authenticated test demo key unless headers are explicitly specified
_orig_testclient_init = TestClient.__init__


def _patched_testclient_init(self, app, *args, **kwargs):
    if "headers" not in kwargs:
        current_key = os.environ.get("ORION_DEMO_KEY", TEST_DEMO_KEY)
        kwargs["headers"] = {"Authorization": f"Bearer {current_key}"}
    _orig_testclient_init(self, app, *args, **kwargs)


TestClient.__init__ = _patched_testclient_init


@pytest.fixture(autouse=True)
def test_setup_teardown():
    os.environ["ORION_DEMO_KEY"] = TEST_DEMO_KEY
    os.environ["ORION_WORKSPACE_ROOT"] = str(_TEST_WORKSPACE)
    _reset_workspace_root_for_testing(_TEST_WORKSPACE)
    _ensure_demo_workspace()
    get_settings.cache_clear()
    limiter.clear()
    yield
    os.environ["ORION_DEMO_KEY"] = TEST_DEMO_KEY
    os.environ["ORION_WORKSPACE_ROOT"] = str(_TEST_WORKSPACE)
    get_settings.cache_clear()
    limiter.clear()
