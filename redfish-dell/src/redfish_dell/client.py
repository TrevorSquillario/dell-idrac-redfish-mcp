import logging
from typing import Any, Dict, List, Optional

from redfish import redfish_client
from .logging_config import configure_logging

configure_logging()
logger = logging.getLogger("DellRedfishClient")

class DellRedfishClient:
    def __init__(self, base_url, username, password, **kwargs):
        # 1. Initialize the official DMTF client
        self._standard_client = redfish_client(
            base_url=base_url, 
            username=username, 
            password=password, 
            **kwargs
        )
        self._standard_client.login()

    # --- REDFISH HELPER METHODS ---

    # --- DELL SPECIFIC ENDPOINTS ---
    
    def get_idrac_attributes(self):
        """Dell-specific: Get iDRAC configuration attributes."""
        return self._standard_self._standard_client.get("/redfish/v1/Managers/iDRAC.Embedded.1/Attributes")

    def get_lifecycle_logs(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        severity: Optional[str] = None,
    ) -> str:

        # default LC log entries resource
        uri = "/redfish/v1/Managers/iDRAC.Embedded.1/LogServices/Lclog/Entries"

        # build filters: support date range and optional severity filter
        filters: List[str] = []
        if start_date and end_date:
            filters.append(f"Created ge '{start_date}' and Created le '{end_date}'")

        # map predefined severity options to the server's Severity values
        if severity:
            sev = severity.lower()
            allowed = {
                "informational": "OK",
                "critical": "Critical",
                "warning": "Warning",
            }
            if sev not in allowed:
                raise ValueError(f"invalid severity '{severity}', valid options: {list(allowed.keys())}")
            filters.append(f"Severity eq '{allowed[sev]}'")

        if filters:
            query_uri = f"{uri}?$filter={' and '.join(filters)}"
        else:
            query_uri = uri

        collected: List[Dict[str, Any]] = []

        # initial request
        try:
            logger.info(f"Executing Redfish URI: {query_uri}")
            resp = self._standard_client.get(query_uri)
        except Exception:
            logger.exception("request failed for %s", query_uri)
            raise

        try:
            data = resp.dict
        except Exception:
            logger.exception("invalid json response from %s", query_uri)
            raise ValueError("invalid json response")

        if resp.status == 401:
            logger.warning("unauthorized access to %s (401)", query_uri)
            raise PermissionError("unauthorized")
        if resp.status != 200:
            logger.error("request failed %s status=%s body=%s", query_uri, resp.status, data)
            raise RuntimeError(f"request failed status={resp.status}")

        if "Members" not in data:
            logger.error("no 'Members' key in response from %s", query_uri)
            raise RuntimeError("no 'Members' key in response")

        if data.get("Members") == []:
            logger.info("no LC logs in date range or resource for %s", query_uri)
            return json.dumps([])

        collected.extend(data.get("Members", []))

        # paginate
        next_link = data.get("Members@odata.nextLink")
        while next_link:
            try:
                resp = self._standard_client.get(next_link)
            except Exception:
                logger.exception("failed following nextLink: %s", next_link)
                break
            if resp.status != 200:
                logger.error("nextLink returned status %s for %s", resp.status, next_link)
                break
            try:
                data = resp.dict
            except Exception:
                logger.exception("invalid json on nextLink %s", next_link)
                break
            if "Members" not in data or data.get("Members") == []:
                break
            collected.extend(data.get("Members", []))
            next_link = data.get("Members@odata.nextLink")

        logger.info("collected %d LC log entries for %s", len(collected), next_link)
        return collected

    # --- PROXY METHOD ---
    
    def __getattr__(self, name):
        """
        Redirect any method calls not defined here (like .get, .patch, .post)
        to the official DMTF client.
        """
        return getattr(self._standard_client, name)