# auto.cl — Scraping Feasibility Report

**Feasibility: HIGH** (conditional on User-Agent choice)

## Method

1. `GET /sitemap.xml` (returns a single `<urlset>` with ~8,090 URLs).
2. Filter to `/usados/<slug>-YYYY-<base64>` entries → **6,140 used-car detail URLs**. The
   trailing base64 fragment decodes to the origin dealer id (e.g. `andescar-cl/1262406`),
   confirming auto.cl is a dealer aggregator.
3. For each detail page, extract the Angular SSR transfer state from
   `<script id="ng-state">…</script>`. The `usedPublication_<slug>` key holds a
   `publication` object with all fields we need.
4. Normalize to the shared schema. No `__NEXT_DATA__`; one `application/ld+json`
   (`@type": "Vehicle"`) block is also present as a fallback but has less info.

## Anti-bot encountered

Cloudflare "managed challenge" (HTTP 403 + interstitial JS page titled *"Just a moment…"*)
blocks requests from:

- `curl/*` UA
- the common Chrome-on-macOS UA
- `Googlebot`, `bingbot`

Requests DO pass cleanly (HTTP 200, full HTML) with:

- Safari desktop UA (used in the scraper)
- Firefox UA
- Social-media bots (`facebookexternalhit`, `Twitterbot`, `WhatsApp/…`)

No captcha, no rate-limit headers observed. No cookie requirement. `robots.txt`
disallows `/*?*` only.

## Sample & data quality (n = 20)

| Field | Coverage |
|---|---|
| source_id, url, title, make, model, version, year, km, price_clp, currency | 20/20 |
| fuel_type, transmission, body_type, region, posted_at, seller_type | 20/20 |
| commune | **0/20** (not exposed anywhere on the page) |

`posted_at` comes from `publication.createdAt` (epoch ms). `seller_type` is native
("dealer" / "private"). All observed listings in the sample were dealer-sourced.

## Rate limit observed

20 consecutive detail requests at 0.5–1 s delay: 20/20 success, no 429, no
Cloudflare challenge re-arming. A single `requests.Session` with keep-alive was used.

## Scaling recommendation

- Safe starting rate: **1 req/s** with the Safari UA. Session reuse recommended.
- Full used-car dataset refresh: ~6,140 URLs → **~105 min single-threaded** at
  1 req/s. A nightly cron is realistic.
- Monitor for the Cloudflare challenge string (`"Just a moment"`) in responses;
  back off to Safari-mobile or social-bot UA if challenged.
- Commune-level data is **not recoverable** from auto.cl alone; either drop the
  field or enrich by following `dealerId` → dealer profile page (not investigated).
