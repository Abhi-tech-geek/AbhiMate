"""Sandbox tests for utils.safe_exec — the AST allowlist that wraps LLM snippets."""

import pytest

from utils.safe_exec import safe_run, SandboxViolation


def test_simple_snippet_runs():
    ctx = {"results": []}
    safe_run("results.append(1)", ctx)
    assert ctx["results"] == [1]


def test_import_is_blocked():
    with pytest.raises(SandboxViolation):
        safe_run("import os", {})


def test_dunder_attribute_blocked():
    with pytest.raises(SandboxViolation):
        safe_run("().__class__.__bases__", {})


def test_eval_builtin_is_stripped():
    # The eval builtin is omitted from SAFE_BUILTINS, so a runtime NameError fires.
    with pytest.raises(NameError):
        safe_run("eval('1+1')", {})


def test_open_builtin_is_stripped():
    with pytest.raises(NameError):
        safe_run("open('/etc/passwd')", {})


def test_lambda_blocked():
    with pytest.raises(SandboxViolation):
        safe_run("f = lambda x: x+1", {})


def test_syntax_error_surfaces_as_violation():
    with pytest.raises(SandboxViolation):
        safe_run("def !", {})


def test_timeout_kicks_in():
    with pytest.raises(TimeoutError):
        safe_run("while True: pass", {}, timeout_seconds=0.5)


def test_snippet_exception_propagates():
    with pytest.raises(ZeroDivisionError):
        safe_run("x = 1 / 0", {})
