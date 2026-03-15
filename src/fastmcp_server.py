from typing import Any, Dict, List, Optional
import os
import json
import logging
from fastmcp import FastMCP

from .utils.idrac_redfish import iDRACRedfish
from .utils.logging_config import configure_logging


configure_logging()
logger = logging.getLogger("idrac_redfish_mcp")

mcp = FastMCP("iDRAC Redfish MCP")

@mcp.tool
def get_lc_logs(
    host: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """Retrieve iDRAC lifecycle (LC) logs.

    Args:
    - host: (str) required
    - username, password: optional basic auth
    - start_date, end_date: optional strings to build $filter
    """
    if not host:
        logger.error("missing 'host' in params")
        raise ValueError("missing 'host' in params")

    # default LC log entries resource
    uri = "/Managers/iDRAC.Embedded.1/LogServices/Lclog/Entries"

    client = iDRACRedfish(host)

    # ensure a valid session when credentials are provided
    if username and password:
        try:
            client.ensure_session(username, password)
        except Exception:
            logger.exception("login failed for host %s", host)
            raise

    query_uri = uri
    if start_date and end_date:
        query_uri = f"{uri}?$filter=Created ge '{start_date}' and Created le '{end_date}'"

    collected: List[Dict[str, Any]] = []

    # initial request
    try:
        resp = client.get(query_uri)
    except Exception:
        logger.exception("request failed for %s", query_uri)
        raise

    try:
        data = resp.json()
    except Exception:
        logger.exception("invalid json response from %s", query_uri)
        raise ValueError("invalid json response")

    if resp.status_code == 401:
        logger.warning("unauthorized access to %s (401)", query_uri)
        raise PermissionError("unauthorized")
    if resp.status_code != 200:
        logger.error("request failed %s status=%s body=%s", query_uri, resp.status_code, data)
        raise RuntimeError(f"request failed status={resp.status_code}")

    if "Members" not in data:
        logger.error("no 'Members' key in response from %s", query_uri)
        raise RuntimeError("no 'Members' key in response")

    if data.get("Members") == []:
        logger.info("no LC logs in date range or resource for %s", host)
        return json.dumps([])

    collected.extend(data.get("Members", []))

    # paginate
    next_link = data.get("Members@odata.nextLink")
    while next_link:
        try:
            resp = client.get(next_link)
        except Exception:
            logger.exception("failed following nextLink: %s", next_link)
            break
        if resp.status_code != 200:
            logger.error("nextLink returned status %s for %s", resp.status_code, next_link)
            break
        try:
            data = resp.json()
        except Exception:
            logger.exception("invalid json on nextLink %s", next_link)
            break
        if "Members" not in data or data.get("Members") == []:
            break
        collected.extend(data.get("Members", []))
        next_link = data.get("Members@odata.nextLink")

    logger.info("collected %d LC log entries for %s", len(collected), host)
    return json.dumps(collected)


if __name__ == "__main__":
    mcp.run()


__all__ = ["mcp"]
