"""Hue Light Bridge by Entertainment.

https://github.com/hrdasdominik/hue-entertainment-pykit/blob/main/src/hue_entertainment_pykit.py
"""

import logging
import time
from typing import Any, Dict, Optional, Tuple

from hue_entertainment_pykit import Streaming  # type: ignore  # missing some types
from hue_entertainment_pykit import Discovery, Entertainment, create_bridge, setup_logs

logger = logging.getLogger(__name__)


class HueEntertainmentGroupKit:

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize the Hue Entertainment Group Kit.

        Args:
            config (Dict[str, Any]): Configuration dictionary containing the necessary parameters.

        Based on official documentation:
        https://github.com/hrdasdominik/hue-entertainment-pykit?tab=readme-ov-file#streaming
        """
        assert isinstance(config, dict), "Configuration must be a dictionary."

        # Initialize default logging (WARNING level to reduce thread spam)
        setup_logs(level=logging.WARNING)

        # Set up the Bridge instance with the all needed configuration
        self._bridge = create_bridge(
            identification=config["_identification"],
            rid=config["_rid"],
            ip_address=config["_ip_address"],
            swversion=config["_swversion"],
            username=config["_username"],
            hue_app_id=config["_hue_app_id"],
            clientkey=config["_client_key"],
            name=config["_name"],
        )

        # Set up the Entertainment API service
        entertainment_service = Entertainment(self._bridge)

        # Fetch all Entertainment Configurations on the Hue bridge
        entertainment_configs = entertainment_service.get_entertainment_configs()

        # Add choose Entertainment Area selection logic
        entertainment_config = list(entertainment_configs.values())[config["index"]]

        # Set up the Streaming service
        self._streaming = Streaming(
            self._bridge, entertainment_config, entertainment_service.get_ent_conf_repo()
        )

        # Start streaming messages to the bridge
        self._streaming.start_stream()

        # Set the color space to xyb or rgb
        self._streaming.set_color_space("rgb")

    def set_color(
        self,
        light_id: int,
        color: Tuple[int, int, int],
    ) -> None:
        """Set given light to given color.

        Args:
            light_id (int): light ID inside the Entertainment API
            color (Tuple[int, int, int]): tuple for the color RGB8(int)
        """
        self._streaming.set_input((*color, light_id))

    def __del__(self) -> None:
        if not hasattr(self, "_streaming"):
            return
        logger.warning("Stop streaming in 10s ...")

        # For the purpose of example sleep is used for all inputs to process before stop_stream is
        # called
        # Inputs are set inside Event queue meaning they're on another thread so user can interact
        # with application continuously
        time.sleep(0.1)

        # Stop the streaming session
        self._streaming.stop_stream()


def detect_hue_entertainment() -> None:
    """Detect Hue Entertainment configuration (legacy CLI version)."""
    print("Get ready to click Hue Bridge button. Sleeping for 5 seconds...")
    time.sleep(5)  # wait for user to click the button

    print("Click Hue Bridge button now!")
    bridges = Discovery().discover_bridges()

    obj_list = list(bridges.values())
    assert (
        len(obj_list) > 0
    ), "No Hue bridges found. Check your network connection. Did you click the button?"

    obj = obj_list[0]
    print("\nCopy & paste configuration to userconfig.yaml:\n")
    print(
        f'  _identification: "{obj._identification}"\n'  # pylint: disable=protected-access
        f'  _rid: "{obj._rid}"\n'  # pylint: disable=protected-access
        f'  _ip_address: "{obj._ip_address}"\n'  # pylint: disable=protected-access
        f"  _swversion: {obj._swversion}\n"  # pylint: disable=protected-access
        f'  _username: "{obj._username}"\n'  # pylint: disable=protected-access
        f'  _hue_app_id: "{obj._hue_app_id}"\n'  # pylint: disable=protected-access
        f'  _client_key: "{obj._client_key}"\n'  # pylint: disable=protected-access
        f'  _name: "{obj._name}"\n'  # pylint: disable=protected-access
    )


def _discover_bridge_ip_via_portal() -> Optional[str]:
    """Discover Hue Bridge IP via Philips discovery portal.

    This works in Docker containers where mDNS doesn't.

    Returns:
        Bridge IP address or None if not found
    """
    import httpx

    try:
        logger.warning("Querying Philips discovery portal (discovery.meethue.com)...")
        response = httpx.get("https://discovery.meethue.com/", timeout=10.0)
        logger.warning(f"Discovery portal response: {response.status_code}")

        if response.status_code == 200:
            bridges = response.json()
            logger.warning(f"Discovery portal found {len(bridges)} bridge(s)")

            if bridges and len(bridges) > 0:
                ip = bridges[0].get("internalipaddress")
                if ip:
                    logger.warning(f"Found Hue Bridge via discovery portal: {ip}")
                    return ip
                else:
                    logger.warning("Bridge found but no IP address in response")
        else:
            logger.warning(f"Discovery portal returned status {response.status_code}")

    except httpx.TimeoutException:
        logger.warning("Discovery portal timed out - check internet connection")
    except Exception as e:
        logger.warning(f"Discovery portal error: {e}")

    return None


def _pair_bridge_directly(ip: str) -> Optional[Dict[str, Any]]:
    """Pair with Hue Bridge using direct HTTP API calls.

    Bypasses mDNS discovery - works in Docker containers.

    Args:
        ip: Bridge IP address

    Returns:
        Dict with bridge credentials or None if button not pressed
    """
    import secrets
    import httpx

    # Generate unique identifiers for this app
    app_id = f"ambihue#{secrets.token_hex(4)}"

    # Request application registration (requires button press)
    pair_data = {
        "devicetype": app_id,
        "generateclientkey": True,
    }

    try:
        response = httpx.post(
            f"https://{ip}/api",
            json=pair_data,
            timeout=5.0,
            verify=False,  # Bridge uses self-signed cert
        )

        if response.status_code == 200:
            result = response.json()
            if isinstance(result, list) and len(result) > 0:
                item = result[0]

                # Check for success
                if "success" in item:
                    success = item["success"]
                    username = success.get("username", "")
                    client_key = success.get("clientkey", "")

                    if username and client_key:
                        logger.warning(f"Successfully paired with Hue Bridge at {ip}")

                        # Get bridge config for additional info
                        config_resp = httpx.get(
                            f"https://{ip}/api/{username}/config",
                            timeout=5.0,
                            verify=False,
                        )
                        config = config_resp.json() if config_resp.status_code == 200 else {}

                        # swversion may be string from API - ensure int
                        sw = config.get("swversion", 0)
                        try:
                            sw = int(sw)
                        except (ValueError, TypeError):
                            sw = 0

                        return {
                            "_identification": config.get("bridgeid", ""),
                            "_rid": "",  # Will be filled by entertainment area discovery
                            "_ip_address": ip,
                            "_swversion": sw,
                            "_username": username,
                            "_hue_app_id": app_id,
                            "_client_key": client_key,
                            "_name": config.get("name", "Hue Bridge"),
                            "index": 0,
                        }

                # Check for "link button not pressed" error (error 101)
                if "error" in item:
                    error = item["error"]
                    if error.get("type") == 101:
                        logger.warning("Waiting for bridge button press...")
                    else:
                        logger.warning(f"Bridge error: {error.get('description', 'unknown')}")

    except httpx.ConnectError:
        logger.warning(f"Cannot connect to bridge at {ip} - check IP address")
    except Exception as e:
        logger.warning(f"Direct pairing error: {e}")

    return None


def pair_hue_bridge(timeout_seconds: int = 30) -> Dict[str, Any]:
    """Pair with Hue Bridge - no CLI input required.

    User should press the bridge button before or during this call.
    Polls for up to timeout_seconds waiting for successful pairing.

    Uses HTTP discovery portal + direct API (works in Docker).
    Falls back to mDNS only if HTTP portal fails to find any bridge.

    Args:
        timeout_seconds: How long to wait for button press (default 30s)

    Returns:
        Dict with bridge credentials for config

    Raises:
        RuntimeError: If pairing times out
    """
    logger.warning("=" * 60)
    logger.warning("HUE BRIDGE PAIRING")
    logger.warning("Press the button on your Hue Bridge now!")
    logger.warning(f"Waiting up to {timeout_seconds} seconds...")
    logger.warning("=" * 60)

    # First, try to find bridge IP via HTTP portal (works in Docker)
    logger.warning("Searching for Hue Bridge via discovery portal...")
    bridge_ip = _discover_bridge_ip_via_portal()

    if bridge_ip:
        logger.warning(f"Found bridge at {bridge_ip}, waiting for button press...")
    else:
        logger.warning("Discovery portal didn't find bridge, will try mDNS fallback")

    attempts = timeout_seconds // 5  # Poll every 5 seconds

    for attempt in range(attempts):
        logger.warning(f"Pairing attempt {attempt + 1}/{attempts}...")

        # Method 1: Direct HTTP pairing (preferred - works in Docker)
        if bridge_ip:
            result = _pair_bridge_directly(bridge_ip)
            if result:
                return result
            # If button not pressed yet, just wait and retry (don't fall through to mDNS)
            time.sleep(5)
            continue

        # Method 2: Library's mDNS discovery (only if HTTP portal failed)
        # This is a fallback for non-Docker environments
        try:
            bridges = Discovery().discover_bridges()
            if bridges:
                bridge = list(bridges.values())[0]
                ip = bridge._ip_address  # pylint: disable=protected-access
                logger.info(f"Paired with Hue Bridge at {ip}")

                return {
                    "_identification": bridge._identification,  # pylint: disable=protected-access
                    "_rid": bridge._rid,  # pylint: disable=protected-access
                    "_ip_address": ip,
                    "_swversion": bridge._swversion,  # pylint: disable=protected-access
                    "_username": bridge._username,  # pylint: disable=protected-access
                    "_hue_app_id": bridge._hue_app_id,  # pylint: disable=protected-access
                    "_client_key": bridge._client_key,  # pylint: disable=protected-access
                    "_name": bridge._name,  # pylint: disable=protected-access
                    "index": 0,
                }
        except Exception as e:
            logger.debug(f"mDNS discovery failed: {e}")

        time.sleep(5)

    raise RuntimeError(
        "Hue Bridge pairing timed out. Press the bridge button and restart AmbiHue."
    )


def _fetch_light_names(ip: str, username: str) -> Dict[str, str]:
    """Fetch light names from Hue Bridge v2 API.

    Args:
        ip: Bridge IP address
        username: Bridge API username

    Returns:
        Dict mapping light resource RID to light name
    """
    import httpx

    names: Dict[str, str] = {}
    try:
        response = httpx.get(
            f"https://{ip}/clip/v2/resource/light",
            headers={"hue-application-key": username},
            verify=False,
            timeout=10.0,
        )
        if response.status_code == 200:
            data = response.json()
            for light in data.get("data", []):
                rid = light.get("id", "")
                name = light.get("metadata", {}).get("name", "")
                if rid and name:
                    names[rid] = name
                # Also map by owner device RID for cross-referencing
                owner_rid = light.get("owner", {}).get("rid", "")
                if owner_rid and name:
                    names[owner_rid] = name
        else:
            logger.debug(f"Light API returned {response.status_code}")
    except Exception as e:
        logger.debug(f"Failed to fetch light names: {e}")

    # Also try entertainment resources to map entertainment RIDs to device names
    try:
        response = httpx.get(
            f"https://{ip}/clip/v2/resource/entertainment",
            headers={"hue-application-key": username},
            verify=False,
            timeout=10.0,
        )
        if response.status_code == 200:
            data = response.json()
            for ent in data.get("data", []):
                ent_rid = ent.get("id", "")
                ent_name = ent.get("renderer_reference", {}).get("rid", "")
                # Map entertainment RID -> owner device RID -> light name
                owner_rid = ent.get("owner", {}).get("rid", "")
                if ent_rid and owner_rid and owner_rid in names:
                    names[ent_rid] = names[owner_rid]
    except Exception as e:
        logger.debug(f"Failed to fetch entertainment resources: {e}")

    return names


def discover_and_log_lights(bridge_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Discover entertainment zones and log lights for user reference.

    Args:
        bridge_config: Dict with bridge credentials

    Returns:
        Dict with 'rid' (str) and 'lights' (list of dicts with 'name' and 'id')
        for the selected entertainment area, or None if discovery fails.
    """
    try:
        selected_index = bridge_config.get("index", 0)

        # Create bridge instance
        bridge = create_bridge(
            identification=bridge_config["_identification"],
            rid=bridge_config["_rid"],
            ip_address=bridge_config["_ip_address"],
            swversion=bridge_config["_swversion"],
            username=bridge_config["_username"],
            hue_app_id=bridge_config["_hue_app_id"],
            clientkey=bridge_config["_client_key"],
            name=bridge_config.get("_name", "Hue Bridge"),
        )

        # Get entertainment configurations
        entertainment = Entertainment(bridge)
        configs = entertainment.get_entertainment_configs()

        if not configs:
            logger.warning("No Entertainment Areas found on Hue Bridge")
            logger.warning("Create an Entertainment Area in the Hue app first")
            return None

        # Fetch actual light names from Hue v2 API
        light_names = _fetch_light_names(
            bridge_config["_ip_address"],
            bridge_config["_username"],
        )
        if light_names:
            logger.warning(f"Fetched {len(light_names)} light/device names from bridge")

        logger.warning("=" * 60)
        logger.warning("ENTERTAINMENT ZONES DISCOVERED")
        logger.warning("=" * 60)

        selected_rid = None
        selected_lights: list[Dict[str, Any]] = []

        for idx, (rid, config) in enumerate(configs.items()):
            logger.warning(f"")
            marker = " (selected)" if idx == selected_index else ""
            logger.warning(f"Zone {idx}: {config.name}{marker}")
            logger.warning(f"  RID: {rid}")

            # Get lights in this entertainment area
            channels = config.channels if hasattr(config, "channels") else []
            zone_lights: list[Dict[str, Any]] = []
            if channels:
                logger.warning("  Lights:")
                for channel_idx, channel in enumerate(channels):
                    # Try to resolve actual light name from channel members
                    light_name = f"Light {channel_idx}"
                    if hasattr(channel, "members") and channel.members:
                        member_rid = channel.members[0].service.rid
                        if member_rid in light_names:
                            light_name = light_names[member_rid]
                    # Fallback: try light_services list (same order as channels)
                    if light_name.startswith("Light ") and hasattr(config, "light_services"):
                        if channel_idx < len(config.light_services):
                            svc_rid = config.light_services[channel_idx].rid
                            if svc_rid in light_names:
                                light_name = light_names[svc_rid]
                    logger.warning(f"    [{channel_idx}] {light_name}")
                    zone_lights.append({"name": light_name, "id": channel_idx})
            else:
                logger.warning("  No lights configured in this zone")

            if idx == selected_index:
                selected_rid = rid
                selected_lights = zone_lights

        logger.warning("")
        logger.warning("=" * 60)
        logger.warning("Set positions for each light in the Configuration tab.")
        logger.warning("Ambilight zone map (positions 0-16):")
        logger.warning("  [4]0T [5]1T [6]2T [7]3T [8]4T [9]5T [10]6T [11]7T [12]8T")
        logger.warning("  [3]3L                                              [13]0R")
        logger.warning("  [2]2L                                              [14]1R")
        logger.warning("  [1]1L                                              [15]2R")
        logger.warning("  [0]0L                                              [16]3R")
        logger.warning("=" * 60)

        return {"rid": selected_rid, "lights": selected_lights}

    except Exception as e:
        logger.error(f"Failed to discover lights: {e}")
        logger.warning("You can still configure lights manually in the config")
        return None
