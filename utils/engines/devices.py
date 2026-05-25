"""Device presets for mobile / tablet emulation.

A small curated table — covers the devices QA teams actually need to test.
Each entry has the same shape as Playwright's device descriptors so we can
hand a preset directly to a Playwright context. The Selenium adapter pulls
the same fields and applies them via Chrome's mobileEmulation + CDP.

Names are case-insensitive on lookup. Aliases (e.g. "iphone" → "iPhone 13")
let LLM output be a little loose.
"""

from __future__ import annotations

from typing import Dict, Optional


# Reference: Chrome DevTools "Mobile" emulator + Playwright devices.
DEVICES: Dict[str, dict] = {
    # ---------- Desktop reset ----------
    "Desktop": {
        "viewport": {"width": 1440, "height": 900},
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "device_scale_factor": 1,
        "is_mobile": False,
        "has_touch": False,
    },
    # ---------- iPhone family ----------
    "iPhone 13": {
        "viewport": {"width": 390, "height": 844},
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
                      "(KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        "device_scale_factor": 3,
        "is_mobile": True,
        "has_touch": True,
    },
    "iPhone 15 Pro Max": {
        "viewport": {"width": 430, "height": 932},
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
                      "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "device_scale_factor": 3,
        "is_mobile": True,
        "has_touch": True,
    },
    "iPhone SE": {
        "viewport": {"width": 375, "height": 667},
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 "
                      "(KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1",
        "device_scale_factor": 2,
        "is_mobile": True,
        "has_touch": True,
    },
    # ---------- Android family ----------
    "Pixel 5": {
        "viewport": {"width": 393, "height": 851},
        "user_agent": "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/90.0.4430.91 Mobile Safari/537.36",
        "device_scale_factor": 3,
        "is_mobile": True,
        "has_touch": True,
    },
    "Pixel 7": {
        "viewport": {"width": 412, "height": 915},
        "user_agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/118.0.5993.96 Mobile Safari/537.36",
        "device_scale_factor": 2.625,
        "is_mobile": True,
        "has_touch": True,
    },
    "Galaxy S22": {
        "viewport": {"width": 360, "height": 780},
        "user_agent": "Mozilla/5.0 (Linux; Android 12; SM-S901U) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/101.0.4951.61 Mobile Safari/537.36",
        "device_scale_factor": 3,
        "is_mobile": True,
        "has_touch": True,
    },
    # ---------- Tablets ----------
    "iPad Pro 11": {
        "viewport": {"width": 834, "height": 1194},
        "user_agent": "Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
                      "(KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        "device_scale_factor": 2,
        "is_mobile": True,
        "has_touch": True,
    },
    "iPad mini": {
        "viewport": {"width": 768, "height": 1024},
        "user_agent": "Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
                      "(KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        "device_scale_factor": 2,
        "is_mobile": True,
        "has_touch": True,
    },
}


# Loose aliases — LLM output may be sloppy ("iphone" / "android pixel").
_ALIASES: Dict[str, str] = {
    "desktop": "Desktop",
    "iphone": "iPhone 13",
    "iphone 13": "iPhone 13",
    "iphone 15": "iPhone 15 Pro Max",
    "iphone se": "iPhone SE",
    "pixel": "Pixel 5",
    "pixel 5": "Pixel 5",
    "pixel 7": "Pixel 7",
    "android": "Pixel 5",
    "galaxy": "Galaxy S22",
    "samsung": "Galaxy S22",
    "ipad": "iPad Pro 11",
    "ipad pro": "iPad Pro 11",
    "ipad mini": "iPad mini",
    "tablet": "iPad Pro 11",
    "mobile": "iPhone 13",
}


def normalize_device_name(name: str) -> Optional[str]:
    """Resolve a (possibly loose) device name to a canonical key. None if unknown."""
    if not name:
        return None
    key = name.strip()
    if key in DEVICES:
        return key
    return _ALIASES.get(key.lower())


def get_device(name: str) -> Optional[dict]:
    """Return the device dict or None for unknown names."""
    canonical = normalize_device_name(name)
    if canonical is None:
        return None
    return DEVICES[canonical]


def list_devices() -> list:
    """Sorted list of canonical device names (Desktop first)."""
    rest = sorted(k for k in DEVICES if k != "Desktop")
    return ["Desktop"] + rest
