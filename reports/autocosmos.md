# Autocosmos.cl — Scraping Feasibility

- **Verdict:** HIGH
- **Method:** HTML + Schema.org microdata + `dfp_*` meta tags (no API, no JS)
- **Anti-bot:** none observed (UA check only; robots.txt advises `Crawl-Delay: 20`)
- **Sample retrieved:** 40 listings
- **Observed rate:** 0.8 s/request, 41 requests in ~35 s, zero 429/403/CAPTCHA

## What worked

Index `https://www.autocosmos.cl/auto/usado?p=N` is fully SSR: 48 `<article class="listing-card">` per page, each with Schema.org/Car microdata (brand, model, modelDate, mileageFromOdometer, price, addressLocality, addressRegion).

Detail pages expose a `dfp_*` meta block used for ad targeting — a goldmine: `dfp_marca`, `dfp_modelo`, `dfp_version`, `dfp_anio`, `dfp_segmentoNick` (body type), `dfp_region`, `dfp_city`, and `dfp_privado` (`particular`=private, `empresa`=dealer).

No `__NEXT_DATA__`, no ld+json, no internal JSON API.

## Data quality (n=40)

| field | fill | notes |
|---|---|---|
| title, make, model, version, year, km, currency, region, commune, body_type, seller_type, price_clp | 40/40 | |
| fuel_type | 40/40 | from model catalog (gasolina/diesel only in sample) |
| transmission | 32/40 | 8 rows fell to `other` — catalog phrase like "manual 5 velocidades" works; outliers have non-standard values |
| posted_at | 0/40 | **not exposed** on public pages |
| seller_type distribution | 39 private / 1 dealer | default sort is price-ascending, skewing private |

Key bug found and fixed: detail pages embed a related-listings carousel with its own `itemprop="price"` tags. A naive `soup.find_all(itemprop="price")` picked sibling listings. Fix: scope all detail scraping to the `.car-specifics` block.

## Scaling recommendation

- Respect the advisory `Crawl-Delay: 20` for recurring jobs. For daily full-index sweeps: 2–5 s delay with jitter, off-hours. Ad-hoc runs at 0.8–1 s are fine.
- Stable source IDs: 32-char hex in the URL path (e.g. `b45db4da343e42b0b353b15fc2ea6e7b`).
- Visible pagination goes to `?p=10`; verify depth via last-page link in prod. Rough estimate ~2,400 active listings.
- `posted_at` gap: track first-seen timestamp locally on first insert.
- `fuel_type`/`transmission` are model-catalog level, not per-listing — fine for 95% of cases.
- For new-listing monitoring, sort by `?orden=mas-reciente` (if supported) to cheaply detect deltas instead of full sweeps.
