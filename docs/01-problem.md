# Problem statement: Funnel Leak Finder

**PM:** Kapil · **Sprint:** 3

## User
A growth PM at an e-commerce company.

## Pain
- Finding where the funnel leaks (which step, for which segment) takes days of analyst time.
- Turning that leak into a testable experiment (hypotheses, metric, sample size) takes more time again, so experiments start late or are not sized properly.

## Why AI
Code can compute funnel metrics, but not explain them. An LLM chain can take the biggest leak, suggest why it happens, and write it up as an experiment brief, the way an analyst and a PM would together. All numbers (conversion rates, sample size) are computed in code, so the LLM never invents them.

## What v1 does
1. Upload funnel data (CSV export from BigQuery).
2. Code finds the biggest leak by segment (step × device, channel).
3. LLM chain:
   - explains the leak,
   - proposes 3 hypotheses,
   - writes an experiment brief with a sample size computed in code.

## Success metrics
| Metric | Target | How measured |
|---|---|---|
| Accuracy | The leak found matches our manual analysis | Manual check of the same data (P3-07) |
| Usefulness | The brief is test-ready: hypothesis, metric, variant, sample size, duration | Checklist review of the brief |
| Speed | < 60 s from upload to brief | Timed in the app |
| Cost | €0 | Free tiers only (BigQuery sandbox, Gemini, Streamlit Community Cloud) |

## Out of scope (v1)
- Live connection to GA4 or a shop backend (CSV upload only)
- Running or analysing the experiment itself
- More than one leak per run

## Backlog (v2)
- Country segmentation (needs country in the BigQuery export; many segments will be too small to judge)
