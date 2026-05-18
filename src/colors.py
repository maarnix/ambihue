#

import logging
from typing import Dict, Tuple

import webcolors  # type: ignore

logger = logging.getLogger(__name__)

# Pre-computed at import time so __closest_color does O(n) distance scan once per lookup
# rather than also rebuilding the name→rgb table on every call.
_CSS3_COLOR_TABLE: Dict[Tuple[int, int, int], str] = {
    tuple(webcolors.name_to_rgb(name)): name  # type: ignore[misc]
    for name in webcolors.names("css3")
}


class Color:
    __slots__ = ("red", "green", "blue")

    def __init__(self, red: int, green: int, blue: int):
        self.red = red
        self.green = green
        self.blue = blue
        # self.print_debug_line()

    def get_dict(self) -> Dict[str, int]:
        rgb_dict = {
            "r": self.red,
            "g": self.green,
            "b": self.blue,
        }
        return rgb_dict

    def get_tuple(self) -> Tuple[int, int, int]:
        rgb_tuple = self.red, self.green, self.blue
        return rgb_tuple

    def get_hue(self) -> Tuple[int, int, int]:
        # Normalize RGB values to the range 0-1
        r, g, b = self.red / 255, self.green / 255, self.blue / 255

        # Find the maximum and minimum values
        max_c = max(r, g, b)
        min_c = min(r, g, b)
        delta = max_c - min_c

        # Calculate Hue
        if delta == 0:
            hue = 0.0  # Achromatic
        elif max_c == r:
            hue = (60 * ((g - b) / delta) + 360) % 360
        elif max_c == g:
            hue = (60 * ((b - r) / delta) + 120) % 360
        elif max_c == b:
            hue = (60 * ((r - g) / delta) + 240) % 360
        else:
            raise ValueError("unexpected conversion error")

        # Calculate Lightness
        lightness = (max_c + min_c) / 2

        # Calculate Saturation
        if delta == 0:
            saturation = 0.0
        else:
            denom = 1 - abs(2 * lightness - 1)
            saturation = delta / denom if denom > 1e-10 else 0.0

        # Convert HSL to Philips Hue format
        hue_philips = int(hue * 65535 / 360)
        saturation_philips = int(saturation * 254)
        brightness_philips = int(lightness * 254)

        return hue_philips, saturation_philips, brightness_philips

    def __closest_color(self) -> str:
        r, g, b = self.red, self.green, self.blue
        closest = min(
            _CSS3_COLOR_TABLE,
            key=lambda c: (c[0] - r) ** 2 + (c[1] - g) ** 2 + (c[2] - b) ** 2,
        )
        return _CSS3_COLOR_TABLE[closest]

    def get_css_color_name(self) -> str:
        try:
            return webcolors.rgb_to_name(self.get_tuple())
        except ValueError:
            return self.__closest_color()

    def get_css_color_name_colored(self) -> str:
        color_code = f"\033[38;2;{self.red};{self.green};{self.blue}m"  # RGB w ANSI
        reset_code = "\033[0m"  # color reset code

        color_name = self.get_css_color_name()

        return f"{color_code}{color_name[:7]:<7}{reset_code}"

    def print_debug_line(self, prefix: str = "", posix: str = "") -> None:
        print(f"{prefix} {self.get_dict()}={self.get_css_color_name_colored()} {posix}")
