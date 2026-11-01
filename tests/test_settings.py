"""Tests for the sandbox-only guard and environment helpers in cleat.settings (invariant I-6)."""

import importlib
import sys
from types import ModuleType

import pytest


def _fresh_settings(monkeypatch: pytest.MonkeyPatch, paypal_env: str) -> ModuleType:
    """Import cleat.settings from scratch, as a new process would, with PAYPAL_ENV set."""
    monkeypatch.setenv("PAYPAL_ENV", paypal_env)
    monkeypatch.delitem(sys.modules, "cleat.settings", raising=False)
    return importlib.import_module("cleat.settings")


def test_sandbox_is_accepted_and_base_url_is_fixed_to_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _fresh_settings(monkeypatch, "sandbox")
    assert settings.PAYPAL_ENV == "sandbox"
    assert settings.PAYPAL_BASE_URL == "https://api-m.sandbox.paypal.com"


@pytest.mark.parametrize("paypal_env", ["live", "production", "Sandbox", ""])
def test_import_refuses_anything_but_sandbox(monkeypatch: pytest.MonkeyPatch, paypal_env: str) -> None:
    with pytest.raises(RuntimeError, match="PAYPAL_ENV must be"):
        _fresh_settings(monkeypatch, paypal_env)


def test_unset_paypal_env_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # Checked through the function because a developer's .env would fill in an unset variable on import.
    settings = _fresh_settings(monkeypatch, "sandbox")
    with pytest.raises(settings.SettingsError):
        settings.check_sandbox(None)


def test_require_names_the_missing_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _fresh_settings(monkeypatch, "sandbox")
    monkeypatch.delenv("CLEAT_TEST_UNSET", raising=False)
    with pytest.raises(settings.SettingsError, match="CLEAT_TEST_UNSET"):
        settings.require("CLEAT_TEST_UNSET")


def test_agent_run_limit_must_be_a_whole_number(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_RUNS_PER_HOUR", "forty")
    with pytest.raises(RuntimeError, match="AGENT_RUNS_PER_HOUR"):
        _fresh_settings(monkeypatch, "sandbox")
