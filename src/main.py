import logging
import sys
import time
from json import JSONDecodeError
from pathlib import Path
from time import sleep
from typing import Any, Dict, Optional, Union

from src.ambilight_tv import AmbilightTV  # TODO install
from src.color_mixer import ColorMixer
from src.config_loader import ConfigLoader
from src.hue_entertainment import HueEntertainmentGroupKit, detect_hue_entertainment

logger = logging.getLogger(__name__)


class AmbiHueMain:
    """Main class to run the AmbiHue application."""

    def __init__(self, config_path: Union[str, Path] = "userconfig.yaml") -> None:
        """Initialize the AmbiHue main class."""
        self._config_loader = ConfigLoader(config_path)

        self._tv = AmbilightTV(self._config_loader.get_ambilight_tv())
        self._mixer = ColorMixer()

        self._light_setup = self._config_loader.get_lights_setup()

        self._tv_error_cnt = 0
        self._tv_is_online = True  # Track TV state
        self._tv_has_content = True  # Track if TV is showing actual content (not all black)

        # Get runtime error threshold from config
        tv_config = self._config_loader.get_ambilight_tv()
        self._runtime_error_threshold = tv_config.get("runtime_error_threshold", 10)

        # Get refresh rate from config (in milliseconds)
        self._refresh_rate_ms = tv_config.get("refresh_rate_ms", 10)
        self._refresh_rate_s = self._refresh_rate_ms / 1000.0

        # Get idle refresh rate from config (when TV is black/off)
        self._idle_refresh_rate_ms = tv_config.get("idle_refresh_rate_ms", 1000)
        self._idle_refresh_rate_s = self._idle_refresh_rate_ms / 1000.0

        self._previous_time = time.time()

        # Hue will be initialized after TV is ready
        self._hue = None

    def _read_tv(self) -> Optional[Dict[str, Any]]:
        """Read the Ambilight TV data.

        If the TV is not reachable, return None.

        Returns:
            Optional[Dict[str, Any]]: The JSON data from the TV or None if an error occurs.
        """
        try:
            tv_data = self._tv.get_ambilight_json()

            # TV came back online
            if not self._tv_is_online:
                logger.info("TV connection restored!")
                self._tv_is_online = True

            self._tv_error_cnt = 0  # reset error count on success
            return tv_data

        except (JSONDecodeError, RuntimeError) as err:
            self._tv_error_cnt += 1

            # Log only on state transition
            if self._tv_is_online:
                logger.warning(f"TV connection lost: {err}")
                self._tv_is_online = False
            elif self._tv_error_cnt % 100 == 0:
                # Log every ~1 second during extended offline period
                logger.debug(f"TV still offline (error count: {self._tv_error_cnt})")

            # Exit if threshold is set and reached
            if self._runtime_error_threshold > 0 and self._tv_error_cnt > self._runtime_error_threshold:
                self._exit(10)

            return None  # return None if an error occurs

    def _debug_log_time(self, msg: str) -> None:
        if logger.getEffectiveLevel() > logging.DEBUG:
            return  # skip if debug logging is not enabled

        current_time = time.time()
        elapsed_time = int((current_time - self._previous_time) * 1000)  # convert to ms
        logger.warning(f"[{msg}] elapsed time: {elapsed_time} ms")
        self._previous_time = current_time

    def run(self) -> None:
        """Run the main loop of the AmbiHue application."""
        self._tv.wait_for_startup()
        logger.info("TV is ready, waiting for content before starting Hue Entertainment...")

        # Don't initialize Hue connection until TV has actual content
        self._hue = None
        logger.info("Starting AmbiHue application in polling mode...")

        while True:  # while true
            # Use idle refresh rate when no content, normal rate when syncing
            current_refresh_rate = self._idle_refresh_rate_s if self._hue is None else self._refresh_rate_s
            sleep(current_refresh_rate)
            self._debug_log_time("sleep")

            tv_data = self._read_tv()
            if tv_data is None:
                continue  # skip this loop if TV data is not available this time
            self._debug_log_time("read_tv")

            self._mixer.apply_tv_data(tv_data)
            self._mixer.print_colors()
            self._debug_log_time("print_colors")

            # Check if TV screen is all black (no content playing)
            is_black = self._mixer.is_all_black()
            logger.debug(f"is_all_black() returned: {is_black}")
            if is_black:
                # TV is showing black screen - terminate sync session and go to idle mode
                if self._tv_has_content:
                    logger.info("TV screen is black (no content), terminating Entertainment session")
                    self._tv_has_content = False
                    if self._hue is not None:
                        logger.info("Stopping Hue Entertainment stream...")
                        del self._hue
                        self._hue = None
                        logger.info("Entering idle polling mode")
                continue  # skip to next loop in idle mode

            # TV has actual content - start/resume Entertainment session if not already active
            if self._hue is None:
                logger.info("TV content detected, starting Entertainment session...")
                self._tv_has_content = True
                self._hue = HueEntertainmentGroupKit(self._config_loader.get_hue_entertainment())
                logger.info("Entertainment session started, resuming light updates")
            elif not self._tv_has_content:
                # Content resumed after being black
                logger.info("TV content resumed")
                self._tv_has_content = True

            for light_name, light_data in self._light_setup.items():
                color = self._mixer.get_average_color(light_data["positions"])
                self._hue.set_color(light_data["id"], color.get_tuple())

                print_color = color.get_css_color_name_colored()
                logger.info(f"Light: {light_name} - {print_color} - {light_data} ")

            logger.info("\n\n")
            self._debug_log_time("set_color_x_lights")

    def _exit(self, exit_code: int = 0) -> None:
        """Exit the AmbiHue application."""
        logger.warning(f"Exiting AmbiHue application {exit_code}.")
        if self._hue is not None:
            del self._hue
        del self._tv
        sys.exit(exit_code)


def verify_tv() -> None:
    """Verify the Ambilight TV connection."""
    config = ConfigLoader().get_ambilight_tv()
    data = AmbilightTV(config).get_ambilight_json()
    mixer = ColorMixer()
    mixer.apply_tv_data(data)
    mixer.print_colors()


def verify_hue() -> None:
    """Verify the Hue Entertainment connection."""
    config = ConfigLoader().get_hue_entertainment()
    HueEntertainmentGroupKit(config).set_color(0, (255, 0, 0))  # check zero index light


def discover_hue() -> None:
    """Discover Hue Entertainment configuration."""
    detect_hue_entertainment()
