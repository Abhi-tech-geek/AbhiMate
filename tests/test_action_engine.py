"""Dispatcher tests for the action engine — driver is faked.

We avoid real Selenium by injecting a stub driver that records the calls we
care about, then assert against that record. Locator-resolution logic that
needs WebDriverWait is exercised via patched expected_conditions.
"""

from unittest.mock import MagicMock, patch

import pytest

from utils.action_engine import (
    execute_plan, ActionContext, used_flaky_retry, known_ops,
)
from utils.models import Action, Locator, ActionResult


class StubElement:
    def __init__(self, text="", displayed=True, value=""):
        self.text = text
        self._displayed = displayed
        self._value = value
        self.cleared = False
        self.clicked = False
        self.keys = []

    def click(self): self.clicked = True
    def clear(self): self.cleared = True
    def send_keys(self, k): self.keys.append(k)
    def is_displayed(self): return self._displayed
    def get_attribute(self, name): return self._value if name == "value" else None


def make_driver(element=None, current_url="https://example.com/home"):
    drv = MagicMock()
    drv.current_url = current_url
    if element is not None:
        drv.find_element = MagicMock(return_value=element)
        drv.find_elements = MagicMock(return_value=[element])
    return drv


def patched_resolve(monkeypatch, element, used_locator="id=email"):
    """Bypass real WebDriverWait — return the stub element directly."""
    monkeypatch.setattr(
        "utils.action_engine.resolve_element",
        lambda driver, locator, timeout_ms: (element, used_locator),
    )


def test_known_ops_includes_core_vocab():
    ops = set(known_ops())
    for required in ["goto", "click", "fill", "wait_for", "assert_visible",
                     "assert_url", "screenshot", "http_get", "assert_status"]:
        assert required in ops, f"missing op: {required}"


def test_goto_dispatches_to_driver():
    drv = make_driver()
    ctx = ActionContext(driver=drv)
    results = execute_plan([Action(op="goto", url="https://x.com")], ctx, retries=1)
    drv.get.assert_called_once_with("https://x.com")
    assert results[0].success
    assert results[0].op == "goto"


def test_fill_clears_then_sends(monkeypatch):
    el = StubElement()
    drv = make_driver(el)
    patched_resolve(monkeypatch, el)
    ctx = ActionContext(driver=drv)
    execute_plan([
        Action(op="fill", locator=Locator(by="id", value="email"), value="u@x.com"),
    ], ctx, retries=1)
    assert el.cleared
    assert "u@x.com" in el.keys


def test_assert_text_passes_on_match(monkeypatch):
    el = StubElement(text="Welcome back, Alice")
    patched_resolve(monkeypatch, el)
    ctx = ActionContext(driver=make_driver())
    out = execute_plan([
        Action(op="assert_text",
               locator=Locator(by="id", value="hi"),
               expected="Welcome back"),
    ], ctx, retries=1)
    assert out[0].success


def test_assert_text_raises_on_mismatch(monkeypatch):
    el = StubElement(text="Forbidden")
    patched_resolve(monkeypatch, el)
    ctx = ActionContext(driver=make_driver())
    with pytest.raises(AssertionError):
        execute_plan([
            Action(op="assert_text",
                   locator=Locator(by="id", value="hi"),
                   expected="Welcome"),
        ], ctx, retries=1)


def test_assert_url_pattern():
    drv = make_driver(current_url="https://example.com/dashboard?id=1")
    ctx = ActionContext(driver=drv)
    execute_plan([Action(op="assert_url", expected=r"/dashboard")], ctx, retries=1)


def test_unknown_op_raises():
    ctx = ActionContext(driver=make_driver())
    with pytest.raises(ValueError):
        execute_plan([Action(op="teleport")], ctx, retries=1)


def test_retry_on_transient(monkeypatch):
    """First call raises a transient error, second call succeeds — should pass."""
    calls = {"n": 0}

    def flaky_handler(action, ctx):
        calls["n"] += 1
        if calls["n"] == 1:
            from selenium.common.exceptions import StaleElementReferenceException
            raise StaleElementReferenceException("stale element")
        return "id=ok"

    monkeypatch.setitem(
        __import__("utils.action_engine", fromlist=["_HANDLERS"])._HANDLERS,
        "flaky_test_op",
        flaky_handler,
    )

    ctx = ActionContext(driver=make_driver())
    results = execute_plan([Action(op="flaky_test_op")], ctx, retries=3)
    assert results[0].success
    assert results[0].attempts == 2
    assert used_flaky_retry(results)


def test_assertion_errors_are_not_retried(monkeypatch):
    calls = {"n": 0}

    def asserting(action, ctx):
        calls["n"] += 1
        raise AssertionError("nope")

    monkeypatch.setitem(
        __import__("utils.action_engine", fromlist=["_HANDLERS"])._HANDLERS,
        "always_assert_fail",
        asserting,
    )

    ctx = ActionContext(driver=make_driver())
    with pytest.raises(AssertionError):
        execute_plan([Action(op="always_assert_fail")], ctx, retries=5)
    assert calls["n"] == 1
