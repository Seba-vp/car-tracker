# autosusados.cl — Scraping Feasibility Report

**Feasibility: HIGH**

## Method

1. `GET /sitemap.xml` → sitemap index pointing at 5 sub-sitemaps
   (`automotoras`, `particulares`, `catmarmod`, `sucursales`, `preguntas`).
2. The two relevant sitemaps are:
   - `sitemap-automotoras.xml` → **7,385 dealer listings**
   - `sitemap-particulares.xml` → **217 private listings**
   URL pattern: `/<category>/<MAKE>/<MODEL>/<table>/<autoID>`, where
   `<table>` = 1 for dealers, 3 for privates, and `<category>` is one of
   `autos`, `suv`, `camionetas`, `camiones`, `furgones`, `motos`, etc.
3. For each detail page, parse `<script id="__NEXT_DATA__">…</script>`
   (Next.js). `props.pageProps.carInfo` is a flat object with brand, model,
   version, year, km, price, fuel, transmission, body, regionID,
   publicationDate, phone, VIN, and dealer info. An `application/ld+json`
   `@type: "Car"` block is also present as a redundancy.

## Anti-bot encountered

**None.** No Cloudflare, no WAF challenge, no JS gate. robots.txt disallows
`/?`, `/buscar*`, `/api/*`, `/admin/*` only. Plain `requests` with a Chrome UA
works directly.

## Sample & data quality (n = 20; mix of dealers + privates)

| Field | Coverage |
|---|---|
| source_id, url, title, make, model, version, year, km, price_clp, currency | 20/20 |
| fuel_type, transmission, body_type, region, posted_at, seller_type | 20/20 |
| commune | **0/20** (not exposed — only `latitude`/`length` coordinates) |

`region` requires a local lookup: `carInfo.regionID` is a numeric Chile region
code (1–16); the scraper maps it to the region name. `seller_type` is derived
from the sitemap path (`/1/` = dealer, `/3/` = private). 12/20 were privates and
8/20 dealers in this sample.

## Rate limit observed

20 consecutive detail pages at 0.5–1 s delay: 20/20 HTTP 200. No 429. No
slowdown. Response sizes 130–180 KB each.

## Scaling recommendation

- Safe starting rate: **1–2 req/s** with a single `requests.Session`.
- Full-catalog refresh (7,602 listings) → **~80 min at 1.5 req/s**
  single-threaded; trivial for a nightly cron.
- Use the sitemap as the authoritative listing index — it carries `lastmod`
  (daily), enabling delta pulls.
- Commune is recoverable post-hoc by reverse-geocoding `carInfo.latitude/length`
  if needed downstream.
