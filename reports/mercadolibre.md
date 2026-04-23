# MercadoLibre Chile — Scraper Feasibility

- **Feasibility:** HIGH
- **Method:** embedded JSON in search-results HTML (`autos.mercadolibre.cl/autos/usados`). The page embeds the exact payload the internal search API returns — 50 full item objects per page including `attributes`, `seller`, `address`, `permalink`, `price`, `date_created`, `condition`.
- **Anti-bot:** UA check + session/device gate.
  - `api.mercadolibre.com/sites/MLC/search` is **blocked** for anonymous callers (`403 PA_UNAUTHORIZED_RESULT_FROM_POLICIES`) — requires OAuth bearer token.
  - `autos.mercadolibre.cl/*` first hit returns a 5KB "Continuar" micro-landing unless the session already has a subdomain `_csrf` cookie.
  - Outdated UAs (Chrome < ~130) are punted to `/sentry/update-browser`.
  - Fix: warm up with `GET www.mercadolibre.cl/` then `GET autos.mercadolibre.cl/` (micro-landing response is fine — we only need its Set-Cookie). A modern Chrome 138 UA is sufficient. No CAPTCHA observed.
- **Sample count retrieved:** 40/40 used cars, single page fetch.
- **Data quality (per-field completeness on 40 records):**
  - `source, source_id, url, title, make, model, version, year, km, price_clp, currency, fuel_type, region, commune, posted_at, scraped_at, seller_type` — **40/40 (100%)**
  - `transmission` — 35/40 (some EVs / configurator-style listings omit it)
  - `body_type` — **0/40** — not exposed in search response; only available via item-detail page or authenticated `/items/<id>` endpoint
  - `seller_type` normalization uses `seller.car_dealer` boolean and `tags`; in practice ~94% of used-auto search results are dealers, ~6% private.
  - Prices/kms/years look realistic (CLP 6.99M-34.99M, 900-122 000 km, 2019-2026 model years). Condition filter `=="used"` is enforced at record level.
- **Rate limit observed:** none over 2 test pages + 3 warm-up requests. No 429s; no slowdowns. Conservatively throttled to 0.4 s between page fetches.
- **Scaling recommendation:** 10k listings/day is trivial — 200 pages × 50 items × ~0.5 s = ~2 min wall-clock; use 1 session per IP with cookie rotation every ~1k pages and respect a 0.3-0.5 s delay to stay invisible. For resilience, fall back to item-detail HTML (also embeds JSON) only when an attribute is missing.

**Files:**
- Scraper: `/Users/seba/Desktop/seba-core/projects/car-tracker/scrapers/mercadolibre/scraper.py`
- Data: `/Users/seba/Desktop/seba-core/projects/car-tracker/data/mercadolibre.json`
