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
import os
from urllib.parse import urlparse, quote
from PIL import Image
from datetime import datetime
import os
from typing import Any, Dict, List, Optional, Union
import io
import base64

# Domain errors for centralized mapping
from idrac_async_redfish_client.errors import (
    RedfishError,
    RedfishNotFound,
    RedfishUnauthorized,
    RedfishClientError,
    RedfishServerError,
    RedfishTimeout,
    RedfishConnectionError,
    RedfishJSONError,
    RedfishTransientError,
)

logger = logging.getLogger(__name__)

# import services
from idrac_async_redfish_client.services.config import ConfigService
from idrac_async_redfish_client.services.inventory import InventoryService
from idrac_async_redfish_client.services.health import HealthService
from idrac_async_redfish_client.services.logs import LogService
from idrac_async_redfish_client.services.media import MediaService
from idrac_async_redfish_client.services.support import SupportService
from idrac_async_redfish_client.services.telemetry import TelemetryService

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
        self._session_id: Optional[str] = None
        self._token: Optional[str] = None

        # Timestamp when the current token was created (UTC)
        self._token_created_at: Optional[datetime] = None

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
        self.support = SupportService(self)
        self.telemetry = TelemetryService(self)

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

        # Extract explicit session Id from response body if present, otherwise
        # attempt to parse it from the Location header as a fallback.
        session_id = None
        try:
            body = resp.json()
            session_id = body.get('Id') or body.get('id')
        except Exception:
            session_id = None

        if not session_id and self._session_uri:
            try:
                parsed = urlparse(self._session_uri)
                path = parsed.path or self._session_uri
                session_id = path.rstrip('/').rsplit('/', 1)[-1]
            except Exception:
                session_id = None

        if session_id:
            self._session_id = session_id

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
            # record token creation time
            try:
                self._token_created_at = datetime.utcnow()
            except Exception:
                self._token_created_at = None

    async def logout(self) -> None:
        """Delete the Redfish session if possible and clear credentials."""
        # Prefer explicit session id when deleting the session
        if self._session_id:
            try:
                url = self._absolute_url(f"/redfish/v1/SessionService/Sessions/{self._session_id}")
                await self.http.delete(url)
                logger.info(f"session with id {self._session_id} successfully deleted")
            except Exception as e:
                logger.error(f"failed to delete session with id {self._session_id}: {e}")
                pass
        elif self._session_uri:
            try:
                await self.http.delete(self._session_uri)
            except Exception as e:
                logger.error(f"failed to delete session with id {self._session_id}: {e}")
                pass
        
        # Clear token, session identifiers and matching headers
        self._token = None
        self._session_id = None
        self._session_uri = None
        if 'X-Auth-Token' in self.http.headers:
            del self.http.headers['X-Auth-Token']

    def set_token(self, token: str, session_uri: Optional[str] = None) -> None:
        """Set an existing token (and optional session uri) for reuse."""
        self._token = token
        self.http.headers.update({'X-Auth-Token': self._token})
        if session_uri:
            self._session_uri = session_uri
        # record when a token is set externally
        try:
            self._token_created_at = datetime.utcnow()
        except Exception:
            self._token_created_at = None

    def token_valid(self) -> bool:
        """Return True if a token exists."""
        if not self._token:
            return False

        # Enforce timeout from environment variable (seconds)
        try:
            timeout = int(os.getenv("IDRAC_SESSION_TIMEOUT", "1800"))
        except Exception:
            timeout = 1800

        if not self._token_created_at:
            # If we don't know when the token was created, consider it valid
            # to preserve backwards compatibility.
            return True

        try:
            age = (datetime.utcnow() - self._token_created_at).total_seconds()
            if age > float(timeout):
                # Expired: clear token and related session state to force re-auth
                self._token = None
                self._session_id = None
                self._session_uri = None
                if 'X-Auth-Token' in self.http.headers:
                    del self.http.headers['X-Auth-Token']
                return False
        except Exception:
            # On any error while checking age, be conservative and treat token as valid
            return True

        return True

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

    async def support_assist_collection(self, *args, **kwargs) -> Any:
        return await self.support.support_assist_collection(*args, **kwargs)

    async def get_hardware_inventory(self, *args, **kwargs) -> Any:
        return await self.inventory.get_hardware_inventory(*args, **kwargs)

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
        # Retry configuration
        attempts = int(os.getenv("IDRAC_RETRY_ATTEMPTS", "3"))
        backoff_base = float(os.getenv("IDRAC_RETRY_BACKOFF", "0.5"))

        last_exc: Optional[BaseException] = None
        for attempt in range(1, max(1, attempts) + 1):
            try:
                resp = await self.http.request(method, url, **kwargs)

                # Handle authentication renewal on 401
                if resp.status_code == 401:
                    if self._username and self._password:
                        async with self._reauth_lock:
                            if resp.headers.get('X-Auth-Token') != self._token:
                                await self.login(self._username, self._password)
                            resp = await self.http.request(method, url, **kwargs)

                # Map status codes to domain exceptions so callers can handle them
                status = resp.status_code
                if 200 <= status < 300:
                    return resp
                if status == 404:
                    raise RedfishNotFound(f"Client error '404 Not Found' for url '{url}'")
                if status in (401, 403):
                    raise RedfishUnauthorized(f"Client error '{status}' for url '{url}'")
                if 400 <= status < 500:
                    raise RedfishClientError(f"Client error '{status}' for url '{url}'")
                if 500 <= status < 600:
                    # Treat server-side 5xx as transient - allow retries
                    raise RedfishServerError(f"Server error '{status}' for url '{url}'")

            except (httpx.RequestError, RedfishServerError) as e:
                # Network-level errors and server 5xx are considered transient.
                last_exc = e
                if attempt < attempts:
                    sleep_time = backoff_base * (2 ** (attempt - 1))
                    try:
                        await asyncio.sleep(sleep_time)
                    except Exception:
                        pass
                    continue

                # Final attempt failed - map httpx errors to domain exceptions
                if isinstance(e, httpx.RequestError):
                    # Distinguish timeouts
                    if isinstance(e, httpx.TimeoutException):
                        raise RedfishTimeout(str(e)) from e
                    raise RedfishConnectionError(str(e)) from e
                # If it's a RedfishServerError and we've exhausted retries, surface it
                raise

            except httpx.HTTPStatusError as e:
                # Defensive mapping for callers that may have raised via raise_for_status
                resp = getattr(e, 'response', None)
                status = getattr(resp, 'status_code', None)
                if status == 404:
                    raise RedfishNotFound(str(e)) from e
                if status in (401, 403):
                    raise RedfishUnauthorized(str(e)) from e
                if 400 <= (status or 0) < 500:
                    raise RedfishClientError(str(e)) from e
                if 500 <= (status or 0) < 600:
                    last_exc = e
                    if attempt < attempts:
                        sleep_time = backoff_base * (2 ** (attempt - 1))
                        try:
                            await asyncio.sleep(sleep_time)
                        except Exception:
                            pass
                        continue
                    raise RedfishServerError(str(e)) from e

            except Exception as e:
                # Unknown errors - surface as-is
                raise

        # If we exit the loop and still have a last exception, raise it
        if last_exc:
            raise last_exc

        # Fallback - shouldn't normally be reached
        raise RedfishError(f"Unhandled error requesting {method} {url}")

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

    async def get_redfish_uri(self, path: str, select: Optional[str] = None) -> Any:
        """Fetch a Redfish URI and return the payload as-is.

        If `select` is provided, append an OData `$select` query parameter
        to the path (preserving any existing query string).

        Tries to parse JSON and returns the parsed object; falls back to
        returning text when JSON parsing fails.
        """
        if select:
            # preserve existing query string if present
            sel = quote(select, safe=',')
            if '?' in path:
                path = f"{path}&$select={sel}"
            else:
                path = f"{path}?$select={sel}"

        resp = await self.get(path)
        try:
            return resp.json()
        except Exception:
            return resp.text

    async def _loop_job_status(self, job_id: str, poll_interval: int = 2, timeout: int = 1800) -> Any:
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
                    location = resp.headers.get("Location", "")
                    if "sacollect.zip" in location.lower():
                        # Download the file
                        resp_file = await self.get(location)
                        fd, path = tempfile.mkstemp(suffix=".zip")
                        try:
                            with os.fdopen(fd, 'wb') as f:
                                f.write(resp_file.content)
                            return {"sacollect_path": path}
                        except Exception as e:
                            os.close(fd)
                            raise e
                    else:
                        return data
                if state in ("Exception", "Killed", "Canceled", "Cancelled", "Failed"):
                    raise RuntimeError(f"job {job_id} ended with state {state}")

            elapsed = asyncio.get_event_loop().time() - start
            if elapsed >= float(timeout):
                raise TimeoutError(f"job {job_id} did not complete within {timeout} seconds")

            await asyncio.sleep(poll_interval)

