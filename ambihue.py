#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
"""Main docker script."""

import argparse
import json
import logging
import os
import signal
import sys
from typing import Any

import yaml

from src.ah_logger import init_logger
from src.hue_entertainment import discover_and_log_lights, pair_hue_bridge
from src.main import AmbiHueMain, discover_hue, verify_hue, verify_tv
from src.tv_discovery import PhilipsTVDiscovery, discover_tv_from_ha, handle_tv_pairing

logger = logging.getLogger(__name__)

# Placeholder values that trigger auto-setup
PLACEHOLDER_IPS = ("", "192.168.1.X", "replace_me")
PLACEHOLDER_CREDS = ("", "replace_me")


def _signal_handler(sig: Any, frame: Any) -> None:
    """Signal handler to handle Ctrl+C to gracefully exit app.

    Args:
        sig (Any): signal
        frame (Any): frame
    """
    assert sig
    assert frame
    logger.critical("Gracefully stopping all threads...")
    sys.exit(0)


# Register signal handler.
signal.signal(signal.SIGINT, _signal_handler)


def _init_parser() -> Any:
    parser = argparse.ArgumentParser(description="A script to handle test options.")
    parser.add_argument(
        "--verify",
        "-v",
        choices=["hue", "tv"],
        help="Specify which test option to handle.",
    )
    parser.add_argument(
        "--discover_hue",
        action="store_true",
        default=False,
        help="Detect Hue Entertainment configuration.",
    )
    parser.add_argument(
        "--loglevel",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="WARNING",  # Default log level
        help="Set the log level for the logger.",
    )

    try:
        import argcomplete  # pylint: disable=import-outside-toplevel

        argcomplete.autocomplete(parser)
    except ImportError:
        pass

    args = parser.parse_args()
    return args


_HA_OPTIONS_PATH = "/data/options.json"
_HA_STATE_PATH = "/data/ambihue_state.json"


def _load_saved_state() -> dict[str, Any]:
    """Load previously discovered state (persists across restarts).

    HA overwrites /data/options.json on restart, so we save
    discovered data separately.
    """
    if os.path.exists(_HA_STATE_PATH):
        try:
            with open(_HA_STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
            logger.info(f"Loaded saved state from {_HA_STATE_PATH}")
            return state
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load saved state: {e}")
    return {}


def _save_state(state: dict[str, Any]) -> None:
    """Save discovered state to persistent file."""
    with open(_HA_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    logger.info(f"Saved discovered state to {_HA_STATE_PATH}")


def _merge_state_into_config(config: dict[str, Any], state: dict[str, Any]) -> bool:
    """Merge saved state into config, filling in placeholder values.

    Returns True if any values were merged.
    """
    merged = False
    tv_config = config.get("ambilight_tv", {})
    hue_config = config.get("hue_entertainment_group", {})
    tv_state = state.get("ambilight_tv", {})
    hue_state = state.get("hue_entertainment_group", {})

    # Merge TV config - fill placeholders from saved state
    for key in ("ip", "user", "password"):
        current = tv_config.get(key, "")
        saved = tv_state.get(key, "")
        if current in PLACEHOLDER_IPS + PLACEHOLDER_CREDS and saved:
            tv_config[key] = saved
            merged = True

    # Merge Hue config - fill placeholders from saved state
    all_placeholders = PLACEHOLDER_IPS + PLACEHOLDER_CREDS
    for key in ("ip", "identification", "rid", "username", "app_id", "client_key"):
        current = hue_config.get(key, "")
        saved = hue_state.get(key, "")
        if current in all_placeholders and saved:
            hue_config[key] = saved
            merged = True

    # Merge swversion if still default
    if hue_state.get("swversion") and hue_config.get("swversion") == 1972004020:
        hue_config["swversion"] = hue_state["swversion"]
        merged = True

    # Merge lights_setup - if state has non-default lights and config still has defaults
    saved_lights = state.get("lights_setup", [])
    current_lights = config.get("lights_setup", [])
    if saved_lights:
        is_default = False
        if isinstance(current_lights, list):
            names = [l.get("name", "") for l in current_lights if isinstance(l, dict)]
            is_default = set(names) <= {"light1", "light2", ""}
        elif isinstance(current_lights, dict):
            is_default = set(current_lights.keys()) <= {"light1", "light2"}
        # Only replace defaults - saved lights from discovery are better
        saved_names = set()
        if isinstance(saved_lights, list):
            saved_names = {l.get("name", "") for l in saved_lights if isinstance(l, dict)}
        elif isinstance(saved_lights, dict):
            saved_names = set(saved_lights.keys())
        saved_is_default = saved_names <= {"light1", "light2", ""}

        if is_default and not saved_is_default:
            config["lights_setup"] = saved_lights
            merged = True
            logger.info(f"  Merged lights_setup from state ({len(saved_lights)} lights)")

    if merged:
        config["ambilight_tv"] = tv_config
        config["hue_entertainment_group"] = hue_config
        logger.info("Merged saved state into config")

    return merged


def _get_supervisor_token() -> str:
    """Get the Supervisor API token from env vars or s6-overlay filesystem.

    Returns empty string if not found.
    """
    # Check environment variables first
    token = os.environ.get("SUPERVISOR_TOKEN", "") or os.environ.get("HASSIO_TOKEN", "")
    if token:
        return token

    # s6-overlay v3 stores container env vars on the filesystem
    for path in (
        "/run/s6/container_environment/SUPERVISOR_TOKEN",
        "/var/run/s6/container_environment/SUPERVISOR_TOKEN",
        "/run/s6-rc/container_environment/SUPERVISOR_TOKEN",
    ):
        try:
            with open(path, "r", encoding="utf-8") as f:
                token = f.read().strip()
                if token:
                    logger.info(f"Found SUPERVISOR_TOKEN at {path}")
                    return token
        except (FileNotFoundError, PermissionError):
            continue

    return ""


def _update_ha_options(config: dict[str, Any]) -> None:
    """Try to update HA add-on options via Supervisor API.

    This updates the UI Configuration tab so discovered values show up.
    """
    token = _get_supervisor_token()
    if not token:
        logger.info("No SUPERVISOR_TOKEN found via env/filesystem, trying bashio fallback...")
        _update_ha_options_via_bashio(config)
        return

    try:
        import httpx
        response = httpx.post(
            "http://supervisor/addons/self/options",
            json={"options": config},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        if response.status_code == 200:
            logger.info("Updated HA add-on configuration (visible in UI)")
        else:
            logger.warning(f"Failed to update HA options: {response.status_code} {response.text}")
    except Exception as e:
        logger.warning(f"Could not update HA options: {e}")


def _update_ha_options_via_bashio(config: dict[str, Any]) -> None:
    """Fallback: update HA options using bashio CLI (available in HA base images)."""
    import subprocess
    import tempfile

    try:
        # Write config to temp file, then use curl with bashio's token
        config_json = json.dumps({"options": config})
        result = subprocess.run(
            [
                "bash", "-c",
                'curl -s -X POST '
                '-H "Authorization: Bearer ${SUPERVISOR_TOKEN}" '
                '-H "Content-Type: application/json" '
                f"-d '{config_json}' "
                'http://supervisor/addons/self/options'
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and '"result"' in result.stdout:
            logger.info(f"Updated HA options via bashio: {result.stdout.strip()}")
        else:
            logger.warning(f"bashio fallback failed: rc={result.returncode} stdout={result.stdout} stderr={result.stderr}")
    except Exception as e:
        logger.warning(f"bashio fallback error: {e}")


def _convert_ha_options_to_config(options: dict[str, Any]) -> dict[str, Any]:
    """Convert HA options.json format to nested config format expected by ConfigLoader.

    Args:
        options: Dictionary from HA options.json (nested structure)

    Returns:
        Nested config dictionary expected by ConfigLoader
    """
    # Get nested sections from HA options (names match config.yaml)
    tv_opts = options.get("ambilight_tv", {})
    hue_opts = options.get("hue_entertainment_group", {})
    lights_list = options.get("lights_setup", [])

    # Parse lights - positions stored as comma-separated string in HA config
    lights_setup = {}
    for light in lights_list:
        name = light.get("name", "")
        if not name:
            continue
        light_id = light.get("id", 0)
        positions_str = light.get("positions", "")
        try:
            positions = [int(p.strip()) for p in positions_str.split(",") if p.strip()]
        except ValueError:
            logger.warning(f"Invalid positions format for light '{name}': {positions_str}")
            positions = []
        lights_setup[name] = {"id": light_id, "positions": positions}

    return {
        "ambilight_tv": {
            "protocol": tv_opts.get("protocol", "https://"),
            "ip": tv_opts.get("ip", ""),
            "port": tv_opts.get("port", 1926),
            "api_version": tv_opts.get("api_version", 6),
            "path": "ambilight/processed",
            "user": tv_opts.get("user", ""),
            "password": tv_opts.get("password", ""),
            "wait_for_startup_s": 0,
            "power_on_time_s": 0,
            "runtime_error_threshold": 0,
            "refresh_rate_ms": tv_opts.get("refresh_rate_ms", 50),
            "idle_refresh_rate_ms": tv_opts.get("idle_refresh_rate_ms", 5000),
        },
        "hue_entertainment_group": {
            "_identification": hue_opts.get("identification", ""),
            "_rid": hue_opts.get("rid", ""),
            "_ip_address": hue_opts.get("ip", ""),
            "_swversion": hue_opts.get("swversion", 1972004020),
            "_username": hue_opts.get("username", ""),
            "_hue_app_id": hue_opts.get("app_id", ""),
            "_client_key": hue_opts.get("client_key", ""),
            "_name": "Hue Bridge",
            "index": hue_opts.get("index", 0),
        },
        "lights_setup": lights_setup,
    }


def _is_default_lights(lights: Any) -> bool:
    """Check if lights_setup still has default/auto-generated placeholder names.

    Returns True for: light1/light2, Light 0/Light 1, or empty names.
    """
    if isinstance(lights, list):
        names = [l.get("name", "") for l in lights if isinstance(l, dict)]
        if set(names) <= {"light1", "light2", ""}:
            return True
        # Auto-generated "Light N" names from previous discovery without real names
        if all(n.startswith("Light ") and n[6:].isdigit() for n in names if n):
            return True
    elif isinstance(lights, dict):
        keys = set(lights.keys())
        if keys <= {"light1", "light2"}:
            return True
        if all(k.startswith("Light ") and k[6:].isdigit() for k in keys if k):
            return True
    return False


def _assign_default_positions(num_lights: int, total_positions: int = 14) -> list[list[int]]:
    """Distribute TV ambilight positions evenly across discovered lights.

    Args:
        num_lights: Number of lights to distribute positions across
        total_positions: Total number of ambilight zones on the TV (default 14)

    Returns a list of position lists, one per light.
    """
    if num_lights <= 0:
        return []

    positions_per_light: list[list[int]] = []
    chunk_size = total_positions / num_lights

    for i in range(num_lights):
        start = int(round(i * chunk_size))
        end = int(round((i + 1) * chunk_size))
        positions_per_light.append(list(range(start, end)))

    return positions_per_light


def _populate_lights_from_discovery(
    config: dict[str, Any], lights: list[dict[str, Any]], is_ha_mode: bool
) -> None:
    """Populate lights_setup in config from discovered entertainment area lights.

    Only overwrites if lights_setup still has default/placeholder values.
    Auto-assigns default positions spread evenly around the TV perimeter.

    Args:
        config: Full config dict to update
        lights: List of dicts with 'name' and 'id' from discover_and_log_lights()
        is_ha_mode: Whether running in Home Assistant mode
    """
    if not lights:
        return

    current_lights = config.get("lights_setup", [])

    # Check if current lights are still default/auto-generated placeholders
    is_default = False
    if isinstance(current_lights, list):
        names = [l.get("name", "") for l in current_lights if isinstance(l, dict)]
        is_default = set(names) <= {"light1", "light2", ""}
        # Also treat auto-generated "Light N" names as defaults worth refreshing
        if not is_default and all(n.startswith("Light ") and n[6:].isdigit() for n in names if n):
            is_default = True
    elif isinstance(current_lights, dict):
        keys = set(current_lights.keys())
        is_default = keys <= {"light1", "light2"}
        if not is_default and all(k.startswith("Light ") and k[6:].isdigit() for k in keys if k):
            is_default = True

    if not is_default:
        logger.info("lights_setup already configured, not overwriting with discovered lights")
        return

    # Auto-assign default positions spread evenly around TV perimeter
    default_positions = _assign_default_positions(len(lights))

    if is_ha_mode:
        # HA format: list of {name, id, positions} - positions as comma-separated string
        config["lights_setup"] = [
            {
                "name": light["name"],
                "id": light["id"],
                "positions": ",".join(str(p) for p in default_positions[i]),
            }
            for i, light in enumerate(lights)
        ]
    else:
        # Standalone format: dict of {name: {id, positions}}
        config["lights_setup"] = {
            light["name"]: {"id": light["id"], "positions": default_positions[i]}
            for i, light in enumerate(lights)
        }

    for i, light in enumerate(lights):
        logger.info(f"  {light['name']} (id={light['id']}): positions {default_positions[i]}")
    logger.info(f"Populated lights_setup with {len(lights)} lights and default positions")


def _fix_empty_positions(config: dict[str, Any], is_ha_mode: bool) -> bool:
    """Fix lights that have empty positions by assigning defaults.

    Returns True if any positions were fixed.
    """
    lights = config.get("lights_setup", [])
    if not lights:
        return False

    # Check if any light has empty positions
    needs_fix = False
    if isinstance(lights, list):
        for light in lights:
            pos = light.get("positions", "")
            if not pos or pos == "":
                needs_fix = True
                break
    elif isinstance(lights, dict):
        for light_data in lights.values():
            pos = light_data.get("positions", [])
            if not pos:
                needs_fix = True
                break

    if not needs_fix:
        return False

    num_lights = len(lights) if isinstance(lights, list) else len(lights)
    default_positions = _assign_default_positions(num_lights)

    if isinstance(lights, list):
        for i, light in enumerate(lights):
            pos = light.get("positions", "")
            if not pos or pos == "":
                light["positions"] = ",".join(str(p) for p in default_positions[i])
                logger.info(f"  Auto-assigned positions {default_positions[i]} to {light.get('name', f'light {i}')}")
    elif isinstance(lights, dict):
        for i, (name, light_data) in enumerate(lights.items()):
            pos = light_data.get("positions", [])
            if not pos:
                light_data["positions"] = default_positions[i]
                logger.info(f"  Auto-assigned positions {default_positions[i]} to {name}")

    logger.info("Fixed empty light positions with defaults")
    return True


def _persist_config(config: dict[str, Any], is_ha_mode: bool) -> None:
    """Save config to persistent storage immediately.

    Called after each setup step to ensure progress is not lost
    (e.g., if TV pairing triggers sys.exit before the end).
    """
    if is_ha_mode:
        _save_state(config)
        with open(_HA_OPTIONS_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        _update_ha_options(config)
    else:
        with open("userconfig.yaml", "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False)
        logger.info("Updated config saved to userconfig.yaml")


def _check_and_run_setup() -> bool:
    """Run auto-setup if config has placeholder values.

    Returns:
        True if setup was run and config was updated
    """
    setup_performed = False

    # Load raw config based on environment
    if os.path.exists(_HA_OPTIONS_PATH):
        with open(_HA_OPTIONS_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        is_ha_mode = True

        # Merge previously discovered state into HA config
        # (HA overwrites options.json on restart, so we save state separately)
        saved_state = _load_saved_state()
        if saved_state:
            merged = _merge_state_into_config(config, saved_state)
            if merged:
                # Write merged config back to options.json so _get_config_path() picks it up
                with open(_HA_OPTIONS_PATH, "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=2)
                logger.info("Wrote merged config to options.json")
                # Also update Supervisor's copy so the HA UI shows merged values
                _update_ha_options(config)

        # Fix any lights that have empty positions (from previous discovery without defaults)
        if _fix_empty_positions(config, is_ha_mode):
            with open(_HA_OPTIONS_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            _save_state(config)
            setup_performed = True

    elif os.path.exists("userconfig.yaml"):
        with open("userconfig.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        is_ha_mode = False
    else:
        logger.info("No config file found, skipping auto-setup")
        return False

    tv_config = config.get("ambilight_tv", {})
    hue_config = config.get("hue_entertainment_group", {})

    # Get current values
    tv_ip = tv_config.get("ip", "")
    hue_id = hue_config.get("identification", "") if is_ha_mode else hue_config.get("_identification", "")
    hue_ip_key = "ip" if is_ha_mode else "_ip_address"
    hue_ip = hue_config.get(hue_ip_key, "")
    pairing_pin = tv_config.get("pairing_pin", "")

    # === RECOVER MISSING HUE BRIDGE IP ===
    # If we have credentials but the IP is a placeholder (e.g. state was corrupted),
    # re-discover the bridge IP via the portal without requiring button press.
    if hue_id not in PLACEHOLDER_CREDS and hue_ip in PLACEHOLDER_IPS:
        logger.info("Hue credentials found but bridge IP is missing, re-discovering...")
        from src.hue_entertainment import _discover_bridge_ip_via_portal
        recovered_ip = _discover_bridge_ip_via_portal()
        if recovered_ip:
            hue_config[hue_ip_key] = recovered_ip
            config["hue_entertainment_group"] = hue_config
            setup_performed = True
            logger.info(f"Recovered Hue Bridge IP: {recovered_ip}")
            _persist_config(config, is_ha_mode)
        else:
            logger.warning("Could not re-discover Hue Bridge IP. Set it manually in config.")

    # === RECOVER MISSING HUE RID / POPULATE LIGHTS ===
    # If we have credentials and IP but RID is a placeholder, discover it from bridge.
    hue_rid_key = "rid" if is_ha_mode else "_rid"
    hue_rid = hue_config.get(hue_rid_key, "")
    hue_ip = hue_config.get(hue_ip_key, "")  # Re-read after possible recovery
    if hue_id not in PLACEHOLDER_CREDS and hue_ip not in PLACEHOLDER_IPS and hue_rid in PLACEHOLDER_CREDS:
        logger.info("Hue RID is missing, discovering entertainment areas...")
        # Build a config dict compatible with discover_and_log_lights
        temp_hue_config = _convert_ha_options_to_config(config)["hue_entertainment_group"] if is_ha_mode else hue_config
        discovery_result = discover_and_log_lights(temp_hue_config)
        if discovery_result:
            hue_config[hue_rid_key] = discovery_result["rid"]
            config["hue_entertainment_group"] = hue_config
            _populate_lights_from_discovery(config, discovery_result["lights"], is_ha_mode)
            setup_performed = True
            logger.info(f"Recovered Hue RID: {discovery_result['rid']}")
            _persist_config(config, is_ha_mode)

    # === POPULATE LIGHTS FROM BRIDGE ===
    # If Hue is fully configured but lights_setup still has defaults, discover lights.
    hue_ip = hue_config.get(hue_ip_key, "")  # Re-read after possible recovery
    hue_rid = hue_config.get(hue_rid_key, "")
    if (hue_id not in PLACEHOLDER_CREDS and hue_ip not in PLACEHOLDER_IPS
            and hue_rid not in PLACEHOLDER_CREDS):
        current_lights = config.get("lights_setup", [])
        is_default_lights = _is_default_lights(current_lights)

        if is_default_lights:
            logger.info("lights_setup has default values, discovering lights from bridge...")
            temp_hue_config = _convert_ha_options_to_config(config)["hue_entertainment_group"] if is_ha_mode else hue_config
            discovery_result = discover_and_log_lights(temp_hue_config)
            if discovery_result and discovery_result.get("lights"):
                _populate_lights_from_discovery(config, discovery_result["lights"], is_ha_mode)
                setup_performed = True
                _persist_config(config, is_ha_mode)

    # === HUE BRIDGE SETUP ===
    if hue_id in PLACEHOLDER_CREDS:
        logger.info("Hue credentials not configured, starting discovery...")
        try:
            new_hue_config = pair_hue_bridge(timeout_seconds=30)

            # Update config with new credentials
            if is_ha_mode:
                config["hue_entertainment_group"] = {
                    "ip": new_hue_config["_ip_address"],
                    "identification": new_hue_config["_identification"],
                    "rid": new_hue_config["_rid"],
                    "username": new_hue_config["_username"],
                    "app_id": new_hue_config["_hue_app_id"],
                    "client_key": new_hue_config["_client_key"],
                    "swversion": new_hue_config["_swversion"],
                    "index": new_hue_config.get("index", 0),
                }
            else:
                config["hue_entertainment_group"] = new_hue_config

            setup_performed = True
            discovery_result = discover_and_log_lights(new_hue_config)

            # Save discovered RID and lights back into config
            if discovery_result:
                rid = discovery_result["rid"]
                if rid:
                    new_hue_config["_rid"] = rid
                    if is_ha_mode:
                        config["hue_entertainment_group"]["rid"] = rid
                    else:
                        config["hue_entertainment_group"]["_rid"] = rid
                _populate_lights_from_discovery(config, discovery_result["lights"], is_ha_mode)

            # Save immediately so Hue credentials persist even if TV pairing exits
            _persist_config(config, is_ha_mode)

        except RuntimeError as e:
            logger.error(f"Hue setup failed: {e}")
            sys.exit(1)

    # === TV DISCOVERY ===
    if tv_ip in PLACEHOLDER_IPS:
        logger.info("TV IP not configured, searching for Philips TVs...")

        # Try HA device registry first (if TV is already set up in HA)
        found_ip = discover_tv_from_ha()

        # Fall back to SSDP network scan
        if not found_ip:
            discovery = PhilipsTVDiscovery(timeout=5)
            tvs = discovery.discover_tvs()
            if tvs:
                found_ip = tvs[0]["ip"]

        if found_ip:
            tv_ip = found_ip
            tv_config["ip"] = tv_ip
            config["ambilight_tv"] = tv_config
            setup_performed = True
            logger.info(f"Found TV at {tv_ip}")

            # Save immediately so TV IP persists
            _persist_config(config, is_ha_mode)
        else:
            logger.warning("No Philips TVs found. Set TV IP manually in config.")

    # === TV PAIRING ===
    # Only attempt pairing if we don't already have credentials
    tv_user = tv_config.get("user", "")
    tv_password = tv_config.get("password", "")
    has_credentials = tv_user and tv_user not in PLACEHOLDER_CREDS

    if tv_ip and tv_ip not in PLACEHOLDER_IPS and not has_credentials:
        protocol = tv_config.get("protocol", "https://")
        port = tv_config.get("port", 1926)
        api_version = tv_config.get("api_version", 6)

        try:
            user, password = handle_tv_pairing(
                tv_ip=tv_ip,
                pairing_pin=pairing_pin,
                port=port,
                protocol=protocol,
                api_version=api_version,
            )

            if user == "__PIN_REQUIRED__":
                # TV pairing needs user to enter PIN and restart.
                # State is already saved (Hue creds persisted above),
                # and auth_key was saved by handle_tv_pairing itself.
                sys.exit(0)

            if user:  # Android TV was paired
                tv_config["user"] = user
                tv_config["password"] = password
                tv_config["pairing_pin"] = ""  # Clear PIN after use
                config["ambilight_tv"] = tv_config
                setup_performed = True

                # Save TV credentials immediately
                _persist_config(config, is_ha_mode)

        except RuntimeError as e:
            logger.error(f"TV pairing failed: {e}")
            # Don't exit - might just be wrong PIN

    return setup_performed


def _get_config_path() -> str:
    """Get the path to config file.

    In HA mode, reads /data/options.json and converts to nested format.
    In dev mode, uses userconfig.yaml directly.
    """
    # Home Assistant: use /data/options.json (HA add-on Configuration tab)
    if os.path.exists(_HA_OPTIONS_PATH):
        logger.info(f"Using config from {_HA_OPTIONS_PATH} (Home Assistant mode)")
        # Convert HA flat options to nested config and write to temp file
        with open(_HA_OPTIONS_PATH, "r", encoding="utf-8") as f:
            ha_options = json.load(f)
        nested_config = _convert_ha_options_to_config(ha_options)
        # Debug: log the converted hue config
        hue_conv = nested_config.get("hue_entertainment_group", {})
        hue_conv_debug = {k: ("***" if k in ("_client_key",) else v) for k, v in hue_conv.items()}
        logger.info(f"Converted Hue config for runtime: {hue_conv_debug}")
        # Write converted config to a temp location
        converted_path = "/tmp/ambihue_config.yaml"
        with open(converted_path, "w", encoding="utf-8") as f:
            yaml.dump(nested_config, f, default_flow_style=False)
        logger.debug(f"Converted HA options to {converted_path}")
        return converted_path

    # Local dev mode: use userconfig.yaml directly
    if os.path.exists("userconfig.yaml"):
        logger.info("Using local userconfig.yaml (dev mode)")
        return "userconfig.yaml"

    raise FileNotFoundError(
        "No config found. Configure the add-on in Home Assistant Configuration tab, "
        "or create userconfig.yaml for local development."
    )


def main() -> None:
    """Main function to run the spawn AmbiHue. Enable logs and parse input."""
    args = _init_parser()

    init_logger(args.loglevel)

    # Handle verify/discover commands first (don't need full config)
    if args.verify == "hue":
        verify_hue()
        return
    if args.verify == "tv":
        verify_tv()
        return
    if args.discover_hue:
        discover_hue()
        return

    # Run auto-setup if config has placeholder values
    # This may update the config file and/or exit for TV PIN entry
    _check_and_run_setup()

    # Get config path (may have been updated by setup)
    config_path = _get_config_path()

    AmbiHueMain(config_path).run()


if __name__ == "__main__":
    main()
