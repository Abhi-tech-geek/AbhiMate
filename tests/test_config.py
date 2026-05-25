"""Smoke tests for the env-driven config layer."""

import importlib
import sys


def reload_config():
    if "config" in sys.modules:
        return importlib.reload(sys.modules["config"])
    return importlib.import_module("config")


def test_defaults(monkeypatch):
    for k in ["ABHIMATE_HOST", "ABHIMATE_PORT", "ABHIMATE_HEADLESS", "ABHIMATE_DEBUG"]:
        monkeypatch.delenv(k, raising=False)
    cfg = reload_config()
    assert cfg.settings.HOST == "127.0.0.1"
    assert cfg.settings.PORT == 5000
    assert cfg.settings.HEADLESS is False


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("ABHIMATE_HOST", "0.0.0.0")
    monkeypatch.setenv("ABHIMATE_PORT", "8080")
    monkeypatch.setenv("ABHIMATE_HEADLESS", "true")
    cfg = reload_config()
    assert cfg.settings.HOST == "0.0.0.0"
    assert cfg.settings.PORT == 8080
    assert cfg.settings.HEADLESS is True


def test_bool_parsing_variations(monkeypatch):
    for raw, expected in [("1", True), ("yes", True), ("y", True), ("on", True),
                          ("0", False), ("no", False), ("false", False), ("", False)]:
        monkeypatch.setenv("ABHIMATE_HEADLESS", raw)
        cfg = reload_config()
        assert cfg.settings.HEADLESS is expected, f"{raw!r} -> {expected}"
