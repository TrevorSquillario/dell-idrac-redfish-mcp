from typing import Any, Dict, List, Optional
import asyncio
from fastmcp import FastMCP
from fastmcp.utilities.types import Image
from starlette.responses import JSONResponse
from contextlib import asynccontextmanager

from idrac_async_redfish_client.client import iDRACAsyncRedfishClient

class PerHostSessionManager:
    """Cache long-lived iDRAC clients per-host and lazily ensure sessions.

    Clients are reused across requests. The manager serializes initial
    authentication per-host using a per-host lock. Clients are not closed on
    every usage; call `close_all()` to clean them up (registered at exit).
    """
    def __init__(self, default_username: Optional[str] = None, default_password: Optional[str] = None, default_verify: bool = False):
        self.default_username = default_username
        self.default_password = default_password
        self.default_verify = default_verify
        self._clients: Dict[str, iDRACAsyncRedfishClient] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._cache_lock = asyncio.Lock()

    async def _host_lock(self, host: str) -> asyncio.Lock:
        async with self._cache_lock:
            lock = self._locks.get(host)
            if not lock:
                lock = asyncio.Lock()
                self._locks[host] = lock
            return lock

    @asynccontextmanager
    async def get_client(self, host: str, creds: Dict[str, Any]):
        username = creds.get("username") or self.default_username
        password = creds.get("password") or self.default_password
        verify = creds.get("verify", self.default_verify)
        port = creds.get("port", 443)

        client = self._clients.get(host)

        # If client exists and token looks valid, return it immediately.
        if client and client.token_valid():
            yield client
            return

        # Otherwise serialize creation/login for this host.
        host_lock = await self._host_lock(host)
        async with host_lock:
            client = self._clients.get(host)
            if client is None:
                client = iDRACAsyncRedfishClient(host, port=port, verify=verify)
                self._clients[host] = client

            try:
                await client.ensure_session(username, password)
            except Exception:
                logger.exception("failed to ensure session for host %s", host)
                raise

        try:
            yield client
        finally:
            # Intentionally do not close the client here. Clients are reused.
            pass

    async def close_all(self) -> None:
        clients = list(self._clients.items())
        for host, client in clients:
            try:
                # Prefer logout to inform server, fall back to close
                await client.logout()
            except Exception:
                try:
                    await client.close()
                except Exception:
                    logger.exception("failed to close client for host %s", host)
