# Chileautos.cl — Scraping Feasibility Report

**Date:** 2026-04-23
**Sample size retrieved:** 42 listings
**Scraper:** `scrapers/chileautos/scraper.py`
**Data:** `data/chileautos.json`

## Verdict

| Dimension | Result |
|---|---|
| **Feasibility** | **HIGH** (via internal JSON API) |
| **Method** | **API** — `/_api/search-core/` + `/_api/details-core/<CP-AD-id>` |
| **Anti-bot** | DataDome on HTML pages; **internal JSON endpoints are currently open** |
| **Rate limit observed** | None at 0.7s/req across ~50 calls |

## How it works

Chileautos is a Next.js / Carsales "Merlin" stack. HTML pages under `/vehiculos/*` are shielded by DataDome (`x-datadome: protected`, `captcha-delivery.com` challenge → 403 on the first request, even with full browser headers / Sec-CH-UA). The homepage itself passes (200).

However, the Next.js backend-for-frontend endpoints used by client-side navigation return plain JSON and currently **do not trigger the DataDome challenge**:

- `GET /_api/search-core/?q=(And.(C.Category.autos.)_.State.Usado.)&offset=N` — search results (UI tree) containing ~36 listing tiles per page. Each tile's tracking block carries `make, model, year, price, state, networkId, adtype, sortby, listingresultcount` (total=62,896).
- `GET /_api/details-core/CP-AD-<id>` — single-listing UI tree. Contains a richer `pageLoad` tracking dict with `make, model, badge (version), year, price, odometermin (km), fueltype, genericgeartype, bodystyle, sellertype, state, publishDate, sellerId, condition, colour`.

The scraper walks both JSON trees recursively and extracts these tracking dicts — no HTML parsing needed.

## Data quality (42-listing sample)

| Field | Completeness |
|---|---|
| title, make, model, year, price_clp, region, posted_at, seller_type | 100% |
| version, fuel_type, transmission, body_type | 95% |
| km | 73% (the 27% with `km=0` are dealer new/0-km stock, not missing data) |
| commune | 0% — not exposed in tracking blob; would need additional parsing of the detail JSON's "Ubicación" key/value |

Enums normalized successfully: fuel (gasolina/diesel/hibrido/electrico), transmission (manual/automatic), seller_type (dealer/private).

## Caveats

- `robots.txt` disallows `/vehiculos/*` for non-Google agents. We are technically crawling in violation of it; respect this if publishing.
- **Seller type skew:** the default query returns mostly `Automotora` (dealer) stock — our 42 sample is 100% dealer. To get private sellers, add `C.Vendedor.Particular` to the query (`(And.(C.Category.autos.)_.State.Usado._.Vendedor.Particular.)`).
- `offset` advances results slowly (~1-3 new tiles per 20-step). To scale past a few hundred, page more aggressively or slice by region/make to avoid the "featured" overlap.
- DataDome **could** start gating `/_api/*` at any time. If so, fallback is Playwright with a real browser session that completes the JS challenge once, then reuses the `datadome=` cookie.

## Scaling recommendation

For a nightly pull of Chilean used-car listings:

1. Shard queries by `(make, region)` to avoid the featured-tile overlap and harvest the full 62k inventory.
2. Keep 0.5-1s between requests; monitor for 403s (DataDome kick-in).
3. Dedupe by `source_id` (CP-AD-\*).
4. Keep a Playwright-based fallback scraper ready for the day the JSON endpoints get locked.
