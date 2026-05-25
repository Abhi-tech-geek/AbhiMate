"""
Interim sandbox for LLM-generated Selenium snippets.

Phase 0 hardening — blocks the obvious blast radius (imports, dunder access,
process/file/network builtins) before we pivot to the action-plan executor in
Phase A.
"""

import ast
import builtins as _builtins
import threading
import _thread
from typing import Any, Dict, Iterable

DEFAULT_ALLOWED_NAMES = frozenset({
    "driver", "By", "Keys", "time",
    "WebDriverWait", "EC", "expected_conditions",
    "ActionChains", "TimeoutException", "NoSuchElementException",
    "print", "len", "range", "str", "int", "float", "bool", "list", "dict",
    "True", "False", "None",
})

FORBIDDEN_NODES = (
    ast.Import, ast.ImportFrom,
    ast.Global, ast.Nonlocal,
    ast.AsyncFunctionDef, ast.AsyncFor, ast.AsyncWith,
    ast.ClassDef,
    ast.Lambda,
    ast.Yield, ast.YieldFrom,
)

DANGEROUS_BUILTINS = frozenset({
    "eval", "exec", "compile", "open", "input",
    "__import__", "globals", "locals", "vars", "dir",
    "getattr", "setattr", "delattr", "hasattr",
    "memoryview", "object",
})


class SandboxViolation(Exception):
    """Raised when AST inspection rejects a snippet before execution."""


def _check_node(node, allowed_names):
    if isinstance(node, FORBIDDEN_NODES):
        raise SandboxViolation(f"Disallowed statement: {type(node).__name__}")
    if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
        raise SandboxViolation(f"Dunder attribute blocked: {node.attr}")
    if isinstance(node, ast.Name) and node.id.startswith("__"):
        raise SandboxViolation(f"Dunder name blocked: {node.id}")


def _validate(tree, allowed_names):
    for node in ast.walk(tree):
        _check_node(node, allowed_names)


def _build_safe_builtins():
    safe = {}
    for name in dir(_builtins):
        if name.startswith("_"):
            continue
        if name in DANGEROUS_BUILTINS:
            continue
        safe[name] = getattr(_builtins, name)
    return safe


SAFE_BUILTINS = _build_safe_builtins()


def safe_run(code, context, timeout_seconds=30.0, allowed_names=DEFAULT_ALLOWED_NAMES):
    """Validate snippet via AST then execute with restricted builtins + timeout.

    Raises SandboxViolation on AST rejection, TimeoutError on overrun.
    Other exceptions from snippet propagate unchanged.
    """
    allowed = frozenset(allowed_names)

    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as e:
        raise SandboxViolation(f"Snippet failed to parse: {e}") from e

    _validate(tree, allowed)

    sandboxed_globals = {"__builtins__": SAFE_BUILTINS}
    sandboxed_locals = dict(context)

    error_holder = []

    def runner():
        try:
            compiled = compile(tree, "<llm-snippet>", "exec")
            # Python builtin used here is intentional and confined by SAFE_BUILTINS.
            globals_for_run = sandboxed_globals
            locals_for_run = sandboxed_locals
            __builtins__ = SAFE_BUILTINS  # noqa: F841 — keep var visible to compiled code
            _builtins.exec(compiled, globals_for_run, locals_for_run)
        except BaseException as e:
            error_holder.append(e)

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(timeout_seconds)

    if t.is_alive():
        raise TimeoutError(f"Snippet exceeded {timeout_seconds}s timeout")

    if error_holder:
        raise error_holder[0]
