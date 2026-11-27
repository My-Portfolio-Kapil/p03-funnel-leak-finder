# Evals

## Eval set
One dataset for v1: `data/funnel.csv`, the GA4 sample e-commerce export (Google Merchandise Store, 1 Nov 2020–31 Jan 2021, 92 days, 1,649 rows of day × device × medium). The answer key is our manual analysis of the same CSV (P3-07, to do).

## Metrics and pass bar
| Metric | Definition | Pass bar |
|---|---|---|
| Leak accuracy | Biggest leak and biggest testable leak match the manual analysis | Same step and segment |
| Test-ready brief | Brief has hypothesis, primary metric, control, variant, sample size, run time, decision rule | All 7 present |
| Numbers correct | Sample size and run time in the brief equal `app/stats.py` | 100% (enforced in code) |
| Speed | Upload to brief | < 60 s |
| Cost | | €0 |

## Findings

### Data quality: the funnel is not monotonic
- **351 of 1,649 rows (21%)** have more `began_checkout` than `added_to_cart` users: 3,207 users too many in total. One more row has more purchases than payments.
- Likely cause: each step counts users separately per day, not users who completed the earlier steps, and the GA4 sample under-records `add_to_cart`.
- The strict view caps each step at the previous one, row by row. **Purchases drop from 4,842 to 3,872 (−20%)**, overall conversion from 1.5% to 1.2%.
- The biggest leak (visitor → product view) is the same in both views, since the flags only affect later steps. Any leak found at checkout or later should be read in the strict view.

### The biggest leak is not testable in time
- Biggest leak: **visitor → product view**, 252,537 of 328,696 users lost (23.2% convert). Its worst segment is **cpc** (paid ads) at 20.8%, −2.4 pp vs. overall.
- An A/B test on cpc traffic needs **6,197 users per variant** (20.8% → 22.9%, MDE 10% relative), but only ~166 cpc users a day reach that step: **75 days**. The first brief flagged this itself as too slow.
- So we added a second ranking: the **biggest testable leak**, i.e. the step × segment losing the most users vs. the overall rate whose test fits in 28 days. On this data: **visitor → product view for organic traffic** (22.2%, −1.0 pp, 1,158 users lost vs. overall, **10 days**). The chain now runs on that one by default.
- Product lesson: the worst segment is often small, and a leak you can't test in a month isn't actionable. The tool ranks by what a team can act on.

## Manual check (Kapil)
- **Date:** 2026-11-27
- **Checked:** `data/funnel.csv` (raw view), both leaks in the app, and the chain's output for the biggest testable leak (visitor → product view, medium = organic).
- **Verdict: ✅ pass, with the noted fixes.**

| Check | Result |
|---|---|
| Funnel numbers | ✅ Verified: 23.2% visitor → product view matches the CSV |
| Excluding `(data deleted)` / `<Other>` | ✅ Correct (`(data deleted)` converts at 35.0%, +11.8 pp, and would otherwise distort the ranking) |
| Leak finding | Segments are homogeneous: device ±0.1 pp, medium within ~2.5 pp. The bigger opportunity is the step itself across all users, not a segment. Segment-gap ranking adds little on this dataset |
| Hypotheses | H1 (search-query headlines) infeasible, because organic search keywords are hidden ("not provided"). H2 and H3 are realistic. Prompt updated |
| Brief | Complete, with guardrails and decision rule |

**Fixes made**
- The testable-leak card now shows the segment's loss vs. overall ("Users lost vs. overall (organic)": 1,158). The all-users loss (252,537) appears only on the biggest-leak card.
- `prompts/2-hypotheses.md`: hypotheses must be feasible with standard web data; no keyword-based personalisation.

## Results log
| Date | Prompt/model version | Score | Notes |
|---|---|---|---|
| 2026-11-26 | prompts v1, gemini-3.1-flash-lite, biggest leak (cpc) | Brief complete (7/7), numbers copied correctly | 6.1 s. 75-day run time flagged in risks. gemini-3.8-flash returned 503 all afternoon (ADR-003) |
| 2026-11-26 | prompts v1, gemini-3.1-flash-lite, testable leak (organic) | Brief complete (7/7), numbers copied correctly | **114 s, fails the < 60 s bar**: no errors, but the API was slow (33 s, 79 s, 3 s per step). Headline described the overall step, not the organic segment |
| 2026-11-26 | prompt 1 v2 (segment focus + check), 20 s timeout, 60 s budget · run 1 | 7/7, segment named, numbers copied correctly | **5.6 s** (1.6 / 2.2 / 1.8). No retries |
| 2026-11-26 | same · run 2 | 7/7, segment named, numbers copied correctly | **56.2 s** (26.9 / 4.6 / 24.7). Step 1: flash-lite timed out at 20 s, 3.8-flash 503, flash-lite answered. Step 3: 503 on both, then flash-lite answered |
| 2026-11-26 | same · run 3 | 7/7, segment named, numbers copied correctly | **46.0 s** (2.7 / 25.3 / 18.0). Step 2: flash-lite 503, 3.8-flash timed out at 20 s, flash-lite answered |

All 3 runs finished within the 60 s bar, but 2 of 3 only just did, because of retries. All 3 headlines named the organic segment and quoted its 22.2%, so the segment check never had to retry. All 3 runs chose a landing-page hypothesis for organic traffic (10-day test). Every final answer came from flash-lite: 3.8-flash returned 503 or timed out each time it was tried.
| 2026-11-27 | prompt 2 v2 (feasibility rule, no keyword personalisation) | 7/7, segment named, numbers copied correctly | **8.2 s** (1.9 / 3.4 / 2.9), no retries. **No keyword-based hypothesis**: H1 seasonal category banner, H2 page speed (all users, high, 8/10), H3 sticky category bar. H2 chosen: 23.2% → 25.5%, 4 days. Minor: the brief's "because" mentions organic traffic although the test targets all users |
