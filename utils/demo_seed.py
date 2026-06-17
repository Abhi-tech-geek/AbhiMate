"""Read-only live demo: a shared guest account pre-seeded with realistic,
already-executed sessions so first-time visitors instantly see what AbhiMate
does — without signing up, spending an LLM key, or launching a browser.

The demo account is re-seeded on every demo entry (idempotent reset), so it
always looks clean even if a previous visitor poked at it. Generation,
execution, deletion, and external actions are blocked for the demo user
(see ``is_demo_user`` in app.py) — viewing, reports, run-diff, and code/markdown
export all still work, which is exactly the "showcase" surface.
"""

from __future__ import annotations

import secrets
import time
from typing import List

from utils.models import (
    Action, ActionResult, GherkinStep, Locator,
    TestCase, TestSession, ExecutionMetrics, AnalysisReport,
)

DEMO_EMAIL = "demo@abhimate.app"
DEMO_NAME = "Demo (read-only)"


def _g(keyword: str, text: str) -> GherkinStep:
    return GherkinStep(keyword=keyword, text=text)


def _res(op: str, ok: bool = True, ms: int = 320, err: str = None) -> ActionResult:
    return ActionResult(op=op, success=ok, duration_ms=ms, attempts=1, error=err)


def _login_session(uid: int) -> TestSession:
    cases: List[TestCase] = [
        TestCase(
            id="TC001", type="Positive",
            description="Sign in with valid credentials",
            steps=["Open login", "Enter valid email + password", "Submit", "See dashboard"],
            scenario="Successful login",
            tags=["@smoke", "@auth"],
            expected="User lands on the dashboard",
            gherkin_steps=[
                _g("Given", "the user is on the login page"),
                _g("When", "they enter a valid email and password"),
                _g("And", "they click Sign in"),
                _g("Then", "they should be redirected to the dashboard"),
            ],
            action_plan=[
                Action(op="goto", url="https://www.saucedemo.com"),
                Action(op="fill", locator=Locator(by="id", value="user-name"), value="standard_user"),
                Action(op="fill", locator=Locator(by="id", value="password"), value="secret_sauce"),
                Action(op="click", locator=Locator(by="id", value="login-button")),
                Action(op="assert_visible", locator=Locator(by="css", value=".inventory_list")),
            ],
            action_results=[_res("goto", ms=540), _res("fill"), _res("fill"),
                            _res("click"), _res("assert_visible", ms=210)],
            status="Pass",
        ),
        TestCase(
            id="TC002", type="Negative",
            description="Locked-out user is blocked with an error",
            steps=["Open login", "Use locked_out_user", "Submit", "See error"],
            scenario="Locked-out user cannot log in",
            tags=["@auth", "@negative"],
            expected="An error message is shown",
            gherkin_steps=[
                _g("Given", "the user is on the login page"),
                _g("When", "they sign in as a locked-out user"),
                _g("Then", "an error message should be displayed"),
            ],
            action_plan=[
                Action(op="goto", url="https://www.saucedemo.com"),
                Action(op="fill", locator=Locator(by="id", value="user-name"), value="locked_out_user"),
                Action(op="fill", locator=Locator(by="id", value="password"), value="secret_sauce"),
                Action(op="click", locator=Locator(by="id", value="login-button")),
                Action(op="assert_text", locator=Locator(by="css", value="[data-test='error']"),
                       expected="locked out"),
            ],
            action_results=[_res("goto"), _res("fill"), _res("fill"), _res("click"),
                            _res("assert_text", ms=180)],
            status="Pass",
        ),
        TestCase(
            id="TC003", type="Negative",
            description="Empty password shows a validation error",
            steps=["Open login", "Enter email only", "Submit"],
            scenario="Missing password is rejected",
            tags=["@auth", "@validation"],
            expected="Validation error for the password field",
            gherkin_steps=[
                _g("Given", "the user is on the login page"),
                _g("When", "they submit without a password"),
                _g("Then", "a 'Password is required' error appears"),
            ],
            action_plan=[
                Action(op="goto", url="https://www.saucedemo.com"),
                Action(op="fill", locator=Locator(by="id", value="user-name"), value="standard_user"),
                Action(op="click", locator=Locator(by="id", value="login-button")),
                Action(op="assert_text", locator=Locator(by="css", value="[data-test='error']"),
                       expected="Password is required"),
            ],
            action_results=[_res("goto"), _res("fill"), _res("click"),
                            _res("assert_text", ms=160)],
            status="Pass",
        ),
        TestCase(
            id="TC004", type="Edge",
            description="Error toast renders before it can be asserted (flaky timing)",
            steps=["Open login", "Bad password", "Submit", "Assert toast"],
            scenario="Async error toast",
            tags=["@auth", "@flaky"],
            expected="Error toast is visible",
            gherkin_steps=[
                _g("Given", "the user is on the login page"),
                _g("When", "they submit an invalid password"),
                _g("Then", "the error toast should be visible"),
            ],
            action_plan=[
                Action(op="goto", url="https://www.saucedemo.com"),
                Action(op="fill", locator=Locator(by="id", value="user-name"), value="standard_user"),
                Action(op="fill", locator=Locator(by="id", value="password"), value="wrong"),
                Action(op="click", locator=Locator(by="id", value="login-button")),
                Action(op="assert_visible", locator=Locator(by="css", value="[data-test='error']")),
            ],
            action_results=[_res("goto"), _res("fill"), _res("fill"), _res("click"),
                            _res("assert_visible", ms=120, ok=True)],
            status="Flaky",
        ),
        TestCase(
            id="TC005", type="Security",
            description="SQL-injection string in username does not authenticate",
            steps=["Open login", "Inject ' OR 1=1 --", "Submit"],
            scenario="SQL injection is rejected",
            tags=["@security"],
            expected="Login is refused; no dashboard access",
            gherkin_steps=[
                _g("Given", "the user is on the login page"),
                _g("When", "they enter a SQL-injection payload as the username"),
                _g("Then", "login should be refused"),
            ],
            action_plan=[
                Action(op="goto", url="https://www.saucedemo.com"),
                Action(op="fill", locator=Locator(by="id", value="user-name"), value="' OR 1=1 --"),
                Action(op="fill", locator=Locator(by="id", value="password"), value="x"),
                Action(op="click", locator=Locator(by="id", value="login-button")),
                Action(op="assert_visible", locator=Locator(by="css", value="[data-test='error']")),
            ],
            action_results=[_res("goto"), _res("fill"), _res("fill"), _res("click"),
                            _res("assert_visible", ms=140, ok=False, err="Expected error, dashboard shown")],
            status="Fail",
            error="AssertionError: expected error message, but the page navigated to inventory",
            bug_insight="The app appears to accept a SQL-injection-shaped username without "
                        "server-side validation. Add input sanitisation and reject control "
                        "characters before the auth query.",
        ),
    ]
    metrics = ExecutionMetrics(total=5, passed=3, failed=1, skipped=1)
    report = AnalysisReport(
        metrics=metrics,
        executive_summary=("Login flow: 4/5 effective passes. One security case failed — a "
                           "SQL-injection username was not rejected. One flaky timing case on "
                           "the async error toast. | Perf Status: Good (1.8s avg)"),
        test_cases=cases,
    )
    return TestSession(
        session_id="demo-login-flow",
        user_id=uid, feature="Login flow (demo)",
        state="EXECUTED", timestamp=time.time() - 3600,
        test_cases=cases, report=report,
    )


def _checkout_session(uid: int) -> TestSession:
    cases: List[TestCase] = [
        TestCase(
            id="TC001", type="Positive",
            description="Add an item to the cart and reach checkout",
            steps=["Login", "Add product", "Open cart", "Checkout"],
            scenario="Add to cart and checkout",
            tags=["@smoke", "@cart"],
            expected="Checkout step one is shown",
            gherkin_steps=[
                _g("Given", "the user is logged in"),
                _g("When", "they add a product to the cart"),
                _g("And", "open the cart and click checkout"),
                _g("Then", "the checkout information step should appear"),
            ],
            action_plan=[
                Action(op="goto", url="https://www.saucedemo.com/inventory.html"),
                Action(op="click", locator=Locator(by="css", value="[data-test='add-to-cart-sauce-labs-backpack']")),
                Action(op="click", locator=Locator(by="css", value=".shopping_cart_link")),
                Action(op="click", locator=Locator(by="id", value="checkout")),
                Action(op="assert_visible", locator=Locator(by="id", value="first-name")),
            ],
            action_results=[_res("goto", ms=480), _res("click"), _res("click"),
                            _res("click"), _res("assert_visible")],
            status="Pass",
        ),
        TestCase(
            id="TC002", type="Edge",
            description="Checkout with empty form shows required-field errors",
            steps=["Reach checkout", "Submit empty", "See error"],
            scenario="Required fields enforced",
            tags=["@cart", "@validation"],
            expected="A 'First Name is required' error appears",
            gherkin_steps=[
                _g("Given", "the user is on the checkout information step"),
                _g("When", "they continue without filling the form"),
                _g("Then", "a required-field error should be shown"),
            ],
            action_plan=[
                Action(op="click", locator=Locator(by="id", value="continue")),
                Action(op="assert_text", locator=Locator(by="css", value="[data-test='error']"),
                       expected="First Name is required"),
            ],
            action_results=[_res("click"), _res("assert_text", ms=150)],
            status="Pass",
        ),
        TestCase(
            id="TC003", type="Edge",
            description="Inventory page meets the load budget",
            steps=["Open inventory", "Measure LCP"],
            scenario="Inventory LCP under budget",
            tags=["@perf"],
            expected="LCP under 2.5s",
            gherkin_steps=[
                _g("Given", "the inventory page is requested"),
                _g("Then", "the Largest Contentful Paint should be under 2500ms"),
            ],
            action_plan=[
                Action(op="goto", url="https://www.saucedemo.com/inventory.html"),
                Action(op="assert_lcp_under", expected="2500"),
            ],
            action_results=[_res("goto"), _res("assert_lcp_under", ms=90, ok=False,
                                                err="LCP was 3120ms")],
            status="Fail",
            error="PerfBudget: LCP 3120ms exceeded budget of 2500ms",
            bug_insight="The hero product images load without dimensions/lazy hints, pushing "
                        "LCP past budget. Add width/height and preload the first image.",
        ),
    ]
    metrics = ExecutionMetrics(total=3, passed=2, failed=1, skipped=0)
    report = AnalysisReport(
        metrics=metrics,
        executive_summary=("Checkout flow: 2/3 passed. Performance budget failed — inventory "
                           "LCP 3120ms over the 2500ms budget. | Perf Status: Needs work"),
        test_cases=cases,
    )
    return TestSession(
        session_id="demo-checkout-flow",
        user_id=uid, feature="Checkout flow (demo)",
        state="EXECUTED", timestamp=time.time() - 1800,
        test_cases=cases, report=report,
    )


def build_demo_sessions(uid: int) -> List[TestSession]:
    return [_checkout_session(uid), _login_session(uid)]


def ensure_demo(memory_agent, hash_password) -> int:
    """Create the demo user if missing and (re)seed its sample sessions.

    Returns the demo user's id. Idempotent — safe to call on every demo entry.
    """
    db = memory_agent.db
    u = db.get_user_by_email(DEMO_EMAIL)
    if u is None:
        uid = db.create_user(
            email=DEMO_EMAIL,
            password_hash=hash_password(secrets.token_urlsafe(24)),
            display_name=DEMO_NAME,
        )
    else:
        uid = u["id"]

    # Reseed: drop whatever's there, write fresh sample sessions.
    for meta in db.list_sessions(user_id=uid):
        db.delete_session(meta["session_id"])
    for s in build_demo_sessions(uid):
        db.save_session(
            session_id=s.session_id, feature=s.feature, state=s.state,
            timestamp=s.timestamp, session_data=s.model_dump(), user_id=uid,
        )
    return int(uid)
