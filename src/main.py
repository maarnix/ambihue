import logging
import sys
import time
from json import JSONDecodeError
from pathlib import Path
from time import sleep
from typing import Any, Dict, Optional, Union

from src.ambilight_tv import AmbilightTV
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

        # Black screen timeout: tear down session after this many seconds of black
        self._black_screen_timeout_s = tv_config.get("black_screen_timeout_s", 30)
        self._black_since: Optional[float] = None  # timestamp when screen went black

        # Status reporting
        self._frame_count = 0
        self._last_status_time = time.time()
        self._status_interval_s = 60  # Report status every 60 seconds

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

    def _log_status(self) -> None:
        """Log periodic status update every status_interval_s seconds."""
        current_time = time.time()
        elapsed = current_time - self._last_status_time

        if elapsed < self._status_interval_s:
            return  # not time yet

        if self._tv_has_content and self._frame_count > 0:
            # Streaming mode - report achieved Hz
            hz = self._frame_count / elapsed
            logger.warning(f"Status: Streaming at {hz:.1f} Hz ({self._frame_count} frames in {elapsed:.0f}s)")
        elif self._hue is not None:
            # Session active but screen is black
            logger.warning("Status: Session active - TV screen is black")
        else:
            # Waiting for first TV data
            logger.warning("Status: Idle mode - waiting for TV content")

        # Reset counters
        self._frame_count = 0
        self._last_status_time = current_time

    def run(self) -> None:
        """Run the main loop of the AmbiHue application."""
        self._tv.wait_for_startup()
        logger.info("TV is ready, waiting for content before starting Hue Entertainment...")

        # Don't initialize Hue connection until TV has actual content
        self._hue = None
        logger.info("Starting AmbiHue application in polling mode...")

        while True:  # while true
            # Use idle refresh rate when no session or screen is black, normal rate when streaming
            if self._hue is None or not self._tv_has_content:
                current_refresh_rate = self._idle_refresh_rate_s
            else:
                current_refresh_rate = self._refresh_rate_s
            sleep(current_refresh_rate)
            self._debug_log_time("sleep")

            # Periodic status logging
            self._log_status()

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
                if self._tv_has_content:
                    logger.info("TV screen is black, pausing light updates")
                    self._tv_has_content = False
                    self._black_since = time.time()

                # Check if we should tear down an active session
                if self._hue is not None and self._black_since is not None:
                    black_duration = time.time() - self._black_since

                    # Check TV power state after 5s of black to detect standby
                    if black_duration >= 5:
                        powerstate = self._tv.get_powerstate()
                        if powerstate and powerstate != "On":
                            logger.warning(f"TV power state: {powerstate}, stopping Entertainment session")
                            del self._hue
                            self._hue = None
                            self._black_since = None
                            continue

                    # Fallback: tear down after timeout even if powerstate check fails
                    if black_duration >= self._black_screen_timeout_s:
                        logger.warning(f"Black screen for {int(black_duration)}s, stopping Entertainment session")
                        del self._hue
                        self._hue = None
                        self._black_since = None

                continue  # skip - don't start session or send colors for black screen

            # Screen has content - reset black tracking
            if not self._tv_has_content:
                logger.info("TV content resumed")
            self._tv_has_content = True
            self._black_since = None

            # Start Entertainment session when we have actual content
            if self._hue is None:
                num_zones = self._mixer.num_colors
                logger.warning(f"TV content detected ({num_zones} ambilight zones), starting Entertainment session...")

                # Check if any light has out-of-range positions and reassign if needed
                has_out_of_range = False
                for light_data in self._light_setup.values():
                    positions = light_data.get("positions", [])
                    if any(p >= num_zones for p in positions):
                        has_out_of_range = True
                        break

                if has_out_of_range:
                    logger.warning(f"Reassigning light positions for {num_zones}-zone TV...")
                    lights = list(self._light_setup.keys())
                    chunk_size = num_zones / len(lights)
                    for i, light_name in enumerate(lights):
                        start = int(round(i * chunk_size))
                        end = int(round((i + 1) * chunk_size))
                        new_positions = list(range(start, end))
                        self._light_setup[light_name]["positions"] = new_positions
                        logger.warning(f"  {light_name}: positions {new_positions}")
                else:
                    for light_name, light_data in self._light_setup.items():
                        logger.warning(f"  {light_name}: positions {light_data.get('positions', [])}")

                self._hue = HueEntertainmentGroupKit(self._config_loader.get_hue_entertainment())
                logger.warning("Entertainment session started")

            for light_name, light_data in self._light_setup.items():
                color = self._mixer.get_average_color(light_data["positions"])
                self._hue.set_color(light_data["id"], color.get_tuple())

                print_color = color.get_css_color_name_colored()
                logger.debug(f"Light: {light_name} - {print_color} - {light_data} ")

            self._frame_count += 1
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
