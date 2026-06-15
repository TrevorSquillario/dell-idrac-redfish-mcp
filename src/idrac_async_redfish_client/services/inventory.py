from typing import Any, Dict, List, Optional
import logging
from idrac_async_redfish_client.services.base import BaseService

logger = logging.getLogger("idrac_redfish_mcp")

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

    # async def get_hardware_inventory(self, poll_interval: int = 2, timeout: int = 300) -> str:
    #     """Trigger a Local hardware inventory export, wait for completion, then return the hwinv.xml text.

    #     - Only supports Local export (ShareType="Local").
    #     - If the POST returns Location == "/redfish/v1/Dell/hwinv.xml" the file is fetched immediately.
    #     - Otherwise the Location is treated as a job; we poll until Completed then fetch `/redfish/v1/Dell/hwinv.xml`.
    #     """
    #     uri = "/redfish/v1/Managers/iDRAC.Embedded.1/Oem/Dell/DellLCService/Actions/DellLCService.ExportHWInventory"
    #     payload = {"ShareType": "Local"}
    #     payload["FileName"] = "hwinv.xml"

    #     logger.info("posting ExportHWInventory action %s payload=%s", uri, payload)
    #     resp = await self.client.post(uri, json=payload)

    #     if resp.status_code not in (200, 202):
    #         logger.error("ExportHWInventory failed %s status=%s body=%s", uri, resp.status_code, None)
    #         raise RuntimeError(f"ExportHWInventory failed status={resp.status_code}")

    #     loc = None
    #     try:
    #         loc = (getattr(resp, 'headers', {}) or {}).get('Location')
    #     except Exception:
    #         loc = None

    #     if not loc:
    #         logger.error("no Location header returned for ExportHWInventory")
    #         raise RuntimeError("no Location header returned")

    #     # If the device returned the direct hwinv path, fetch and return it
    #     if loc == "/redfish/v1/Dell/hwinv.xml":
    #         logger.info("Export returned direct hwinv path; fetching %s", loc)
    #         r = await self.client.get(loc)
    #         if r.status_code != 200:
    #             logger.error("failed to GET %s status=%s body=%s", loc, r.status_code, None)
    #             raise RuntimeError(f"failed to retrieve hwinv.xml status={r.status_code}")
    #         if hasattr(r, 'text') and isinstance(r.text, str):
    #             return r.text
    #         if hasattr(r, 'content') and isinstance(r.content, (bytes, bytearray)):
    #             return r.content.decode('utf-8', errors='replace')
    #         # fallback
    #         raise RuntimeError("unexpected response when retrieving hwinv.xml")

    #     # Otherwise treat Location as a job path and poll
    #     job_id = loc.rstrip('/').split('/')[-1]
    #     if hasattr(self.client, '_loop_job_status'):
    #         await self.client._loop_job_status(job_id, poll_interval=poll_interval, timeout=timeout)
    #     else:
    #         # Fallback: if not found, we might need to implement it or it's a mistake in the original code.
    #         # For now, I'll just log a warning.
    #         logger.warning("client._loop_job_status not found, skipping polling")

    #     # After completion fetch the exported XML
    #     final = await self.client.get('/redfish/v1/Dell/hwinv.xml')
    #     if final.status_code != 200:
    #         logger.error("failed to GET /redfish/v1/Dell/hwinv.xml status=%s body=%s", final.status_code, None)
    #         raise RuntimeError(f"failed to retrieve hwinv.xml status={final.status_code}")
    #     if hasattr(final, 'text') and isinstance(final.text, str):
    #         return final.text
    #     if hasattr(final, 'content') and isinstance(final.content, (bytes, bytearray)):
    #         return final.content.decode('utf-8', errors='replace')
    #     raise RuntimeError("unexpected response when retrieving hwinv.xml")

    async def get_firmware_inventory(self) -> List[Dict[str, Any]]:
        """Return FirmwareInventory Members (expanded one level).

        Mirrors the previous synchronous logic that requested
        `/redfish/v1/UpdateService/FirmwareInventory?$expand=*($levels=1)`
        and returns the `Members` list.
        """
        uri = "/redfish/v1/UpdateService/FirmwareInventory?$expand=*($levels=1)"
        logger.info("requesting firmware inventory %s", uri)
        resp = await self.client.get(uri)

        if resp.status_code == 401:
            logger.warning("unauthorized access to %s (401)", uri)
            raise PermissionError("unauthorized")
        if resp.status_code != 200:
            try:
                body = resp.json()
            except Exception:
                body = None
            logger.error("failed to get firmware inventory %s status=%s body=%s", uri, resp.status_code, body)
            raise RuntimeError(f"request failed status={resp.status_code}")

        try:
            data = resp.json()
        except Exception:
            logger.exception("invalid json response from %s", uri)
            raise ValueError("invalid json response")

        members = data.get("Members", []) if isinstance(data, dict) else []
        if not isinstance(members, list):
            logger.warning("Firmware inventory Members not a list for %s", uri)
            return []

        simplified: List[Dict[str, Any]] = []
        for m in members:
            # If member is a reference string, try to fetch expanded member
            member_obj = m
            if isinstance(m, str):
                try:
                    r = await self.client.get(m)
                    if r.status_code == 200:
                        member_obj = r.json()
                    else:
                        logger.debug("failed to GET firmware member %s status=%s", m, r.status_code)
                        continue
                except Exception:
                    logger.exception("failed to fetch firmware member %s", m)
                    continue

            if not isinstance(member_obj, dict):
                continue

            name = member_obj.get("Name")
            release = member_obj.get("ReleaseDate")
            # Some devices use 'Updateable' spelling
            updatable = member_obj.get("Updateable")
            version = member_obj.get("Version")

            simplified.append({
                "Name": name,
                "ReleaseDate": release,
                "Updatable": updatable,
                "Version": version,
            })

        logger.info("collected %d firmware inventory members from %s", len(simplified), uri)
        return simplified

    async def get_pciedevice_info(self, all: bool = False) -> List[Dict[str, Any]]:
        """Return expanded PCIe device info for members under the chassis PCIeDevices collection.

        Parameters
        - all: bool
            If False (default) filter results to entries where `SlotLocationType` == "Slot". Thus returning a list of physical slots with cards in them.

        For each member in `/redfish/v1/Chassis/System.Embedded.1/PCIeDevices` the
        method follows the member's odata id and collects a subset of properties:
        - Manufacturer, Model, Name, PartNumber, SKU, SerialNumber, Slot,
          Status.Health, Description, FirmwareVersion, Id
        """
        uri = "/redfish/v1/Chassis/System.Embedded.1/PCIeDevices"
        logger.info("requesting PCIe devices collection %s", uri)
        resp = await self.client.get(uri)

        if resp.status_code == 401:
            logger.warning("unauthorized access to %s (401)", uri)
            raise PermissionError("unauthorized")
        if resp.status_code != 200:
            try:
                body = resp.json()
            except Exception:
                body = None
            logger.error("failed to get PCIeDevices %s status=%s body=%s", uri, resp.status_code, body)
            raise RuntimeError(f"request failed status={resp.status_code}")

        try:
            data = resp.json()
        except Exception:
            logger.exception("invalid json response from %s", uri)
            raise ValueError("invalid json response")

        members = data.get("Members", []) if isinstance(data, dict) else []
        if not isinstance(members, list):
            logger.warning("PCIeDevices Members not a list for %s", uri)
            return []

        results: List[Dict[str, Any]] = []
        for m in members:
            # member can be a dict with @odata.id or a single string
            member_uri = None
            if isinstance(m, dict):
                member_uri = m.get("@odata.id")
            elif isinstance(m, str):
                member_uri = m

            if not member_uri:
                logger.debug("skipping PCIeDevices member without uri: %s", m)
                continue

            logger.debug("requesting PCIe device details %s", member_uri)
            try:
                r = await self.client.get(member_uri)
            except Exception:
                logger.exception("failed request for member %s", member_uri)
                continue

            if r.status_code != 200:
                logger.warning("failed to GET member %s status=%s", member_uri, r.status_code)
                continue

            try:
                dev = r.json()
            except Exception:
                logger.exception("invalid json for PCIe device %s", member_uri)
                continue

            # extract required properties
            entry: Dict[str, Any] = {}
            entry["Manufacturer"] = dev.get("Manufacturer")
            entry["Model"] = dev.get("Model")
            entry["Name"] = dev.get("Name")
            entry["PartNumber"] = dev.get("PartNumber")
            entry["SKU"] = dev.get("SKU")
            entry["SerialNumber"] = dev.get("SerialNumber")
            slot = dev.get("Slot") if isinstance(dev.get("Slot"), dict) else {}
            entry["SlotLanes"] = slot.get("Lanes") if isinstance(slot, dict) else None
            # parse nested Location -> PartLocation for ordinal and type
            part_location: Dict[str, Any] = {}
            if isinstance(slot, dict):
                loc = slot.get("Location")
                if isinstance(loc, dict):
                    pl = loc.get("PartLocation")
                    if isinstance(pl, dict):
                        part_location = pl
            entry["SlotLocationType"] = part_location.get("LocationType") if isinstance(part_location, dict) else None
            entry["SlotNumber"] = part_location.get("LocationOrdinalValue") if isinstance(part_location, dict) else None
            entry["PCIeType"] = slot.get("PCIeType") if isinstance(slot, dict) else None
            entry["SlotType"] = slot.get("SlotType") if isinstance(slot, dict) else None
            # Status.Health may be nested under Status
            status = dev.get("Status") if isinstance(dev.get("Status"), dict) else {}
            entry["Status.Health"] = status.get("Health") if isinstance(status, dict) else None
            entry["Description"] = dev.get("Description")   
            entry["FirmwareVersion"] = dev.get("FirmwareVersion")
            entry["Id"] = dev.get("Id")

            results.append(entry)

        # sort results by SlotLocationType (string) then SlotNumber (ordinal)
        def _pcie_sort_key(e: Dict[str, Any]):
            loc_type = e.get("SlotLocationType") or ""
            num = e.get("SlotNumber")
            try:
                num_val = int(num) if num is not None else float('inf')
            except Exception:
                num_val = float('inf')
            return (loc_type, num_val)

        try:
            # If `all` is False, first filter to only physical slots then sort.
            if not all:
                results = [e for e in results if e.get("SlotLocationType") == "Slot"]
                logger.info("filtered PCIe device entries to SlotLocationType='Slot' -> %d entries", len(results))
            results.sort(key=_pcie_sort_key)
        except Exception:
            logger.exception("failed to sort PCIe device entries; returning unsorted results")

        logger.info("collected %d PCIe device entries from %s", len(results), uri)
        return results
