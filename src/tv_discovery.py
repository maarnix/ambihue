"""Philips TV discovery and pairing module.

Provides SSDP-based discovery and JointSpace v6 pairing for Philips TVs.
Supports both Android TVs (PIN required) and non-Android TVs (no auth).
"""

import json
import logging
import socket
import time
from base64 import b64decode, b64encode
from secrets import token_hex
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx

logger = logging.getLogger(__name__)

# SSDP Constants
SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900
SSDP_MX = 3  # Maximum wait time in seconds
SSDP_ST = "ssdp:all"  # Search target

SSDP_REQUEST = f"""M-SEARCH * HTTP/1.1\r
HOST: {SSDP_ADDR}:{SSDP_PORT}\r
MAN: "ssdp:discover"\r
MX: {SSDP_MX}\r
ST: {SSDP_ST}\r
\r
"""


class PhilipsTVDiscovery:
    """Discovers Philips TVs on the local network using SSDP."""

    def __init__(self, timeout: int = 5) -> None:
        """Initialize discovery with timeout.

        Args:
            timeout: Seconds to wait for SSDP responses
        """
        self._timeout = timeout

    def discover_tvs(self) -> List[Dict[str, str]]:
        """Discover Philips TVs on the network.

        Returns:
            List of dicts with 'ip', 'name', 'model' for each discovered TV
        """
        logger.info("Searching for Philips TVs on the network...")

        responses = self._send_ssdp_search()
        tvs = []

        for location in responses:
            try:
                device_info = self._fetch_device_description(location)
                if device_info and self._is_philips_tv(device_info):
                    # Verify TV has JointSpace API
                    ip = urlparse(location).hostname
                    if ip and self._has_jointspace_api(ip):
                        tvs.append({
                            "ip": ip,
                            "name": device_info.get("friendlyName", "Philips TV"),
                            "model": device_info.get("modelName", "Unknown"),
                        })
                        logger.info(f"Found: {device_info.get('friendlyName')} at {ip}")
            except Exception as e:
                logger.debug(f"Error processing {location}: {e}")

        if not tvs:
            logger.warning("No Philips TVs found on the network")

        return tvs

    def _send_ssdp_search(self) -> List[str]:
        """Send SSDP M-SEARCH and collect location URLs.

        Returns:
            List of unique location URLs from responses
        """
        locations = set()

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(self._timeout)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

            sock.sendto(SSDP_REQUEST.encode(), (SSDP_ADDR, SSDP_PORT))

            start_time = time.time()
            while time.time() - start_time < self._timeout:
                try:
                    data, _ = sock.recvfrom(4096)
                    response = data.decode("utf-8", errors="ignore")

                    # Extract LOCATION header
                    for line in response.split("\r\n"):
                        if line.lower().startswith("location:"):
                            location = line.split(":", 1)[1].strip()
                            locations.add(location)
                            break
                except socket.timeout:
                    break
                except Exception as e:
                    logger.debug(f"Error receiving SSDP response: {e}")

            sock.close()
        except Exception as e:
            logger.error(f"SSDP search failed: {e}")

        return list(locations)

    def _fetch_device_description(self, location: str) -> Optional[Dict[str, str]]:
        """Fetch and parse UPnP device description XML.

        Args:
            location: URL to device description XML

        Returns:
            Dict with device info or None if failed
        """
        try:
            response = httpx.get(location, timeout=3.0, verify=False)
            if response.status_code != 200:
                return None

            root = ElementTree.fromstring(response.text)
            ns = {"upnp": "urn:schemas-upnp-org:device-1-0"}

            device = root.find(".//upnp:device", ns)
            if device is None:
                return None

            return {
                "friendlyName": self._get_text(device, "upnp:friendlyName", ns),
                "manufacturer": self._get_text(device, "upnp:manufacturer", ns),
                "modelName": self._get_text(device, "upnp:modelName", ns),
                "modelNumber": self._get_text(device, "upnp:modelNumber", ns),
            }
        except Exception as e:
            logger.debug(f"Failed to fetch device description: {e}")
            return None

    def _get_text(
        self, element: ElementTree.Element, path: str, ns: Dict[str, str]
    ) -> str:
        """Get text from XML element safely."""
        found = element.find(path, ns)
        return found.text if found is not None and found.text else ""

    def _is_philips_tv(self, device_info: Dict[str, str]) -> bool:
        """Check if device is a Philips TV."""
        manufacturer = device_info.get("manufacturer", "").lower()
        return "philips" in manufacturer or "royal philips" in manufacturer

    def _has_jointspace_api(self, ip: str) -> bool:
        """Check if TV has JointSpace API available.

        Args:
            ip: TV IP address

        Returns:
            True if JointSpace API responds
        """
        try:
            # Try to access the API without auth first
            response = httpx.get(
                f"https://{ip}:1926/6/system",
                timeout=2.0,
                verify=False,
            )
            # 200 = no auth needed, 401 = auth required (Android TV)
            return response.status_code in (200, 401)
        except Exception:
            return False


class PhilipsTVPairing:
    """Handles Philips TV authentication and pairing.

    Uses the JointSpace v6 pairing protocol with HMAC-SHA1 signatures,
    matching the ha-philipsjs implementation used by Home Assistant.
    """

    # Shared key for HMAC signature (from ha-philipsjs / Philips pairing protocol)
    _SHARED_KEY = b64decode(
        "ZmVay1EQVFOaZhwQ4Kv81ypLAZNczV9sG4KkseXWn1NEk6cXmPKO/MCa9sryslvLCFMnNe4Z4CPXzToowvhHvA=="
    )

    def __init__(
        self,
        ip: str,
        port: int = 1926,
        protocol: str = "https://",
        api_version: int = 6,
    ) -> None:
        """Initialize pairing handler.

        Args:
            ip: TV IP address
            port: API port (default 1926 for HTTPS)
            protocol: http:// or https://
            api_version: JointSpace API version
        """
        self._ip = ip
        self._port = port
        self._protocol = protocol
        self._api_version = api_version
        self._base_url = f"{protocol}{ip}:{port}/{api_version}"

        # HTTP client with SSL verification disabled (TV uses self-signed cert)
        self._client = httpx.Client(verify=False, timeout=5.0)

    @staticmethod
    def _hmac_signature(key: bytes, timestamp: str, pin: str) -> str:
        """Compute HMAC-SHA1 signature for pairing grant.

        Args:
            key: Shared secret key (decoded from base64)
            timestamp: Timestamp from pair/request response
            pin: PIN code displayed on TV

        Returns:
            Base64-encoded HMAC-SHA1 signature
        """
        import hashlib
        import hmac as hmac_mod

        h = hmac_mod.new(key, digestmod=hashlib.sha1)
        h.update(str(timestamp).encode("utf-8"))
        h.update(str(pin).encode("utf-8"))
        return b64encode(h.digest()).decode("utf-8")

    def try_connect_no_auth(self) -> bool:
        """Try to access TV API without authentication.

        Returns:
            True if TV allows unauthenticated access
        """
        try:
            response = self._client.get(f"{self._base_url}/ambilight/processed")
            return response.status_code == 200
        except Exception as e:
            logger.debug(f"No-auth connection failed: {e}")
            return False

    def request_pin_display(self) -> Dict[str, Any]:
        """Request TV to display PIN code for pairing.

        Returns:
            Pairing state dict with auth_key, timestamp, and device info
            needed for grant_pairing()
        """
        device_id = token_hex(16)

        device = {
            "device_name": "AmbiHue",
            "device_os": "Linux",
            "app_id": "ambihue",
            "app_name": "AmbiHue",
            "type": "native",
            "id": device_id,
        }

        request_data = {
            "device": device,
            "scope": ["read", "write", "control"],
        }

        try:
            response = self._client.post(
                f"{self._base_url}/pair/request",
                json=request_data,
            )
            response.raise_for_status()
            result = response.json()
            logger.debug(f"pair/request response: {result}")

            # Return full state needed for grant
            return {
                "auth_key": result.get("auth_key", ""),
                "timestamp": result.get("timestamp", ""),
                "device": device,
            }
        except Exception as e:
            logger.error(f"Failed to request PIN display: {e}")
            raise RuntimeError(f"TV pairing request failed: {e}") from e

    def grant_pairing(self, pairing_state: Dict[str, Any], pin: str) -> Tuple[str, str]:
        """Complete pairing using saved state and PIN.

        Uses HMAC-SHA1 signature and HTTP Digest Auth as required by
        the Philips JointSpace v6 pairing protocol.

        Args:
            pairing_state: State dict from request_pin_display() containing
                           auth_key, timestamp, and device info
            pin: 4-digit PIN displayed on TV

        Returns:
            Tuple of (username, password) for subsequent DigestAuth API calls.
            username = device_id, password = auth_key
        """
        auth_key = pairing_state.get("auth_key", "")
        timestamp = pairing_state.get("timestamp", "")
        device = pairing_state.get("device", {})
        device_id = device.get("id", "")

        # Compute HMAC-SHA1 signature
        signature = self._hmac_signature(self._SHARED_KEY, str(timestamp), str(pin))

        # Build grant payload with auth block
        grant_data = {
            "auth": {
                "auth_AppId": "1",
                "pin": str(pin),
                "auth_timestamp": timestamp,
                "auth_signature": signature,
            },
            "device": {
                **device,
                "auth_key": auth_key,
            },
        }

        try:
            # Grant request requires HTTP Digest Auth
            response = self._client.post(
                f"{self._base_url}/pair/grant",
                json=grant_data,
                auth=httpx.DigestAuth(device_id, auth_key),
            )

            logger.debug(f"pair/grant response status: {response.status_code}")
            logger.debug(f"pair/grant response body: {response.text}")

            response.raise_for_status()

            # Credentials for subsequent API calls:
            # username = device_id, password = auth_key
            logger.info(f"TV paired successfully (device_id={device_id[:8]}...)")
            return (device_id, auth_key)

        except httpx.HTTPStatusError as e:
            logger.error(f"pair/grant HTTP {e.response.status_code}: {e.response.text}")
            if e.response.status_code == 401:
                raise RuntimeError("Invalid PIN code or expired auth key") from e
            raise RuntimeError(f"TV pairing grant failed: {e}") from e
        except Exception as e:
            raise RuntimeError(f"TV pairing grant failed: {e}") from e

    def complete_pairing(self, pin: str) -> Tuple[str, str]:
        """Request a fresh PIN display and immediately grant with that PIN.

        Only use this for interactive/stdin mode where the user can see
        the new PIN displayed on TV and enter it immediately.

        Args:
            pin: 4-digit PIN displayed on TV

        Returns:
            Tuple of (username, password) for DigestAuth
        """
        pairing_state = self.request_pin_display()
        return self.grant_pairing(pairing_state, pin)

    def close(self) -> None:
        """Close HTTP client."""
        self._client.close()


def discover_tv_from_ha() -> Optional[str]:
    """Discover Philips TV IP from Home Assistant's device registry.

    Queries HA's config entries for the philips_js integration,
    which stores the TV IP in its config entry data.

    Returns:
        TV IP address or None if not found
    """
    import json as _json
    import os

    token = os.environ.get("SUPERVISOR_TOKEN", "") or os.environ.get("HASSIO_TOKEN", "")
    if not token:
        logger.warning("No SUPERVISOR_TOKEN found - HA API discovery unavailable")
        # Log available env vars for debugging (keys only, no values)
        ha_vars = [k for k in os.environ if "HA" in k.upper() or "SUPER" in k.upper() or "HASS" in k.upper()]
        logger.warning(f"Available HA env vars: {ha_vars}")
        return None

    try:
        import websocket  # websocket-client

        logger.warning("Querying Home Assistant for Philips TV devices...")

        ws = websocket.create_connection(
            "ws://supervisor/core/websocket",
            timeout=10,
        )

        # Auth handshake
        ws.recv()  # auth_required message
        ws.send(_json.dumps({"type": "auth", "access_token": token}))
        auth_result = _json.loads(ws.recv())

        if auth_result.get("type") != "auth_ok":
            logger.warning("HA WebSocket auth failed")
            ws.close()
            return None

        logger.warning("Connected to HA, querying philips_js config entries...")

        # Query config entries for philips_js integration
        ws.send(_json.dumps({
            "id": 1,
            "type": "config_entries/get",
            "domain": "philips_js",
        }))
        result = _json.loads(ws.recv())
        ws.close()

        entries = result.get("result", [])
        if not entries:
            logger.warning("No Philips TV integration found in Home Assistant")
            return None

        # Extract host from config entry data
        for entry in entries:
            data = entry.get("data", {})
            host = data.get("host")
            if host:
                logger.warning(f"Found Philips TV in HA: {host} ({entry.get('title', 'unknown')})")
                return host

        logger.warning("Philips TV found in HA but no host in config data")
        return None

    except ImportError:
        logger.warning("websocket-client not installed, skipping HA discovery")
        return None
    except Exception as e:
        logger.warning(f"HA device discovery failed: {e}")
        return None


def discover_and_select_tv() -> Optional[str]:
    """Discover TVs and return the first one found.

    Tries Home Assistant device registry first, then falls back to SSDP.

    Returns:
        TV IP address or None if no TVs found
    """
    # Method 1: Query HA for existing Philips TV device
    ha_ip = discover_tv_from_ha()
    if ha_ip:
        return ha_ip

    # Method 2: SSDP network scan
    discovery = PhilipsTVDiscovery(timeout=5)
    tvs = discovery.discover_tvs()

    if tvs:
        tv = tvs[0]
        logger.info(f"Selected TV: {tv['name']} ({tv['model']}) at {tv['ip']}")
        return tv["ip"]

    return None


def _prompt_for_pin_with_timeout(timeout_seconds: int = 10) -> str:
    """Prompt user for PIN with timeout (standalone mode only).

    Args:
        timeout_seconds: How long to wait for input

    Returns:
        PIN entered by user, or empty string if timeout/no input/HA mode
    """
    import sys
    import threading

    # In HA mode, stdin is closed - skip the prompt
    if not sys.stdin or sys.stdin.closed:
        return ""

    pin = ""

    def read_input() -> None:
        nonlocal pin
        try:
            pin = input().strip()
        except EOFError:
            pass

    logger.warning(f"Enter PIN now (you have {timeout_seconds} seconds): ")

    # Use threading for cross-platform timeout
    input_thread = threading.Thread(target=read_input, daemon=True)
    input_thread.start()
    input_thread.join(timeout=timeout_seconds)

    if input_thread.is_alive():
        logger.info("Input timeout reached")
        return ""

    return pin


def _poll_ha_config_for_pin(timeout_seconds: int = 120) -> str:
    """Poll HA add-on config for PIN entry via Supervisor API.

    After PIN is displayed on TV, the user enters it in the HA Configuration tab.
    This function polls the Supervisor API until the PIN appears or timeout.

    Args:
        timeout_seconds: How long to wait for PIN entry

    Returns:
        PIN string or empty string if timeout
    """
    import os

    token = os.environ.get("SUPERVISOR_TOKEN", "") or os.environ.get("HASSIO_TOKEN", "")
    if not token:
        logger.warning("No Supervisor API access - cannot poll for PIN")
        return ""

    logger.warning(f"Waiting up to {timeout_seconds}s for PIN in Configuration tab...")
    logger.warning("Enter the PIN shown on your TV in: Settings -> Add-ons -> AmbiHue -> Configuration")
    logger.warning("Set 'pairing_pin' under ambilight_tv, then SAVE (no restart needed).")

    headers = {"Authorization": f"Bearer {token}"}
    poll_interval = 5
    attempts = timeout_seconds // poll_interval

    for attempt in range(attempts):
        try:
            response = httpx.get(
                "http://supervisor/addons/self/options/config",
                headers=headers,
                timeout=5.0,
            )
            if response.status_code == 200:
                options = response.json()
                tv_opts = options.get("data", options).get("ambilight_tv", {})
                pin = tv_opts.get("pairing_pin", "")
                if pin:
                    logger.warning(f"PIN received from config!")
                    return pin
        except Exception as e:
            logger.debug(f"Config poll error: {e}")

        remaining = timeout_seconds - (attempt + 1) * poll_interval
        if remaining > 0:
            logger.warning(f"Waiting for PIN... ({remaining}s remaining)")
        time.sleep(poll_interval)

    logger.warning("PIN entry timed out")
    return ""


def _load_pairing_state() -> Dict[str, Any]:
    """Load saved pairing state from state file.

    The pairing state (auth_key, timestamp, device info) is saved after
    request_pin_display() so that on restart we can call grant_pairing()
    with the same state + user's PIN without triggering a new PIN on the TV.

    Returns:
        Saved pairing state dict, or empty dict if not found
    """
    import os

    state_path = "/data/ambihue_state.json"
    if not os.path.exists(state_path):
        return {}

    try:
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        return state.get("tv_pairing_state", {})
    except (json.JSONDecodeError, OSError) as e:
        logger.debug(f"Failed to load pairing state: {e}")
        return {}


def _save_pairing_state(pairing_state: Dict[str, Any]) -> None:
    """Save full pairing state to state file for use after restart.

    Args:
        pairing_state: Dict with auth_key, timestamp, and device info
    """
    import os

    state_path = "/data/ambihue_state.json"
    state: Dict[str, Any] = {}

    if os.path.exists(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    state["tv_pairing_state"] = pairing_state

    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        logger.warning("Saved TV pairing state to state file")
    except OSError as e:
        logger.error(f"Failed to save pairing state: {e}")


def _clear_pairing_state() -> None:
    """Remove pairing state from state file after successful pairing."""
    import os

    state_path = "/data/ambihue_state.json"
    if not os.path.exists(state_path):
        return

    try:
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        state.pop("tv_pairing_state", None)
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except (json.JSONDecodeError, OSError):
        pass


def handle_tv_pairing(
    tv_ip: str,
    pairing_pin: str = "",
    port: int = 1926,
    protocol: str = "https://",
    api_version: int = 6,
) -> Tuple[str, str]:
    """Handle TV pairing - two-phase approach for Android TVs.

    Phase 1 (no PIN in config):
        - Request PIN display on TV (pair/request)
        - Save full pairing state (auth_key, timestamp, device) to state file
        - Try stdin input (standalone) or exit with instructions (HA)

    Phase 2 (PIN in config from previous run):
        - Load saved pairing state from state file
        - Call pair/grant with saved state + PIN (HMAC signature, Digest Auth)
        - Clear pairing state on success

    Args:
        tv_ip: TV IP address
        pairing_pin: PIN code from config (empty on first run)
        port: API port
        protocol: http:// or https://
        api_version: JointSpace API version

    Returns:
        Tuple of (username, password) - empty strings if no auth needed.
        Returns ("__PIN_REQUIRED__", "") if the caller should save state and exit.
    """
    pairing = PhilipsTVPairing(tv_ip, port, protocol, api_version)

    try:
        # Try no-auth first (non-Android TVs)
        if pairing.try_connect_no_auth():
            logger.info("TV connected (no authentication required)")
            return ("", "")

        # === Phase 2: PIN available from config ===
        if pairing_pin:
            saved_state = _load_pairing_state()

            if saved_state and saved_state.get("auth_key"):
                logger.warning("Using saved pairing state with PIN from config...")
                try:
                    user, password = pairing.grant_pairing(saved_state, pairing_pin)
                    logger.warning("TV paired successfully!")
                    _clear_pairing_state()
                    return (user, password)
                except RuntimeError as e:
                    logger.error(f"Pairing with saved state failed: {e}")
                    _clear_pairing_state()
                    logger.warning("=" * 60)
                    logger.warning("PIN or pairing state was invalid.")
                    logger.warning("Clear 'pairing_pin' in config, then restart.")
                    logger.warning("A new PIN will be displayed on your TV.")
                    logger.warning("=" * 60)
                    return ("__PIN_REQUIRED__", "")
            else:
                logger.warning("PIN in config but no saved pairing state found.")
                logger.warning("Will request fresh PIN from TV...")

        # === Phase 1: Request PIN display on TV ===
        logger.warning("=" * 60)
        logger.warning("TV PAIRING REQUIRED (Android TV)")
        logger.warning("=" * 60)

        pairing_state = pairing.request_pin_display()

        # Save full pairing state so it survives a restart
        if pairing_state.get("auth_key"):
            _save_pairing_state(pairing_state)

        logger.warning("A PIN code is now displayed on your TV screen.")
        logger.warning("")

        # Try to get PIN from stdin with timeout (for standalone usage)
        entered_pin = _prompt_for_pin_with_timeout(10)

        if entered_pin and pairing_state.get("auth_key"):
            # User entered PIN via stdin - grant immediately
            logger.warning("Completing pairing with entered PIN...")
            user, password = pairing.grant_pairing(pairing_state, entered_pin)
            logger.warning("TV paired successfully!")
            _clear_pairing_state()
            return (user, password)

        # No PIN entered (HA mode or timeout) - tell caller to save state and exit
        logger.warning("To complete pairing:")
        logger.warning("  Home Assistant: Settings -> Add-ons -> AmbiHue -> Configuration")
        logger.warning("  Standalone: Edit userconfig.yaml")
        logger.warning("")
        logger.warning("Set 'pairing_pin' to the PIN shown on your TV, then restart.")
        logger.warning("=" * 60)

        return ("__PIN_REQUIRED__", "")

    finally:
        pairing.close()
