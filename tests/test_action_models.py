"""Schema round-trip tests for the Action Plan models."""

from utils.models import Action, Locator, ActionResult, TestCase


def test_locator_with_fallbacks_roundtrip():
    loc = Locator(by="id", value="email", fallbacks=[
        Locator(by="name", value="email"),
        Locator(by="css", value="input[type=email]"),
    ])
    data = loc.model_dump()
    rebuilt = Locator(**data)
    assert rebuilt.fallbacks[1].by == "css"
    assert rebuilt.fallbacks[1].value == "input[type=email]"


def test_action_minimal_fields():
    a = Action(op="goto", url="https://example.com")
    assert a.op == "goto"
    assert a.url == "https://example.com"
    assert a.locator is None


def test_action_result_defaults():
    r = ActionResult(op="click", success=True)
    assert r.attempts == 1
    assert r.duration_ms == 0
    assert r.error is None


def test_testcase_carries_action_plan():
    tc = TestCase(
        id="TC001", type="Positive", description="login",
        steps=["Given x"],
        action_plan=[
            Action(op="goto", url="https://x.com"),
            Action(op="click", locator=Locator(by="css", value="button")),
        ],
        expected="ok",
    )
    assert len(tc.action_plan) == 2
    assert tc.action_plan[0].op == "goto"
    # Serializes round-trip without losing structure
    rebuilt = TestCase(**tc.model_dump())
    assert rebuilt.action_plan[1].locator.value == "button"


def test_legacy_selenium_action_still_optional():
    """Phase A allows selenium_action to be blank when action_plan is present."""
    tc = TestCase(
        id="X", type="Edge", description="d", steps=["s"],
        selenium_action="",
        action_plan=[Action(op="goto", url="https://x.com")],
        expected="ok",
    )
    assert tc.selenium_action == ""
