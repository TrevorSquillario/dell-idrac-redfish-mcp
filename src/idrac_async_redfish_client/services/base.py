from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from idrac_async_redfish_client.client import iDRACAsyncRedfishClient

class BaseService:
    def __init__(self, client: 'iDRACAsyncRedfishClient') -> None:
        self.client = client
