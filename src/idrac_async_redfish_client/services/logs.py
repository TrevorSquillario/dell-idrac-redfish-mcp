from typing import Any, Dict, List, Optional
import logging
from idrac_async_redfish_client.services.base import BaseService

logger = logging.getLogger(__name__)

class LogService(BaseService):
    async def get_lifecycle_logs(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        severity: Optional[str] = None,
        top: Optional[int] = 10,
        skip: Optional[int] = None,
    ) -> List[Dict[str, Any]]:

        # default LC log entries resource
        uri = "/redfish/v1/Managers/iDRAC.Embedded.1/LogServices/Lclog/Entries"

        # build filters: support date range (start/end optional) and optional severity filter
        filters: List[str] = []
        if start_date or end_date:
            date_parts: List[str] = []
            if start_date:
                date_parts.append(f"Created ge '{start_date}'")
            if end_date:
                date_parts.append(f"Created le '{end_date}'")
            if date_parts:
                filters.append(' and '.join(date_parts))

        # map predefined severity options to the server's Severity values
        target_severity: Optional[str] = None
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
            target_severity = allowed[sev]

        # build query parameters (filter, $top, $skip) and pass as params
        params: Dict[str, Any] = {}
        if filters:
            params["$filter"] = ' and '.join(filters)

        # validate and append top/skip if provided
        if top is not None:
            try:
                top_i = int(top)
                if top_i < 0:
                    raise ValueError("$top must be non-negative")
            except Exception:
                raise ValueError("invalid $top value")

        if skip is not None:
            try:
                skip_i = int(skip)
                if skip_i < 0:
                    raise ValueError("$skip must be non-negative")
            except Exception:
                raise ValueError("invalid $skip value")
            params["$skip"] = str(skip_i)

        collected: List[Dict[str, Any]] = []

        # initial request (pass params so httpx will URL-encode them)
        try:
            logger.info(f"Executing Redfish URI: %s params=%s", uri, params)
            resp = await self.client.get(uri, params=params)
        except Exception:
            logger.exception("request failed for %s params=%s", uri, params)
            raise

        try:
            data = resp.json()
        except Exception:
            logger.exception("invalid json response from %s params=%s", uri, params)
            raise ValueError("invalid json response")

        if resp.status_code == 401:
            logger.warning("unauthorized access to %s params=%s (401)", uri, params)
            raise PermissionError("unauthorized")
        if resp.status_code != 200:
            logger.error("request failed %s params=%s status=%s body=%s", uri, params, resp.status_code, data)
            raise RuntimeError(f"request failed status={resp.status_code}")

        if "Members" not in data:
            logger.error("no 'Members' key in response from %s params=%s", uri, params)
            raise RuntimeError("no 'Members' key in response")

        if data.get("Members") == []:
            logger.info("no LC logs in date range or resource for %s params=%s", uri, params)
            return []

        collected.extend(data.get("Members", []))

        # paginate
        next_link = data.get("Members@odata.nextLink")
        while next_link:
            try:
                resp = await self.client.get(next_link)
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

        # If server-side filtering failed to apply, perform client-side filter
        if target_severity:
            ts_lower = target_severity.lower()
            filtered = []
            for e in collected:
                sev_val = (e.get("Severity") or e.get("severity") or "").lower()
                if sev_val == ts_lower:
                    filtered.append(e)
            logger.info("filtered %d -> %d LC log entries for severity=%s", len(collected), len(filtered), target_severity)
            return filtered

        logger.info("collected %d LC log entries for %s", len(collected), next_link)
        return collected
