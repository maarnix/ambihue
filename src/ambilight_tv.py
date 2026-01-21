import json
import logging
import os
import time
from typing import Any, Dict

import httpx
from httpx import DigestAuth
import urllib3

logger = logging.getLogger(__name__)

# Suppress "Unverified HTTPS request is being made" error message
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class AmbilightTV:
    def __init__(self, config: Dict[str, Any]) -> None:
        # Credentials for JointSpace v6 API
        self._user = config.get("user")
        self._password = config.get("password")

        auth = None
        if self._user and self._password:
            auth = DigestAuth(self._user, self._password)

        # HTTP client with optional DigestAuth
        self._client = httpx.Client(verify=False, http2=True, auth=auth)

        # Connection / API parameters
        self._protocol = config.get("protocol", "https://")
        self._ip = config["ip"]
        self._port = config.get("port", "1926")
        self._api_version = config.get("api_version", "6")

        # Build the full API endpoint path
        self._path = config.get("path", "ambilight/processed")
        self._full_path = (
            f"{self._protocol}{self._ip}:{self._port}/{self._api_version}/{self._path}"
        )

        # Startup and boot timing parameters
        self._wait_for_startup_s = config.get("wait_for_startup_s", 29)
        self.power_on_time_s = config.get("power_on_time_s", 8)

    def wait_for_startup(self) -> None:
        """Waits for TV to become reachable. Waits indefinitely if wait_for_startup_s is 0."""
        if self._wait_for_startup_s == 0:
            # Infinite waiting mode - for HA automation users
            self._wait_indefinitely()
        else:
            # Timeout mode - current behavior
            self._wait_with_timeout()

    def _wait_indefinitely(self) -> None:
        """Wait indefinitely for TV to come online."""
        logger.info(f"Waiting indefinitely for TV at {self._ip} (wait_for_startup_s=0)")
        wait_iteration = 0
        was_offline = False

        while True:
            response = os.system(f"ping -c 1 -W 1 {self._ip} > /dev/null 2>&1")

            if response == 0:
                if was_offline:
                    logger.info(f"TV is now online, waiting {self.power_on_time_s}s for full boot...")
                    time.sleep(self.power_on_time_s)
                else:
                    logger.info("TV is online")
                return

            was_offline = True
            if wait_iteration % 60 == 0:  # Log every 5 minutes (5s * 60)
                logger.warning(f"Waiting for TV at {self._ip} to become available...")

            wait_iteration += 1
            time.sleep(5)  # Poll every 5 seconds

    def _wait_with_timeout(self) -> None:
        """Wait with timeout - current behavior."""
        _was_enabled = True

        for cnt in range(int(self._wait_for_startup_s / 3)):
            response = os.system(f"ping -c 1 -W 1 {self._ip} > /dev/null 2>&1")
            if response == 0:
                if _was_enabled is False:
                    logger.error(f"TV is powering on... add {self.power_on_time_s}s more")
                    time.sleep(self.power_on_time_s)
                return

            _was_enabled = False
            logger.error(f"TV is not responding for {cnt*3}/{self._wait_for_startup_s}s")
            time.sleep(2)

        raise RuntimeError(f"TV IS NOT RESPONDING FOR {self._wait_for_startup_s}s")

    def get_ambilight_raw(self) -> Any:
        # logger.debug(f"Sending GET request to:\n{self._full_path}")
        # HTTPX is faster than requests: 55ms vs 90ms
        try:
            # _time = time.time()
            response = self._client.get(self._full_path, timeout=0.2)
            # elapsed_time = int((time.time() - _time) * 1000)  # convert to ms
            # logger.debug(f"[tv_get_request] elapsed time: {elapsed_time} ms")
        except httpx.RequestError as err:
            raise RuntimeError(err) from err

        return response.text

    def get_ambilight_json(self) -> Dict[str, Any]:
        response_text = self.get_ambilight_raw()

        try:
            data = json.loads(response_text)
            assert isinstance(data, dict), "Response is not a JSON object"
            # logger.debug(f"data:\n{data}\n")
        except json.JSONDecodeError as err:
            logger.error(f"Decoding JSON error:\n{response_text}")
            raise err
        return data
