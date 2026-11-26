# ADR-002: Funnel metrics and sample size in code, not by the LLM

- **Date:** 2026-11-26
- **Status:** accepted
- **Context:** The brief is only test-ready if its numbers are right: conversion rates, users lost, sample size and run time. LLMs are unreliable at arithmetic and statistics, and a wrong sample size leads to an underpowered or needlessly long test. A PM reading the brief can't easily tell a computed number from an invented one.
- **Options considered:**
  - **A. Give the LLM the raw CSV and let it do everything.** Pros: one call, least code. Cons: numbers can be invented or miscalculated; 1,649 rows also cost many tokens.
  - **B. LLM uses a code tool (function calling) for the maths.** Pros: correct numbers, the LLM decides what to compute. Cons: more moving parts, harder to evaluate, and still no guarantee the final text repeats the tool's numbers.
  - **C. Code computes everything first; the LLM only explains and writes.** Pros: every number is deterministic and unit-tested; the LLM gets a short metrics JSON; the chain is easy to evaluate step by step. Cons: the LLM can't ask for an analysis the code doesn't run.
- **Decision:** C.
  - `app/funnel.py` computes conversion, the biggest leak, the worst segment and data-quality flags.
  - `app/stats.py` computes sample size per variant (two-sided two-proportion test, alpha 0.05, power 0.8) and run time from daily users at the leaky step.
  - The code chooses the best hypothesis (impact, then confidence) and computes its numbers for the right audience (all users or the worst segment).
  - Prompt 3 must copy the numbers; afterwards the code overwrites sample size and run time with its own values and records whether the model copied them correctly.
- **Consequences:**
  - Easier: numbers are always correct and testable (`tests/`); the eval only has to judge the reasoning and the brief's wording.
  - Harder: new analyses (e.g. country, time trends) need code first; the MDE is a user setting rather than derived from the hypothesis.
