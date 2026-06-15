import os

import sys
from pathlib import Path

import pytest

# Ensure `src` is importable
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from fastmcp.client import Client
from fastmcp_server import mcp
import httpx
import os

from idrac_async_redfish_client.client import iDRACAsyncRedfishClient

@pytest.fixture(scope='session')
def username():
    """Test fixture for username (from env `IDRAC_USERNAME`)."""
    return os.getenv('IDRAC_USERNAME', None)


@pytest.fixture(scope='session')
def password():
    """Test fixture for password (from env `IDRAC_PASSWORD`)."""
    return os.getenv('IDRAC_PASSWORD', None)

@pytest.fixture
async def main_mcp_client():
    async with Client(transport=mcp) as mcp_client:
        yield mcp_client

def pytest_addoption(parser):
    parser.addoption(
        "--hosts",
        action="store",
        default=os.getenv("TEST_HOSTS", "192.168.0.200,192.168.0.201,192.168.0.202,192.168.0.203"),
        help="Comma-separated list of hosts to run tests against",
    )

def pytest_generate_tests(metafunc):
    if "host" in metafunc.fixturenames:
        raw = metafunc.config.getoption("--hosts")
        hosts = [h.strip() for h in raw.split(",") if h.strip()]
        metafunc.parametrize("host", hosts)

@pytest.fixture
async def mock_idrac_client(host):
    """Provide an iDRAC client configured to hit the real host.

    The `host` fixture is parametrized via `--hosts` (or `TEST_HOSTS`).
    Username/password are read from the `IDRAC_USERNAME`/`IDRAC_PASSWORD` env vars by the
    `username`/`password` fixtures.
    """
    client = iDRACAsyncRedfishClient(host=host, verify=False)
    yield client
    await client.logout()


@pytest.fixture(autouse=True)
async def clear_session_manager_between_tests():
    """Autouse fixture: ensure any cached sessions in the module-level
    `session_mgr` are closed after each test to avoid cross-test reuse.
    """
    yield
    try:
        # import here to avoid circular import at module import time
        from fastmcp_server import session_mgr
        await session_mgr.close_all()
    except Exception:
        # best-effort cleanup; don't mask test errors
        pass
