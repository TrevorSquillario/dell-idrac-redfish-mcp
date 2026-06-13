from typing import Any, Dict, List, Optional, Union
import logging
import io
import base64
from PIL import Image
from idrac_async_redfish_client.services.base import BaseService

logger = logging.getLogger(__name__)

class MediaService(BaseService):
    async def export_server_screen_shot(self, filetype: int = 2) -> str:
        """Export a server screenshot via the Dell LC action and return the path to a temporary PNG file.

        `filetype` values: 0=LastCrashScreenShot, 1=Preview, 2=ServerScreenShot
        Returns path to the temporary file.
        """
        uri = "/redfish/v1/Managers/iDRAC.Embedded.1/Oem/Dell/DellLCService/Actions/DellLCService.ExportServerScreenShot"

        mapping = {
            0: "LastCrashScreenShot",
            1: "Preview",
            2: "ServerScreenShot",
        }

        # accept numeric strings as well
        try:
            ft_i = int(filetype)
        except Exception:
            raise ValueError("filetype must be 0, 1, or 2")

        if ft_i not in mapping:
            raise ValueError("filetype must be 0, 1, or 2")

        payload = {"FileType": mapping[ft_i]}
        logger.info("posting ExportServerScreenShot action %s payload=%s", uri, payload)
        resp = await self.client.post(uri, json=payload)

        if resp.status_code not in (200, 202):
            logger.error("ExportServerScreenShot failed %s status=%s body=%s", uri, resp.status_code, None)
            raise RuntimeError(f"ExportServerScreenShot failed status={resp.status_code}")

        data = resp.json()
        b64 = data.get("ServerScreenShotFile")
        if not b64:
            logger.error("no ServerScreenShotFile returned for %s", uri)
            raise RuntimeError("no screenshot data returned")

        try:
            raw = base64.b64decode(b64)
        except Exception:
            logger.exception("invalid base64 in ServerScreenShotFile")
            raise

        # create PIL Image from bytes
        try:
            with io.BytesIO(raw) as bio:
                im = Image.open(bio)
                im.load()
        except Exception:
            logger.exception("failed to create image from screenshot bytes")
            raise RuntimeError("invalid image data")

        # resize longest side to 1000 while preserving aspect ratio
        w, h = im.size
        max_side = max(w, h)
        if max_side > 1000:
            scale = 1000 / float(max_side)
            new_size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
            im = im.resize(new_size, Image.LANCZOS)
            logger.info("Resized screenshot from %dx%d to %dx%d", w, h, new_size[0], new_size[1])
        else:
            logger.info("Screenshot size %dx%d <=1000, not resized", w, h)

        # encode back to PNG bytes
        out = io.BytesIO()
        try:
            im.save(out, format="PNG")
            png_bytes = out.getvalue()
        except Exception:
            logger.exception("failed to encode image to PNG")
            raise RuntimeError("failed to encode image")

        logger.info("ExportServerScreenShot: returning %d bytes", len(png_bytes))
        # write PNG bytes to a temporary file and return the path
        try:
            import tempfile

            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tf:
                tf.write(png_bytes)
                temp_path = tf.name
            logger.info("ExportServerScreenShot: saved %d bytes to %s", len(png_bytes), temp_path)
            return temp_path
        except Exception:
            logger.exception("failed to write screenshot to tempfile")
            raise
