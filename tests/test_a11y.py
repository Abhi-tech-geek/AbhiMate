"""Lightweight a11y smoke checks on the rendered template.

These are not a substitute for a real a11y audit (axe-core, Lighthouse) but
they catch the common regressions: every icon-only button has aria-label,
every form control has a programmatic label, tabs are wired with ARIA.
"""

import os
import re

import pytest


@pytest.fixture
def html(authed_html):
    """Authenticated render of the SPA — most a11y markers live behind login."""
    return authed_html


def test_theme_toggle_present_and_labelled(html):
    assert 'id="themeToggle"' in html
    assert re.search(r'id="themeToggle"[^>]*aria-label=', html)


def test_icon_buttons_labelled(html):
    # sidebarToggle, generateBtn, themeToggle, lightbox-close, modal-close are icon-only
    for marker in [
        r'id="sidebarToggle"[^>]*aria-label=',
        r'id="generateBtn"[^>]*aria-label=',
        r'id="themeToggle"[^>]*aria-label=',
        r'class="lightbox-close"[^>]*aria-label=',
        r'class="modal-close"[^>]*aria-label=',
    ]:
        assert re.search(marker, html), f"missing aria-label match: {marker}"


def test_tablist_wired(html):
    assert 'role="tablist"' in html
    assert html.count('role="tab"') >= 3
    assert html.count('role="tabpanel"') >= 3
    # All tabs reference the panel they control
    assert 'aria-controls="dashboardView"' in html
    assert 'aria-controls="automatedView"' in html
    assert 'aria-controls="globalStatsView"' in html


def test_progress_bar_has_aria(html):
    assert 'role="progressbar"' in html
    assert 'aria-valuemin="0"' in html
    assert 'aria-valuemax="100"' in html


def test_live_region_present(html):
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html


def test_no_inline_styles_left_in_template(html):
    # We allow a small set (e.g. accent override on logo svg via stroke attr) but
    # the template should be free of inline style= attributes.
    leftovers = re.findall(r'\sstyle="[^"]*"', html)
    assert leftovers == [], f"inline styles still present: {leftovers[:3]}"


def test_theme_bootstrap_runs_before_paint(html):
    # The early <script> sets data-theme on <html>. The actual attribute is set
    # at runtime; assert the bootstrap snippet is in <head>.
    head = html.split("</head>")[0]
    assert "localStorage.getItem('abhimate.theme')" in head
    assert "data-theme" in head


def test_reduced_motion_handled():
    # The CSS clamps animation-duration when prefers-reduced-motion is set.
    css_path = os.path.join(os.path.dirname(__file__), os.pardir, "ui", "static", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()
    assert "prefers-reduced-motion: reduce" in css
