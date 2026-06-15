"""Export a TestSession's Action Plans as runnable test code.

AbhiMate runs tests through an engine-agnostic Action Plan (typed JSON). This
module translates that plan into **real, copy-pasteable test files** in popular
frameworks so a user can drop the output straight into their own repo:

    generate_code(session, "playwright")  -> Playwright (Python) .py
    generate_code(session, "selenium")    -> Selenium + pytest   .py
    generate_code(session, "cypress")     -> Cypress             .cy.js

Ops that have no clean 1:1 mapping in a given framework (a11y / perf / visual /
auth-state) are emitted as ``# TODO`` comments rather than silently dropped, so
the output is honest and the file still reads cleanly.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from utils.models import TestSession, TestCase, Action, Locator


FRAMEWORKS = {
    "playwright": {"label": "Playwright (Python)", "ext": "py"},
    "selenium": {"label": "Selenium + pytest", "ext": "py"},
    "cypress": {"label": "Cypress (JS)", "ext": "cy.js"},
}


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _slug(text: str, default: str = "tests") -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "").strip()).strip("_").lower()
    return s or default


def _func_name(tc: "TestCase") -> str:
    base = _slug(tc.scenario or tc.description or tc.id, default=tc.id.lower())
    return f"test_{tc.id.lower()}_{base}"[:80]


def _qpy(value) -> str:
    """Quote a value as a Python string literal (single-quoted, escaped)."""
    s = "" if value is None else str(value)
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _qjs(value) -> str:
    """Quote a value as a JS string literal (single-quoted, escaped)."""
    s = "" if value is None else str(value)
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


_KEY_MAP_SELENIUM = {
    "enter": "Keys.ENTER", "return": "Keys.ENTER", "tab": "Keys.TAB",
    "escape": "Keys.ESCAPE", "esc": "Keys.ESCAPE", "space": "Keys.SPACE",
    "backspace": "Keys.BACK_SPACE", "delete": "Keys.DELETE",
    "arrowdown": "Keys.ARROW_DOWN", "arrowup": "Keys.ARROW_UP",
}


# ======================================================================
# Playwright (Python)
# ======================================================================

def _pw_locator(loc: Optional["Locator"]) -> str:
    if not loc:
        return "page.locator('body')"
    by, val = loc.by, loc.value
    if by == "id":
        return f"page.locator({_qpy('#' + val)})"
    if by == "name":
        return f"page.locator({_qpy(f'[name=\"{val}\"]')})"
    if by == "css":
        return f"page.locator({_qpy(val)})"
    if by == "xpath":
        return f"page.locator({_qpy('xpath=' + val)})"
    if by == "text":
        return f"page.get_by_text({_qpy(val)})"
    if by == "role":
        return f"page.get_by_role({_qpy(val)})"
    if by == "label":
        return f"page.get_by_label({_qpy(val)})"
    if by == "placeholder":
        return f"page.get_by_placeholder({_qpy(val)})"
    if by == "testid":
        return f"page.get_by_test_id({_qpy(val)})"
    if by in ("link_text", "partial_link_text"):
        return f"page.get_by_role('link', name={_qpy(val)})"
    return f"page.locator({_qpy(val)})"


def _pw_action(a: "Action") -> List[str]:
    op = a.op
    loc = _pw_locator(a.locator) if a.locator else None
    if op == "goto":
        return [f"page.goto({_qpy(a.url or a.value)})"]
    if op == "reload":
        return ["page.reload()"]
    if op == "back":
        return ["page.go_back()"]
    if op == "forward":
        return ["page.go_forward()"]
    if op == "click":
        return [f"{loc}.click()"]
    if op == "fill":
        return [f"{loc}.fill({_qpy(a.value)})"]
    if op == "press":
        return [f"page.keyboard.press({_qpy(a.value)})"]
    if op == "select":
        return [f"{loc}.select_option({_qpy(a.value)})"]
    if op == "hover":
        return [f"{loc}.hover()"]
    if op in ("wait_for", "wait_for_selector"):
        return [f"{loc}.wait_for()"]
    if op == "wait_for_url":
        return [f"page.wait_for_url({_qpy(a.value or a.url)})"]
    if op == "sleep":
        return [f"page.wait_for_timeout({int(a.value or 1000)})"]
    if op == "scroll_to":
        return [f"{loc}.scroll_into_view_if_needed()"]
    if op == "eval_js":
        return [f"page.evaluate({_qpy(a.value)})"]
    if op == "assert_text":
        return [f"expect({loc}).to_contain_text({_qpy(a.expected or a.value)})"]
    if op == "assert_visible":
        return [f"expect({loc}).to_be_visible()"]
    if op == "assert_hidden":
        return [f"expect({loc}).to_be_hidden()"]
    if op == "assert_url":
        return [f"expect(page).to_have_url({_qpy(a.expected or a.value)})"]
    if op == "assert_value":
        return [f"expect({loc}).to_have_value({_qpy(a.expected or a.value)})"]
    if op.startswith("http_"):
        return [f"# TODO: API op {op!r} — use Playwright's request fixture or `requests`"]
    return [f"# TODO: unsupported op {op!r} (AbhiMate-specific — port manually)"]


def _gen_playwright(session: "TestSession") -> str:
    out: List[str] = [
        '"""Generated by AbhiMate — Playwright (Python).',
        "",
        f"Feature: {session.feature}",
        "Install:  pip install playwright pytest-playwright && playwright install",
        "Run:      pytest this_file.py",
        '"""',
        "from playwright.sync_api import Page, expect",
        "",
        "",
    ]
    for tc in session.test_cases:
        out.append(f"def {_func_name(tc)}(page: Page):")
        out.append(f"    # {tc.type}: {tc.description}")
        plan = tc.action_plan or []
        if not plan:
            out.append("    pass  # no action plan generated for this case")
            out.append("")
            continue
        for a in plan:
            for line in _pw_action(a):
                out.append(f"    {line}")
        out.append("")
    return "\n".join(out)


# ======================================================================
# Selenium (Python + pytest)
# ======================================================================

def _se_by(loc: Optional["Locator"]) -> str:
    if not loc:
        return "By.TAG_NAME, 'body'"
    by, val = loc.by, loc.value
    if by == "id":
        return f"By.ID, {_qpy(val)}"
    if by == "name":
        return f"By.NAME, {_qpy(val)}"
    if by == "css":
        return f"By.CSS_SELECTOR, {_qpy(val)}"
    if by == "xpath":
        return f"By.XPATH, {_qpy(val)}"
    if by == "text":
        return f"By.XPATH, {_qpy(f'//*[contains(text(), \"{val}\")]')}"
    if by == "testid":
        return f"By.CSS_SELECTOR, {_qpy(f'[data-testid=\"{val}\"]')}"
    if by == "placeholder":
        return f"By.CSS_SELECTOR, {_qpy(f'[placeholder=\"{val}\"]')}"
    if by == "role":
        return f"By.CSS_SELECTOR, {_qpy(f'[role=\"{val}\"]')}"
    if by == "link_text":
        return f"By.LINK_TEXT, {_qpy(val)}"
    if by == "partial_link_text":
        return f"By.PARTIAL_LINK_TEXT, {_qpy(val)}"
    if by == "label":
        return f"By.XPATH, {_qpy(f'//label[contains(text(), \"{val}\")]')}"
    return f"By.CSS_SELECTOR, {_qpy(val)}"


def _se_action(a: "Action") -> List[str]:
    op = a.op
    by = _se_by(a.locator) if a.locator else None
    find = f"driver.find_element({by})" if by else None
    if op == "goto":
        return [f"driver.get({_qpy(a.url or a.value)})"]
    if op == "reload":
        return ["driver.refresh()"]
    if op == "back":
        return ["driver.back()"]
    if op == "forward":
        return ["driver.forward()"]
    if op == "click":
        return [f"{find}.click()"]
    if op == "fill":
        return [f"el = {find}", "el.clear()", f"el.send_keys({_qpy(a.value)})"]
    if op == "press":
        key = _KEY_MAP_SELENIUM.get(str(a.value or "").lower())
        send = key or _qpy(a.value)
        return [f"driver.switch_to.active_element.send_keys({send})"]
    if op == "select":
        return [f"Select({find}).select_by_visible_text({_qpy(a.value)})"]
    if op == "hover":
        return [f"ActionChains(driver).move_to_element({find}).perform()"]
    if op in ("wait_for", "wait_for_selector"):
        return [f"WebDriverWait(driver, 10).until(EC.presence_of_element_located(({by})))"]
    if op == "sleep":
        return [f"time.sleep({float(a.value or 1000) / 1000:.1f})"]
    if op == "scroll_to":
        return [f"driver.execute_script('arguments[0].scrollIntoView();', {find})"]
    if op == "eval_js":
        return [f"driver.execute_script({_qpy(a.value)})"]
    if op == "assert_text":
        return [f"assert {_qpy(a.expected or a.value)} in {find}.text"]
    if op == "assert_visible":
        return [f"assert {find}.is_displayed()"]
    if op == "assert_url":
        return [f"assert {_qpy(a.expected or a.value)} in driver.current_url"]
    if op == "assert_value":
        return [f"assert {find}.get_attribute('value') == {_qpy(a.expected or a.value)}"]
    if op.startswith("http_"):
        return [f"# TODO: API op {op!r} — use the `requests` library"]
    return [f"# TODO: unsupported op {op!r} (AbhiMate-specific — port manually)"]


def _gen_selenium(session: "TestSession") -> str:
    out: List[str] = [
        '"""Generated by AbhiMate — Selenium + pytest.',
        "",
        f"Feature: {session.feature}",
        "Install:  pip install selenium pytest webdriver-manager",
        "Run:      pytest this_file.py",
        '"""',
        "import time",
        "import pytest",
        "from selenium import webdriver",
        "from selenium.webdriver.common.by import By",
        "from selenium.webdriver.common.keys import Keys",
        "from selenium.webdriver.common.action_chains import ActionChains",
        "from selenium.webdriver.support.ui import WebDriverWait, Select",
        "from selenium.webdriver.support import expected_conditions as EC",
        "",
        "",
        "@pytest.fixture",
        "def driver():",
        "    d = webdriver.Chrome()",
        "    d.implicitly_wait(10)",
        "    yield d",
        "    d.quit()",
        "",
        "",
    ]
    for tc in session.test_cases:
        out.append(f"def {_func_name(tc)}(driver):")
        out.append(f"    # {tc.type}: {tc.description}")
        plan = tc.action_plan or []
        if not plan:
            out.append("    pass  # no action plan generated for this case")
            out.append("")
            continue
        for a in plan:
            for line in _se_action(a):
                out.append(f"    {line}")
        out.append("")
    return "\n".join(out)


# ======================================================================
# Cypress (JavaScript)
# ======================================================================

def _cy_locator(loc: Optional["Locator"]) -> str:
    if not loc:
        return "cy.get('body')"
    by, val = loc.by, loc.value
    if by == "id":
        return f"cy.get({_qjs('#' + val)})"
    if by == "name":
        return f"cy.get({_qjs(f'[name=\"{val}\"]')})"
    if by == "css":
        return f"cy.get({_qjs(val)})"
    if by == "text":
        return f"cy.contains({_qjs(val)})"
    if by == "testid":
        return f"cy.get({_qjs(f'[data-testid=\"{val}\"]')})"
    if by == "placeholder":
        return f"cy.get({_qjs(f'[placeholder=\"{val}\"]')})"
    if by == "role":
        return f"cy.get({_qjs(f'[role=\"{val}\"]')})"
    if by in ("link_text", "partial_link_text"):
        return f"cy.contains('a', {_qjs(val)})"
    if by == "xpath":
        return f"cy.get('body') /* TODO xpath: {val} — needs cypress-xpath plugin */"
    return f"cy.get({_qjs(val)})"


def _cy_action(a: "Action") -> List[str]:
    op = a.op
    loc = _cy_locator(a.locator) if a.locator else None
    if op == "goto":
        return [f"cy.visit({_qjs(a.url or a.value)});"]
    if op == "reload":
        return ["cy.reload();"]
    if op == "back":
        return ["cy.go('back');"]
    if op == "forward":
        return ["cy.go('forward');"]
    if op == "click":
        return [f"{loc}.click();"]
    if op == "fill":
        return [f"{loc}.clear().type({_qjs(a.value)});"]
    if op == "press":
        target = loc or "cy.get('body')"
        key = str(a.value or "enter").lower()
        return [f"{target}.type('{{{key}}}');"]
    if op == "select":
        return [f"{loc}.select({_qjs(a.value)});"]
    if op == "hover":
        return [f"{loc}.trigger('mouseover');"]
    if op == "sleep":
        return [f"cy.wait({int(a.value or 1000)});"]
    if op in ("wait_for", "wait_for_selector"):
        return [f"{loc}.should('exist');"]
    if op == "assert_text":
        return [f"{loc}.should('contain', {_qjs(a.expected or a.value)});"]
    if op == "assert_visible":
        return [f"{loc}.should('be.visible');"]
    if op == "assert_hidden":
        return [f"{loc}.should('not.be.visible');"]
    if op == "assert_url":
        return [f"cy.url().should('include', {_qjs(a.expected or a.value)});"]
    if op == "assert_value":
        return [f"{loc}.should('have.value', {_qjs(a.expected or a.value)});"]
    if op.startswith("http_"):
        return [f"// TODO: API op {op!r} — use cy.request()"]
    return [f"// TODO: unsupported op {op!r} (AbhiMate-specific — port manually)"]


def _gen_cypress(session: "TestSession") -> str:
    out: List[str] = [
        "// Generated by AbhiMate — Cypress (JavaScript).",
        f"// Feature: {session.feature}",
        "// Install:  npm install cypress --save-dev",
        "// Run:      npx cypress run",
        "",
        f"describe({_qjs(session.feature or 'AbhiMate suite')}, () => {{",
    ]
    for tc in session.test_cases:
        title = tc.scenario or tc.description or tc.id
        out.append(f"  it({_qjs(f'{tc.id} — {title}')}, () => {{")
        plan = tc.action_plan or []
        if not plan:
            out.append("    // no action plan generated for this case")
            out.append("  });")
            continue
        for a in plan:
            for line in _cy_action(a):
                out.append(f"    {line}")
        out.append("  });")
    out.append("});")
    out.append("")
    return "\n".join(out)


# ======================================================================
# Public entry
# ======================================================================

_GENERATORS = {
    "playwright": _gen_playwright,
    "selenium": _gen_selenium,
    "cypress": _gen_cypress,
}


def generate_code(session: "TestSession", framework: str) -> str:
    """Render ``session``'s action plans as a runnable test file.

    Raises ``ValueError`` for an unknown framework.
    """
    fw = (framework or "").strip().lower()
    gen = _GENERATORS.get(fw)
    if gen is None:
        raise ValueError(
            f"Unknown framework {framework!r}. Choose one of: "
            + ", ".join(sorted(_GENERATORS))
        )
    return gen(session)


def filename_for(session: "TestSession", framework: str) -> str:
    fw = (framework or "").strip().lower()
    ext = FRAMEWORKS.get(fw, {}).get("ext", "txt")
    base = _slug(session.feature, default="abhimate")[:40]
    if fw == "cypress":
        return f"{base}.cy.js"
    return f"test_{base}_{fw}.{ext}"
