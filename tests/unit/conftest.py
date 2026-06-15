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

@pytest.fixture
async def main_mcp_client():
    async with Client(transport=mcp) as mcp_client:
        yield mcp_client

@pytest.fixture
async def mock_idrac_client(host):
    """Provide an iDRAC client configured to hit the real host.

    The `host` fixture is parametrized via `--hosts` (or `TEST_HOSTS`).
    Username/password are read from the `IDRAC_USERNAME`/`IDRAC_PASSWORD` env vars by the
    `username`/`password` fixtures.
    """
    client = iDRACAsyncRedfishClient(host=host, verify=False)
    yield client
    await client.close()

