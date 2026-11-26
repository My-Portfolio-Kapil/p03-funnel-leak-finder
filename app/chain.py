"""Three sequential Gemini calls: explain the leak -> 3 hypotheses -> experiment brief.

Each step's output is part of the next step's input. All numbers come from
app/funnel.py and app/stats.py; the LLM only explains and writes.

Model: GEMINI_MODEL (default gemini-3.1-flash-lite). If a call is overloaded or takes
over 20 s, it falls back to the other model and back again (ADR-003). The whole chain
has a 60 s budget; past it, the steps that finished are returned with an error.
The model per step and every timeout are logged in `_meta`.

Settings are read from the environment / .env, or from st.secrets on Streamlit Cloud.

Usage: python -m app.chain [--strict] [--mde 0.10] [--leak testable|biggest]
"""

import argparse
import json
import logging
import os
import time
from pathlib import Path

import httpx2
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

from app import funnel, stats

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"
IMPACT_RANK = {"high": 3, "medium": 2, "low": 1}
MODELS = ("gemini-3.1-flash-lite", "gemini-3.8-flash")  # default first; each is the other's fallback
OVERLOAD_CODES = (429, 500, 503)
TIMEOUT_CODE = 504  # the API's answer when our per-call deadline passes
CALL_TIMEOUT_S = 20
TOTAL_BUDGET_S = 60
MIN_DEADLINE_S = 10  # the API rejects deadlines shorter than this
TOO_SLOW_MESSAGE = "Model too slow, try again."


class TooSlow(Exception):
    """The chain's time budget ran out."""


def load_prompt(name: str) -> str:
    # The prompt is everything after the first '---' line; above it are notes.
    text = (PROMPTS / name).read_text(encoding="utf-8")
    return text.split("\n---\n", 1)[1].strip()


def setting(name: str) -> str | None:
    """From the environment / .env, else from Streamlit secrets (Streamlit Community Cloud)."""
    load_dotenv(ROOT / ".env")
    if os.getenv(name):
        return os.getenv(name)
    try:
        import streamlit as st

        return st.secrets.get(name)
    except Exception:  # no secrets.toml, e.g. on the command line
        return None


def make_client() -> tuple[genai.Client, tuple[str, str]]:
    """Client plus (primary, fallback) model names."""
    api_key = setting("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY in .env or in the Streamlit secrets")
    primary = setting("GEMINI_MODEL") or MODELS[0]
    fallback = setting("GEMINI_FALLBACK_MODEL") or (MODELS[1] if primary == MODELS[0] else MODELS[0])
    # SDK retries off: on overload we switch model at once instead of waiting on the same one.
    http = types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1))
    return genai.Client(api_key=api_key, http_options=http), (primary, fallback)


def call(client: genai.Client, models: tuple[str, str], prompt: str, payload: dict, required: set,
         *, step: str, deadline: float, events: list, check=None) -> tuple[dict, str]:
    """One JSON-mode call; returns (data, model used).

    - Overload (429/500/503) or no answer within CALL_TIMEOUT_S: switch to the other
      model, alternating with growing pauses.
    - Invalid JSON, or `check(data)` false: retried once on the same model.
    - Raises TooSlow when `deadline` (a perf_counter time) leaves no room for a call.
    Every retry is appended to `events`.
    """
    contents = prompt + "\n" + json.dumps(payload, indent=2, ensure_ascii=False)
    which, bad_json, checked, last_error = 0, 0, False, None
    for attempt in range(6):
        remaining = deadline - time.perf_counter()
        if remaining < MIN_DEADLINE_S:
            raise TooSlow(step)
        model = models[which]
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            thinking_config=types.ThinkingConfig(thinking_level="LOW"),
            http_options=types.HttpOptions(timeout=int(min(CALL_TIMEOUT_S, remaining) * 1000)),
        )
        try:
            response = client.models.generate_content(model=model, contents=contents, config=config)
        except (errors.APIError, httpx2.TimeoutException) as e:
            code = getattr(e, "code", TIMEOUT_CODE)
            if code not in OVERLOAD_CODES + (TIMEOUT_CODE,):
                raise
            last_error = e
            event = "timeout" if code == TIMEOUT_CODE else f"overload_{code}"
            events.append({"step": step, "model": model, "event": event})
            log.warning("%s: %s on %s, switching to %s", step, event, model, models[1 - which])
            which = 1 - which
            if attempt:  # first switch is immediate, then 1 s, 2 s, 4 s, 8 s
                time.sleep(min(2 ** (attempt - 1), max(0, deadline - time.perf_counter() - MIN_DEADLINE_S)))
            continue
        try:
            data = json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
            data = None
        if not isinstance(data, dict) or not required <= data.keys():
            events.append({"step": step, "model": model, "event": "invalid_json"})
            bad_json += 1
            if bad_json == 2:
                raise RuntimeError(f"{model} returned invalid JSON twice")
            continue
        if check and not check(data) and not checked:
            events.append({"step": step, "model": model, "event": "check_failed"})
            checked = True
            continue
        return data, model
    raise RuntimeError(f"Both models overloaded: {last_error}")


def mentions_segment(explanation: dict, segment: str) -> bool:
    """True if the headline or explanation names the segment, e.g. "organic" or "(none)" -> "none"."""
    name = segment.strip("()<>").lower()
    text = f'{explanation.get("headline", "")} {explanation.get("explanation", "")}'.lower()
    return name in text


def pick_best(hypotheses: list[dict]) -> dict:
    return max(
        hypotheses,
        key=lambda h: (IMPACT_RANK.get(str(h.get("expected_impact")).lower(), 0), h.get("confidence", 0)),
    )


def numbers_for(hypothesis: dict, metrics: dict, mde: float) -> dict:
    """Baseline and daily traffic for the hypothesis' scope: all users or the worst segment."""
    leak = metrics["leak"]
    if hypothesis.get("scope") == "segment":
        source = leak["worst_segment"]
        audience = f'{source["dimension"]} = {source["value"]}'
    else:
        source = leak
        audience = "all users"
    daily = source["users_entering"] / metrics["days"]
    numbers = stats.experiment_numbers(source["step_conversion"], mde, daily)
    numbers["audience_basis"] = audience
    return numbers


def run(metrics: dict, mde: float = 0.10, leak: str = "testable") -> dict:
    """Run the chain on the biggest testable leak (default) or the biggest leak.

    Falls back to the biggest leak if no leak is testable within the time limit.
    If the 60 s budget runs out, returns the steps that finished, `error` set and
    `_meta.status` "too_slow".
    """
    client, models = make_client()
    leak_type = "testable" if leak == "testable" and metrics.get("testable_leak") else "biggest"
    chosen = metrics[f"{leak_type}_leak"]
    segment = chosen["worst_segment"]["value"]
    # The LLM sees one leak only, so it can't mix them up.
    metrics = {k: v for k, v in metrics.items() if k not in ("biggest_leak", "testable_leak")}
    metrics = {**metrics, "leak_type": leak_type, "leak": chosen}

    start = time.perf_counter()
    deadline = start + TOTAL_BUDGET_S
    timings, used, events = {}, {}, []
    out = {"leak_type": leak_type, "leak": chosen, "explanation": None, "hypotheses": None,
           "best_hypothesis_id": None, "numbers": None, "brief": None, "error": None}

    def step(name, prompt, payload, required, check=None):
        t = time.perf_counter()
        data, used[name] = call(client, models, load_prompt(prompt), payload, required,
                                step=name, deadline=deadline, events=events, check=check)
        timings[name] = time.perf_counter() - t
        return data

    try:
        out["explanation"] = step(
            "explain", "1-explain-leak.md", metrics, {"headline", "explanation", "data_quality_note"},
            check=lambda d: mentions_segment(d, segment),
        )
        result = step("hypotheses", "2-hypotheses.md",
                      {"leak": chosen, "explanation": out["explanation"]}, {"hypotheses"})
        out["hypotheses"] = result["hypotheses"][:3]

        best = pick_best(out["hypotheses"])
        out["best_hypothesis_id"] = best.get("id")
        out["numbers"] = numbers = numbers_for(best, metrics, mde)

        brief = step(
            "brief", "3-experiment-brief.md",
            {"leak": chosen, "explanation": out["explanation"], "hypothesis": best, "numbers": numbers},
            {"hypothesis", "primary_metric", "sample_size_per_variant", "run_time_days"},
        )
        # The code's numbers win; record whether the model copied them correctly.
        copied_ok = (
            brief.get("sample_size_per_variant") == numbers["sample_size_per_variant"]
            and brief.get("run_time_days") == numbers["run_time_days"]
        )
        brief["sample_size_per_variant"] = numbers["sample_size_per_variant"]
        brief["run_time_days"] = numbers["run_time_days"]
        out["brief"] = brief
    except TooSlow as e:
        out["error"] = TOO_SLOW_MESSAGE
        log.warning("Budget of %s s ran out during %s", TOTAL_BUDGET_S, e)
        copied_ok = None

    out["_meta"] = {
        "status": "too_slow" if out["error"] else "ok",
        "models": used,
        "primary_model": models[0],
        "fallback_used": any(m != models[0] for m in used.values()),
        "timeouts": [e for e in events if e["event"] == "timeout"],
        "events": events,
        "segment_mentioned": mentions_segment(out["explanation"], segment) if out["explanation"] else None,
        "seconds": {k: round(v, 1) for k, v in timings.items()},
        "total_seconds": round(time.perf_counter() - start, 1),
        "numbers_copied_correctly": copied_ok,
    }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--strict", action="store_true", help="use the strict funnel view")
    parser.add_argument("--mde", type=float, default=0.10, help="minimum detectable effect, relative")
    parser.add_argument("--leak", choices=["testable", "biggest"], default="testable")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    metrics = funnel.summary(funnel.load(), strict=args.strict, mde=args.mde)
    result = run(metrics, args.mde, args.leak)
    log.info("Models used: %s", result["_meta"]["models"])
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
