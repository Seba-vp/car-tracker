# Yapo.cl scraping feasibility

**Feasibility: HIGH**

## Method used
Plain `requests` + `BeautifulSoup` against the server-rendered category list at
`https://www.yapo.cl/autos-usados` (paginated `/autos-usados.N`, up to page
1,203 = ~36,082 listings total). No JS, no headless browser, no proxy.

Per page we extract:
- 30 `<div class="d3-ad-tile d3-ads-grid__item">` nodes (title, visible price,
  year/fuel/transmission/km from the icon-tagged details list, commune text,
  seller seal).
- 30 paired `ga4addata[<adid>] = {...}` JSON blobs that contain canonical
  make, model, fuel, transmission, region-slug and commune-slug — more
  reliable than the tile's free text.
- Listing URL and `source_id` from the adid exposed on the favourite button
  and the description anchor.

Per-listing detail pages (`/autos-usados/<slug>/<adid>`) are also unblocked
and ship a `<script type="application/ld+json">` with schema.org `Car` data
(brand, model, price CLP, `mileageFromOdometer`, `vehicleModelDate`, seller
org/address). Not used here because the listing page already covers the
required schema — fetching detail pages would 50x the request count for
marginal gain (colour, seating capacity, full seller address).

## Anti-bot measures encountered
- robots.txt: HTTP 200, allows everything under `/autos-usados`; only blocks
  `/ajax/`, `/captcha/`, sharded dealer paths.
- Category page: HTTP 200, 700 KB HTML, no Cloudflare challenge, no JS
  challenge, no CAPTCHA, no cookie gate.
- No WAF fingerprint hits with realistic headers
  (Chrome UA + `Accept-Language: es-CL`).
- Gotcha (not anti-bot, but bit me first run): the server returns Brotli
  when the client advertises `br` in `Accept-Encoding`; `requests` only
  auto-decodes Brotli if the `brotli` package is installed. Fix: advertise
  only `gzip, deflate` (see `scraper.py` line note).

Detail pages: HTTP 200 with Referer = category page, same handling.

## Sample count retrieved
**50 listings** scraped in two page fetches (1.5 s throttle between pages) ->
`data/yapo.json`.

## Data quality
| Field | Completeness | Notes |
|---|---|---|
| source_id, url, title, make, model | 50/50 | |
| year, price_clp, fuel_type, transmission | 50/50 | price parsed, CLP |
| region, commune | 50/50 | region derived from ga4 province slug |
| km | 48/50 | 2 listings omit km on source |
| seller_type | 50/50 | "Profesional" seal -> professional, else private |
| version, body_type, posted_at | 0/50 | not exposed on list tile; version recoverable from detail slug / ld+json if needed |

Prices span 5.99M - 79.99M CLP (median ~14.3M). 34/50 listings are in Region
Metropolitana (matches Yapo's traffic distribution).

## What it would take to scrape at scale
- Nothing extra. Plain `requests` handles it today.
- To traverse all 1,203 pages: ~1,203 requests at 1.5 s = ~30 min per full
  sweep. Ship a `--max-pages` flag and a simple de-dup by `source_id` for
  incremental runs.
- For richer fields (colour, seating, trim) fetch `/autos-usados/<slug>/<id>`
  and parse the ld+json `Car` block (same method, no extra anti-bot layer).
- Add Brotli support (`pip install brotli`) or keep gzip-only advertising —
  current choice avoids an extra dep.
- Rotate UA and back off to 3 s between pages if Yapo later tightens; today
  1.5 s was not rate-limited.

No headless browser, no paid proxy, no cloudscraper needed.
