from types import SimpleNamespace

import pytest
from google.genai import errors

from app import chain

MODELS = ("primary-model", "fallback-model")


class FakeModels:
    """Raises `fail_codes` in order, then answers with valid JSON."""

    def __init__(self, fail_codes):
        self.fail_codes = list(fail_codes)
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        if self.fail_codes:
            code = self.fail_codes.pop(0)
            raise errors.APIError(code, {"error": {"code": code, "message": "overloaded", "status": "UNAVAILABLE"}})
        return SimpleNamespace(text='{"ok": true}')


def client(fail_codes):
    return SimpleNamespace(models=FakeModels(fail_codes))


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(chain.time, "sleep", lambda s: None)


def test_primary_used_when_available():
    c = client([])
    assert chain.call(c, MODELS, "p", {}, {"ok"}) == ({"ok": True}, "primary-model")


def test_falls_back_on_503_and_logs_model():
    c = client([503])
    data, model = chain.call(c, MODELS, "p", {}, {"ok"})
    assert model == "fallback-model"
    assert c.models.calls == ["primary-model", "fallback-model"]


def test_switches_back_when_fallback_is_overloaded_too():
    c = client([503, 503])
    _, model = chain.call(c, MODELS, "p", {}, {"ok"})
    assert model == "primary-model"


def test_other_errors_are_not_retried():
    c = client([400])
    with pytest.raises(errors.APIError):
        chain.call(c, MODELS, "p", {}, {"ok"})
    assert c.models.calls == ["primary-model"]
