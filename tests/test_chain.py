import json
from types import SimpleNamespace

import pytest
from google.genai import errors

from app import chain, funnel

MODELS = ("primary-model", "fallback-model")


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeModels:
    """Raises `fail_codes` in order, then answers `reply`. Each call costs `seconds` on the clock."""

    def __init__(self, clock, fail_codes=(), reply='{"ok": true}', seconds=1.0):
        self.clock, self.fail_codes, self.reply, self.seconds = clock, list(fail_codes), reply, seconds
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        self.clock.now += self.seconds
        if self.fail_codes:
            code = self.fail_codes.pop(0)
            raise errors.APIError(code, {"error": {"code": code, "message": "x", "status": "UNAVAILABLE"}})
        reply = self.reply(contents) if callable(self.reply) else self.reply
        return SimpleNamespace(text=reply)


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(chain.time, "perf_counter", c)
    monkeypatch.setattr(chain.time, "sleep", lambda s: None)
    return c


def call(fake, events=None, deadline=60.0, check=None):
    client = SimpleNamespace(models=fake)
    return chain.call(client, MODELS, "p", {}, {"ok"}, step="explain", deadline=deadline,
                      events=events if events is not None else [], check=check)


def test_primary_used_when_available(clock):
    assert call(FakeModels(clock)) == ({"ok": True}, "primary-model")


def test_falls_back_on_503(clock):
    fake = FakeModels(clock, [503])
    _, model = call(fake)
    assert model == "fallback-model"
    assert fake.calls == ["primary-model", "fallback-model"]


def test_timeout_switches_model_and_is_logged(clock):
    events = []
    _, model = call(FakeModels(clock, [504]), events)
    assert model == "fallback-model"
    assert events == [{"step": "explain", "model": "primary-model", "event": "timeout"}]


def test_switches_back_when_fallback_is_overloaded_too(clock):
    _, model = call(FakeModels(clock, [503, 503]))
    assert model == "primary-model"


def test_other_errors_are_not_retried(clock):
    fake = FakeModels(clock, [400])
    with pytest.raises(errors.APIError):
        call(fake)
    assert fake.calls == ["primary-model"]


def test_failed_check_retries_once(clock):
    fake = FakeModels(clock)
    events = []
    call(fake, events, check=lambda d: False)
    assert len(fake.calls) == 2
    assert [e["event"] for e in events] == ["check_failed"]


def test_too_slow_when_budget_is_used_up(clock):
    clock.now = 55.0
    with pytest.raises(chain.TooSlow):
        call(FakeModels(clock), deadline=60.0)


def test_mentions_segment():
    assert chain.mentions_segment({"headline": "Organic traffic leaks", "explanation": ""}, "organic")
    assert chain.mentions_segment({"headline": "", "explanation": "Direct (none) users"}, "(none)")
    assert not chain.mentions_segment({"headline": "The step leaks", "explanation": ""}, "organic")


def reply_for(contents):
    if '"numbers"' in contents:
        return json.dumps({"hypothesis": "If ...", "primary_metric": "m", "sample_size_per_variant": 1,
                           "run_time_days": 1})
    if '"explanation"' in contents and '"leak"' in contents and '"funnel"' not in contents:
        return json.dumps({"hypotheses": [{"id": "H1", "expected_impact": "high", "confidence": 5,
                                           "scope": "segment"}]})
    return json.dumps({"headline": "organic leaks", "explanation": "organic", "data_quality_note": "-"})


def test_run_returns_finished_steps_when_too_slow(clock, monkeypatch):
    fake = FakeModels(clock, reply=reply_for, seconds=26.0)  # 2 × 26 s leaves < 10 s, the API minimum, for step 3
    monkeypatch.setattr(chain, "make_client", lambda: (SimpleNamespace(models=fake), MODELS))
    out = chain.run(funnel.summary(funnel.load()))
    assert out["error"] == chain.TOO_SLOW_MESSAGE
    assert out["explanation"] and out["hypotheses"] and out["brief"] is None
    assert out["_meta"]["status"] == "too_slow"
    assert out["_meta"]["models"] == {"explain": "primary-model", "hypotheses": "primary-model"}


def test_run_overwrites_numbers_from_code(clock, monkeypatch):
    fake = FakeModels(clock, reply=reply_for)
    monkeypatch.setattr(chain, "make_client", lambda: (SimpleNamespace(models=fake), MODELS))
    out = chain.run(funnel.summary(funnel.load()))
    assert out["_meta"]["status"] == "ok"
    assert out["brief"]["sample_size_per_variant"] == out["numbers"]["sample_size_per_variant"]
    assert out["_meta"]["numbers_copied_correctly"] is False


def test_settings_from_streamlit_secrets_without_env(tmp_path, monkeypatch):
    # Streamlit Community Cloud: no .env, the key comes from st.secrets
    (tmp_path / ".streamlit").mkdir()
    (tmp_path / ".streamlit" / "secrets.toml").write_text('GEMINI_API_KEY = "from-secrets"\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(chain, "ROOT", tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert chain.setting("GEMINI_API_KEY") == "from-secrets"
