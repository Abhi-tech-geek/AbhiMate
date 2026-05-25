"""Tests for the Gherkin normalization + expansion helpers."""

import pytest

from utils.gherkin import (
    normalize_raw_case,
    render_gherkin,
    validate_case_quality,
    expand_examples,
)
from utils.models import TestCase, GherkinStep


@pytest.fixture
def raw_llm_case():
    return {
        "id": "TC001",
        "type": "Positive",
        "tags": ["@smoke", "@happy"],
        "scenario": "Successful login",
        "description": "Login with valid creds",
        "gherkin_steps": [
            {"keyword": "Given", "text": "the user is on /login", "code": "driver.get('/login')"},
            {"keyword": "When", "text": "valid credentials are submitted",
             "code": "WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.NAME, 'username'))).send_keys('u')"},
            {"keyword": "Then", "text": "the dashboard loads",
             "code": "el = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, 'dash')))\nassert el.is_displayed()"},
        ],
        "expected": "Dashboard visible",
    }


def test_normalize_derives_steps_and_action(raw_llm_case):
    normalized = normalize_raw_case(raw_llm_case, feature_label="Login feature")
    assert normalized["steps"][0].startswith("Given ")
    assert "driver.get" in normalized["selenium_action"]
    assert "assert" in normalized["selenium_action"]
    assert normalized["feature"] == "Login feature"
    assert "Feature: Login feature" in normalized["gherkin"]
    # Tags preserved.
    assert "@smoke" in normalized["tags"]


def test_normalize_handles_string_tags():
    rc = {
        "id": "X",
        "type": "Edge",
        "tags": "@a @b",
        "description": "d",
        "gherkin_steps": [{"keyword": "Given", "text": "t"}],
        "expected": "e",
    }
    normalized = normalize_raw_case(rc)
    assert normalized["tags"] == ["@a", "@b"]


def test_testcase_constructs_from_normalized(raw_llm_case):
    normalized = normalize_raw_case(raw_llm_case, feature_label="F")
    tc = TestCase(**normalized)
    assert tc.id == "TC001"
    assert len(tc.gherkin_steps) == 3
    assert tc.gherkin_steps[0].keyword == "Given"
    assert tc.tags == ["@smoke", "@happy"]


def test_render_gherkin_basic():
    txt = render_gherkin(
        feature="Login",
        scenario="happy path",
        tags=["@smoke"],
        steps=[
            {"keyword": "Given", "text": "user exists"},
            {"keyword": "When", "text": "they log in"},
            {"keyword": "Then", "text": "they see home"},
        ],
        examples=[],
    )
    assert "Feature: Login" in txt
    assert "@smoke" in txt
    assert "Scenario: happy path" in txt
    assert "Given user exists" in txt


def test_render_gherkin_with_examples():
    txt = render_gherkin(
        feature="F",
        scenario="s",
        tags=[],
        steps=[{"keyword": "Given", "text": "input <x>"}],
        examples=[{"x": "1"}, {"x": "2"}],
    )
    assert "Examples:" in txt
    assert "| x |" in txt
    assert "| 1 |" in txt


def test_quality_warns_on_no_wait():
    tc = TestCase(
        id="T1", type="Positive", description="d", steps=["s"],
        gherkin_steps=[GherkinStep(keyword="Then", text="ok", code="x = 1")],
        selenium_action="x = 1", expected="e",
    )
    warnings = validate_case_quality(tc)
    assert any("explicit wait" in w for w in warnings)


def test_quality_warns_on_missing_assert_for_then():
    tc = TestCase(
        id="T1", type="Positive", description="d", steps=["s"],
        gherkin_steps=[GherkinStep(keyword="Then", text="ok", code="time.sleep(1)")],
        selenium_action="time.sleep(1)", expected="e",
    )
    warnings = validate_case_quality(tc)
    assert any("assert" in w for w in warnings)


def test_quality_warns_on_xpath_only():
    code = "driver.find_element(By.XPATH, '//div').click()\nassert True"
    tc = TestCase(
        id="T1", type="Positive", description="d", steps=["s"],
        gherkin_steps=[GherkinStep(keyword="Then", text="ok", code=code)],
        selenium_action=code, expected="e",
    )
    warnings = validate_case_quality(tc)
    assert any("XPATH" in w for w in warnings)


def test_quality_clean_when_well_formed():
    code = (
        "WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, 'x')))\n"
        "assert True"
    )
    tc = TestCase(
        id="T1", type="Positive", description="d", steps=["s"],
        gherkin_steps=[GherkinStep(keyword="Then", text="ok", code=code)],
        selenium_action=code, expected="e",
    )
    assert validate_case_quality(tc) == []


def test_expand_examples_no_examples_returns_original():
    tc = TestCase(
        id="T1", type="Positive", description="d", steps=["s"],
        gherkin_steps=[GherkinStep(keyword="Given", text="x")],
        selenium_action="pass", expected="e",
    )
    out = expand_examples(tc)
    assert len(out) == 1
    assert out[0].id == "T1"


def test_expand_examples_substitutes_placeholders():
    tc = TestCase(
        id="T1", type="Edge", description="boundary check", steps=["s"],
        gherkin_steps=[
            GherkinStep(keyword="When", text="user enters <pw>", code="el.send_keys('<pw>')"),
            GherkinStep(keyword="Then", text="result is <res>", code="assert '<res>' == expected"),
        ],
        examples=[
            {"pw": "Ab1@5678", "res": "accept"},
            {"pw": "short", "res": "reject"},
        ],
        selenium_action="pass", expected="e",
    )
    expanded = expand_examples(tc)
    assert len(expanded) == 2
    assert expanded[0].id == "T1_01"
    assert "Ab1@5678" in expanded[0].gherkin_steps[0].code
    assert "short" in expanded[1].gherkin_steps[0].code
    # Examples cleared on the expanded copies (no infinite recursion).
    assert expanded[0].examples == []
