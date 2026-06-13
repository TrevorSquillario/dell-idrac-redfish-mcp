"""Minimal iDRAC Redfish client.

Provides a small `iDRACAsyncRedfishClient` class for session-based login and REST
operations against a Redfish endpoint using async/await syntax.

Example:
    import asyncio

    async def main():
        async with iDRACAsyncRedfishClient('1.2.3.4') as client:
            await client.login('admin', 'password')
            r = await client.get('/redfish/v1/Systems')
            print(r.json())

    asyncio.run(main())
"""

from typing import Optional, Any

import urllib3
import httpx
import logging
import asyncio
from PIL import Image
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
import io
import base64

logger = logging.getLogger(__name__)

# import services
from idrac_async_redfish_client.services.config import ConfigService
from idrac_async_redfish_client.services.inventory import InventoryService
from idrac_async_redfish_client.services.health import HealthService
from idrac_async_redfish_client.services.logs import LogService
from idrac_async_redfish_client.services.media import MediaService

class iDRACAsyncRedfishClient:
    def __init__(
        self,
        host: str,
        port: Optional[int] = 443,
        verify: bool = True,
        timeout: int = 30,
    ) -> None:
        self.host = host
        self.port = port
        self.base_url = f"https://{host}"
        
        if port != 443:
            host_part = f"{host}:{port}"
            self.base_url = f"https://{host_part}"
            
        self.verify = verify
        self.timeout = timeout

        if verify is False:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        # Initialize the asynchronous HTTPX client
        self.http = httpx.AsyncClient(
            verify=verify, 
            timeout=timeout,
            headers={"Content-Type": "application/json"}
        )

        self._session_uri: Optional[str] = None
        self._token: Optional[str] = None

        # Stored credentials for automatic token refreshes
        self._username: Optional[str] = None
        self._password: Optional[str] = None

        self._reauth_lock = asyncio.Lock()

        # attach service helpers
        self.config = ConfigService(self)
        self.inventory = InventoryService(self)
        self.health = HealthService(self)
        self.logs = LogService(self)
        self.media = MediaService(self)

    async def login(self, username: str, password: str) -> None:
        """Create a Redfish session and store the session token."""
        self._username = username
        self._password = password
        url = self._absolute_url('/redfish/v1/SessionService/Sessions')
        payload = {"UserName": username, "Password": password}
        
        resp = await self.http.post(url, json=payload)
        resp.raise_for_status()

        # Extract Session URI from Location header
        if 'Location' in resp.headers:
            self._session_uri = resp.headers['Location']

        # Extract token from varying potential case-insensitive headers
        token = resp.headers.get('X-Auth-Token') or resp.headers.get('x-auth-token')
        if not token and resp.headers.get('X-AuthToken'):
            token = resp.headers.get('X-AuthToken')
            
        if not token:
            try:
                body = resp.json()
                token = body.get('Token') or body.get('token')
            except Exception:
                token = None

        if token:
            self._token = token
            self.http.headers.update({'X-Auth-Token': self._token})

    async def logout(self) -> None:
        """Delete the Redfish session if possible and clear credentials."""
        if self._session_uri:
            try:
                await self.http.delete(self._session_uri)
            except Exception:
                pass
        
        # Clear token and matching headers
        self._token = None
        if 'X-Auth-Token' in self.http.headers:
            del self.http.headers['X-Auth-Token']

    def set_token(self, token: str, session_uri: Optional[str] = None) -> None:
        """Set an existing token (and optional session uri) for reuse."""
        self._token = token
        self.http.headers.update({'X-Auth-Token': self._token})
        if session_uri:
            self._session_uri = session_uri

    def token_valid(self) -> bool:
        """Return True if a token exists."""
        return bool(self._token)

    async def ensure_session(self, username: str, password: str) -> None:
        """Ensure a valid session/token exists. If not, create one."""
        self._username = username
        self._password = password

        if self.token_valid():
            try:
                url = self._absolute_url('/')
                resp = await self.http.get(url)
                if resp.status_code == 200:
                    return
            except Exception:
                pass

        # No valid token found, trigger async login
        await self.login(username, password)

    # Backwards-compatible convenience wrappers delegating to service helpers
    async def get_lifecycle_logs(self, *args, **kwargs) -> Any:
        return await self.logs.get_lifecycle_logs(*args, **kwargs)

    async def get_error_and_event_registry(self, message_id: Optional[str] = None) -> Any:
        return await self.config.get_error_and_event_registry(message_id)

    async def export_server_screen_shot(self, filetype: int = 2) -> Any:
        return await self.media.export_server_screen_shot(filetype=filetype)

    async def get_idrac_attributes(self, *args, **kwargs) -> Any:
        return await self.config.get_idrac_attributes(*args, **kwargs)

    async def get_device_rollup_health_status(self, *args, **kwargs) -> Any:
        return await self.health.get_device_rollup_health_status(*args, **kwargs)

    async def get_memory_processor_health_information(self, *args, **kwargs) -> Any:
        return await self.health.get_memory_processor_health_information(*args, **kwargs)

    async def get_server_slot_info(self, *args, **kwargs) -> Any:
        return await self.hardware.get_server_slot_info(*args, **kwargs)

    def _absolute_url(self, path: str) -> str:
        if path.startswith('http://') or path.startswith('https://'):
            return path
        if path.startswith('/'):
            return self.base_url.rstrip('/') + path
        return self.base_url.rstrip('/') + '/' + path

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Generic async request wrapper with automatic 401 token refresh."""
        url = self._absolute_url(path)
        
        resp = await self.http.request(method, url, **kwargs)
        
        if resp.status_code == 401:
            if self._username and self._password:
                async with self._reauth_lock:
                    # Double-check inside the lock to see if another task refreshed it already
                    if resp.headers.get('X-Auth-Token') != self._token:
                        await self.login(self._username, self._password)
                    
                    # Retry request
                    resp = await self.http.request(method, url, **kwargs)
                    
        resp.raise_for_status()
        return resp

    async def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.request('GET', path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.request('POST', path, **kwargs)

    async def patch(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.request('PATCH', path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.request('DELETE', path, **kwargs)

    async def close(self) -> None:
        """Explicitly close the underlying HTTPX client transport."""
        await self.http.aclose()

    async def _loop_job_status(self, job_id: str, poll_interval: int = 2, timeout: int = 300) -> Any:
        """Poll a Redfish job until completion or timeout.

        Raises on non-completed terminal job states or on timeout.
        Returns the final job JSON when completed, or the path to a temporary file
        if the job results in a sacollect.zip file.

        job_id can be a job ID or a full URI/path.
        """
        import tempfile
        import os
        start = asyncio.get_event_loop().time()
        
        if job_id.startswith(('http://', 'https://', '/')):
            uri = job_id
        else:
            uri = f"/redfish/v1/Jobs/{job_id}"

        while True:
            try:
                resp = await self.get(uri)
            except Exception:
                # propagate underlying errors
                raise

            if resp.status_code == 200:
                try:
                    data = resp.json()
                except Exception:
                    data = None
                state = (data or {}).get("JobState") if isinstance(data, dict) else None
                if state in ("Completed",):
                    return data
                if state in ("Exception", "Killed", "Canceled", "Cancelled", "Failed"):
                    raise RuntimeError(f"job {job_id} ended with state {state}")
            elif resp.status_code == 204:
                location = resp.headers.get("Location", "")
                if "sacollect.zip" in location.lower():
                    # Download the file
                    resp_file = await self.get(location)
                    fd, path = tempfile.mkstemp(suffix=".zip")
                    try:
                        with os.fdopen(fd, 'wb') as f:
                            f.write(resp_file.content)
                        return path
                    except Exception as e:
                        os.close(fd)
                        raise e
                else:
                    raise RuntimeError(f"job {job_id} ended with 204 but Location header does not contain sacollect.zip: {location}")

            elapsed = asyncio.get_event_loop().time() - start
            if elapsed >= float(timeout):
                raise TimeoutError(f"job {job_id} did not complete within {timeout} seconds")

            await asyncio.sleep(poll_interval)

