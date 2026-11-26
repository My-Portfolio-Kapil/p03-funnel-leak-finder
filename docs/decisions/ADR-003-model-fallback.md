# ADR-003: Default to gemini-3.1-flash-lite, fall back between models on overload

- **Date:** 2026-11-26
- **Status:** accepted
- **Context:** The chain makes 3 Gemini calls in a row; if any one fails, the user gets no brief. P1 used `gemini-3.8-flash`. On 26 Nov it returned `503 UNAVAILABLE` ("high demand") on every call all afternoon, including after the SDK's own retries (~100 s per attempt), while `gemini-3.1-flash-lite` on the same key answered normally. The free tier gives no capacity guarantee for either model.
- **Options considered:**
  - **A. Keep 3.8-flash and retry.** Pros: best reasoning quality. Cons: no brief at all while it is overloaded; long waits break the < 60 s target.
  - **B. Switch to flash-lite only.** Pros: available when we needed it, faster and cheaper. Cons: no way out if flash-lite is overloaded instead.
  - **C. flash-lite by default, fall back to 3.8-flash on overload, and back again.** Pros: a brief whenever either model is up. Cons: quality can differ between runs; two models to watch.
- **Decision:** C. Reliability over peak quality: the chain's numbers are computed in code (ADR-002), so the model only explains and writes, and flash-lite is good enough for that.
  - Default `GEMINI_MODEL=gemini-3.1-flash-lite`; fallback `gemini-3.8-flash`, or the other way round if the primary is set to 3.8-flash. `GEMINI_FALLBACK_MODEL` overrides it.
  - On 429, 500, 503 or 504 the call switches model at once, then alternates with pauses of 1, 2, 4 and 8 s, up to 6 attempts. The SDK's own retries are off so the switch is immediate. Other errors (e.g. 400, bad key) are not retried.
  - Each step logs the model it used (`_meta.models`, `fallback_used`), and the app shows it under the brief.
- **Consequences:**
  - Easier: the demo keeps working when one model is overloaded.
  - Harder: evals must record the model per step, since a run may mix models. Slow but successful responses don't trigger the fallback: on 26 Nov flash-lite took 114 s for the 3 calls without a single error. A per-call timeout that counts as overload would fix that (not built yet).
