"""BrowserPort abstraction tests.

Two layers:
1. Locator translation in ``locator_to_css`` and ``_xpath_literal``.
2. The action engine dispatches handlers through the port — verified by
   running the same Action Plan against a fake port and checking the
   recorded call log.
"""

from unittest.mock import MagicMock

import pytest

from utils.action_engine import execute_plan, ActionContext, known_ops
from utils.models import Action, Locator
from utils.engines.port import locator_to_css, _xpath_literal


# ----------------------------------------------------------------------
# Locator translation
# ----------------------------------------------------------------------

@pytest.mark.parametrize("by,value,expected", [
    ("id",          "email",          "#email"),
    ("name",        "username",       '[name="username"]'),
    ("css",         ".btn-primary",   ".btn-primary"),
    ("testid",      "submit",         '[data-testid="submit"]'),
    ("role",        "button",         '[role="button"]'),
    ("placeholder", "Enter email",    '[placeholder="Enter email"]'),
])
def test_locator_to_css_simple(by, value, expected):
    assert locator_to_css(Locator(by=by, value=value)) == expected


def test_locator_to_css_text_uses_xpath():
    css = locator_to_css(Locator(by="text", value="Sign in"))
    assert css.startswith("xpath=") and "Sign in" in css


def test_locator_to_css_xpath_passthrough():
    css = locator_to_css(Locator(by="xpath", value="//div[@id='x']"))
    assert css == "xpath=//div[@id='x']"


def test_xpath_literal_escapes_quotes():
    assert _xpath_literal("hello") == "'hello'"
    assert _xpath_literal('he said "hi"') == "'he said \"hi\"'"
    # Both quotes present → concat() expression
    assert "concat(" in _xpath_literal("it's \"funny\"")


# ----------------------------------------------------------------------
# Fake BrowserPort — verifies handlers go through port methods
# ----------------------------------------------------------------------

class _FakeElement:
    """Implements ElementHandle protocol for tests."""
    def __init__(self, text="", displayed=True, value=""):
        self._text = text
        self._displayed = displayed
        self._value = value
        self.calls = []

    def click(self): self.calls.append(("click",))
    def clear(self): self.calls.append(("clear",))
    def send_keys(self, v): self.calls.append(("send_keys", v))
    def fill(self, v): self.calls.append(("fill", v))
    def hover(self): self.calls.append(("hover",))
    def select_option(self, t): self.calls.append(("select_option", t))
    def scroll_into_view(self): self.calls.append(("scroll_into_view",))
    @property
    def text(self): return self._text
    def is_displayed(self): return self._displayed
    def get_attribute(self, name): return self._value if name == "value" else None


class _FakePort:
    """Minimum BrowserPort — records every call for assertions."""
    def __init__(self, element=None, current_url="https://example.com/x"):
        self.element = element or _FakeElement()
        self._current_url = current_url
        self.calls = []
        self.driver = None
        self._logs = []

    def start(self): return self
    def quit(self): pass

    def goto(self, url): self.calls.append(("goto", url))
    def back(self): self.calls.append(("back",))
    def forward(self): self.calls.append(("forward",))
    def reload(self): self.calls.append(("reload",))

    @property
    def current_url(self): return self._current_url

    def find(self, locator, timeout_ms):
        self.calls.append(("find", locator.by, locator.value, timeout_ms))
        return self.element, f"{locator.by}={locator.value}"

    def evaluate(self, script, *args):
        self.calls.append(("evaluate", script[:30]))
        return {}

    execute_script = evaluate

    def screenshot(self, path): self.calls.append(("screenshot", path))
    def drain_console_logs(self): return self._logs
    def press_key(self, key): self.calls.append(("press_key", key))


def make_ctx(element=None, url="https://example.com/x"):
    port = _FakePort(element=element, current_url=url)
    return ActionContext(port=port), port


# ----------------------------------------------------------------------
# Handler tests via fake port — same coverage as Selenium tests
# ----------------------------------------------------------------------

def test_goto_routes_through_port():
    ctx, port = make_ctx()
    execute_plan([Action(op="goto", url="https://x.com")], ctx, retries=1)
    assert ("goto", "https://x.com") in port.calls


def test_click_routes_through_port():
    el = _FakeElement()
    ctx, port = make_ctx(element=el)
    execute_plan([Action(op="click", locator=Locator(by="css", value="button"))],
                 ctx, retries=1)
    assert any(c[0] == "find" for c in port.calls)
    assert ("click",) in el.calls


def test_fill_clears_then_sends_via_port():
    el = _FakeElement()
    ctx, port = make_ctx(element=el)
    execute_plan([
        Action(op="fill", locator=Locator(by="id", value="email"), value="u@x.com"),
    ], ctx, retries=1)
    assert ("clear",) in el.calls
    assert ("send_keys", "u@x.com") in el.calls


def test_select_uses_port_element_method():
    el = _FakeElement()
    ctx, port = make_ctx(element=el)
    execute_plan([
        Action(op="select", locator=Locator(by="id", value="country"), value="IN"),
    ], ctx, retries=1)
    assert ("select_option", "IN") in el.calls


def test_hover_uses_port_element_method():
    el = _FakeElement()
    ctx, port = make_ctx(element=el)
    execute_plan([
        Action(op="hover", locator=Locator(by="css", value=".menu")),
    ], ctx, retries=1)
    assert ("hover",) in el.calls


def test_assert_text_via_port():
    el = _FakeElement(text="Welcome back, Alice")
    ctx, port = make_ctx(element=el)
    execute_plan([
        Action(op="assert_text",
               locator=Locator(by="id", value="hi"),
               expected="Welcome back"),
    ], ctx, retries=1)


def test_assert_text_failure_propagates():
    el = _FakeElement(text="Forbidden")
    ctx, port = make_ctx(element=el)
    with pytest.raises(AssertionError):
        execute_plan([
            Action(op="assert_text",
                   locator=Locator(by="id", value="hi"),
                   expected="Welcome"),
        ], ctx, retries=1)


def test_assert_url_pulls_from_port():
    ctx, port = make_ctx(url="https://example.com/dashboard")
    execute_plan([Action(op="assert_url", expected=r"/dashboard")], ctx, retries=1)


def test_scroll_element_uses_port():
    el = _FakeElement()
    ctx, port = make_ctx(element=el)
    execute_plan([Action(op="scroll", locator=Locator(by="id", value="footer"))],
                 ctx, retries=1)
    assert ("scroll_into_view",) in el.calls


def test_scroll_window_routes_through_evaluate():
    ctx, port = make_ctx()
    execute_plan([Action(op="scroll", value=200)], ctx, retries=1)
    assert any(c[0] == "evaluate" for c in port.calls)


def test_press_key_global_routes_through_port():
    ctx, port = make_ctx()
    execute_plan([Action(op="press", value="enter")], ctx, retries=1)
    assert ("press_key", "ENTER") in port.calls


def test_press_key_on_element_uses_send_keys():
    el = _FakeElement()
    ctx, port = make_ctx(element=el)
    execute_plan([
        Action(op="press", locator=Locator(by="id", value="search"), value="enter"),
    ], ctx, retries=1)
    # Element receives a send_keys with the key name (port translates).
    assert any(c[0] == "send_keys" for c in el.calls)


def test_unknown_op_still_blocked_with_port():
    ctx, port = make_ctx()
    with pytest.raises(ValueError):
        execute_plan([Action(op="not_a_real_op")], ctx, retries=1)


def test_known_ops_unchanged_after_refactor():
    ops = set(known_ops())
    # Core ops still present after the port refactor
    for required in ["goto", "click", "fill", "press", "select", "hover",
                     "wait_for", "wait_for_url", "sleep",
                     "assert_text", "assert_visible", "assert_hidden",
                     "assert_url", "assert_value",
                     "screenshot", "scroll",
                     "http_get", "http_post", "assert_status",
                     "assert_lcp_under", "measure_perf"]:
        assert required in ops, f"lost op after refactor: {required}"


def test_selenium_port_module_imports():
    """Smoke: the SeleniumPort can be constructed without instantiating selenium."""
    from utils.engines.selenium_port import SeleniumPort
    p = SeleniumPort()
    assert p.driver is None
    assert p._driver_wrap is None


def test_build_port_factory_selenium_default():
    from utils.engines import build_port
    p = build_port("selenium")
    assert p.__class__.__name__ == "SeleniumPort"


def test_build_port_factory_playwright_raises_friendly():
    """Without playwright installed, building the port should still succeed
    (lazy import) — only .start() would fail with a friendly message."""
    from utils.engines import build_port
    p = build_port("playwright")
    # Class itself constructs fine
    assert p.__class__.__name__ == "PlaywrightPort"
