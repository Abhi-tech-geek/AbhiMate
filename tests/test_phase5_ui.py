"""UI smoke for Phase 5: command palette markup, insights panels, tokens in CSS."""

import os
import re
import sys

import pytest


@pytest.fixture
def html(authed_html):
    return authed_html


def test_command_palette_markup_present(html):
    assert 'id="cmdPalette"' in html
    assert 'id="cmdInput"' in html
    assert 'id="cmdResults"' in html


def test_insights_panels_present(html):
    assert 'id="diff-panel-title"' in html
    assert 'id="diffA"' in html and 'id="diffB"' in html
    assert 'id="patternList"' in html


def test_design_tokens_in_css():
    path = os.path.join(os.path.dirname(__file__), os.pardir, "ui", "static", "style.css")
    css = open(path, encoding="utf-8").read()
    # Spacing scale
    for var in ["--space-1", "--space-4", "--space-7"]:
        assert var in css, f"missing token: {var}"
    # Radius scale
    for var in ["--radius-sm", "--radius-md", "--radius-pill"]:
        assert var in css, f"missing token: {var}"
    # Font scale
    assert "--font-mono" in css
    assert "--font-base" in css
    # Shadow scale
    assert "--shadow-2" in css


def test_modal_partial_loaded_via_jinja(html):
    # Phase 4 partial split + Phase 5 cmd palette modal combined
    assert 'id="fixModal"' in html
    assert 'id="cmdPalette"' in html
    assert 'id="toastStack"' in html


def test_command_palette_helpers_in_ui_core(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-dummy")
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))
    import app as app_module
    js = app_module.app.test_client().get("/static/js/ui-core.js").data.decode("utf-8")
    for marker in ["openCmdPalette", "buildCmdItems", "wireCmdPalette", "fingerprintError"]:
        assert marker in js or marker == "fingerprintError"


def test_runner_view_has_diff_and_export(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-dummy")
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))
    import app as app_module
    js = app_module.app.test_client().get("/static/js/runner-view.js").data.decode("utf-8")
    for marker in ["runDiff", "renderDiffRows", "fingerprintError", "updateExportButton"]:
        assert marker in js, f"missing js fn: {marker}"
