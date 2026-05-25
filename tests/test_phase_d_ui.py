"""Phase D — design tokens, aurora background, glass + tilt + ripple wiring."""

import os


def test_depth_and_gradient_tokens_in_css():
    path = os.path.join(os.path.dirname(__file__), os.pardir, "ui", "static", "style.css")
    css = open(path, encoding="utf-8").read()
    for tok in ["--depth-1", "--depth-4", "--grad-primary", "--grad-aurora",
                "--blur-sm", "--blur-md", "--tilt-strength"]:
        assert tok in css, f"missing token: {tok}"


def test_aurora_background_in_main_app(authed_html):
    assert 'class="app-aurora"' in authed_html
    assert 'aria-hidden="true"' in authed_html


def test_glass_panel_utility_in_css():
    path = os.path.join(os.path.dirname(__file__), os.pardir, "ui", "static", "style.css")
    css = open(path, encoding="utf-8").read()
    assert ".glass-panel" in css
    assert "backdrop-filter" in css


def test_auth_card_uses_glass(anonymous_client):
    r = anonymous_client.get("/login")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert 'class="auth-card glass-panel"' in body
    assert 'data-tilt' in body


def test_ui_core_has_tilt_and_ripple(authed_html, anonymous_client):
    js = anonymous_client.get("/static/js/ui-core.js").data.decode("utf-8")
    for marker in ["wireTilt", "wireRipples", "autoDecorateTilt", "autoDecorateRipples",
                   "tilt-sheen", "ripple-ink"]:
        assert marker in js, f"missing JS marker: {marker}"


def test_reduced_motion_paths_present():
    path = os.path.join(os.path.dirname(__file__), os.pardir, "ui", "static", "style.css")
    css = open(path, encoding="utf-8").read()
    # The PHASE D block explicitly disables aurora drift + view animations.
    assert "prefers-reduced-motion: reduce" in css
    assert ".app-aurora::before" in css and "animation: none" in css


def test_auth_page_renders_aurora(anonymous_client):
    body = anonymous_client.get("/login").data.decode("utf-8")
    assert 'class="auth-aurora"' in body
    assert "aurora-1" in body and "aurora-2" in body and "aurora-3" in body
