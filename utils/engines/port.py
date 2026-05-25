"""Backend-agnostic browser interface.

A ``BrowserPort`` is what the action engine talks to. It exposes the
minimum surface needed by every op:

* navigation (``goto``, ``back``, ``forward``, ``reload``, ``current_url``)
* element finding (``find`` returning an ``ElementHandle``)
* JS evaluation (``evaluate``) — used by performance budgets
* screenshot + log capture
* lifecycle (``start``, ``quit``)

The ``ElementHandle`` is the second half — every node returned by ``find``
exposes ``click``, ``fill``, ``send_keys``, ``clear``, ``text``,
``is_displayed``, ``get_attribute``.

These two interfaces are deliberately tiny. New ops should be expressible
in terms of them, OR they should request a new port method by name.
"""

from __future__ import annotations

from typing import Any, List, Protocol, Tuple, runtime_checkable

from utils.models import Locator


@runtime_checkable
class ElementHandle(Protocol):
    """One element resolved by a port. Methods match Selenium's WebElement
    for low-friction porting; the Playwright adapter translates internally."""

    def click(self) -> None: ...
    def clear(self) -> None: ...
    def send_keys(self, value: str) -> None: ...
    def fill(self, value: str) -> None: ...
    def hover(self) -> None: ...
    def select_option(self, text: str) -> None: ...
    def scroll_into_view(self) -> None: ...

    @property
    def text(self) -> str: ...
    def is_displayed(self) -> bool: ...
    def get_attribute(self, name: str) -> Any: ...


@runtime_checkable
class BrowserPort(Protocol):
    """Engine-agnostic browser interface used by every action handler."""

    # Lifecycle ---------------------------------------------------------
    def start(self) -> "BrowserPort": ...
    def quit(self) -> None: ...

    # Navigation --------------------------------------------------------
    def goto(self, url: str) -> None: ...
    def back(self) -> None: ...
    def forward(self) -> None: ...
    def reload(self) -> None: ...

    @property
    def current_url(self) -> str: ...

    # Element resolution -----------------------------------------------
    def find(self, locator: Locator, timeout_ms: int) -> Tuple[ElementHandle, str]:
        """Resolve the primary locator with fallback walk.

        Returns ``(element, used_strategy)`` where ``used_strategy`` is a
        short string like ``"id=email"`` recorded into the ActionResult so
        Phase A's self-healing layer can promote winning fallbacks later.

        Raises ``LookupError`` if nothing in the chain matches.
        """

    # Scripting / metrics ----------------------------------------------
    def evaluate(self, script: str, *args: Any) -> Any: ...
    def execute_script(self, script: str, *args: Any) -> Any: ...   # legacy alias

    # Capture -----------------------------------------------------------
    def screenshot(self, path: str) -> None: ...
    def drain_console_logs(self) -> List[dict]: ...

    # Action chains (key sends not tied to an element) ----------------
    def press_key(self, key: str) -> None: ...

    # Auth state ---------------------------------------------------------
    # Save: dump cookies + localStorage of the active origin to ``path``.
    # Load: read the file and apply (visits the URL field first so domain
    # scoping is satisfied on both engines).
    def save_auth_state(self, path: str) -> None: ...
    def load_auth_state(self, path: str) -> None: ...

    # Device emulation ---------------------------------------------------
    def set_viewport(self, width: int, height: int) -> None: ...
    def set_user_agent(self, user_agent: str) -> None: ...
    def emulate_device(self, device: dict) -> None:
        """Apply a full device preset (viewport + UA + touch). Default impl
        in adapters; the protocol lists it for completeness."""


# ---------------------------------------------------------------------
# Shared helpers — used by both adapters
# ---------------------------------------------------------------------

def _xpath_literal(s: str) -> str:
    """Quote a string safely for XPath 1.0 (no native escape)."""
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    parts = s.split("'")
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in parts) + ")"


def locator_to_css(loc: Locator) -> str:
    """Best-effort CSS-or-XPath translation used by adapters that prefer CSS
    (Playwright's locator engine likes CSS). Returns either a CSS selector
    or an ``xpath=...`` prefixed string."""
    by, val = loc.by, loc.value
    if by == "id":          return f"#{val}"
    if by == "name":        return f'[name="{val}"]'
    if by == "css":         return val
    if by == "testid":      return f'[data-testid="{val}"]'
    if by == "role":        return f'[role="{val}"]'
    if by == "placeholder": return f'[placeholder="{val}"]'
    if by == "text":        return f"xpath=//*[normalize-space(text())={_xpath_literal(val)}]"
    if by == "label":
        # Playwright has page.get_by_label() but for parity we use xpath.
        xp = (f"//label[normalize-space(text())={_xpath_literal(val)}]"
              f"/following::*[self::input or self::textarea or self::select][1]")
        return "xpath=" + xp
    if by == "link_text":
        return f"xpath=//a[normalize-space(text())={_xpath_literal(val)}]"
    if by == "partial_link_text":
        return f"xpath=//a[contains(text(), {_xpath_literal(val)})]"
    if by == "xpath":       return "xpath=" + val
    raise ValueError(f"Unknown locator strategy: {by}")
