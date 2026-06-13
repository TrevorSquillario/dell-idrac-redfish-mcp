from typing import Any, Dict, List, Optional, Union
import logging
from idrac_async_redfish_client.services.base import BaseService

logger = logging.getLogger(__name__)

class ConfigService(BaseService):
    async def get_error_and_event_registry(self, message_id: str) -> Any:
        """Query the iDRAC Message Registry (EEMIRegistry) which contains detailed descriptions for error and event message IDs with suggestions for resolutions to errors.

        If `message_id` is provided, return the specific message entry
        (e.g. "ACC0001"). Otherwise return the entire `Messages` mapping.
        """
        uri = "/redfish/v1/Registries/Messages/EEMIRegistry"
        logger.info("requesting message registry %s", uri)
        resp = await self.client.get(uri)

        if resp.status_code == 401:
            logger.warning("unauthorized access to %s (401)", uri)
            raise PermissionError("unauthorized")
        if resp.status_code != 200:
            logger.error("failed to get message registry %s status=%s body=%s", uri, resp.status_code, None)
            raise RuntimeError(f"request failed status={resp.status_code}")

        try:
            data = resp.json()
        except Exception:
            logger.exception("invalid json response from %s", uri)
            raise ValueError("invalid json response")

        messages = data.get("Messages") or {}
        if message_id:
            return messages.get(message_id)
        return messages

    async def get_bios_registry(self) -> List[str]:
        """Return a list of BIOS registry attribute names from the BIOS Attribute Registry.

        Queries: /redfish/v1/Systems/System.Embedded.1/Bios/BiosRegistry
        Extracts the `AttributeName` value from each entry under
        `RegistryEntries -> Attributes` and returns it as a list of strings.
        """
        uri = "/redfish/v1/Systems/System.Embedded.1/Bios/BiosRegistry"
        logger.info("requesting BIOS registry %s", uri)
        resp = await self.client.get(uri)

        if resp.status_code == 401:
            logger.warning("unauthorized access to %s (401)", uri)
            raise PermissionError("unauthorized")
        if resp.status_code != 200:
            logger.error("failed to get BIOS registry %s status=%s body=%s", uri, resp.status_code, None)
            raise RuntimeError(f"request failed status={resp.status_code}")

        try:
            data = resp.json()
        except Exception:
            logger.exception("invalid json response from %s", uri)
            raise ValueError("invalid json response")

        registry = data.get("RegistryEntries") or {}
        attributes = registry.get("Attributes") or []
        if not isinstance(attributes, list):
            logger.error("unexpected Attributes format in BIOS registry %s", uri)
            raise RuntimeError("invalid BIOS registry format")

        names: List[str] = []
        for a in attributes:
            if isinstance(a, dict):
                name = a.get("AttributeName")
                if isinstance(name, str):
                    names.append(name)

        logger.info("found %d BIOS registry attributes", len(names))
        return names

    async def get_bios_attributes(self, attributes: Optional[Union[str, List[str]]] = None) -> Dict[str, Any]:
        """Return a mapping of requested BIOS `AttributeName` -> current value.

        `attributes` may be a comma-separated string or a list of attribute names.
        Queries: /redfish/v1/Systems/System.Embedded.1/Bios
        """
        uri = "/redfish/v1/Systems/System.Embedded.1/Bios"
        logger.info("requesting BIOS attributes %s", uri)
        resp = await self.client.get(uri)

        if resp.status_code == 401:
            logger.warning("unauthorized access to %s (401)", uri)
            raise PermissionError("unauthorized")
        if resp.status_code != 200:
            logger.error("failed to get BIOS attributes %s status=%s body=%s", uri, resp.status_code, None)
            raise RuntimeError(f"request failed status={resp.status_code}")

        try:
            data = resp.json()
        except Exception:
            logger.exception("invalid json response from %s", uri)
            raise ValueError("invalid json response")

        attrs_map = data.get("Attributes")
        if not isinstance(attrs_map, dict):
            logger.error("unexpected Attributes format in BIOS resource %s", uri)
            raise RuntimeError("invalid BIOS attributes format")

        # if no specific attributes requested, return the full attributes map
        if attributes is None:
            return attrs_map

        # normalize requested attributes into a list
        if isinstance(attributes, str):
            wanted = [s.strip() for s in attributes.split(",") if s.strip()]
        elif isinstance(attributes, list):
            wanted = [str(s).strip() for s in attributes if str(s).strip()]
        else:
            raise ValueError("attributes must be a comma-separated string or a list of names")

        results: Dict[str, Any] = {}
        missing: List[str] = []
        for w in wanted:
            if w in attrs_map:
                results[w] = attrs_map[w]
            else:
                missing.append(w)

        if not results:
            logger.error("no matching BIOS attributes found for requested names: %s", wanted)
            raise RuntimeError("no matching BIOS attributes found")

        if missing:
            logger.warning("some requested BIOS attributes were not found: %s", missing)

        logger.info("retrieved %d BIOS attribute values", len(results))
        return results

    async def get_idrac_attributes(self, group: str = "idrac", attributes: Optional[str] = None) -> Dict[str, Any]:
        """Dell-specific: Get iDRAC configuration attributes.

        Parameters
        - group: one of "idrac", "lc", or "system" (case-insensitive). Determines
          the FQDD used when querying DellAttributes.
        - attributes: optional comma-separated list of attribute names to return.

        Returns the full Attributes mapping when `attributes` is omitted, or a
        dict containing only the requested attributes when provided.
        """
        g = (group or "").lower()
        if g == "idrac":
            fqdd = "iDRAC.Embedded.1"
        elif g == "lc" or g == "lifecyclecontroller":
            fqdd = "LifecycleController.Embedded.1"
        elif g == "system":
            fqdd = "System.Embedded.1"
        else:
            logger.error("invalid value entered for group: %s", group)
            raise ValueError(f"invalid group '{group}', expected one of: idrac, lc, system")

        uri = f"/redfish/v1/Managers/iDRAC.Embedded.1/Oem/Dell/DellAttributes/{fqdd}"
        logger.info("requesting iDRAC attributes %s (group=%s attributes=%s)", uri, group, attributes)
        resp = await self.client.get(uri)

        if resp.status_code == 401:
            logger.warning("unauthorized access to %s (401)", uri)
            raise PermissionError("unauthorized")
        if resp.status_code != 200:
            logger.error("failed to get attributes %s status=%s body=%s", uri, resp.status_code, None)
            raise RuntimeError(f"request failed status={resp.status_code}")

        try:
            data = resp.json()
        except Exception:
            logger.exception("invalid json response from %s", uri)
            raise ValueError("invalid json response")

        attributes_map = data.get("Attributes") or {}
        if attributes is None:
            return attributes_map

        # filter requested comma-separated attributes
        wanted = [s.strip() for s in str(attributes).split(",") if s.strip()]
        results: Dict[str, Any] = {}
        missing: List[str] = []
        for w in wanted:
            if w in attributes_map:
                results[w] = attributes_map[w]
            else:
                missing.append(w)

        if not results:
            logger.error("unable to locate requested attributes %s in %s", wanted, uri)
            raise RuntimeError(f"unable to locate requested attributes: {wanted}")

        if missing:
            logger.warning("some requested attributes were not found: %s", missing)

        return results

    async def get_location_indicator_active(self) -> bool:
        """Return the current value of the LocationIndicatorActive property from the Chassis.

        Queries: /redfish/v1/Chassis/System.Embedded.1
        """
        uri = "/redfish/v1/Chassis/System.Embedded.1"
        logger.info("requesting chassis location indicator active status %s", uri)
        resp = await self.client.get(uri)

        if resp.status_code == 401:
            logger.warning("unauthorized access to %s (401)", uri)
            raise PermissionError("unauthorized")
        if resp.status_code != 200:
            logger.error("failed to get chassis status %s status=%s", uri, resp.status_code)
            raise RuntimeError(f"request failed status={resp.status_code}")

        try:
            data = resp.json()
            active = data.get("LocationIndicatorActive")
            if active is None:
                logger.error("LocationIndicatorActive property not found in response from %s", uri)
                raise ValueError("LocationIndicatorActive property not found")
            
            logger.info("current chassis location indicator active property setting: %s", active)
            return bool(active)
        except Exception:
            logger.exception("invalid json response from %s", uri)
            raise ValueError("invalid json response")

    async def set_location_indicator_active(self, active: bool) -> None:
        """Set the LocationIndicatorActive property on the Chassis.

        Queries: PATCH /redfish/v1/Chassis/System.Embedded.1
        """
        uri = "/redfish/v1/Chassis/System.Embedded.1"
        payload = {"LocationIndicatorActive": active}
        logger.info("setting chassis location indicator active to %s at %s", active, uri)
        
        resp = await self.client.patch(uri, json=payload)

        if resp.status_code != 200:
            logger.error("failed to set location indicator active %s status=%s", uri, resp.status_code)
            raise RuntimeError(f"failed to set LocationIndicatorActive: status={resp.status_code}")

        logger.info("successfully set LocationIndicatorActive to %s", active)
