"""Central config knobs — env-driven so the same code runs locally and in CI.

Read via ``from config import settings``. Anything not in env falls back to
sensible defaults for a developer laptop.
"""

import os


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class _Settings:
    # Server
    HOST: str = os.environ.get("ABHIMATE_HOST", "127.0.0.1")
    PORT: int = _int("ABHIMATE_PORT", 5000)
    DEBUG: bool = _bool("ABHIMATE_DEBUG", True)

    # Browser
    # BACKEND: which automation engine to use. "selenium" (default, mature)
    # or "playwright" (faster, auto-waits, native trace viewer).
    BACKEND: str = os.environ.get("ABHIMATE_BACKEND", "selenium")
    HEADLESS: bool = _bool("ABHIMATE_HEADLESS", False)
    BROWSER: str = os.environ.get("ABHIMATE_BROWSER", "chromium")
    # Default device emulation. "Desktop" disables emulation. Other valid
    # values: "iPhone 13", "Pixel 5", "iPad Pro 11", etc. — see
    # utils/engines/devices.py for the full list.
    DEVICE: str = os.environ.get("ABHIMATE_DEVICE", "Desktop")
    DRIVER_CACHE_DIR: str = os.environ.get(
        "ABHIMATE_DRIVER_CACHE",
        os.path.join(os.path.expanduser("~"), ".cache", "abhimate-drivers"),
    )

    # Execution
    DEFAULT_TIMEOUT_MS: int = _int("ABHIMATE_TIMEOUT_MS", 10_000)
    DEFAULT_RETRIES: int = _int("ABHIMATE_RETRIES", 2)
    PER_TEST_TIMEOUT_S: float = float(os.environ.get("ABHIMATE_TEST_TIMEOUT_S", "30"))

    # Output
    SCREENSHOTS_DIR: str = "data/screenshots"
    TRACES_DIR: str = "data/traces"
    JUNIT_DIR: str = "data/junit"

    # LLM
    DEFAULT_MODEL: str = os.environ.get("ABHIMATE_MODEL", "llama-3.3-70b-versatile")

    @classmethod
    def as_dict(cls) -> dict:
        return {
            k: getattr(cls, k) for k in vars(cls)
            if not k.startswith("_") and not callable(getattr(cls, k))
        }


settings = _Settings
