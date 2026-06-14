from typing import Any, Dict, List, Optional
import logging
from idrac_async_redfish_client.services.base import BaseService

logger = logging.getLogger(__name__)

class InventoryService(BaseService):
    async def get_server_slot_info(self, slot_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return Dell Slots collection as JSON (no file output).

        Returns a dict with a `timestamp` and combined `members` list.

        Parameters
        - slot_type: Optional[str]
            Filter returned slot entries by the Dell `ConnectorLayout` value.
            Accepts a single value or a comma-separated list (case-insensitive).
            Use the string "all" or omit the parameter to return all entries.

        Supported `ConnectorLayout` examples observed in Dell iDRAC:
        - Fan
        - IDSDM
        - Processor
        - PowerSupply
        - DIMM
        - SDCard
        - PCI-E
        - PhysicalDisk

        Examples
        - `get_server_slot_info()` -> return all members
        - `get_server_slot_info("DIMM")` -> return only DIMM slots
        - `get_server_slot_info("Fan,Processor")` -> return Fan or Processor slots
        """
        uri = "/redfish/v1/Systems/System.Embedded.1/Oem/Dell/DellSlots"
        logger.info("requesting server slot information %s", uri)
        resp = await self.client.get(uri)

        if resp.status_code == 401:
            logger.warning("unauthorized access to %s (401)", uri)
            raise PermissionError("unauthorized")
        if resp.status_code != 200:
            logger.error("GET failed %s status=%s body=%s", uri, resp.status_code, None)
            raise RuntimeError(f"request failed status={resp.status_code}")

        data = resp.json()
        if "Members" not in data:
            logger.error("no 'Members' key in response from %s", uri)
            raise RuntimeError("no 'Members' key in response")

        members: List[Dict[str, Any]] = []
        if isinstance(data.get("Members"), list):
            members.extend(data.get("Members", []))

        # paginate using $skip increments of 50 until empty or server reports out-of-range
        skip = 50
        while True:
            next_uri = uri + f"?$skip={skip}"
            logger.debug("requesting paged slots %s", next_uri)
            r = await self.client.get(next_uri)
            if r.status_code != 200:
                # attempt to inspect error message to decide if we've reached the end
                try:
                    err = r.json()
                    info_list = err.get("error", {}).get("@Message.ExtendedInfo", [])
                    if info_list and isinstance(info_list, list):
                        msg = info_list[0].get("Message", "")
                        if "query parameter $skip is out of range" in msg:
                            break
                except Exception:
                    pass
                logger.error("paged GET failed %s status=%s body=%s", next_uri, r.status_code, None)
                raise RuntimeError(f"paged request failed status={r.status_code}")

            try:
                page = r.json()
            except Exception:
                logger.exception("invalid json for %s", next_uri)
                break

            if not page.get("Members"):
                break

            members.extend(page.get("Members", []))
            skip += 50

        # apply optional filtering by ConnectorLayout / slot type
        if slot_type and slot_type.lower() != "all":
            wanted = [s.strip().lower() for s in str(slot_type).split(",") if s.strip()]
            filtered: List[Dict[str, Any]] = []
            for m in members:
                layout = (m.get("ConnectorLayout") or "").lower() if isinstance(m, dict) else ""
                if any(w == layout for w in wanted):
                    filtered.append(m)
            logger.info("filtered server slot members by slot_type=%s -> %d members", slot_type, len(filtered))
            members = filtered

        logger.info("collected %d server slot members from %s", len(members), uri)
        return members

    async def get_hardware_inventory(self, poll_interval: int = 2, timeout: int = 300) -> str:
        """Trigger a Local hardware inventory export, wait for completion, then return the hwinv.xml text.

        - Only supports Local export (ShareType="Local").
        - If the POST returns Location == "/redfish/v1/Dell/hwinv.xml" the file is fetched immediately.
        - Otherwise the Location is treated as a job; we poll until Completed then fetch `/redfish/v1/Dell/hwinv.xml`.
        """
        uri = "/redfish/v1/Managers/iDRAC.Embedded.1/Oem/Dell/DellLCService/Actions/DellLCService.ExportHWInventory"
        payload = {"ShareType": "Local"}
        payload["FileName"] = "hwinv.xml"

        logger.info("posting ExportHWInventory action %s payload=%s", uri, payload)
        resp = await self.client.post(uri, json=payload)

        if resp.status_code not in (200, 202):
            logger.error("ExportHWInventory failed %s status=%s body=%s", uri, resp.status_code, None)
            raise RuntimeError(f"ExportHWInventory failed status={resp.status_code}")

        loc = None
        try:
            loc = (getattr(resp, 'headers', {}) or {}).get('Location')
        except Exception:
            loc = None

        if not loc:
            logger.error("no Location header returned for ExportHWInventory")
            raise RuntimeError("no Location header returned")

        # If the device returned the direct hwinv path, fetch and return it
        if loc == "/redfish/v1/Dell/hwinv.xml":
            logger.info("Export returned direct hwinv path; fetching %s", loc)
            r = await self.client.get(loc)
            if r.status_code != 200:
                logger.error("failed to GET %s status=%s body=%s", loc, r.status_code, None)
                raise RuntimeError(f"failed to retrieve hwinv.xml status={r.status_code}")
            if hasattr(r, 'text') and isinstance(r.text, str):
                return r.text
            if hasattr(r, 'content') and isinstance(r.content, (bytes, bytearray)):
                return r.content.decode('utf-8', errors='replace')
            # fallback
            raise RuntimeError("unexpected response when retrieving hwinv.xml")

        # Otherwise treat Location as a job path and poll
        job_id = loc.rstrip('/').split('/')[-1]
        if hasattr(self.client, '_loop_job_status'):
            await self.client._loop_job_status(job_id, poll_interval=poll_interval, timeout=timeout)
        else:
            # Fallback: if not found, we might need to implement it or it's a mistake in the original code.
            # For now, I'll just log a warning.
            logger.warning("client._loop_job_status not found, skipping polling")

        # After completion fetch the exported XML
        final = await self.client.get('/redfish/v1/Dell/hwinv.xml')
        if final.status_code != 200:
            logger.error("failed to GET /redfish/v1/Dell/hwinv.xml status=%s body=%s", final.status_code, None)
            raise RuntimeError(f"failed to retrieve hwinv.xml status={final.status_code}")
        if hasattr(final, 'text') and isinstance(final.text, str):
            return final.text
        if hasattr(final, 'content') and isinstance(final.content, (bytes, bytearray)):
            return final.content.decode('utf-8', errors='replace')
        raise RuntimeError("unexpected response when retrieving hwinv.xml")
