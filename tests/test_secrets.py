"""Тесты redaction-хелперов: API key и Bearer в вывод и JSON не попадают."""
from __future__ import annotations

from superteam_agent.secrets import get_api_key, redact, safe, to_safe_json


def test_get_api_key_strips_whitespace(monkeypatch):
    monkeypatch.setenv("SUPERTEAM_API_KEY", "  abc123  ")
    assert get_api_key() == "abc123"


def test_get_api_key_empty_when_unset(monkeypatch):
    monkeypatch.delenv("SUPERTEAM_API_KEY", raising=False)
    assert get_api_key() == ""


def test_redact_masks_real_api_key(monkeypatch):
    monkeypatch.setenv("SUPERTEAM_API_KEY", "supersecretkey123")
    text = "request failed: supersecretkey123 was rejected"
    assert "supersecretkey123" not in redact(text)
    assert "***REDACTED***" in redact(text)


def test_redact_masks_bearer_without_env_key(monkeypatch):
    monkeypatch.delenv("SUPERTEAM_API_KEY", raising=False)
    masked = redact("Authorization: Bearer someToken42")
    assert "someToken42" not in masked
    assert "Bearer ***REDACTED***" in masked


def test_redact_does_not_touch_other_words():
    masked = redact("hello world, no secrets here")
    assert masked == "hello world, no secrets here"


def test_safe_converts_any_value():
    assert safe(123) == "123"
    assert safe(None) == "None"
    assert safe(["a", "b"]) == "['a', 'b']"


def test_to_safe_json_truncates_by_default():
    value = {"long": "x" * 400}
    text = to_safe_json(value)
    assert text.endswith("... (truncated)")
    assert "x" * 400 not in text


def test_to_safe_json_no_truncation_with_none_limit():
    value = {"long": "x" * 400}
    text = to_safe_json(value, limit=None)
    assert "... (truncated)" not in text
    assert "x" * 400 in text


def test_to_safe_json_masks_secrets(monkeypatch):
    monkeypatch.setenv("SUPERTEAM_API_KEY", "hiddenkey999")
    text = to_safe_json({"api_key": "hiddenkey999", "n": 1}, limit=None)
    assert "hiddenkey999" not in text
