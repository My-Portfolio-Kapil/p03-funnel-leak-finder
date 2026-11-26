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

## Results log
| Date | Prompt/model version | Score | Notes |
|---|---|---|---|
| 2026-11-26 | prompts v1, gemini-3.1-flash-lite, biggest leak (cpc) | Brief complete (7/7), numbers copied correctly | 6.1 s. 75-day run time flagged in risks. gemini-3.8-flash returned 503 all afternoon (ADR-003) |
| 2026-11-26 | prompts v1, gemini-3.1-flash-lite, testable leak (organic) | Brief complete (7/7), numbers copied correctly | **114 s, fails the < 60 s bar**: no errors, but the API was slow (33 s, 79 s, 3 s per step). Headline described the overall step, not the organic segment |
