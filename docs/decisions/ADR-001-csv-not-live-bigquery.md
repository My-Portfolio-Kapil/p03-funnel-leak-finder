# ADR-001: CSV upload instead of a live BigQuery connection

- **Date:** 2026-11-26
- **Status:** accepted
- **Context:** The funnel data comes from the GA4 sample e-commerce dataset in BigQuery (Google Merchandise Store, Nov 2020–Jan 2021). The app needs that data on every run, both locally and on Streamlit Community Cloud. Budget is €0 and no credit card.
- **Options considered:**
  - **A. Live BigQuery query from the app.** Pros: always the full dataset, any date range or segment. Cons: needs a Google Cloud service-account key stored in the deployed app; every visitor's run uses the sandbox's query quota; slower (seconds per query); a real shop would need its own GA4 export set up first.
  - **B. Export once to CSV and upload.** Pros: no cloud credentials in the app, instant, works offline, any shop can export the same columns from GA4 or its shop system. Cons: data is a snapshot; changing segments or dates means a new export.
  - **C. GA4 Data API.** Pros: the "real" integration for a shop. Cons: needs OAuth and a GA4 property with access; the public sample is not available through it.
- **Decision:** B for v1. The query that produced `data/funnel.csv` is run by hand in the BigQuery sandbox; the app reads the committed CSV or an uploaded one with the same columns.
- **Consequences:**
  - Easier: no secrets except the Gemini key; deploy is a plain Streamlit app; demo always works.
  - Harder: no country segment unless it is added to the export; data doesn't update itself.
  - Revisit with C when the tool is used on a real shop with GA4 access.
