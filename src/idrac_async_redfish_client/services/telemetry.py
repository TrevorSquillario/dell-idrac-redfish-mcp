from typing import Any, Dict
import logging
from idrac_async_redfish_client.services.base import BaseService
from typing import Optional, List
import json

logger = logging.getLogger("idrac_redfish_mcp")

class TelemetryService(BaseService):
    async def get_metric_report_definitions(self, report_name: Optional[str] = None) -> List[Any]:
        """Return MetricReportDefinitions members as list of objects with '@odata.id' and short 'name'.

        Queries: /redfish/v1/TelemetryService/MetricReportDefinitions[/{report}]
        """
        base = "/redfish/v1/TelemetryService/MetricReportDefinitions"
        path = f"{base}/{report_name}" if report_name else base
        logger.info("requesting metric report definitions %s", path)

        # Use client's helper to fetch and parse JSON where possible
        res = await self.client.get_redfish_uri(path)

        data = res
        if isinstance(res, str):
            try:
                data = json.loads(res)
            except Exception:
                data = {}

        # If a specific report was requested, return list of MetricIds
        if report_name:
            # Accept 'Metrics' key in a case-insensitive way and tolerate
            # non-dict metric entries (strings or simple ids).
            metrics = data.get("Metrics") or []

            # Ensure we have a list
            if not isinstance(metrics, list):
                metrics = []

            metric_ids: List[str] = []
            for m in metrics:
                # metric entry may be a dict with 'MetricId' or a string id
                if isinstance(m, dict):
                    mid = m.get("MetricId")
                    if mid:
                        metric_ids.append(mid)
                elif isinstance(m, str):
                    metric_ids.append(m)

            return metric_ids

        # Otherwise return a simple list of member '@odata.id' strings.
        members = data.get("Members", []) if isinstance(data, dict) else []
        out: List[str] = []
        for m in members:
            odata_id = m.get("@odata.id") if isinstance(m, dict) else None
            if odata_id:
                name = odata_id.rstrip("/").split("/")[-1]
                out.append(name)

        return out
        
    async def get_metric_report_readings(self, report_name: str) -> Dict[str, Any]:
        """Fetch a MetricReport and return the latest MetricValue per MetricId+ContextID.

        Queries: /redfish/v1/TelemetryService/MetricReports/{report_name}
        Returns a dict mapping '{MetricId}_{ContextID}' -> latest MetricValue.
        """
        uri = f"/redfish/v1/TelemetryService/MetricReports/{report_name}"
        logger.info("requesting metric report %s", uri)
        resp = await self.client.get(uri)

        if resp.status_code == 401:
            logger.warning("unauthorized access to %s (401)", uri)
            raise PermissionError("unauthorized")
        if resp.status_code != 200:
            logger.error("failed to get metric report %s status=%s body=%s", uri, resp.status_code, None)
            raise RuntimeError(f"request failed status={resp.status_code}")

        try:
            data = resp.json()
        except Exception:
            logger.exception("invalid json response from %s", uri)
            raise ValueError("invalid json response")

        latest = self.get_latest_metrics(data)
        logger.info("parsed %d latest metrics from report %s", len(latest), report_name)
        return latest

    @staticmethod
    def get_latest_metrics(report_data: dict) -> dict:
        """
        Parses a Dell Redfish MetricReport to find the latest value for each metric.
        Returns a dictionary mapping '{MetricId}_{ContextID}' to its latest 'MetricValue'.
        """
        # Safely fetch MetricValues to avoid KeyErrors if the list is empty/missing
        metric_values = report_data.get("MetricValues", [])

        latest_metrics: dict[str, dict[str, dict]] = {}
        for entry in metric_values:
            try:
                metric_id = entry["MetricId"]
                context_id = entry["Oem"]["Dell"]["ContextID"]
                timestamp = entry["Timestamp"]
                value = entry["MetricValue"]

                # Ensure a container for this metric_id exists
                if metric_id not in latest_metrics:
                    latest_metrics[metric_id] = {}

                # If this context_id is new, or this entry is newer, store it
                existing = latest_metrics[metric_id].get(context_id)
                if not existing or timestamp > existing["Timestamp"]:
                    latest_metrics[metric_id][context_id] = {
                        "Timestamp": timestamp,
                        "Value": value,
                    }

            except KeyError:
                continue

        # Return a simplified mapping: {MetricId: {ContextID: Value}}
        return {metric: {ctx: info["Value"] for ctx, info in ctxs.items()} for metric, ctxs in latest_metrics.items()}
