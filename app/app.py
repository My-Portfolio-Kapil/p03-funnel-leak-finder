"""Funnel Leak Finder: upload a funnel CSV, see the biggest leak, get 3 hypotheses and an experiment brief.

Run: streamlit run app/app.py
"""

import sys
import time
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import chain, funnel  # noqa: E402

STEP_LABELS = {
    "visitors": "Visitors",
    "viewed_product": "Viewed product",
    "added_to_cart": "Added to cart",
    "began_checkout": "Began checkout",
    "added_payment": "Added payment",
    "purchased": "Purchased",
}


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def label(step: str) -> str:
    return STEP_LABELS.get(step, step)


st.set_page_config(page_title="Funnel Leak Finder", layout="wide")
st.title("Funnel Leak Finder")
st.caption("Upload a funnel export, find the biggest leak, and get a test-ready experiment brief.")

with st.sidebar:
    upload = st.file_uploader("Funnel CSV", type="csv")
    st.caption(f"Columns: date, {', '.join(funnel.SEGMENTS)}, {', '.join(funnel.STEPS)}. "
               "Without an upload the GA4 sample (Google Merchandise Store) is used.")
    view = st.radio("Funnel view", ["Raw", "Strict"], horizontal=True,
                    help="Strict caps each step at the previous one, row by row.")
    mde = st.slider("Minimum detectable effect (relative)", 0.02, 0.30, 0.10, 0.01, format="%.2f",
                    help="Smallest lift the test should detect, e.g. 0.10 = 20.0% → 22.0%.")
    leak_choice = st.radio("Run the chain on", ["Biggest testable leak", "Biggest leak"],
                           help=f"Testable: its A/B test finishes within {funnel.MAX_TEST_DAYS} days.")

try:
    df = funnel.load(upload if upload else funnel.DEFAULT_CSV)
except ValueError as e:
    st.error(str(e))
    st.stop()

strict = view == "Strict"
metrics = funnel.summary(df, strict=strict, mde=mde)
biggest, testable = metrics["biggest_leak"], metrics["testable_leak"]
chain_leak = "testable" if leak_choice == "Biggest testable leak" else "biggest"
leak = testable if chain_leak == "testable" and testable else biggest

# Data quality
flags = metrics["data_quality_flags"]
if flags:
    lines = [
        f"- **{label(f['step'])}** exceeds **{label(f['previous_step'])}** on "
        f"{f['rows_affected']} rows ({pct(f['share_of_rows'])}), {f['excess_users']:,} users too many."
        for f in flags
    ]
    advice = "Shown: strict view." if strict else "Switch to the strict view to cap these steps."
    st.warning("**Data quality: the funnel is not monotonic.**\n" + "\n".join(lines) + f"\n\n{advice}")

# Funnel chart
st.subheader(f"Funnel ({metrics['date_range'][0]} to {metrics['date_range'][1]}, {view.lower()} view)")
chart_df = pd.DataFrame(metrics["funnel"])
chart_df["label"] = chart_df["step"].map(label)
chart_df["text"] = chart_df.apply(lambda r: f"{r.users:,} · {pct(r.step_conversion)}", axis=1)
chart_df["is_leak"] = chart_df["step"] == leak["step"]
order = list(chart_df["label"])
bars = alt.Chart(chart_df).mark_bar().encode(
    x=alt.X("users:Q", title="Users"),
    y=alt.Y("label:N", sort=order, title=None),
    color=alt.condition("datum.is_leak", alt.value("#d1495b"), alt.value("#4c78a8")),
    tooltip=[alt.Tooltip("label:N", title="Step"), alt.Tooltip("users:Q", format=","),
             alt.Tooltip("step_conversion:Q", title="From previous step", format=".1%"),
             alt.Tooltip("overall_conversion:Q", title="From visitors", format=".1%")],
)
text = bars.mark_text(align="left", dx=4).encode(text="text:N", color=alt.value("#555"))
st.altair_chart((bars + text).properties(height=260), width="stretch")

# Leaks
def show_leak(title: str, leak: dict, note: str) -> None:
    seg = leak["worst_segment"]
    st.markdown(f"**{title}**")
    st.caption(note)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Step", f"{label(leak['from_step'])} → {label(leak['step'])}")
    c2.metric("Users lost (all)", f"{leak['users_lost']:,}", f"{pct(leak['step_conversion'])} convert",
              delta_color="off")
    c3.metric(f"Segment: {seg['dimension']} = {seg['value']}", pct(seg["step_conversion"]),
              f"{seg['gap_vs_overall_pp']:+.1f} pp vs. overall", delta_color="inverse")
    days = seg["test_run_time_days"]
    c4.metric("Test run time (segment)", f"{days} days" if days is not None else "n/a",
              f"{seg['users_lost_vs_overall']:,} users lost vs. overall", delta_color="off")


st.subheader("Leaks")
show_leak("Biggest leak", biggest,
          "The step losing the most users, and the segment where it converts worst.")
if testable:
    show_leak("Biggest testable leak", testable,
              f"The step × segment losing the most users vs. the overall rate whose test fits in "
              f"{funnel.MAX_TEST_DAYS} days at this MDE.")
else:
    st.info(f"No leak is testable within {funnel.MAX_TEST_DAYS} days at this MDE. "
            "Raise the MDE, or the chain runs on the biggest leak.")

with st.expander("Conversion by segment"):
    for dim in funnel.SEGMENTS:
        table = funnel.conversion(funnel.make_strict(df) if strict else df, by=dim)
        table = table.pivot(index="segment", columns="step", values="step_conversion")[funnel.STEPS[1:]]
        st.markdown(f"**{dim}**")
        st.dataframe(table.rename(columns=label).style.format("{:.1%}"), width="stretch")

# Chain
st.subheader("Hypotheses and experiment brief")
key = (upload.name if upload else "sample", view, mde, chain_leak)
if st.button("Generate with Gemini", type="primary"):
    with st.spinner("Explaining the leak → 3 hypotheses → experiment brief…"):
        start = time.perf_counter()
        try:
            st.session_state["result"] = chain.run(metrics, mde, chain_leak)
            st.session_state["result_key"] = key
        except Exception as e:  # show API or JSON errors in the UI instead of a stack trace
            st.error(f"Gemini call failed: {e}")
        st.session_state["elapsed"] = time.perf_counter() - start

result = st.session_state.get("result")
if result and st.session_state.get("result_key") == key:
    ex = result["explanation"]
    st.caption("Analysed: " + ("biggest testable leak" if result["leak_type"] == "testable" else "biggest leak"))
    st.markdown(f"#### {ex['headline']}")
    st.write(ex["explanation"])
    if ex.get("segment_insight"):
        st.write(ex["segment_insight"])
    st.info(ex["data_quality_note"])
    if ex.get("questions_to_check"):
        st.markdown("**Check before acting:**\n" + "\n".join(f"- {q}" for q in ex["questions_to_check"]))

    st.markdown("#### 3 hypotheses")
    for h in result["hypotheses"]:
        best = " · **chosen for the brief**" if h.get("id") == result["best_hypothesis_id"] else ""
        st.markdown(
            f"**{h.get('id')}: {h.get('title')}**{best}  \n"
            f"Impact: {h.get('expected_impact')} · Confidence: {h.get('confidence')}/10 · Scope: {h.get('scope')}  \n"
            f"*Because* {h.get('because')}  \n*Test:* {h.get('change')}"
        )

    b, n = result["brief"], result["numbers"]
    st.markdown(f"#### Experiment brief: {b.get('title', '')}")
    st.markdown(f"> {b['hypothesis']}")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Baseline → target", f"{pct(n['baseline_rate'])} → {pct(n['target_rate'])}")
    k2.metric("Sample size per variant", f"{n['sample_size_per_variant']:,}")
    k3.metric("Run time", f"{n['run_time_days']} days")
    k4.metric("Daily users at step", f"{n['daily_users_at_step']:,}")
    st.caption(f"Two-sided test, alpha {n['alpha']}, power {n['power']}, audience: {n['audience_basis']}. "
               "Computed in code (app/stats.py), not by the LLM.")
    st.markdown(
        f"**Audience:** {b.get('audience')}  \n**Control:** {b.get('control')}  \n"
        f"**Variant:** {b.get('variant')}  \n**Primary metric:** {b.get('primary_metric')}  \n"
        f"**Guardrails:** {', '.join(b.get('guardrail_metrics', []))}  \n"
        f"**Decision rule:** {b.get('decision_rule')}"
    )
    if b.get("risks"):
        st.markdown("**Risks:**\n" + "\n".join(f"- {r}" for r in b["risks"]))

    meta = result["_meta"]
    models = ", ".join(f"{step}: {m}" for step, m in meta["models"].items())
    fallback = " (fallback used)" if meta["fallback_used"] else ""
    st.caption(f"Models: {models}{fallback} · {st.session_state['elapsed']:.1f} s in total · "
               f"numbers copied correctly by the model: {'yes' if meta['numbers_copied_correctly'] else 'no (overwritten)'}")
elif result:
    st.caption("Settings changed. Generate again for this view.")
