"""Playwright implementation of BrowserPort.

Uses the sync API (sync_playwright). Each port instance owns one browser,
one context, one page — same lifecycle as the Selenium adapter.

Translation notes:

* Selenium ``By.ID="x"`` → Playwright ``"#x"``
* ``testid`` uses ``page.get_by_test_id`` when ``data-testid="x"`` exists,
  falls back to a CSS attribute selector.
* ``label`` uses ``page.get_by_label`` directly — Playwright's accessibility
  engine resolves the linked control.
* The Playwright equivalent of ``WebDriverWait.until(presence_of_element)``
  is ``Locator.wait_for(state="attached", timeout=...)``.
"""

from __future__ import annotations

import os
from typing import Any, List, Tuple

from utils.models import Locator
from utils.engines.port import ElementHandle


class _PlaywrightElement:
    """ElementHandle adapter over a Playwright Locator.first."""

    __slots__ = ("_loc", "_page")

    def __init__(self, loc, page):
        self._loc = loc
        self._page = page

    def click(self) -> None: self._loc.click()
    def clear(self) -> None: self._loc.fill("")

    def send_keys(self, value: str) -> None:
        # Playwright fill() replaces; for incremental typing the user wants
        # type(). Mimic Selenium semantics — append text.
        existing = self._loc.input_value() if self._is_inputlike() else ""
        if existing:
            self._loc.type(value)
        else:
            self._loc.fill(value)

    def fill(self, value: str) -> None:
        self._loc.fill(value)

    @property
    def text(self) -> str:
        return self._loc.inner_text() or ""

    def is_displayed(self) -> bool:
        try:
            return bool(self._loc.is_visible())
        except Exception:
            return False

    def get_attribute(self, name: str) -> Any:
        # Playwright spells the value field differently for input/select
        if name == "value":
            try:
                return self._loc.input_value()
            except Exception:
                return self._loc.get_attribute("value")
        return self._loc.get_attribute(name)

    def _is_inputlike(self) -> bool:
        try:
            tag = (self._loc.evaluate("el => el.tagName") or "").lower()
        except Exception:
            tag = ""
        return tag in {"input", "textarea"}

    def hover(self) -> None:
        self._loc.hover()

    def select_option(self, text: str) -> None:
        self._loc.select_option(label=text)

    def scroll_into_view(self) -> None:
        self._loc.scroll_into_view_if_needed()


class PlaywrightPort:
    """BrowserPort backed by playwright.sync_api.

    Lazy-imports playwright so the Selenium-only deployment doesn't need the
    library installed. ImportError propagates with a friendly message.
    """

    def __init__(self):
        self._pw = None
        self._browser = None
        self._context = None
        self.page = None
        self._console_logs: List[dict] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> "PlaywrightPort":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise RuntimeError(
                "Playwright backend selected but the library isn't installed. "
                "Run:\n  pip install playwright\n  playwright install chromium"
            ) from e

        try:
            from config import settings
        except Exception:
            class _F:
                HEADLESS = False
                BROWSER = "chromium"
            settings = _F

        self._pw = sync_playwright().start()
        browser_kind = (getattr(settings, "BROWSER", "chromium") or "chromium").lower()
        launcher = {
            "chromium": self._pw.chromium,
            "firefox": self._pw.firefox,
            "webkit": self._pw.webkit,
        }.get(browser_kind, self._pw.chromium)

        self._browser = launcher.launch(headless=bool(getattr(settings, "HEADLESS", False)))
        self._context = self._browser.new_context()
        self.page = self._context.new_page()
        # Capture console messages so drain_console_logs can return them.
        self.page.on("console", self._on_console)
        return self

    def _on_console(self, msg) -> None:
        try:
            self._console_logs.append({
                "level": msg.type,
                "message": msg.text,
            })
        except Exception:
            pass

    def quit(self) -> None:
        try:
            if self._context: self._context.close()
        finally:
            try:
                if self._browser: self._browser.close()
            finally:
                if self._pw: self._pw.stop()
        self._pw = self._browser = self._context = self.page = None

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def goto(self, url: str) -> None: self.page.goto(url)
    def back(self) -> None: self.page.go_back()
    def forward(self) -> None: self.page.go_forward()
    def reload(self) -> None: self.page.reload()

    @property
    def current_url(self) -> str:
        return self.page.url

    # ------------------------------------------------------------------
    # Element resolution (fallback chain)
    # ------------------------------------------------------------------
    def _resolve_one(self, cand: Locator, timeout_ms: int):
        page = self.page
        by, val = cand.by, cand.value
        if by == "id":
            loc = page.locator(f"#{val}")
        elif by == "name":
            loc = page.locator(f'[name="{val}"]')
        elif by == "css":
            loc = page.locator(val)
        elif by == "xpath":
            loc = page.locator(f"xpath={val}")
        elif by == "text":
            loc = page.get_by_text(val, exact=True)
        elif by == "testid":
            loc = page.get_by_test_id(val)
        elif by == "role":
            loc = page.get_by_role(val)
        elif by == "label":
            loc = page.get_by_label(val)
        elif by == "placeholder":
            loc = page.get_by_placeholder(val)
        elif by == "link_text":
            loc = page.locator(f'a:has-text("{val}")')
        elif by == "partial_link_text":
            loc = page.locator(f'a:has-text("{val}")')
        else:
            raise ValueError(f"Unknown locator strategy: {by}")

        first = loc.first
        first.wait_for(state="attached", timeout=timeout_ms)
        return first

    def find(self, locator: Locator, timeout_ms: int) -> Tuple[ElementHandle, str]:
        candidates = [locator, *locator.fallbacks]
        per_attempt = max(500, int(timeout_ms / max(1, len(candidates))))
        last_err: Exception | None = None

        for cand in candidates:
            try:
                loc = self._resolve_one(cand, per_attempt)
                return _PlaywrightElement(loc, self.page), f"{cand.by}={cand.value}"
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
        # Playwright's page.evaluate takes a JS expression OR function.
        # Selenium-style scripts that end with `return X` need to be wrapped.
        if "return " in script and not script.strip().startswith("()"):
            wrapped = "(() => { " + script + " })()"
            return self.page.evaluate(wrapped)
        return self.page.evaluate(script)

    # Keep the legacy name working for any caller that still uses it.
    execute_script = evaluate

    def screenshot(self, path: str) -> None:
        if self.page:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self.page.screenshot(path=path)

    def drain_console_logs(self) -> List[dict]:
        out, self._console_logs = self._console_logs, []
        return out

    def press_key(self, key: str) -> None:
        # Map Selenium-style key names (ENTER, TAB, ARROW_DOWN) to Playwright.
        pw_key = {
            "ENTER": "Enter", "TAB": "Tab", "ESCAPE": "Escape", "ESC": "Escape",
            "BACKSPACE": "Backspace", "DELETE": "Delete", "SPACE": "Space",
            "ARROW_UP": "ArrowUp", "ARROW_DOWN": "ArrowDown",
            "ARROW_LEFT": "ArrowLeft", "ARROW_RIGHT": "ArrowRight",
            "HOME": "Home", "END": "End", "PAGE_UP": "PageUp", "PAGE_DOWN": "PageDown",
        }.get(key.upper(), key)
        self.page.keyboard.press(pw_key)

    # ------------------------------------------------------------------
    # Auth state — Playwright has native storage_state for this
    # ------------------------------------------------------------------
    def save_auth_state(self, path: str) -> None:
        import os
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Native: writes cookies + origins (localStorage) as JSON.
        snap = self._context.storage_state()
        snap["engine"] = "playwright"
        snap["url"] = self.page.url
        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snap, f, indent=2)

    def load_auth_state(self, path: str) -> None:
        import json
        with open(path, "r", encoding="utf-8") as f:
            snap = json.load(f) or {}

        # Apply cookies straight onto the context.
        cookies = snap.get("cookies") or []
        if cookies:
            try:
                self._context.add_cookies(cookies)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Device emulation
    # ------------------------------------------------------------------
    def set_viewport(self, width: int, height: int) -> None:
        if self.page:
            self.page.set_viewport_size({"width": int(width), "height": int(height)})

    def set_user_agent(self, user_agent: str) -> None:
        # Playwright sets UA per-context at creation; runtime override
        # requires recreating the context with extra_http_headers.
        if not self._context or not self._browser:
            return
        try:
            # Swap context with same storage_state + new UA.
            storage = None
            try:
                storage = self._context.storage_state()
            except Exception:
                pass
            self._context.close()
            self._context = self._browser.new_context(
                user_agent=user_agent,
                storage_state=storage,
            )
            self.page = self._context.new_page()
            self.page.on("console", self._on_console)
        except Exception:
            pass

    def emulate_device(self, device: dict) -> None:
        if not device:
            return
        vp = device.get("viewport") or {}
        if vp.get("width") and vp.get("height"):
            self.set_viewport(vp["width"], vp["height"])
        if device.get("user_agent"):
            self.set_user_agent(device["user_agent"])

        # localStorage is origin-scoped. Visit each origin, then inject items.
        target = snap.get("url")
        for origin_entry in snap.get("origins") or []:
            origin = origin_entry.get("origin")
            items = origin_entry.get("localStorage") or []
            if not origin:
                continue
            try:
                self.page.goto(origin)
                for item in items:
                    self.page.evaluate(
                        "([k,v]) => { window.localStorage.setItem(k, v); }",
                        [item.get("name", ""), item.get("value", "")]
                    )
            except Exception:
                continue

        # Land on the original URL so the rest of the plan picks up authed state.
        if target:
            try: self.page.goto(target)
            except Exception: pass
