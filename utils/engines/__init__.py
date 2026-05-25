"""Engine adapters for the Action Plan executor.

Two backends speak a common ``BrowserPort`` protocol:

* ``SeleniumPort`` — wraps the existing WebSeleniumDriver. Default.
* ``PlaywrightPort`` — wraps a Playwright sync_api page. Opt-in via
  ``ABHIMATE_BACKEND=playwright``.

Action handlers in ``utils/action_engine.py`` call port methods (``goto``,
``find``, ``screenshot``, ``evaluate``, etc.) — never raw Selenium /
Playwright APIs. That keeps the LLM-emitted Action Plan engine-agnostic.
"""

from utils.engines.port import BrowserPort, ElementHandle, locator_to_css
from utils.engines.selenium_port import SeleniumPort

__all__ = ["BrowserPort", "ElementHandle", "SeleniumPort", "locator_to_css", "build_port"]


def build_port(backend: str = "selenium"):
    """Factory — return the configured engine. Lazy-imports Playwright so the
    Selenium-only path doesn't require the library to be installed."""
    b = (backend or "selenium").lower()
    if b == "playwright":
        from utils.engines.playwright_port import PlaywrightPort
        return PlaywrightPort()
    return SeleniumPort()
