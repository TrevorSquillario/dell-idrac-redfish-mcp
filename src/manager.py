from typing import Any, Dict, List, Optional
import asyncio
import logging
from fastmcp import FastMCP
from fastmcp.utilities.types import Image
from starlette.responses import JSONResponse
from contextlib import asynccontextmanager

from idrac_async_redfish_client.client import iDRACAsyncRedfishClient
logger = logging.getLogger("idrac_redfish_mcp")

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
        # Background session logger task
        self._logger_task: Optional[asyncio.Task] = None
        self._logger_stop: asyncio.Event = asyncio.Event()

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
        # Stop background logger first to avoid racing with client shutdown
        try:
            await self.stop_session_logger()
        except Exception:
            logger.exception("failed to stop session logger")

        clients = list(self._clients.items())
        logger.info("closing %d clients for hosts: %s", len(clients), [host for host, _ in clients])
        for host, client in clients:
            try:
                # Prefer logout to inform server, fall back to close
                await client.logout()
            except Exception:
                try:
                    await client.close()
                except Exception:
                    logger.exception("failed to close client for host %s", host)

    def start_session_logger(self, interval: int = 60) -> None:
        """Start an ongoing background task that logs session counts per-host.

        This is safe to call multiple times; it will no-op if a task is already running.
        """
        if self._logger_task and not self._logger_task.done():
            return
        # Reset stop event
        try:
            self._logger_stop.clear()
        except Exception:
            self._logger_stop = asyncio.Event()

        loop = asyncio.get_event_loop()
        self._logger_task = loop.create_task(self._session_logger_loop(interval))

    async def stop_session_logger(self) -> None:
        """Signal the background logger to stop and await its completion."""
        if not self._logger_task:
            return
        self._logger_stop.set()
        try:
            await self._logger_task
        except Exception:
            logger.exception("error while stopping session logger")
        finally:
            self._logger_task = None

    async def _session_logger_loop(self, interval: int) -> None:
        """Periodic loop that logs overall and per-host session information."""
        logger.info("session logger started (interval=%s seconds)", interval)
        try:
            while not self._logger_stop.is_set():
                try:
                    total_hosts = len(self._clients)
                    valid_sessions = sum(1 for c in self._clients.values() if c.token_valid())
                    logger.info("session counts: total_hosts=%d valid_sessions=%d", total_hosts, valid_sessions)

                    for host, client in list(self._clients.items()):
                        try:
                            has_session = bool(getattr(client, "_session_id", None) or getattr(client, "_session_uri", None))
                            logger.debug("host %s: has_session=%s token_valid=%s", host, has_session, client.token_valid())
                        except Exception:
                            logger.exception("error checking session for host %s", host)

                    await asyncio.sleep(interval)
                except asyncio.CancelledError:
                    break
                except Exception:
                    logger.exception("unexpected error in session logger loop")
                    # Sleep briefly to avoid tight error loops
                    await asyncio.sleep(max(1, interval))
        finally:
            logger.info("session logger stopped")
