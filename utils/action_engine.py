"""Phase A — engine-agnostic Action Plan executor.

The executor walks a list of ``Action`` dicts and dispatches each one through a
registry of typed handlers. Each handler talks to the browser through a
``BrowserPort`` (utils/engines/port.py) so the same plan runs on either
Selenium or Playwright with no handler changes.

Design points
-------------
* Locator resolution lives inside the port (``port.find()``) so the
  fallback-chain + self-heal behaviour is identical across engines.
* Each handler returns an ``ActionResult``. The dispatcher wraps it with retry
  / timeout / duration timing so handlers stay tiny.
* HTTP ops do not need a browser — they short-circuit before any port work.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Dict, List, Optional

from utils.models import Action, ActionResult, Locator


DEFAULT_TIMEOUT_MS = 10_000
DEFAULT_RETRIES = 2  # one immediate retry on transient errors


# ============================================================
# Context
# ============================================================

class ActionContext:
    """Shared state across one test's action plan execution.

    ``port`` is the BrowserPort (Selenium or Playwright). ``driver`` is kept as
    a backwards-compat alias: when port is a SeleniumPort, ``driver`` exposes
    the underlying selenium webdriver so legacy callers and tests still work.

    ``locator_db`` enables Phase #9 self-healing — when set, every successful
    fallback resolution is cached for the host so the next run tries the
    winning selector first. Pass ``None`` to disable (tests + legacy paths).
    """

    def __init__(self, driver=None, port=None, base_url: Optional[str] = None,
                 locator_db=None, user_id: Optional[int] = None,
                 session_id: Optional[str] = None):
        self.port = port
        self.driver = driver if driver is not None else (getattr(port, "driver", None) if port else None)
        self.base_url = base_url
        self.locator_db = locator_db
        # ``user_id`` scopes visual baselines (Feature #4). ``session_id`` is
        # the active run id — used to land the diff/actual artifacts in the
        # right trace folder for the UI to pick up.
        self.user_id = user_id
        self.session_id = session_id
        self.variables: Dict[str, Any] = {}     # bound names -> response objects
        self.console_logs: List[str] = []
        self.network_errors: List[str] = []
        self.last_http_response = None          # for chained assertions
        # Filled in by visual ops so callers (executor, UI) can surface the
        # baseline / actual / diff PNG paths on the test card.
        self.visual_artifacts: List[Dict[str, Any]] = []


# ============================================================
# Locator resolution
# ============================================================

_TRANSIENT_ERROR_PATTERNS = (
    "stale element",
    "element click intercepted",
    "element not interactable",
    "no such element",
    "element is not attached",
    "timeoutexception",
)


def _is_transient(err: BaseException) -> bool:
    s = (str(err) or "").lower()
    return any(p in s for p in _TRANSIENT_ERROR_PATTERNS)


def resolve_element(driver, locator: Locator, timeout_ms: int) -> tuple:
    """Walk the locator + its fallbacks until one resolves.

    Returns (element, used_locator_description). Raises LookupError if nothing
    matches inside the timeout budget.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    by_map = {
        "id": By.ID,
        "name": By.NAME,
        "css": By.CSS_SELECTOR,
        "xpath": By.XPATH,
        "link_text": By.LINK_TEXT,
        "partial_link_text": By.PARTIAL_LINK_TEXT,
    }

    candidates: List[Locator] = [locator, *locator.fallbacks]
    last_err: Optional[BaseException] = None
    per_attempt = max(1.0, (timeout_ms / 1000.0) / max(1, len(candidates)))

    for cand in candidates:
        try:
            if cand.by in by_map:
                el = WebDriverWait(driver, per_attempt).until(
                    EC.presence_of_element_located((by_map[cand.by], cand.value))
                )
            elif cand.by == "text":
                xpath = f"//*[normalize-space(text())={_xpath_literal(cand.value)}]"
                el = WebDriverWait(driver, per_attempt).until(
                    EC.presence_of_element_located((By.XPATH, xpath))
                )
            elif cand.by == "placeholder":
                el = WebDriverWait(driver, per_attempt).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, f'[placeholder="{cand.value}"]')
                    )
                )
            elif cand.by == "testid":
                el = WebDriverWait(driver, per_attempt).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, f'[data-testid="{cand.value}"]')
                    )
                )
            elif cand.by == "role":
                el = WebDriverWait(driver, per_attempt).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, f'[role="{cand.value}"]')
                    )
                )
            elif cand.by == "label":
                xpath = (
                    f"//label[normalize-space(text())={_xpath_literal(cand.value)}]"
                    f"/following::*[self::input or self::textarea or self::select][1]"
                )
                el = WebDriverWait(driver, per_attempt).until(
                    EC.presence_of_element_located((By.XPATH, xpath))
                )
            else:
                raise ValueError(f"Unknown locator strategy: {cand.by}")
            return el, f"{cand.by}={cand.value}"
        except Exception as e:
            last_err = e
            continue

    raise LookupError(
        f"No locator matched (tried {[c.by + '=' + c.value for c in candidates]}): {last_err}"
    )


def _xpath_literal(s: str) -> str:
    """Quote a string safely for XPath 1.0 (which has no native escape)."""
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    parts = s.split("'")
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in parts) + ")"


# ---------- Engine-agnostic dispatch shims ----------

def _find(ctx, locator: Locator, timeout_ms: int):
    """Prefer the port's find (works for both Selenium + Playwright). Fall
    back to legacy resolve_element so existing tests that monkey-patch it
    keep working.

    Phase #9 self-heal: when ctx.locator_db is set, we consult the cache for
    a previously-winning selector and prepend it to the fallback chain. Any
    fallback that wins is then persisted back to the cache.
    """
    # Self-heal: enhance locator from cache if we have one.
    effective = locator
    host = ""
    if ctx.locator_db is not None:
        try:
            from utils.self_healing import enhance_locator, host_from_url
            host = host_from_url(_current_url(ctx))
            effective = enhance_locator(locator, host, ctx.locator_db)
        except Exception:
            effective = locator

    # Resolve via the port (or legacy driver fallback).
    if ctx.port is not None:
        el, used = ctx.port.find(effective, timeout_ms)
    else:
        el, used = resolve_element(ctx.driver, effective, timeout_ms)

    # Self-heal: record the winner if a non-primary saved the day.
    if ctx.locator_db is not None and host:
        try:
            from utils.self_healing import record_winning
            record_winning(locator, used, host, ctx.locator_db)
        except Exception:
            pass
    return el, used


def _evaluate(ctx, script: str, *args):
    """Engine-agnostic JS execution."""
    if ctx.port is not None:
        return ctx.port.evaluate(script, *args)
    return ctx.driver.execute_script(script, *args)


def _goto(ctx, url: str) -> None:
    if ctx.port is not None: ctx.port.goto(url)
    else: ctx.driver.get(url)


def _back(ctx) -> None:
    if ctx.port is not None: ctx.port.back()
    else: ctx.driver.back()


def _forward(ctx) -> None:
    if ctx.port is not None: ctx.port.forward()
    else: ctx.driver.forward()


def _reload(ctx) -> None:
    if ctx.port is not None: ctx.port.reload()
    else: ctx.driver.refresh()


def _current_url(ctx) -> str:
    if ctx.port is not None: return ctx.port.current_url
    return ctx.driver.current_url


def _take_screenshot(ctx, path: str) -> None:
    if ctx.port is not None: ctx.port.screenshot(path)
    elif ctx.driver: ctx.driver.save_screenshot(path)


# ============================================================
# Handler registry
# ============================================================

_HANDLERS: Dict[str, Callable] = {}


def register(op: str):
    def deco(fn):
        _HANDLERS[op] = fn
        return fn
    return deco


def known_ops() -> List[str]:
    return sorted(_HANDLERS.keys())


# ---------- Navigation ----------

@register("goto")
def _op_goto(action: Action, ctx: ActionContext) -> None:
    url = action.url or action.value
    if not url:
        raise ValueError("goto requires url or value")
    _goto(ctx, str(url))


@register("back")
def _op_back(action: Action, ctx: ActionContext) -> None:
    _back(ctx)


@register("forward")
def _op_forward(action: Action, ctx: ActionContext) -> None:
    _forward(ctx)


@register("reload")
def _op_reload(action: Action, ctx: ActionContext) -> None:
    _reload(ctx)


# ---------- Interaction ----------

@register("click")
def _op_click(action: Action, ctx: ActionContext) -> str:
    if not action.locator:
        raise ValueError("click requires a locator")
    el, used = _find(ctx, action.locator, action.timeout_ms or DEFAULT_TIMEOUT_MS)
    el.click()
    return used


@register("fill")
def _op_fill(action: Action, ctx: ActionContext) -> str:
    if not action.locator or action.value is None:
        raise ValueError("fill requires locator and value")
    el, used = _find(ctx, action.locator, action.timeout_ms or DEFAULT_TIMEOUT_MS)
    el.clear()
    el.send_keys(str(action.value))   # coerce: LLM may emit ints/booleans
    return used


@register("press")
def _op_press(action: Action, ctx: ActionContext) -> Optional[str]:
    """Press a key. With locator → on that element; without → global."""
    key_name = str(action.value or "").upper()
    if not key_name:
        raise ValueError("press: missing key name")

    if action.locator:
        el, used = _find(ctx, action.locator, action.timeout_ms or DEFAULT_TIMEOUT_MS)
        # Selenium path uses Keys.X mapping when raw WebElement is in play.
        if ctx.port is None:
            from selenium.webdriver.common.keys import Keys
            key = getattr(Keys, key_name, None)
            if key is None:
                raise ValueError(f"press: unknown key '{action.value}'")
            el.send_keys(key)
        else:
            # ElementHandle.send_keys takes a string; the port will translate.
            el.send_keys(key_name)
        return used

    # No locator → global keystroke.
    if ctx.port is not None:
        ctx.port.press_key(key_name)
    else:
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.common.action_chains import ActionChains
        key = getattr(Keys, key_name, None)
        if key is None:
            raise ValueError(f"press: unknown key '{action.value}'")
        ActionChains(ctx.driver).send_keys(key).perform()
    return None


@register("select")
def _op_select(action: Action, ctx: ActionContext) -> str:
    if not action.locator or action.value is None:
        raise ValueError("select requires locator and value")
    el, used = _find(ctx, action.locator, action.timeout_ms or DEFAULT_TIMEOUT_MS)
    if hasattr(el, "select_option"):
        el.select_option(str(action.value))
    else:
        # Raw Selenium WebElement (test stubs or legacy callers) — fall through.
        from selenium.webdriver.support.ui import Select
        Select(el).select_by_visible_text(str(action.value))
    return used


@register("hover")
def _op_hover(action: Action, ctx: ActionContext) -> str:
    if not action.locator:
        raise ValueError("hover requires locator")
    el, used = _find(ctx, action.locator, action.timeout_ms or DEFAULT_TIMEOUT_MS)
    if hasattr(el, "hover"):
        el.hover()
    else:
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(ctx.driver).move_to_element(el).perform()
    return used


# ---------- Wait / Sleep ----------

@register("wait_for")
def _op_wait_for(action: Action, ctx: ActionContext) -> str:
    if not action.locator:
        raise ValueError("wait_for requires locator")
    _, used = _find(ctx, action.locator, action.timeout_ms or DEFAULT_TIMEOUT_MS)
    return used


@register("wait_for_url")
def _op_wait_for_url(action: Action, ctx: ActionContext) -> None:
    pattern = action.expected or action.value
    if not pattern:
        raise ValueError("wait_for_url requires expected pattern")
    deadline = time.monotonic() + (action.timeout_ms or DEFAULT_TIMEOUT_MS) / 1000.0
    pat = str(pattern)
    while time.monotonic() < deadline:
        if re.search(pat, _current_url(ctx)):
            return
        time.sleep(0.2)
    raise AssertionError(f"wait_for_url: URL never matched /{pat}/")


@register("sleep")
def _op_sleep(action: Action, ctx: ActionContext) -> None:
    ms = int(action.value or action.timeout_ms or 0)
    time.sleep(min(ms / 1000.0, 5.0))  # cap at 5s to discourage abuse


# ---------- Assertions ----------

@register("assert_text")
def _op_assert_text(action: Action, ctx: ActionContext) -> str:
    if not action.locator or action.expected is None:
        raise ValueError("assert_text requires locator and expected")
    el, used = _find(ctx, action.locator, action.timeout_ms or DEFAULT_TIMEOUT_MS)
    text = (el.text or "").strip()
    expected = str(action.expected)
    if expected not in text:
        raise AssertionError(f"assert_text: '{expected}' not found in '{text}'")
    return used


@register("assert_visible")
def _op_assert_visible(action: Action, ctx: ActionContext) -> str:
    if not action.locator:
        raise ValueError("assert_visible requires locator")
    el, used = _find(ctx, action.locator, action.timeout_ms or DEFAULT_TIMEOUT_MS)
    if not el.is_displayed():
        raise AssertionError("assert_visible: element exists but is not displayed")
    return used


@register("assert_hidden")
def _op_assert_hidden(action: Action, ctx: ActionContext) -> Optional[str]:
    try:
        el, used = _find(ctx, action.locator, (action.timeout_ms or 1000))
    except LookupError:
        return None  # absent = hidden
    if el.is_displayed():
        raise AssertionError("assert_hidden: element is currently visible")
    return used


@register("assert_url")
def _op_assert_url(action: Action, ctx: ActionContext) -> None:
    pattern = action.expected or action.value
    actual = _current_url(ctx)
    if not re.search(str(pattern), actual):
        raise AssertionError(f"assert_url: '{actual}' does not match /{pattern}/")


@register("assert_value")
def _op_assert_value(action: Action, ctx: ActionContext) -> str:
    if not action.locator:
        raise ValueError("assert_value requires locator")
    el, used = _find(ctx, action.locator, action.timeout_ms or DEFAULT_TIMEOUT_MS)
    actual = el.get_attribute("value") or ""
    if actual != str(action.expected or ""):
        raise AssertionError(f"assert_value: expected '{action.expected}', got '{actual}'")
    return used


@register("screenshot")
def _op_screenshot(action: Action, ctx: ActionContext) -> None:
    path = action.value or "screenshot.png"
    _take_screenshot(ctx, str(path))


@register("scroll")
def _op_scroll(action: Action, ctx: ActionContext) -> None:
    if action.locator:
        el, _ = _find(ctx, action.locator, action.timeout_ms or DEFAULT_TIMEOUT_MS)
        if hasattr(el, "scroll_into_view"):
            el.scroll_into_view()
        else:
            ctx.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'})", el
            )
    else:
        y = int(action.value or 0)
        _evaluate(ctx, f"window.scrollTo(0, {y});")


# ============================================================
# Performance budgets (Web Vitals via browser native APIs)
# ============================================================

# This JS snippet runs in the page and returns the full perf snapshot.
# We keep it minimal so it works on any page load without setup.
_PERF_METRICS_SCRIPT = """
    const nav = (performance.getEntriesByType('navigation') || [])[0] || {};
    const paintEntries = performance.getEntriesByType('paint') || [];
    const fcpEntry = paintEntries.find(p => p.name === 'first-contentful-paint');
    const fcp = fcpEntry ? fcpEntry.startTime : null;

    let lcp = null;
    try {
        const lcpEntries = performance.getEntriesByType('largest-contentful-paint') || [];
        if (lcpEntries.length) lcp = lcpEntries[lcpEntries.length - 1].startTime;
    } catch (e) { /* not supported in some browsers */ }

    const resources = performance.getEntriesByType('resource') || [];
    const totalTransfer = resources.reduce((s, e) => s + (e.transferSize || 0), 0)
                          + (nav.transferSize || 0);

    return {
        ttfb_ms:          nav.responseStart ? Math.round(nav.responseStart) : null,
        fcp_ms:           fcp != null ? Math.round(fcp) : null,
        lcp_ms:           lcp != null ? Math.round(lcp) : null,
        dom_loaded_ms:    nav.domContentLoadedEventEnd ? Math.round(nav.domContentLoadedEventEnd) : null,
        load_complete_ms: nav.loadEventEnd ? Math.round(nav.loadEventEnd) : null,
        transfer_bytes:   totalTransfer,
        resource_count:   resources.length + 1,
        url:              location.href
    };
""".strip()


def _read_perf_metrics(driver_or_ctx) -> dict:
    """Run the perf-snapshot script and return a dict. Empty dict on error.

    Accepts either an ActionContext (preferred, port-aware) or a raw Selenium
    driver (legacy/test path). Selenium's execute_script wraps the body in an
    anonymous function — the script just needs to end with ``return``.
    """
    try:
        # ActionContext path (preferred): goes through the port.
        if hasattr(driver_or_ctx, "port") or hasattr(driver_or_ctx, "driver"):
            ctx = driver_or_ctx
            return _evaluate(ctx, _PERF_METRICS_SCRIPT) or {}
        # Legacy: raw selenium driver.
        return driver_or_ctx.execute_script(_PERF_METRICS_SCRIPT) or {}
    except Exception:
        return {}


def _expected_limit(action: Action) -> float:
    """Pull a numeric budget from the most common LLM field choices."""
    for candidate in (action.expected, action.value):
        if candidate is None:
            continue
        try:
            return float(candidate)
        except (TypeError, ValueError):
            continue
    raise ValueError("performance assertion requires a numeric budget on 'expected' or 'value'")


def _assert_metric_under(metrics: dict, key: str, op_name: str, limit: float, unit: str) -> None:
    actual = metrics.get(key)
    if actual is None:
        raise AssertionError(
            f"{op_name}: metric '{key}' not available "
            "(page may not have finished rendering, or the browser does not expose it)"
        )
    if actual > limit:
        raise AssertionError(f"{op_name}: {actual}{unit} exceeds budget {int(limit)}{unit}")


@register("assert_ttfb_under")
def _op_assert_ttfb_under(action: Action, ctx: ActionContext) -> None:
    metrics = _read_perf_metrics(ctx)
    _assert_metric_under(metrics, "ttfb_ms", "assert_ttfb_under", _expected_limit(action), "ms")


@register("assert_fcp_under")
def _op_assert_fcp_under(action: Action, ctx: ActionContext) -> None:
    metrics = _read_perf_metrics(ctx)
    _assert_metric_under(metrics, "fcp_ms", "assert_fcp_under", _expected_limit(action), "ms")


@register("assert_lcp_under")
def _op_assert_lcp_under(action: Action, ctx: ActionContext) -> None:
    metrics = _read_perf_metrics(ctx)
    _assert_metric_under(metrics, "lcp_ms", "assert_lcp_under", _expected_limit(action), "ms")


@register("assert_dom_loaded_under")
def _op_assert_dom_loaded_under(action: Action, ctx: ActionContext) -> None:
    metrics = _read_perf_metrics(ctx)
    _assert_metric_under(metrics, "dom_loaded_ms", "assert_dom_loaded_under",
                         _expected_limit(action), "ms")


@register("assert_page_load_under")
def _op_assert_page_load_under(action: Action, ctx: ActionContext) -> None:
    metrics = _read_perf_metrics(ctx)
    _assert_metric_under(metrics, "load_complete_ms", "assert_page_load_under",
                         _expected_limit(action), "ms")


@register("assert_page_size_under")
def _op_assert_page_size_under(action: Action, ctx: ActionContext) -> None:
    metrics = _read_perf_metrics(ctx)
    _assert_metric_under(metrics, "transfer_bytes", "assert_page_size_under",
                         _expected_limit(action), " bytes")


@register("assert_resource_count_under")
def _op_assert_resource_count_under(action: Action, ctx: ActionContext) -> None:
    metrics = _read_perf_metrics(ctx)
    _assert_metric_under(metrics, "resource_count", "assert_resource_count_under",
                         _expected_limit(action), " requests")


@register("measure_perf")
def _op_measure_perf(action: Action, ctx: ActionContext) -> None:
    """Capture the full perf snapshot. If ``name`` is set, bind it to ctx.variables
    so later assertions or reports can reference it."""
    metrics = _read_perf_metrics(ctx)
    ctx.variables[action.name or "perf"] = metrics


# ============================================================
# Auth state — save once, reuse across tests
# ============================================================

import os

AUTH_STATES_DIR = "data/auth_states"

# Filename safety: alphanumerics + dash + underscore + dot only.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _auth_state_path(name: str) -> str:
    """Resolve a name like ``my_session`` to ``data/auth_states/my_session.json``.

    Rejects path traversal attempts and reserved characters. The state file
    lives under ``data/auth_states/`` and never escapes that directory.
    """
    if not name:
        raise ValueError("auth state name is required")
    if not _SAFE_NAME_RE.match(name):
        raise ValueError(
            f"invalid auth state name '{name}': use letters, digits, '.', '_', '-' only"
        )
    if not name.endswith(".json"):
        name = name + ".json"
    base = os.path.abspath(AUTH_STATES_DIR)
    candidate = os.path.abspath(os.path.join(base, name))
    if not candidate.startswith(base + os.sep) and candidate != base:
        raise ValueError("auth state path escapes the sandbox")
    return candidate


def _save_auth(ctx, path: str) -> None:
    if ctx.port is not None and hasattr(ctx.port, "save_auth_state"):
        ctx.port.save_auth_state(path)
        return
    # Selenium fallback when no port (legacy / test ctx with driver only).
    if ctx.driver is None:
        raise RuntimeError("save_auth needs a browser port or driver")
    cookies = ctx.driver.get_cookies() or []
    try:
        ls = ctx.driver.execute_script(
            "var o = {}; for (var i=0; i<localStorage.length; i++) "
            "{ var k = localStorage.key(i); o[k] = localStorage.getItem(k); } return o;"
        ) or {}
    except Exception:
        ls = {}
    snap = {"engine": "selenium", "url": ctx.driver.current_url,
            "cookies": cookies, "local_storage": ls}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=2)


def _load_auth(ctx, path: str) -> None:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"auth state file not found: {path}")
    if ctx.port is not None and hasattr(ctx.port, "load_auth_state"):
        ctx.port.load_auth_state(path)
        return
    # Fallback to direct selenium driver.
    if ctx.driver is None:
        raise RuntimeError("load_auth needs a browser port or driver")
    with open(path, "r", encoding="utf-8") as f:
        snap = json.load(f) or {}
    target = snap.get("url")
    if target:
        ctx.driver.get(target)
    for c in snap.get("cookies", []) or []:
        cookie = dict(c)
        cookie.pop("sameSite", None)
        try:
            ctx.driver.add_cookie(cookie)
        except Exception:
            continue
    for k, v in (snap.get("local_storage") or {}).items():
        try:
            ctx.driver.execute_script(
                "window.localStorage.setItem(arguments[0], arguments[1]);", k, str(v)
            )
        except Exception:
            continue
    if target:
        ctx.driver.get(target)


@register("save_auth")
def _op_save_auth(action: Action, ctx: ActionContext) -> str:
    """Save cookies + localStorage of the current origin to a named state file.

    Use ``value`` (preferred) or ``name`` to name the state — e.g.
    ``{"op": "save_auth", "value": "logged_in_admin"}``.
    """
    name = str(action.value or action.name or "")
    path = _auth_state_path(name)
    _save_auth(ctx, path)
    return f"saved={path}"


@register("load_auth")
def _op_load_auth(action: Action, ctx: ActionContext) -> str:
    """Restore a previously-saved auth state. Visits the saved URL after
    applying cookies + localStorage so the page renders authenticated."""
    name = str(action.value or action.name or "")
    path = _auth_state_path(name)
    _load_auth(ctx, path)
    return f"loaded={path}"


# ============================================================
# Device emulation (mobile / tablet)
# ============================================================

def _parse_viewport_spec(action: Action) -> tuple:
    """Accept width/height as 'WxH' string OR value=W expected=H."""
    raw_value = action.value
    if isinstance(raw_value, str) and "x" in raw_value.lower():
        a, b = raw_value.lower().split("x", 1)
        return int(a.strip()), int(b.strip())
    if raw_value is not None and action.expected is not None:
        return int(raw_value), int(action.expected)
    raise ValueError(
        "set_viewport: provide value='WIDTHxHEIGHT' or value=WIDTH + expected=HEIGHT"
    )


@register("set_viewport")
def _op_set_viewport(action: Action, ctx: ActionContext) -> str:
    """Resize the browser viewport. Accepts ``value="375x667"`` or
    ``value=375 expected=667``. Works on both Selenium + Playwright."""
    width, height = _parse_viewport_spec(action)
    if width <= 0 or height <= 0:
        raise ValueError(f"set_viewport: invalid size {width}x{height}")
    if ctx.port is not None and hasattr(ctx.port, "set_viewport"):
        ctx.port.set_viewport(width, height)
    elif ctx.driver is not None:
        ctx.driver.set_window_size(width, height)
    return f"viewport={width}x{height}"


# ============================================================
# Accessibility (axe-core)
# ============================================================

@register("assert_a11y")
def _op_assert_a11y(action: Action, ctx: ActionContext) -> str:
    """Inject axe-core, run an accessibility scan, fail if any violation is
    at-or-above the configured severity threshold.

    Usage:
        {"op": "assert_a11y"}                               # default: serious
        {"op": "assert_a11y", "expected": "critical"}       # strictest
        {"op": "assert_a11y", "expected": "any"}            # any violation fails
        {"op": "assert_a11y", "value": "moderate"}          # value also accepted
    """
    from utils.a11y import run_axe, filter_violations, summarize_violations

    threshold = str(action.expected or action.value or "serious").lower()
    timeout_ms = action.timeout_ms or 15_000

    result = run_axe(ctx, timeout_ms=timeout_ms)
    violations = result.get("violations") or []
    blocking = filter_violations(violations, threshold=threshold)

    # Bind the full report so a later step can `measure_perf`-style read it.
    if action.name:
        ctx.variables[action.name] = result

    if blocking:
        # Surface the worst-impact rule first for readable error output.
        top = max(blocking,
                  key=lambda v: ["minor", "moderate", "serious", "critical"]
                                .index(v.get("impact", "minor")
                                       if v.get("impact") in
                                          ("minor", "moderate", "serious", "critical")
                                       else "minor"))
        raise AssertionError(
            f"assert_a11y[{threshold}]: {summarize_violations(blocking)} — "
            f"top: {top.get('id')} ({top.get('impact')}) — {top.get('help')}"
        )
    return f"a11y_pass=violations={len(violations)} blocking=0"


@register("measure_a11y")
def _op_measure_a11y(action: Action, ctx: ActionContext) -> str:
    """Run axe-core and bind the full report to ctx.variables[name].
    Useful when you want the report on a passing page (or want to assert
    separately afterwards). Never raises on the audit itself — only on
    infrastructure errors (axe-core failed to load)."""
    from utils.a11y import run_axe

    timeout_ms = action.timeout_ms or 15_000
    result = run_axe(ctx, timeout_ms=timeout_ms)
    ctx.variables[action.name or "a11y"] = result
    return f"a11y_violations={result.get('violation_count', 0)}"


@register("emulate_device")
def _op_emulate_device(action: Action, ctx: ActionContext) -> str:
    """Apply a device preset — viewport + user agent + touch hints.

    Examples:
        {"op": "emulate_device", "value": "iPhone 13"}
        {"op": "emulate_device", "value": "Pixel 5"}
        {"op": "emulate_device", "value": "Desktop"}   // reset
    """
    from utils.engines.devices import get_device, normalize_device_name, list_devices

    name = str(action.value or action.name or "")
    device = get_device(name)
    if device is None:
        raise ValueError(
            f"emulate_device: unknown device '{name}'. Known: {', '.join(list_devices())}"
        )

    if ctx.port is not None and hasattr(ctx.port, "emulate_device"):
        ctx.port.emulate_device(device)
    elif ctx.driver is not None:
        vp = device.get("viewport") or {}
        if vp.get("width") and vp.get("height"):
            ctx.driver.set_window_size(int(vp["width"]), int(vp["height"]))
    return f"device={normalize_device_name(name)}"


# ============================================================
# Visual regression (Feature #4)
# ============================================================

DEFAULT_VISUAL_THRESHOLD = 0.98


def _capture_screenshot(ctx: "ActionContext", path: str) -> None:
    """Wrap port/driver screenshot with a consistent error surface."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if ctx.port is not None:
        ctx.port.screenshot(path)
        return
    if ctx.driver is not None:
        ctx.driver.save_screenshot(path)
        return
    raise RuntimeError("visual op needs a browser port or driver")


def _write_visual_sidecar(image_path: str, ctx: "ActionContext", name: str, kind: str) -> None:
    """Drop a JSON sidecar next to the PNG with provenance + dimensions."""
    try:
        from utils.visual_diff import image_sha256, image_size
        w, h = image_size(image_path)
        meta = {
            "name": name,
            "kind": kind,                # 'baseline' | 'actual' | 'diff'
            "user_id": getattr(ctx, "user_id", None),
            "session_id": getattr(ctx, "session_id", None),
            "url": _current_url(ctx) if (ctx.port or ctx.driver) else None,
            "width": w,
            "height": h,
            "sha256": image_sha256(image_path),
            "created_at": time.time(),
        }
        with open(image_path.rsplit(".", 1)[0] + ".json", "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2, default=str)
    except Exception:
        # Sidecar is best-effort — never let it sink the test.
        pass


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "force", "overwrite")
    return False


@register("visual_baseline")
def _op_visual_baseline(action: Action, ctx: ActionContext) -> str:
    """Capture a named baseline screenshot (or no-op if one already exists).

    Examples:
        {"op": "visual_baseline", "value": "checkout_page"}
        {"op": "visual_baseline", "value": "checkout_page", "expected": "force"}

    Set ``expected`` to a truthy/"force" string to overwrite an existing
    baseline — useful when the UI intentionally changed.
    """
    from utils.visual_store import baseline_path as _bp
    name = str(action.value or action.name or "").strip()
    path = _bp(getattr(ctx, "user_id", None), name)
    force = _truthy(action.expected)
    if os.path.exists(path) and not force:
        ctx.visual_artifacts.append({"name": name, "kind": "baseline",
                                     "path": path, "status": "kept"})
        return f"baseline:{name}=kept"
    _capture_screenshot(ctx, path)
    _write_visual_sidecar(path, ctx, name, "baseline")
    ctx.visual_artifacts.append({"name": name, "kind": "baseline",
                                 "path": path, "status": "saved"})
    return f"baseline:{name}=saved"


@register("assert_visual_match")
def _op_assert_visual_match(action: Action, ctx: ActionContext) -> str:
    """Compare a fresh screenshot against the named baseline.

    Behaviour:
      * No baseline yet  → capture one and soft-pass with `seeded` status.
      * Baseline exists  → take an actual, compare, fail if similarity
        is below ``expected`` (default ``DEFAULT_VISUAL_THRESHOLD``).

    A diff artifact is written under ``data/visual_artifacts/<user>/`` so
    the UI can render a baseline-vs-actual lightbox.
    """
    from utils.visual_store import (
        baseline_path as _bp,
        artifact_path as _ap,
    )
    name = str(action.value or action.name or "").strip()
    uid = getattr(ctx, "user_id", None)
    baseline_path = _bp(uid, name)
    if not os.path.exists(baseline_path):
        _capture_screenshot(ctx, baseline_path)
        _write_visual_sidecar(baseline_path, ctx, name, "baseline")
        ctx.visual_artifacts.append({"name": name, "kind": "baseline",
                                     "path": baseline_path, "status": "seeded"})
        return f"visual:{name}=seeded"

    actual_path = _ap(uid, name, "actual")
    _capture_screenshot(ctx, actual_path)

    threshold = DEFAULT_VISUAL_THRESHOLD
    if action.expected is not None:
        try:
            threshold = float(action.expected)
        except (TypeError, ValueError):
            pass

    from utils.visual_diff import compare_images, render_diff, VisualDiffUnavailable
    try:
        result = compare_images(baseline_path, actual_path, threshold=threshold)
    except VisualDiffUnavailable as e:
        raise AssertionError(
            f"assert_visual_match[{name}]: {e}"
        )

    if not result.passed:
        diff_path = _ap(uid, name, "diff")
        try:
            render_diff(baseline_path, actual_path, diff_path, result.diff_box)
        except Exception:
            diff_path = None
        ctx.visual_artifacts.append({
            "name": name, "kind": "diff",
            "baseline": baseline_path, "actual": actual_path, "diff": diff_path,
            "similarity": result.similarity, "threshold": result.threshold,
            "diff_percent": result.diff_percent, "status": "failed",
        })
        raise AssertionError(
            f"assert_visual_match[{name}]: similarity {result.similarity:.4f} "
            f"below threshold {result.threshold:.4f} "
            f"({result.diff_percent:.2f}% changed). "
            f"baseline={baseline_path} actual={actual_path}"
        )

    ctx.visual_artifacts.append({
        "name": name, "kind": "match",
        "baseline": baseline_path, "actual": actual_path,
        "similarity": result.similarity, "threshold": result.threshold,
        "status": "passed",
    })
    return f"visual:{name}=match({result.similarity:.4f})"


# ---------- HTTP / API ----------

def _do_http(method: str, action: Action, ctx: ActionContext) -> None:
    import requests
    url = action.url or action.value
    if not url:
        raise ValueError(f"{method} requires url")
    started = time.monotonic()
    resp = requests.request(
        method,
        url,
        headers=action.headers or None,
        json=action.body if action.body is not None else None,
        timeout=(action.timeout_ms or DEFAULT_TIMEOUT_MS) / 1000.0,
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    record = {
        "status": resp.status_code,
        "headers": dict(resp.headers),
        "elapsed_ms": elapsed_ms,
        "text": resp.text[:5000],
    }
    try:
        record["json"] = resp.json()
    except Exception:
        record["json"] = None
    ctx.last_http_response = record
    if action.name:
        ctx.variables[action.name] = record


@register("http_get")
def _op_http_get(action: Action, ctx: ActionContext) -> None:
    _do_http("GET", action, ctx)


@register("http_post")
def _op_http_post(action: Action, ctx: ActionContext) -> None:
    _do_http("POST", action, ctx)


@register("http_put")
def _op_http_put(action: Action, ctx: ActionContext) -> None:
    _do_http("PUT", action, ctx)


@register("http_delete")
def _op_http_delete(action: Action, ctx: ActionContext) -> None:
    _do_http("DELETE", action, ctx)


@register("http_patch")
def _op_http_patch(action: Action, ctx: ActionContext) -> None:
    _do_http("PATCH", action, ctx)


@register("assert_status")
def _op_assert_status(action: Action, ctx: ActionContext) -> None:
    if ctx.last_http_response is None:
        raise AssertionError("assert_status: no prior HTTP response")
    actual = ctx.last_http_response["status"]
    if int(actual) != int(action.expected):
        raise AssertionError(f"assert_status: expected {action.expected}, got {actual}")


@register("assert_json_path")
def _op_assert_json_path(action: Action, ctx: ActionContext) -> None:
    if ctx.last_http_response is None or ctx.last_http_response.get("json") is None:
        raise AssertionError("assert_json_path: no JSON body on last response")
    body = ctx.last_http_response["json"]
    path = action.json_path or ""
    actual = _walk_json_path(body, path)
    if actual != action.expected:
        raise AssertionError(
            f"assert_json_path: at '{path}' expected {action.expected!r}, got {actual!r}"
        )


@register("assert_header")
def _op_assert_header(action: Action, ctx: ActionContext) -> None:
    if ctx.last_http_response is None:
        raise AssertionError("assert_header: no prior HTTP response")
    name = action.value or ""
    headers = ctx.last_http_response.get("headers") or {}
    actual = headers.get(name) or headers.get(name.lower())
    if action.expected is not None and actual != action.expected:
        raise AssertionError(
            f"assert_header[{name}]: expected {action.expected!r}, got {actual!r}"
        )


@register("assert_response_time")
def _op_assert_response_time(action: Action, ctx: ActionContext) -> None:
    if ctx.last_http_response is None:
        raise AssertionError("assert_response_time: no prior HTTP response")
    limit = int(action.expected or 0)
    elapsed = ctx.last_http_response.get("elapsed_ms", 0)
    if elapsed > limit:
        raise AssertionError(f"assert_response_time: {elapsed}ms exceeds limit {limit}ms")


def _walk_json_path(body: Any, path: str) -> Any:
    """Minimal JSONPath-ish walker — supports dotted keys and [index]."""
    cur = body
    if not path or path == "$":
        return cur
    path = path.lstrip("$").lstrip(".")
    parts = re.split(r"\.|\[(\d+)\]", path)
    for raw in parts:
        if raw is None or raw == "":
            continue
        if raw.isdigit():
            cur = cur[int(raw)]
        else:
            cur = cur[raw]
    return cur


# ============================================================
# Dispatcher (retry + timing wrapper)
# ============================================================

def execute_plan(
    actions: List[Action],
    ctx: ActionContext,
    retries: int = DEFAULT_RETRIES,
) -> List[ActionResult]:
    """Run every action, capturing per-step results. Raises on first hard fail."""
    results: List[ActionResult] = []
    for action in actions:
        handler = _HANDLERS.get(action.op)
        if handler is None:
            results.append(ActionResult(
                op=action.op, success=False, error=f"Unknown op: {action.op}"
            ))
            raise ValueError(f"Unknown op: {action.op}")

        attempts = 0
        started = time.monotonic()
        last_err: Optional[BaseException] = None
        locator_used: Optional[str] = None

        while attempts < retries:
            attempts += 1
            try:
                locator_used = handler(action, ctx)
                duration_ms = int((time.monotonic() - started) * 1000)
                results.append(ActionResult(
                    op=action.op, success=True, duration_ms=duration_ms,
                    attempts=attempts, locator_used=locator_used,
                ))
                break
            except AssertionError as e:
                # Assertions are not retried — they're real failures.
                duration_ms = int((time.monotonic() - started) * 1000)
                results.append(ActionResult(
                    op=action.op, success=False, duration_ms=duration_ms,
                    attempts=attempts, error=f"AssertionError: {e}",
                ))
                raise
            except Exception as e:
                last_err = e
                if attempts >= retries or not _is_transient(e):
                    duration_ms = int((time.monotonic() - started) * 1000)
                    results.append(ActionResult(
                        op=action.op, success=False, duration_ms=duration_ms,
                        attempts=attempts, error=f"{type(e).__name__}: {e}",
                    ))
                    raise
                time.sleep(0.4)
        else:  # while-else: only fires if break didn't happen
            duration_ms = int((time.monotonic() - started) * 1000)
            results.append(ActionResult(
                op=action.op, success=False, duration_ms=duration_ms,
                attempts=attempts, error=f"{type(last_err).__name__}: {last_err}",
            ))
            raise last_err or RuntimeError("action failed after retries")

    return results


def used_flaky_retry(results: List[ActionResult]) -> bool:
    """True if every action passed but at least one required >1 attempt."""
    if not results:
        return False
    return all(r.success for r in results) and any(r.attempts > 1 for r in results)
