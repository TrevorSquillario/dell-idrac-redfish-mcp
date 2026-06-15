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
from utils.logging_config import configure_logging

# Configure logging early so Docker/stdout captures logs consistently
configure_logging()
logger = logging.getLogger("idrac_redfish_mcp")

mcp = FastMCP("iDRAC Redfish MCP")

IDRAC_USERNAME = os.getenv("IDRAC_USERNAME")
IDRAC_PASSWORD = os.getenv("IDRAC_PASSWORD")
_env_verify = os.getenv("IDRAC_SSL_VERIFY")
if _env_verify is None:
    DEFAULT_IDRAC_SSL_VERIFY = False
else:
    DEFAULT_IDRAC_SSL_VERIFY = _env_verify.lower() in ("1", "true", "yes", "on")

# Fail fast if required credentials are not provided
if not IDRAC_USERNAME or not IDRAC_PASSWORD:
    logger.error("IDRAC_USERNAME and IDRAC_PASSWORD environment variables must be set")
    raise SystemExit("IDRAC_USERNAME and IDRAC_PASSWORD environment variables must be set")

session_mgr = PerHostSessionManager(IDRAC_USERNAME, IDRAC_PASSWORD, DEFAULT_IDRAC_SSL_VERIFY)
session_mgr.start_session_logger(interval=10)

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
async def get_storage_health(
    host: str,
    port: int = 443,
    verify: bool = DEFAULT_IDRAC_SSL_VERIFY,
) -> str:
    """
    Retrieve storage health (drive status and PredictedMediaLifeLeftPercent).
    """
    if not host:
        logger.error("missing 'host' in params")
        raise ValueError("missing 'host' in params")

    creds = {"username": IDRAC_USERNAME, "password": IDRAC_PASSWORD, "verify": verify}
    async with session_mgr.get_client(host, creds) as client:
        try:
            res = await client.health.get_storage_health()
        except Exception:
            logger.exception("failed to fetch storage health for %s", host)
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
    Mapping of physical slot locations and device FQDD occupying the slot.

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
async def get_pciedevice_info(
    host: str,
    port: int = 443,
    verify: bool = DEFAULT_IDRAC_SSL_VERIFY,
) -> str:
    """
    Retrieve PCIe device inventory for the chassis and return a concise list.

    Calls: /redfish/v1/Chassis/System.Embedded.1/PCIeDevices and expands each member.
    """
    if not host:
        logger.error("missing 'host' in params")
        raise ValueError("missing 'host' in params")

    creds = {"username": IDRAC_USERNAME, "password": IDRAC_PASSWORD, "verify": verify}
    async with session_mgr.get_client(host, creds) as client:
        try:
            res = await client.inventory.get_pciedevice_info()
        except Exception:
            logger.exception("failed to fetch PCIe device info for %s", host)
            raise

    return json.dumps(res, default=str)

@mcp.tool
async def get_chassis_info(
    host: str,
    port: int = 443,
    verify: bool = DEFAULT_IDRAC_SSL_VERIFY,
    select: Optional[str] = None,
) -> str:
    """
    Parameters:
    select: Optional comma-separated list of top-level fields to include in the output. Translates to odata $select query parameter. 

    Description:
    Retrieve the Redfish Chassis resource at /redfish/v1/Chassis/System.Embedded.1

    #### Hardware Identity & Telemetry Status
    * **Inventory Details:** Manufacturer (Dell), Model (e.g., R6615), Serial Number, SKU, and Part Number.
    * **Physical Security:** Chassis intrusion sensor states (e.g., `Normal` or tripped).

    #### Exact Physical Location
    * **Datacenter Coordinates:** Returns the precise physical deployment mapping, including the Data Center name, Room/Lab, Aisle row, Rack identifier, and exact Rack unit slot height (EIA_310 offset).

    #### Complete Component Topology (Resource Maps)
    Rather than raw performance metrics, this tool maps out the architecture and inventory counts of what the chassis physically contains, providing API routing endpoints (`@odata.id`) for:
    * **Power & Cooling:** Locations and counts of all installed Power Supplies and Chassis Fans (e.g., 16 fan units).
    * **Storage Infrastructure:** Links to installed Storage Controllers, BOSS cards, and direct-attached physical drives.
    * **Compute & I/O Expansion:** Network adapters, Memory arrays, CPU sockets, and the exact count/addresses of all connected PCIe devices (e.g., 27 discrete PCIe endpoints).
    """
    if not host:
        logger.error("missing 'host' in params")
        raise ValueError("missing 'host' in params")

    creds = {"username": IDRAC_USERNAME, "password": IDRAC_PASSWORD, "verify": verify}
    async with session_mgr.get_client(host, creds) as client:
        try:
            res = await client.get_redfish_uri('/redfish/v1/Chassis/System.Embedded.1')
        except Exception:
            logger.exception("failed to fetch chassis info for %s", host)
            raise

    return json.dumps(res, default=str)

@mcp.tool
async def get_firmware_inventory(
    host: str,
    port: int = 443,
    verify: bool = DEFAULT_IDRAC_SSL_VERIFY,
) -> str:
    """
    Retrieve FirmwareInventory members for the target iDRAC.

    Calls: /redfish/v1/UpdateService/FirmwareInventory?$expand=*($levels=1)
    Returns a JSON list of firmware inventory member objects.
    """
    if not host:
        logger.error("missing 'host' in params")
        raise ValueError("missing 'host' in params")

    creds = {"username": IDRAC_USERNAME, "password": IDRAC_PASSWORD, "verify": verify}
    async with session_mgr.get_client(host, creds) as client:
        try:
            res = await client.inventory.get_firmware_inventory()
        except Exception:
            logger.exception("failed to fetch firmware inventory for %s", host)
            raise

    return json.dumps(res, default=str)

@mcp.tool
async def get_power_usage(
    host: str,
    port: int = 443,
    verify: bool = DEFAULT_IDRAC_SSL_VERIFY,
) -> str:
    """
    Retrieve the PowerControl collection for the chassis. Includes power cap/limits and power consumption readings.
    
    Calls: /redfish/v1/Chassis/System.Embedded.1/Power/PowerControl
    """
    if not host:
        logger.error("missing 'host' in params")
        raise ValueError("missing 'host' in params")

    creds = {"username": IDRAC_USERNAME, "password": IDRAC_PASSWORD, "verify": verify}
    async with session_mgr.get_client(host, creds) as client:
        try:
            res = await client.get_redfish_uri('/redfish/v1/Chassis/System.Embedded.1/Power/PowerControl')
        except Exception:
            logger.exception("failed to fetch power usage for %s", host)
            raise

    return json.dumps(res, default=str)


@mcp.tool
async def get_system_info(
    host: str,
    port: int = 443,
    verify: bool = DEFAULT_IDRAC_SSL_VERIFY,
    select: Optional[str] = None,
) -> str:
    """
    Parameters:
    select: Optional comma-separated list of top-level fields to include in the output. Translates to odata $select query parameter. 

    Description:
    Retrieve the Redfish System resource at /redfish/v1/Systems/System.Embedded.1

    #### Core Compute & Memory Allocations
    * **Processor Architecture:** Returns full hardware context for the execution engine, including socket population (1 CPU), core density (16 physical cores, multithreading disabled), and the exact silicon model (`AMD EPYC 9124 16-Core Processor`).
    * **Memory Resources:** Summarizes active memory topologies, indicating the aggregate payload volume (`192 GiB`), multi-bit ECC error correction validation, and physical slot configuration (all 12 DIMM slots fully populated).

    #### Live Boot State & Environment Tracing
    * **Boot Order & Targets:** Exposes the permanent hardware sequence (`UEFI` baseline, active order list), custom temporary bypass override configurations (`Pxe`, `Hdd`, `BiosSetup`, `UefiHttp`), and security boundaries (`SecureBoot` profiles).

    #### Low-Level I/O & Bus Interconnect Maps
    * **Peripheral Architecture:** Returns structured maps detailing hardware expansion capacities: maximum slot limits (3 PCIe slots), active profiles of all interconnected devices (28 elements)
    * **Trusted Security Infrastructure:** Verifies local identity and cryptographic integrity components, validating type (`TPM2_0`), running firmware levels (`7.2.2.0`), and current initialization status (`Enabled`).
    """
    if not host:
        logger.error("missing 'host' in params")
        raise ValueError("missing 'host' in params")

    creds = {"username": IDRAC_USERNAME, "password": IDRAC_PASSWORD, "verify": verify}
    async with session_mgr.get_client(host, creds) as client:
        try:
            res = await client.get_redfish_uri('/redfish/v1/Systems/System.Embedded.1', select=select)
        except Exception:
            logger.exception("failed to fetch system info for %s", host)
            raise

    return json.dumps(res, default=str)


@mcp.tool
async def get_metric_report_definitions(
    host: str,
    report_name: Optional[str] = None,
    port: int = 443,
    verify: bool = DEFAULT_IDRAC_SSL_VERIFY,
) -> str:
    """
    Retrieve metric report's available or the metrics for a specific report.

    Calls: /redfish/v1/TelemetryService/MetricReportDefinitions[/{report}]

    Returns: 
    If `report_name` is provided it will return a list of the metrics in a report instead. 
    If not it will return a list of available metric reports.
    """
    if not host:
        logger.error("missing 'host' in params")
        raise ValueError("missing 'host' in params")

    creds = {"username": IDRAC_USERNAME, "password": IDRAC_PASSWORD, "verify": verify}
    async with session_mgr.get_client(host, creds) as client:
        try:
            res_members = await client.telemetry.get_metric_report_definitions(report_name=report_name)
        except Exception:
            logger.exception("failed to fetch metric report definitions for %s", host)
            raise
    return json.dumps(res_members, default=str)


@mcp.tool
async def get_metric_report_readings(
    host: str,
    report_name: str,
    port: int = 443,
    verify: bool = DEFAULT_IDRAC_SSL_VERIFY,
) -> str:
    """
    Retrieve MetricReport readings and return latest values per MetricId/ContextID.

    """
    if not host:
        logger.error("missing 'host' in params")
        raise ValueError("missing 'host' in params")
    if not report_name:
        logger.error("missing 'report_name' in params")
        raise ValueError("missing 'report_name' in params")

    creds = {"username": IDRAC_USERNAME, "password": IDRAC_PASSWORD, "verify": verify}
    async with session_mgr.get_client(host, creds) as client:
        try:
            res = await client.telemetry.get_metric_report_readings(report_name=report_name)
        except Exception:
            logger.exception("failed to fetch metric report readings for %s", host)
            raise
    return json.dumps(res, default=str)

@mcp.tool
async def get_storage_controller_info(
    host: str,
    port: int = 443,
    verify: bool = DEFAULT_IDRAC_SSL_VERIFY,
    controller: Optional[str] = None,
    select: Optional[str] = None,
) -> str:
    """
    Retrieve storage controllers listing or a specific controller's info.

    Parameters:
    select: Optional comma-separated list of top-level fields to include in the output. Translates to odata $select query parameter. 

    If `controller` is None, returns the storage collection at
    `/redfish/v1/Systems/System.Embedded.1/Storage` which lists controller links.
    If `controller` is provided, returns the specific controller resource at
    `/redfish/v1/Systems/System.Embedded.1/Storage/{controller}`.
    """
    if not host:
        logger.error("missing 'host' in params")
        raise ValueError("missing 'host' in params")

    creds = {"username": IDRAC_USERNAME, "password": IDRAC_PASSWORD, "verify": verify}
    async with session_mgr.get_client(host, creds) as client:
        try:
            if controller:
                path = f"/redfish/v1/Systems/System.Embedded.1/Storage/{controller}"
            else:
                path = "/redfish/v1/Systems/System.Embedded.1/Storage"
            res = await client.get_redfish_uri(path, select=select)
        except Exception:
            logger.exception("failed to fetch storage info for %s (controller=%s)", host, controller)
            raise

    return json.dumps(res, default=str)


@mcp.tool
async def get_bios_attributes(
    host: str,
    attributes: str,
    port: int = 443,
    verify: bool = DEFAULT_IDRAC_SSL_VERIFY,
) -> str:
    """
    Retrieve BIOS attribute(s) by name from the target iDRAC.

    Args:
        host: iDRAC hostname or IP.
        attributes: Comma-separated BIOS attribute name(s) to retrieve (required).
        port: HTTPS port (default 443).
        verify: Whether to verify SSL certs.
    """
    if not host:
        logger.error("missing 'host' in params")
        raise ValueError("missing 'host' in params")
    if not attributes:
        logger.error("missing 'attributes' in params")
        raise ValueError("missing 'attributes' in params")

    creds = {"username": IDRAC_USERNAME, "password": IDRAC_PASSWORD, "verify": verify}
    async with session_mgr.get_client(host, creds) as client:
        try:
            res = await client.config.get_bios_attributes(attributes=attributes)
        except Exception:
            logger.exception("failed to fetch BIOS attributes for %s (attributes=%s)", host, attributes)
            raise

    return json.dumps(res, default=str)


@mcp.tool
async def get_idrac_attributes(
    host: str,
    attributes: str,
    group: str = "idrac",
    port: int = 443,
    verify: bool = DEFAULT_IDRAC_SSL_VERIFY,
) -> str:
    """
    Retrieve Dell iDRAC configuration attribute(s) for a given group.

    Args:
        host: iDRAC hostname or IP.
        attributes: Comma-separated attribute name(s) to retrieve (required).
        group: one of "idrac", "lc", or "system" (default "idrac").
        port: HTTPS port (default 443).
        verify: Whether to verify SSL certs.
    """
    if not host:
        logger.error("missing 'host' in params")
        raise ValueError("missing 'host' in params")
    if not attributes:
        logger.error("missing 'attributes' in params")
        raise ValueError("missing 'attributes' in params")

    creds = {"username": IDRAC_USERNAME, "password": IDRAC_PASSWORD, "verify": verify}
    async with session_mgr.get_client(host, creds) as client:
        try:
            res = await client.config.get_idrac_attributes(group=group, attributes=attributes)
        except Exception:
            logger.exception("failed to fetch iDRAC attributes for %s (group=%s attributes=%s)", host, group, attributes)
            raise

    return json.dumps(res, default=str)


@mcp.tool
async def search_bios_attributes(
    host: str,
    term: str,
    port: int = 443,
    verify: bool = DEFAULT_IDRAC_SSL_VERIFY,
) -> str:
    """
    Search BIOS attributes for a matching name or value.

    Args:
        host: iDRAC hostname or IP.
        term: Search term to match against attribute names or values (required).
        port: HTTPS port (default 443).
        verify: Whether to verify SSL certs.
    """
    if not host:
        logger.error("missing 'host' in params")
        raise ValueError("missing 'host' in params")
    if not term:
        logger.error("missing 'term' in params")
        raise ValueError("missing 'term' in params")

    creds = {"username": IDRAC_USERNAME, "password": IDRAC_PASSWORD, "verify": verify}
    async with session_mgr.get_client(host, creds) as client:
        try:
            res = await client.config.search_bios_attributes(term=term)
        except Exception:
            logger.exception("failed to search BIOS attributes for %s (term=%s)", host, term)
            raise

    return json.dumps(res, default=str)


@mcp.tool
async def search_idrac_attributes(
    host: str,
    term: str,
    group: str = "idrac",
    port: int = 443,
    verify: bool = DEFAULT_IDRAC_SSL_VERIFY,
) -> str:
    """
    Search iDRAC attributes for a matching name or value within a group.

    Args:
        host: iDRAC hostname or IP.
        term: Search term to match against attribute names or values (required).
        group: one of "idrac", "lc", or "system" (default "idrac").
        port: HTTPS port (default 443).
        verify: Whether to verify SSL certs.
    """
    if not host:
        logger.error("missing 'host' in params")
        raise ValueError("missing 'host' in params")
    if not term:
        logger.error("missing 'term' in params")
        raise ValueError("missing 'term' in params")

    creds = {"username": IDRAC_USERNAME, "password": IDRAC_PASSWORD, "verify": verify}
    async with session_mgr.get_client(host, creds) as client:
        try:
            res = await client.config.search_idrac_attributes(term=term, group=group)
        except Exception:
            logger.exception("failed to search iDRAC attributes for %s (group=%s term=%s)", host, group, term)
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


@mcp.tool
async def get_redfish_uri(
    host: str,
    path: str,
    select: Optional[str] = None,
    port: int = 443,
    verify: bool = DEFAULT_IDRAC_SSL_VERIFY,
) -> str:
    """
    Generic pass-through to fetch any Redfish URI from the target iDRAC and
    return the payload as-is.
    """
    if not host:
        logger.error("missing 'host' in params")
        raise ValueError("missing 'host' in params")
    if not path:
        logger.error("missing 'path' in params")
        raise ValueError("missing 'path' in params")

    creds = {"username": IDRAC_USERNAME, "password": IDRAC_PASSWORD, "verify": verify}
    async with session_mgr.get_client(host, creds) as client:
        try:
            res = await client.get_redfish_uri(path, select=select)
        except Exception:
            logger.exception("failed to fetch %s from %s", path, host)
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