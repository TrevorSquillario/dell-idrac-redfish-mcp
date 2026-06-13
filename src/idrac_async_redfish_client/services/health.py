from typing import Any, Dict, List, Optional
import logging
from idrac_async_redfish_client.services.base import BaseService

logger = logging.getLogger(__name__)

class HealthService(BaseService):
    async def get_device_rollup_health_status(self, device_filter: str = "all") -> List[Dict[str, Any]]:
        """Return DellRollupStatus Members filtered by `device_filter`.

        `device_filter` may be "all" or a comma-separated list of substrings
        that are matched (case-insensitive) against each Member's `SubSystem`.
        """
        uri = "/redfish/v1/Systems/System.Embedded.1/Oem/Dell/DellRollupStatus"
        logger.info("requesting Dell rollup status %s", uri)
        resp = await self.client.get(uri)

        if resp.status_code == 401:
            logger.warning("unauthorized access to %s (401)", uri)
            raise PermissionError("unauthorized")
        if resp.status_code != 200:
            logger.error("failed to get rollup status %s status=%s body=%s", uri, resp.status_code, None)
            raise RuntimeError(f"request failed status={resp.status_code}")

        data = resp.json()
        members = data.get("Members", [])

        if device_filter.lower() == "all":
            if members == []:
                logger.info("no rollup status members found for %s", uri)
            return members

        wanted = [p.strip().lower() for p in device_filter.split(",") if p.strip()]
        matched: List[Dict[str, Any]] = []
        for m in members:
            sub = (m.get("SubSystem") or "").lower()
            for w in wanted:
                if w in sub:
                    matched.append(m)
                    break

        if not matched:
            logger.warning("no supported device(s) detected for filter '%s'", device_filter)
        else:
            logger.info("found %d rollup entries for filter '%s'", len(matched), device_filter)

        return matched

    async def get_memory_processor_health_information(self, device_name: str) -> Dict[str, Optional[str]]:
        """For a given `device_name` collection, query each member's Status/Health.

        Returns a mapping of member short-name -> Health value (or None if absent).
        """
        base_uri = f"/redfish/v1/Systems/System.Embedded.1/{device_name}"
        logger.info("requesting members for %s", base_uri)
        resp = await self.client.get(base_uri)

        if resp.status_code == 401:
            logger.warning("unauthorized access to %s (401)", base_uri)
            raise PermissionError("unauthorized")
        if resp.status_code != 200:
            logger.error("failed to get resource %s status=%s body=%s", base_uri, resp.status_code, None)
            raise RuntimeError(f"request failed status={resp.status_code}")

        data = resp.json()
        members = data.get("Members", [])
        if not isinstance(members, list) or members == []:
            logger.info("no members found for %s", base_uri)
            return {}

        results: Dict[str, Optional[str]] = {}
        for m in members:
            member_id = None
            if isinstance(m, dict):
                member_id = m.get("@odata.id") or m.get("href")
            elif isinstance(m, str):
                member_id = m
            if not member_id:
                logger.debug("skipping member without @odata.id/href in %s", base_uri)
                continue

            # ensure path-only URI for client.get; if member_id includes host, use as-is
            select_uri = member_id + ('?$select=Status/Health' if '?' not in member_id else '&$select=Status/Health')
            logger.debug("requesting Health for %s", select_uri)
            r2 = await self.client.get(select_uri)
            if r2.status_code != 200:
                logger.error("failed to get health for %s status=%s", select_uri, r2.status_code)
                results[member_id.split("/")[-1]] = None
                continue
            try:
                d2 = r2.json()
            except Exception:
                logger.exception("invalid json for %s", select_uri)
                results[member_id.split("/")[-1]] = None
                continue

            health = None
            if isinstance(d2, dict):
                health = (d2.get("Status") or {}).get("Health")
            results[member_id.split("/")[-1]] = health

        logger.info("collected health for %d members under %s", len(results), base_uri)
        return results

    async def get_storage_health(self) -> List[Dict[str, Any]]:
        """Return `Status` and `PredictedMediaLifeLeftPercent` for each drive.

        Walks /redfish/v1/Systems/System.Embedded.1/Storage -> Members ->
        for each storage resource read `Drives` and query each drive resource.
        Returns a list of dicts with `@odata.id`, `Status`, and `PredictedMediaLifeLeftPercent`.
        """
        base_uri = "/redfish/v1/Systems/System.Embedded.1/Storage"
        logger.info("requesting storage collection %s", base_uri)
        resp = await self.client.get(base_uri)

        if resp.status_code == 401:
            logger.warning("unauthorized access to %s (401)", base_uri)
            raise PermissionError("unauthorized")
        if resp.status_code != 200:
            logger.error("failed to get storage collection %s status=%s body=%s", base_uri, resp.status_code, None)
            raise RuntimeError(f"request failed status={resp.status_code}")

        try:
            data = resp.json()
        except Exception:
            logger.exception("invalid json response from %s", base_uri)
            raise ValueError("invalid json response")

        members = data.get("Members", [])
        if not isinstance(members, list) or members == []:
            logger.info("no storage members found for %s", base_uri)
            return []

        results: List[Dict[str, Any]] = []

        for m in members:
            member_id = None
            if isinstance(m, dict):
                member_id = m.get("@odata.id") or m.get("href")
            elif isinstance(m, str):
                member_id = m
            if not member_id:
                logger.debug("skipping storage member without @odata.id/href in %s", base_uri)
                continue

            logger.debug("requesting storage member %s", member_id)
            r1 = await self.client.get(member_id)
            if r1.status_code != 200:
                logger.error("failed to get storage member %s status=%s", member_id, r1.status_code)
                continue
            try:
                d1 = r1.json()
            except Exception:
                logger.exception("invalid json for %s", member_id)
                continue

            drives = d1.get("Drives", [])
            if not isinstance(drives, list) or drives == []:
                logger.debug("no drives listed for storage member %s", member_id)
                continue

            for drv in drives:
                drive_id = None
                if isinstance(drv, dict):
                    drive_id = drv.get("@odata.id") or drv.get("href")
                elif isinstance(drv, str):
                    drive_id = drv
                if not drive_id:
                    logger.debug("skipping drive entry without @odata.id/href under %s", member_id)
                    continue

                select_uri = drive_id + ('?$select=Status,PredictedMediaLifeLeftPercent' if '?' not in drive_id else '&$select=Status,PredictedMediaLifeLeftPercent')
                logger.debug("requesting drive health %s", select_uri)
                r2 = await self.client.get(select_uri)
                if r2.status_code != 200:
                    logger.error("failed to get drive %s status=%s", drive_id, r2.status_code)
                    results.append({"@odata.id": drive_id, "Status": None, "PredictedMediaLifeLeftPercent": None})
                    continue

                try:
                    d2 = r2.json()
                except Exception:
                    logger.exception("invalid json for %s", drive_id)
                    results.append({"@odata.id": drive_id, "Status": None, "PredictedMediaLifeLeftPercent": None})
                    continue

                status = d2.get("Status") if isinstance(d2, dict) else None
                pm = d2.get("PredictedMediaLifeLeftPercent") if isinstance(d2, dict) else None
                results.append({"@odata.id": drive_id, "Status": status, "PredictedMediaLifeLeftPercent": pm})

        logger.info("collected storage health for %d drives", len(results))
        return results
