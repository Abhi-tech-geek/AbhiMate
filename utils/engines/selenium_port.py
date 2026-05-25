"""Selenium implementation of BrowserPort.

Wraps the existing WebSeleniumDriver. All current 28 action handlers go
through this port, so behavior is identical to the pre-refactor world —
just one indirection away.
"""

from __future__ import annotations

from typing import Any, List, Tuple

from utils.models import Locator
from utils.engines.port import ElementHandle, _xpath_literal


class _SeleniumElement:
    """Tiny adapter so handler code can call `el.fill(value)` consistently.

    The underlying selenium.webdriver.remote.webelement.WebElement already
    has click(), clear(), send_keys(), text, is_displayed(), get_attribute().
    We just add fill() = clear + send_keys for ergonomic parity with PW.
    """

    __slots__ = ("_w",)

    def __init__(self, webelement):
        self._w = webelement

    def click(self) -> None: self._w.click()
    def clear(self) -> None: self._w.clear()
    def send_keys(self, value: str) -> None: self._w.send_keys(value)

    def fill(self, value: str) -> None:
        self._w.clear()
        self._w.send_keys(value)

    @property
    def text(self) -> str:
        return self._w.text or ""

    def is_displayed(self) -> bool:
        return bool(self._w.is_displayed())

    def get_attribute(self, name: str) -> Any:
        return self._w.get_attribute(name)

    def hover(self) -> None:
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(self._w.parent).move_to_element(self._w).perform()

    def select_option(self, text: str) -> None:
        from selenium.webdriver.support.ui import Select
        Select(self._w).select_by_visible_text(text)

    def scroll_into_view(self) -> None:
        self._w.parent.execute_script(
            "arguments[0].scrollIntoView({block:'center'})", self._w
        )

    # Escape hatch — some handlers (Select, ActionChains) might need raw access.
    @property
    def raw(self):
        return self._w


class SeleniumPort:
    """BrowserPort backed by selenium.webdriver."""

    def __init__(self):
        self._driver_wrap = None      # WebSeleniumDriver
        self.driver = None             # the underlying selenium driver (public for handlers that still need it)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> "SeleniumPort":
        from utils.automation_drivers import WebSeleniumDriver
        self._driver_wrap = WebSeleniumDriver()
        self._driver_wrap.start()
        self.driver = self._driver_wrap.driver
        return self

    def quit(self) -> None:
        if self._driver_wrap:
            self._driver_wrap.quit()
        self.driver = None
        self._driver_wrap = None

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def goto(self, url: str) -> None:    self.driver.get(url)
    def back(self) -> None:               self.driver.back()
    def forward(self) -> None:            self.driver.forward()
    def reload(self) -> None:             self.driver.refresh()

    @property
    def current_url(self) -> str:
        return self.driver.current_url

    # ------------------------------------------------------------------
    # Element resolution (fallback chain)
    # ------------------------------------------------------------------
    def find(self, locator: Locator, timeout_ms: int) -> Tuple[ElementHandle, str]:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        by_map = {
            "id": By.ID, "name": By.NAME, "css": By.CSS_SELECTOR,
            "xpath": By.XPATH, "link_text": By.LINK_TEXT,
            "partial_link_text": By.PARTIAL_LINK_TEXT,
        }
        candidates = [locator, *locator.fallbacks]
        per_attempt = max(1.0, (timeout_ms / 1000.0) / max(1, len(candidates)))
        last_err: Exception | None = None

        for cand in candidates:
            try:
                if cand.by in by_map:
                    el = WebDriverWait(self.driver, per_attempt).until(
                        EC.presence_of_element_located((by_map[cand.by], cand.value))
                    )
                elif cand.by == "text":
                    xp = f"//*[normalize-space(text())={_xpath_literal(cand.value)}]"
                    el = WebDriverWait(self.driver, per_attempt).until(
                        EC.presence_of_element_located((By.XPATH, xp))
                    )
                elif cand.by == "placeholder":
                    el = WebDriverWait(self.driver, per_attempt).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, f'[placeholder="{cand.value}"]')
                        )
                    )
                elif cand.by == "testid":
                    el = WebDriverWait(self.driver, per_attempt).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, f'[data-testid="{cand.value}"]')
                        )
                    )
                elif cand.by == "role":
                    el = WebDriverWait(self.driver, per_attempt).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, f'[role="{cand.value}"]')
                        )
                    )
                elif cand.by == "label":
                    xp = (f"//label[normalize-space(text())={_xpath_literal(cand.value)}]"
                          f"/following::*[self::input or self::textarea or self::select][1]")
                    el = WebDriverWait(self.driver, per_attempt).until(
                        EC.presence_of_element_located((By.XPATH, xp))
                    )
                else:
                    raise ValueError(f"Unknown locator strategy: {cand.by}")
                return _SeleniumElement(el), f"{cand.by}={cand.value}"
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue

        raise LookupError(
            f"No locator matched (tried {[c.by + '=' + c.value for c in candidates]}): {last_err}"
        )

    # ------------------------------------------------------------------
    # Scripting + capture
    # ------------------------------------------------------------------
    def evaluate(self, script: str, *args: Any) -> Any:
        return self.driver.execute_script(script, *args)

    # Legacy alias kept for any external callers.
    execute_script = evaluate

    def screenshot(self, path: str) -> None:
        if self.driver:
            self.driver.save_screenshot(path)

    def drain_console_logs(self) -> List[dict]:
        try:
            return self.driver.get_log("browser")
        except Exception:
            return []

    def press_key(self, key: str) -> None:
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(self.driver).send_keys(key).perform()

    # ------------------------------------------------------------------
    # Auth state
    # ------------------------------------------------------------------
    def save_auth_state(self, path: str) -> None:
        import json, os
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cookies = self.driver.get_cookies() or []
        # localStorage is per-origin — read it via JS as {key: value}.
        try:
            ls = self.driver.execute_script(
                "var o = {}; for (var i=0; i<localStorage.length; i++) "
                "{ var k = localStorage.key(i); o[k] = localStorage.getItem(k); } return o;"
            ) or {}
        except Exception:
            ls = {}
        snapshot = {
            "engine": "selenium",
            "url": self.driver.current_url,
            "cookies": cookies,
            "local_storage": ls,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)

    def load_auth_state(self, path: str) -> None:
        import json
        with open(path, "r", encoding="utf-8") as f:
            snap = json.load(f) or {}

        # Cookies are domain-scoped: visit the URL first.
        target = snap.get("url")
        if target:
            self.driver.get(target)

        # Selenium rejects cookies that don't match the current domain.
        for c in snap.get("cookies", []) or []:
            cookie = dict(c)
            # add_cookie can choke on optional fields like sameSite=None
            cookie.pop("sameSite", None)
            try:
                self.driver.add_cookie(cookie)
            except Exception:
                continue

        # Restore localStorage entries via JS.
        ls = snap.get("local_storage") or {}
        for k, v in ls.items():
            try:
                self.driver.execute_script(
                    "window.localStorage.setItem(arguments[0], arguments[1]);", k, str(v)
                )
            except Exception:
                continue

        # Reload so the page picks up the restored state.
        if target:
            self.driver.get(target)

    # ------------------------------------------------------------------
    # Device emulation
    # ------------------------------------------------------------------
    def set_viewport(self, width: int, height: int) -> None:
        if self.driver:
            self.driver.set_window_size(int(width), int(height))

    def set_user_agent(self, user_agent: str) -> None:
        # Chrome only supports UA override via CDP at runtime.
        if not self.driver:
            return
        try:
            self.driver.execute_cdp_cmd("Network.setUserAgentOverride", {"userAgent": user_agent})
        except Exception:
            # Older drivers or non-Chromium — fall back to a CSS-only viewport hint.
            pass

    def emulate_device(self, device: dict) -> None:
        if not device:
            return
        vp = device.get("viewport") or {}
        if vp.get("width") and vp.get("height"):
            self.set_viewport(vp["width"], vp["height"])
        if device.get("user_agent"):
            self.set_user_agent(device["user_agent"])
        # Touch emulation via CDP (Chrome-only, best-effort).
        if self.driver and device.get("has_touch"):
            try:
                self.driver.execute_cdp_cmd("Emulation.setTouchEmulationEnabled",
                                            {"enabled": True})
            except Exception:
                pass
