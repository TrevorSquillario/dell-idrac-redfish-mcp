from typing import Any, Dict, List, Optional
import os
import sys
import json
import logging
import base64
import asyncio
import atexit
from fastmcp import FastMCP
from fastmcp.utilities.types import Image
from starlette.responses import JSONResponse

from manager import PerHostSessionManager
#from utils.logging_config import configure_logging

#configure_logging()
logger = logging.getLogger("idrac_redfish_mcp")

mcp = FastMCP("iDRAC Redfish MCP")

IDRAC_USERNAME = os.getenv("IDRAC_USERNAME")
IDRAC_PASSWORD = os.getenv("IDRAC_PASSWORD")
_env_verify = os.getenv("IDRAC_SSL_VERIFY")
if _env_verify is None:
    DEFAULT_IDRAC_SSL_VERIFY = False
else:
    DEFAULT_IDRAC_SSL_VERIFY = _env_verify.lower() in ("1", "true", "yes", "on")


session_mgr = PerHostSessionManager(IDRAC_USERNAME, IDRAC_PASSWORD, DEFAULT_IDRAC_SSL_VERIFY)

def _close_sessions_at_exit():
    try:
        asyncio.run(session_mgr.close_all())
    except Exception:
        logger.exception("error while closing cached Redfish sessions at exit")

atexit.register(_close_sessions_at_exit)

@mcp.tool
async def get_error_and_event_registry(
    message_id: Optional[str],
    host: str,
    port: int = 443,
    verify: bool = DEFAULT_IDRAC_SSL_VERIFY,
) -> str:
    """
    Retrieve the iDRAC Message Registry (EEMI) mapping or specific message entries.

    This will first attempt to load the bundled `files/eemi.json` registry shipped
    with this package. If that file is present and valid, its `Messages` mapping
    (or the specific entries for `message_ids`) will be returned. If not present
    or loading fails, the code falls back to querying the target iDRAC via Redfish.

    Args:
        message_ids: List of message ID strings to retrieve (e.g. ['CPU0001']).
        host: The IP address or hostname of the iDRAC.
        port: Optional HTTPS port for the Redfish API (default 443).
        verify: Optional Whether to verify SSL certificates when contacting iDRAC.
        username: Optional iDRAC username for basic authentication.
        password: Optional iDRAC password for basic authentication.
    """
    if not host:
        logger.error("missing 'host' in params")
        raise ValueError("missing 'host' in params")

    # First attempt to load bundled registry file if present
    try:
        base = os.path.dirname(__file__)
        eemi_path = os.path.join(base, "files", "eemi.json")
        if os.path.exists(eemi_path):
            with open(eemi_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            messages = data.get("Messages") or {}
            if message_id:
                return json.dumps(messages.get(message_id))
            return json.dumps(messages)
    except Exception:
        logger.debug("failed to load bundled eemi.json, falling back to iDRAC", exc_info=True)

    creds = {"username": IDRAC_USERNAME, "password": IDRAC_PASSWORD, "verify": verify}
    async with session_mgr.get_client(host, creds) as client:
        # delegate to the config service
        res = await client.config.get_error_and_event_registry(message_id)
    return json.dumps(res, default=str)

@mcp.tool
async def get_lc_logs(
    host: str,
    port: int = 443,
    verify: bool = DEFAULT_IDRAC_SSL_VERIFY,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    severity: Optional[str] = None,
    top: Optional[int] = 10,
    skip: Optional[int] = None,
) -> str:
    """
    Retrieve iDRAC lifecycle (LC) logs from a Dell server.

    Args:
        host: The IP address or hostname of the iDRAC.
        port: The HTTPS port for the Redfish API (default 443).
        verify: Whether to verify SSL certificates.
        username: iDRAC username for basic authentication.
        password: iDRAC password for basic authentication.
        start_date: Start filter in this format: YYYY-MM-DDTHH:MM:SS-offset (example: 2023-03-14T10:10:10-05:00)
        end_date: End filter in this format: YYYY-MM-DDTHH:MM:SS-offset (example: 2023-03-14T10:10:10-05:00)
        severity: Filter logs by severity, options include: informational, warning and critical
        top: Optional integer to limit returned entries (maps to $top)
        skip: Optional integer to skip initial entries (maps to $skip)
    """
    if not host:
        logger.error("missing 'host' in params")
        raise ValueError("missing 'host' in params")

    creds = {"username": IDRAC_USERNAME, "password": IDRAC_PASSWORD, "verify": verify}
    async with session_mgr.get_client(host, creds) as client:
        logs = await client.logs.get_lifecycle_logs(
            start_date=start_date,
            end_date=end_date,
            severity=severity,
            top=top,
            skip=skip,
        )
    return json.dumps(logs)


@mcp.tool
async def get_idrac_attributes(
    host: str,
    port: int = 443,
    verify: bool = DEFAULT_IDRAC_SSL_VERIFY,
) -> str:
    """
    Retrieve iDRAC configuration attributes.

    Args:
        host: iDRAC hostname or IP.
        port: HTTPS port (default 443).
        verify: Whether to verify SSL certs.
        username: iDRAC username.
        password: iDRAC password.

    Returns:
        JSON string containing the attributes mapping.
    """
    if not host:
        logger.error("missing 'host' in params")
        raise ValueError("missing 'host' in params")

    creds = {"username": IDRAC_USERNAME, "password": IDRAC_PASSWORD, "verify": verify}
    async with session_mgr.get_client(host, creds) as client:
        try:
            resp = await client.config.get_idrac_attributes()
        except Exception:
            logger.exception("failed to fetch iDRAC attributes for %s", host)
            raise

    return json.dumps(resp, default=str)


@mcp.tool
async def get_device_rollup_health_status(
    host: str,
    device_filter: str = "all",
    port: int = 443,
    verify: bool = DEFAULT_IDRAC_SSL_VERIFY,
) -> str:
    """
    Get Dell rollup health status entries filtered by `device_filter`.

    Args:
        host: iDRAC hostname or IP.
        device_filter: "all" or comma-separated substrings to match against SubSystem.
        port: HTTPS port (default 443).
        verify: Whether to verify SSL certs.
        username: iDRAC username.
        password: iDRAC password.

    Returns:
        JSON string list of matched rollup members.
    """
    if not host:
        logger.error("missing 'host' in params")
        raise ValueError("missing 'host' in params")

    creds = {"username": IDRAC_USERNAME, "password": IDRAC_PASSWORD, "verify": verify}
    async with session_mgr.get_client(host, creds) as client:
        try:
            res = await client.health.get_device_rollup_health_status(device_filter=device_filter)
        except Exception:
            logger.exception("failed to fetch rollup health status for %s", host)
            raise

    return json.dumps(res, default=str)


@mcp.tool
async def get_memory_processor_health_information(
    host: str,
    device_name: str,
    port: int = 443,
    verify: bool = DEFAULT_IDRAC_SSL_VERIFY,
) -> str:
    """
    For a given `device_name` collection, return mapping of member -> Health value.

    Args:
        host: iDRAC hostname or IP.
        device_name: The device collection name under `/Systems/...` (e.g. "Memory", "Processors").
    """
    if not host:
        logger.error("missing 'host' in params")
        raise ValueError("missing 'host' in params")
    if not device_name:
        logger.error("missing 'device_name' in params")
        raise ValueError("missing 'device_name' in params")

    url = host

    creds = {"username": IDRAC_USERNAME, "password": IDRAC_PASSWORD, "verify": verify}
    async with session_mgr.get_client(url, creds) as client:
        try:
            res = await client.health.get_memory_processor_health_information(device_name=device_name)
        except Exception:
            logger.exception("failed to fetch health information for %s %s", host, device_name)
            raise

    return json.dumps(res, default=str)


@mcp.tool
async def get_server_slot_info(
    host: str,
    slot_type: Optional[str] = None,
    port: int = 443,
    verify: bool = DEFAULT_IDRAC_SSL_VERIFY,
) -> str:
    """
    Retrieve Dell server slot information (DellSlots collection).

    Args:
        host: iDRAC hostname or IP.
        slot_type: Optional filter by ConnectorLayout (single or comma-separated).

    Returns:
        JSON list of slot member objects (possibly filtered).
    """
    if not host:
        logger.error("missing 'host' in params")
        raise ValueError("missing 'host' in params")

    creds = {"username": IDRAC_USERNAME, "password": IDRAC_PASSWORD, "verify": verify}
    async with session_mgr.get_client(host, creds) as client:
        try:
            res = await client.inventory.get_server_slot_info(slot_type=slot_type)
        except Exception:
            logger.exception("failed to fetch server slot info for %s", host)
            raise

    return json.dumps(res, default=str)


@mcp.tool
async def export_server_screen_shot(
    host: str,
    filetype: int = 2,
    port: int = 443,
    verify: bool = DEFAULT_IDRAC_SSL_VERIFY,
) -> Image:
    """
    Trigger a Dell LC action to export a server screenshot and return it as base64.

    Args:
        host: iDRAC hostname or IP.
        filetype: 0=LastCrashScreenShot, 1=Preview, 2=ServerScreenShot (default 2).

    Returns:
        ImageContent bytes
    """
    if not host:
        logger.error("missing 'host' in params")
        raise ValueError("missing 'host' in params")

    creds = {"username": IDRAC_USERNAME, "password": IDRAC_PASSWORD, "verify": verify}
    async with session_mgr.get_client(host, creds) as client:
        try:
            img_path = await client.media.export_server_screen_shot(filetype=filetype)
        except Exception:
            logger.exception("failed to export server screenshot for %s", host)
            raise

    return Image(path=img_path, format="png")


@mcp.tool
async def support_assist_collection(
    host: str,
    filter_val: Optional[str] = None,
    data: Optional[str] = None,
    port: int = 443,
    verify: bool = DEFAULT_IDRAC_SSL_VERIFY,
) -> str:
    """
    Start a SupportAssist collection via the iDRAC Support service.

    Args:
        host: iDRAC hostname or IP.
        filter_val: "0" for No, "1" for Yes.
        data: Comma-separated list of data selectors (0..5).
        port: HTTPS port (default 443).
        verify: Whether to verify SSL certs.

    Returns:
        JSON string of the job result or path to sacollect.zip.
    """
    if not host:
        logger.error("missing 'host' in params")
        raise ValueError("missing 'host' in params")

    creds = {"username": IDRAC_USERNAME, "password": IDRAC_PASSWORD, "verify": verify}
    async with session_mgr.get_client(host, creds) as client:
        try:
            res = await client.support.support_assist_collection(filter_val=filter_val, data=data)
        except Exception:
            logger.exception("failed to start SupportAssist collection for %s", host)
            raise

    return json.dumps(res, default=str)


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request):
    return JSONResponse({"status": "ok"})

if __name__ == "__main__":
    # Choose transport mode from environment: "http" (default) or "stdio".
    TRANSPORT_MODE = os.getenv("IDRAC_MCP_TRANSPORT_MODE", "stdio").lower()
    logger.info("starting MCP with TRANSPORT_MODE=%s", TRANSPORT_MODE)
    if TRANSPORT_MODE == "stdio":
        # Run over stdio (useful for running as a direct process)
        mcp.run(transport="stdio")
    else:
        # Default: run over HTTP so the container keeps running and listens on port 8080.
        mcp.run(transport="http", host="0.0.0.0", port=8080)