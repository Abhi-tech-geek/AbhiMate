"""Feature #13 — mobile/tablet device emulation.

Two surfaces:
1. Device registry + name normalization
2. emulate_device + set_viewport action ops dispatch through the port
"""

import pytest

from utils.action_engine import execute_plan, ActionContext, known_ops
from utils.models import Action
from utils.engines.devices import (
    DEVICES, get_device, normalize_device_name, list_devices,
)


# ---------- Device registry ----------

def test_device_registry_includes_core_presets():
    for needed in ["Desktop", "iPhone 13", "Pixel 5", "iPad Pro 11", "Galaxy S22"]:
        assert needed in DEVICES, f"missing device preset: {needed}"


def test_normalize_known_aliases():
    assert normalize_device_name("iphone") == "iPhone 13"
    assert normalize_device_name("Pixel") == "Pixel 5"
    assert normalize_device_name("ipad") == "iPad Pro 11"
    assert normalize_device_name("samsung") == "Galaxy S22"
    assert normalize_device_name("DESKTOP") == "Desktop"
    assert normalize_device_name("iPhone 13") == "iPhone 13"  # exact passthrough


def test_normalize_unknown_returns_none():
    assert normalize_device_name("Nokia 3310") is None
    assert normalize_device_name("") is None
    assert normalize_device_name(None) is None


def test_get_device_returns_full_descriptor():
    iphone = get_device("iPhone 13")
    assert iphone is not None
    assert iphone["viewport"]["width"] == 390
    assert iphone["viewport"]["height"] == 844
    assert iphone["is_mobile"] is True
    assert iphone["has_touch"] is True
    assert "iPhone" in iphone["user_agent"]


def test_list_devices_starts_with_desktop():
    lst = list_devices()
    assert lst[0] == "Desktop"
    assert "iPhone 13" in lst
    assert "Pixel 5" in lst


# ---------- Action op dispatch via fake port ----------

class _StubDevicePort:
    """Records every emulate_device / set_viewport call."""
    def __init__(self):
        self.viewports = []
        self.user_agents = []
        self.devices = []
        self.driver = None
    def emulate_device(self, device):
        self.devices.append(device)
        vp = device.get("viewport") or {}
        if vp.get("width") and vp.get("height"):
            self.viewports.append((vp["width"], vp["height"]))
        if device.get("user_agent"):
            self.user_agents.append(device["user_agent"])
    def set_viewport(self, w, h):
        self.viewports.append((int(w), int(h)))
    def set_user_agent(self, ua):
        self.user_agents.append(ua)


def make_ctx():
    p = _StubDevicePort()
    return ActionContext(port=p), p


def test_emulate_device_op_registered():
    assert "emulate_device" in known_ops()
    assert "set_viewport" in known_ops()


def test_emulate_device_applies_preset():
    ctx, port = make_ctx()
    execute_plan([Action(op="emulate_device", value="iPhone 13")], ctx, retries=1)
    assert (390, 844) in port.viewports
    assert any("iPhone" in ua for ua in port.user_agents)


def test_emulate_device_with_alias():
    ctx, port = make_ctx()
    execute_plan([Action(op="emulate_device", value="pixel")], ctx, retries=1)
    assert (393, 851) in port.viewports


def test_emulate_device_desktop_resets():
    ctx, port = make_ctx()
    execute_plan([
        Action(op="emulate_device", value="iPhone 13"),
        Action(op="emulate_device", value="Desktop"),
    ], ctx, retries=1)
    assert (1440, 900) in port.viewports
    # iPhone applied first, then Desktop afterwards
    assert port.viewports[-1] == (1440, 900)


def test_emulate_device_unknown_raises_with_suggestions():
    ctx, port = make_ctx()
    with pytest.raises(ValueError, match="unknown device"):
        execute_plan([Action(op="emulate_device", value="Nokia 3310")], ctx, retries=1)


def test_emulate_device_uses_name_field_as_fallback():
    ctx, port = make_ctx()
    execute_plan([Action(op="emulate_device", name="iPad mini")], ctx, retries=1)
    assert (768, 1024) in port.viewports


# ---------- set_viewport ----------

def test_set_viewport_with_wxh_string():
    ctx, port = make_ctx()
    execute_plan([Action(op="set_viewport", value="375x667")], ctx, retries=1)
    assert (375, 667) in port.viewports


def test_set_viewport_with_value_expected():
    ctx, port = make_ctx()
    execute_plan([Action(op="set_viewport", value=414, expected=896)], ctx, retries=1)
    assert (414, 896) in port.viewports


def test_set_viewport_requires_dimensions():
    ctx, port = make_ctx()
    with pytest.raises(ValueError):
        execute_plan([Action(op="set_viewport")], ctx, retries=1)


def test_set_viewport_rejects_negative():
    ctx, port = make_ctx()
    with pytest.raises(ValueError):
        execute_plan([Action(op="set_viewport", value="-10x500")], ctx, retries=1)


# ---------- Realistic plan ----------

def test_realistic_mobile_plan_routes_through_port():
    """A typical responsive smoke: emulate iPhone, goto, assert."""
    from tests.test_browser_port import _FakePort  # reuse the fuller fake
    port = _FakePort()
    ctx = ActionContext(port=port)
    # The _FakePort doesn't implement emulate_device — the handler should
    # gracefully fall through to the driver path (None here → ValueError).
    # Instead use our stub which DOES implement it, but also wire goto/find:
    class CombinedPort(_StubDevicePort):
        calls = []
        def goto(self, url): self.calls.append(("goto", url))
        def find(self, locator, ms):
            from tests.test_browser_port import _FakeElement
            return _FakeElement(displayed=True), f"{locator.by}={locator.value}"
        @property
        def current_url(self): return "https://m.example.com/"

    combined = CombinedPort()
    ctx2 = ActionContext(port=combined)
    from utils.models import Locator
    execute_plan([
        Action(op="emulate_device", value="iPhone 13"),
        Action(op="goto", url="https://m.example.com/"),
        Action(op="assert_visible", locator=Locator(by="css", value=".menu")),
    ], ctx2, retries=1)
    assert (390, 844) in combined.viewports
