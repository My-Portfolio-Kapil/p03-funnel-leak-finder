# ADR-003: Default to gemini-3.1-flash-lite, fall back between models on overload

- **Date:** 2026-11-26
- **Status:** accepted (timeout and budget added the same day)
- **Context:** The chain makes 3 Gemini calls in a row; if any one fails, the user gets no brief. P1 used `gemini-3.8-flash`. On 26 Nov it returned `503 UNAVAILABLE` ("high demand") on every call all afternoon, including after the SDK's own retries (~100 s per attempt), while `gemini-3.1-flash-lite` on the same key answered normally. The free tier gives no capacity guarantee for either model.
- **Options considered:**
  - **A. Keep 3.8-flash and retry.** Pros: best reasoning quality. Cons: no brief at all while it is overloaded; long waits break the < 60 s target.
  - **B. Switch to flash-lite only.** Pros: available when we needed it, faster and cheaper. Cons: no way out if flash-lite is overloaded instead.
  - **C. flash-lite by default, fall back to 3.8-flash on overload, and back again.** Pros: a brief whenever either model is up. Cons: quality can differ between runs; two models to watch.
- **Decision:** C. Reliability over peak quality: the chain's numbers are computed in code (ADR-002), so the model only explains and writes, and flash-lite is good enough for that.
  - Default `GEMINI_MODEL=gemini-3.1-flash-lite`; fallback `gemini-3.8-flash`, or the other way round if the primary is set to 3.8-flash. `GEMINI_FALLBACK_MODEL` overrides it.
  - On 429, 500 or 503, or if a call takes longer than 20 s, the call switches model at once, then alternates with pauses of 1, 2, 4 and 8 s, up to 6 attempts. The 20 s timeout is sent as the request deadline; the API answers 504 when it passes (it rejects deadlines under 10 s). The SDK's own retries are off so the switch is immediate. Other errors (e.g. 400, bad key) are not retried.
  - The whole chain has a 60 s budget, matching the speed target. When less than 10 s is left before a call, the chain stops and returns the steps that finished with "Model too slow, try again."
  - Each step logs the model it used (`_meta.models`, `fallback_used`) and every timeout and overload (`_meta.timeouts`, `_meta.events`); the app shows them under the brief.
- **Consequences:**
  - Easier: the demo keeps working when one model is overloaded.
  - Harder: evals must record the model per step, since a run may mix models. Retries eat the budget: in 2 of 3 runs on 26 Nov the chain took 46–56 s because of timeouts and 503s, close to the limit.
  - Before the timeout, a slow but successful run took 114 s for the 3 calls without a single error; that is why slowness now counts as overload.
