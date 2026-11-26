"""Three sequential Gemini calls: explain the leak -> 3 hypotheses -> experiment brief.

Each step's output is part of the next step's input. All numbers come from
app/funnel.py and app/stats.py; the LLM only explains and writes.

Model: GEMINI_MODEL (default gemini-3.1-flash-lite). If it is overloaded, the call
falls back to the other model and back again (ADR-003). The model used per step is
logged in `_meta.models`.

Usage: python -m app.chain [--strict] [--mde 0.10] [--leak testable|biggest]
"""

import argparse
import json
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

from app import funnel, stats

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"
IMPACT_RANK = {"high": 3, "medium": 2, "low": 1}
MODELS = ("gemini-3.1-flash-lite", "gemini-3.8-flash")  # default first; each is the other's fallback
OVERLOAD_CODES = (429, 500, 503, 504)


def load_prompt(name: str) -> str:
    # The prompt is everything after the first '---' line; above it are notes.
    text = (PROMPTS / name).read_text(encoding="utf-8")
    return text.split("\n---\n", 1)[1].strip()


def make_client() -> tuple[genai.Client, tuple[str, str]]:
    """Client plus (primary, fallback) model names."""
    load_dotenv(ROOT / ".env")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY in .env")
    primary = os.getenv("GEMINI_MODEL") or MODELS[0]
    fallback = os.getenv("GEMINI_FALLBACK_MODEL") or (MODELS[1] if primary == MODELS[0] else MODELS[0])
    # SDK retries off: on overload we switch model at once instead of waiting on the same one.
    http = types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1))
    return genai.Client(api_key=api_key, http_options=http), (primary, fallback)


def call(client: genai.Client, models: tuple[str, str], prompt: str, payload: dict,
         required: set) -> tuple[dict, str]:
    """One JSON-mode call; returns (data, model used).

    On 429/5xx it alternates primary -> fallback -> primary ... with growing pauses.
    Invalid JSON is retried once on the same model.
    """
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        thinking_config=types.ThinkingConfig(thinking_level="LOW"),
    )
    contents = prompt + "\n" + json.dumps(payload, indent=2, ensure_ascii=False)
    which, bad_json, last_error = 0, 0, None
    for attempt in range(6):
        model = models[which]
        try:
            response = client.models.generate_content(model=model, contents=contents, config=config)
        except errors.APIError as e:
            if e.code not in OVERLOAD_CODES:
                raise
            last_error = e
            log.warning("%s returned %s, switching to %s", model, e.code, models[1 - which])
            which = 1 - which
            if attempt:  # first switch is immediate, then 1 s, 2 s, 4 s, 8 s
                time.sleep(2 ** (attempt - 1))
            continue
        try:
            data = json.loads(response.text)
            if isinstance(data, dict) and required <= data.keys():
                return data, model
        except (json.JSONDecodeError, TypeError):
            pass
        bad_json += 1
        if bad_json == 2:
            raise RuntimeError(f"{model} returned invalid JSON twice")
    raise RuntimeError(f"Both models overloaded: {last_error}")


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
    """
    client, models = make_client()
    leak_type = "testable" if leak == "testable" and metrics.get("testable_leak") else "biggest"
    chosen = metrics[f"{leak_type}_leak"]
    # The LLM sees one leak only, so it can't mix them up.
    metrics = {k: v for k, v in metrics.items() if k not in ("biggest_leak", "testable_leak")}
    metrics = {**metrics, "leak_type": leak_type, "leak": chosen}

    timings, used = {}, {}

    t = time.perf_counter()
    explanation, used["explain"] = call(
        client, models, load_prompt("1-explain-leak.md"), metrics,
        {"headline", "explanation", "data_quality_note"},
    )
    timings["explain"] = time.perf_counter() - t

    t = time.perf_counter()
    step2_input = {"leak": chosen, "explanation": explanation}
    result, used["hypotheses"] = call(client, models, load_prompt("2-hypotheses.md"), step2_input, {"hypotheses"})
    hypotheses = result["hypotheses"][:3]
    timings["hypotheses"] = time.perf_counter() - t

    best = pick_best(hypotheses)
    numbers = numbers_for(best, metrics, mde)

    t = time.perf_counter()
    step3_input = {"leak": chosen, "explanation": explanation, "hypothesis": best, "numbers": numbers}
    brief, used["brief"] = call(
        client, models, load_prompt("3-experiment-brief.md"), step3_input,
        {"hypothesis", "primary_metric", "sample_size_per_variant", "run_time_days"},
    )
    timings["brief"] = time.perf_counter() - t

    # The code's numbers win; record whether the model copied them correctly.
    copied_ok = (
        brief.get("sample_size_per_variant") == numbers["sample_size_per_variant"]
        and brief.get("run_time_days") == numbers["run_time_days"]
    )
    brief["sample_size_per_variant"] = numbers["sample_size_per_variant"]
    brief["run_time_days"] = numbers["run_time_days"]

    return {
        "leak_type": leak_type,
        "leak": chosen,
        "explanation": explanation,
        "hypotheses": hypotheses,
        "best_hypothesis_id": best.get("id"),
        "numbers": numbers,
        "brief": brief,
        "_meta": {
            "models": used,
            "primary_model": models[0],
            "fallback_used": any(m != models[0] for m in used.values()),
            "seconds": {k: round(v, 1) for k, v in timings.items()},
            "total_seconds": round(sum(timings.values()), 1),
            "numbers_copied_correctly": copied_ok,
        },
    }


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
