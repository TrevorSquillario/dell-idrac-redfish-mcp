from typing import Any, Dict, Optional
import logging
import asyncio
from idrac_async_redfish_client.services.base import BaseService

logger = logging.getLogger("idrac_redfish_mcp")

class SupportService(BaseService):
    async def support_assist_collection(
        self,
        filter_val: Optional[str] = None,
        data: Optional[str] = None,
    ) -> Any:
        """
        Start a SupportAssist collection.

        Parameters
        - filter_val: Optional[str]
            Filter for the collection. "0" for No, "1" for Yes.
        - data: Optional[str]
            Comma-separated list of data to collect.
            0: DebugLogs
            1: HWData
            2: OSAppData
            3: TTYLogs
            4: TelemetryReports
            5: GPULogs

        Returns
        - Any: The final job JSON when completed, or the path to a temporary file
          if the job results in a sacollect.zip file.
        """
        uri = "/redfish/v1/Managers/iDRAC.Embedded.1/Oem/Dell/DellLCService/Actions/DellLCService.SupportAssistCollection"
        logger.info("requesting support assist collection %s", uri)

        payload = {"ShareType": "Local"}
        if filter_val is not None:
            if filter_val == "0":
                payload["Filter"] = "No"
            elif filter_val == "1":
                payload["Filter"] = "Yes"

        if data:
            data_selector_values = []
            data_list = [i.strip() for i in data.split(",")]
            mapping = {
                "0": "DebugLogs",
                "1": "HWData",
                "2": "OSAppData",
                "3": "TTYLogs",
                "4": "TelemetryReports",
                "5": "GPULogs"
            }
            for val in data_list:
                if val in mapping:
                    data_selector_values.append(mapping[val])

            if data_selector_values:
                payload["DataSelectorArrayIn"] = data_selector_values

        logger.debug("SupportAssistCollection payload: %s", payload)
        resp = await self.client.post(uri, json=payload)

        if resp.status_code != 202:
            logger.error("SupportAssistCollection failed status=%s body=%s", resp.status_code, resp.text)
            raise RuntimeError(f"SupportAssistCollection failed status={resp.status_code}")

        try:
            job_id_uri = resp.headers.get("Location")
            if not job_id_uri:
                raise RuntimeError("Location header not found in response")
            logger.info("SupportAssistCollection job ID %s successfully created", job_id_uri.split("/")[-1])
            return await self.client._loop_job_status(job_id_uri)
        except Exception as e:
            logger.error("Failed to get job ID or poll status: %s", e)
            raise RuntimeError(f"SupportAssistCollection failed: {e}")

    async def support_assist_accept_eula(self) -> None:
        """
        Accept the SupportAssist EULA.
        """
        uri = "/redfish/v1/Managers/iDRAC.Embedded.1/Oem/Dell/DellLCService/Actions/DellLCService.SupportAssistAcceptEULA"
        logger.info("requesting support assist accept EULA %s", uri)

        payload = {}
        resp = await self.client.post(uri, json=payload)

        if resp.status_code not in (200, 202):
            logger.error("SupportAssistAcceptEULA failed status=%s body=%s", resp.status_code, resp.text)
            raise RuntimeError(f"SupportAssistAcceptEULA failed status={resp.status_code}")
        
        logger.info("SupportAssistAcceptEULA passed and EULA has been accepted")

    async def support_assist_get_eula_status(self) -> Optional[Dict[str, Any]]:
        """
        Get the SupportAssist EULA status.

        Returns
        - Optional[Dict[str, Any]]: The EULA status data.
        """
        uri = "/redfish/v1/Managers/iDRAC.Embedded.1/Oem/Dell/DellLCService/Actions/DellLCService.SupportAssistGetEULAStatus"
        logger.info("requesting support assist get EULA status %s", uri)

        payload = {}
        resp = await self.client.post(uri, json=payload)

        if resp.status_code != 200:
            logger.error("SupportAssistGetEULAStatus failed status=%s body=%s", resp.status_code, resp.text)
            raise RuntimeError(f"SupportAssistGetEULAStatus failed status={resp.status_code}")

        data = resp.json()
        logger.debug("SupportAssist EULA status: %s", data)
        return data
