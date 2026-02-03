import logging
from pathlib import Path
from typing import Any, Dict, Optional, Union

import yaml

logger = logging.getLogger(__name__)


class ConfigLoader:
    """Singleton class to load and access configuration data from a YAML file.

    Config can be provided via a file or an environment variable USER_CONFIG_YAML
    """

    _instance: Optional["ConfigLoader"] = None
    _config_data: dict[str, Any]

    def __new__(cls, config_path: Union[str, Path] = "userconfig.yaml") -> "ConfigLoader":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load(config_path)
        return cls._instance

    def _load(self, config_path: Union[str, Path]) -> None:

        with open(config_path, "r", encoding="utf-8") as file:
            self._config_data = yaml.safe_load(file)

        # Validate required sections with helpful error messages
        self._validate_config()

    def _validate_config(self) -> None:
        """Validate config has all required sections with helpful error messages."""
        errors = []

        # Check ambilight_tv section
        tv_config = self._config_data.get("ambilight_tv")
        if not isinstance(tv_config, dict):
            errors.append("- 'ambilight_tv' section is missing or invalid")
        elif tv_config.get("ip") in (None, "", "replace_me", "192.168.1.X"):
            errors.append("- 'ambilight_tv.ip' must be set to your TV's IP address")

        # Check hue_entertainment_group section
        hue_config = self._config_data.get("hue_entertainment_group")
        if not isinstance(hue_config, dict):
            errors.append("- 'hue_entertainment_group' section is missing or invalid")
        elif hue_config.get("_identification") in (None, "", "replace_me"):
            errors.append("- 'hue_entertainment_group' credentials not configured (run --discover_hue)")

        # Check lights_setup section
        lights_config = self._config_data.get("lights_setup")
        if not lights_config:
            errors.append("- 'lights_setup' section is missing or empty")

        if errors:
            separator = "=" * 60
            error_msg = (
                f"\n{separator}\n"
                f"CONFIGURATION ERROR\n"
                f"{separator}\n"
                f"Please configure the add-on in Home Assistant:\n"
                f"Settings -> Add-ons -> AmbiHue -> Configuration\n\n"
                f"Issues found:\n"
                + "\n".join(errors)
                + f"\n{separator}"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

    def get(self, key: str, default: Any = None) -> Dict[str, Any]:
        _ret = self._config_data.get(key, default)
        assert isinstance(_ret, dict)
        return _ret

    def get_ambilight_tv(self) -> Dict[str, Any]:
        _ret = self._config_data.get("ambilight_tv")
        if not isinstance(_ret, dict):
            raise ValueError("'ambilight_tv' section missing. Check Configuration tab.")
        return _ret

    def get_hue_entertainment(self) -> Dict[str, Any]:
        _ret = self._config_data.get("hue_entertainment_group")
        if not isinstance(_ret, dict):
            raise ValueError("'hue_entertainment_group' section missing. Check Configuration tab.")
        return _ret

    def get_lights_setup(self) -> Dict[str, Any]:
        _ret = self._config_data.get("lights_setup")
        assert _ret is not None, "lights_setup is required"

        # Support new nested format: lights_setup: {light_name: {id: X, positions: [...]}}
        if isinstance(_ret, dict):
            first_value = next(iter(_ret.values()), None)
            if isinstance(first_value, dict) and "id" in first_value:
                # New format - already in correct structure
                return _ret

            # Legacy flat format: A_name, A_id, A_positions, etc.
            lights = {}
            for key in ["A", "B", "C", "D", "E", "F", "G", "H"]:
                if f"{key}_name" not in _ret:
                    continue
                name = _ret.get(f"{key}_name")
                id_ = _ret.get(f"{key}_id")
                positions = _ret.get(f"{key}_positions")
                if name is not None:
                    lights[name] = {"id": id_, "positions": positions}
            return lights

        # Support list format: [{name: X, id: Y, positions: [...]}]
        if isinstance(_ret, list):
            lights = {}
            for light in _ret:
                name = light.get("name")
                if name:
                    lights[name] = {"id": light.get("id"), "positions": light.get("positions")}
            return lights

        raise ValueError("lights_setup must be a dict or list")

    def get_nested(self, *keys: str, default: Any = None) -> Any:
        """Access nested values, e.g. get_nested("db", "host")"""
        data: Any = self._config_data
        for key in keys:
            if isinstance(data, dict):
                data = data.get(key)
            else:
                return default
        return data if data is not None else default
