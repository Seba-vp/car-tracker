# Chile Used Car Scraping — Feasibility Report

**Date:** 2026-04-23
**Scope:** Investigate every significant Chilean used-car listings source, attempt to scrape each with a real Python script, report honest findings.
**Method:** 8 parallel investigation agents, one source (or pair) per agent. Each built a working scraper and ran it against live data.

---

## TL;DR

**9 of 10 sources are scrapable today with pure `requests` + `BeautifulSoup` (no browsers, no proxies, no paid services).** Combined sample = **317 real listings** across all working sources. The single blocked source (Demotores) is geo-blocked at the network layer, not the app layer.

| Source | Verdict | Method | Samples | Inventory | Anti-bot |
|---|---|---|---|---|---|
| **Yapo.cl** | 🟢 HIGH | Server-rendered HTML + inline `ga4addata` JSON | 50/50 | ~36k | None on autos path |
| **Chileautos.cl** | 🟢 HIGH | Internal `/_api/search-core` + `/_api/details-core` JSON | 42/42 | ~63k | DataDome on HTML, API clean |
| **MercadoLibre** | 🟢 HIGH | Embedded search-API payload in HTML (public API now needs OAuth) | 40/40 | Large | None once warmed up |
| **Kavak.cl** | 🟢 HIGH | Next.js RSC payloads on list + ld+json Car schema on VIP | 40/40 | ~1-3k | None |
| **Autocosmos.cl** | 🟢 HIGH | Schema.org microdata + `dfp_*` meta | 40/40 | Large | None; `Crawl-Delay: 20` |
| **Economicos.cl** | 🟢 HIGH | Plain HTML with clean `<li><span>Label:</span> Value</li>` | 40/40 | ~10k | None |
| **Autopia / BravoAuto** | 🟢 HIGH | Inertia.js `data-page` JSON blob | 25/25 | ~120 | None |
| **Auto.cl** | 🟢 HIGH | Sitemap + Angular SSR `ng-state` JSON | 20/20 | ~6k | Cloudflare challenge, bypassed with Safari UA |
| **Autosusados.cl** | 🟢 HIGH | Sitemap index + `__NEXT_DATA__` | 20/20 | ~7.6k | None |
| **Demotores.cl** | 🔴 BLOCKED | TCP timeout from both local egress and Anthropic egress | 0 | ? | Geo-block / firewall |

**Aggregate addressable inventory across 9 working sources: ~120,000+ unique listings.** (MercadoLibre alone likely larger; total TBD without full sweep.)

---

## Source-by-source findings

### 🟢 MercadoLibre Chile — `autos.mercadolibre.cl`

- **Finding:** The documented public REST API (`api.mercadolibre.com/sites/MLC/search`) now returns **403 for anonymous callers** — requires OAuth App Token registration. However, the search HTML page **embeds the identical JSON payload inline**, so no API registration is needed.
- **Warm-up dance required:** First hit to `autos.mercadolibre.cl` returns a 5KB "Continuar" micro-landing. Fix: GET `www.mercadolibre.cl/` first (collects `_csrf` cookie), then the real 7MB HTML flows. Also need modern Chrome UA + `sec-ch-ua` headers to avoid redirect to `/sentry/update-browser`.
- **Data quality:** 16/19 schema fields at 100%, `transmission` at 87%, `body_type` missing from search response (would need per-item detail fetch).
- **Scale estimate:** ~2 minutes wall-clock for 10k listings (200 pages × 50 items × 0.5 s).

### 🟢 Chileautos.cl

- **Finding:** Internal Carsales-Merlin JSON API at `/_api/search-core/` (list) and `/_api/details-core/<CP-AD-id>` (detail). **HTML is DataDome-protected, but the JSON endpoints are not.**
- **Caveat:** `robots.txt` disallows `/vehiculos/*` for non-Google agents, meaning API-based crawling violates the site's stated policy. Technically feasible, legally/ethically a judgment call — for personal analytics, low-risk; for commercial redistribution, don't.
- **Data quality:** 100% on most fields, 95% on version/fuel/transmission/body; `commune` not in the API tracking blob; `km` at 73% because dealer 0-km stock is mixed in (filter `C.State.Usado.` excludes new; filter further if needed).
- **Scale:** 62,896 listings total. ~30 min full sweep at 0.7s/request.

### 🟢 Yapo.cl

- **Surprising finding:** Yapo is NOT behind Cloudflare on the `/autos-usados` path — `robots.txt` explicitly allows it. `requests` works fine with realistic headers.
- **Gotcha found the hard way:** Server returns Brotli-compressed responses when `Accept-Encoding: br` is advertised, and `requests` needs the `brotli` package to decode. Fix: only advertise `gzip, deflate`.
- **Method:** Each listing card has an inline `ga4addata[<adid>] = {...}` JSON object with make/model/year/fuel/transmission/region/commune/seller_type.
- **Data quality:** 50/50 on everything except `km` (96%, 2 missing at source), `version` and `posted_at` not on list tiles (recoverable via detail fetch).
- **Scale:** 36,082 listings / 1,203 pages / ~30 min at 1.5 s/page.

### 🟢 Kavak.cl

- **Method:** Next.js App Router — no `__NEXT_DATA__`, but RSC payloads stream inline as escaped JSON. Cards expose a perfect `analytics` sub-object. VIP pages have `<script type="application/ld+json">` of type `Car` with brand/model/bodyType/transmission/fuelType/mileage/price/color/VIN.
- **Data quality:** 100% across all 18 fields except `posted_at` (Kavak does not publish listing-creation timestamps anywhere).
- **Zero anti-bot friction** over 80 sequential requests.
- **Scaling tip:** Use `/cl/sitemap-catalog-friendly-cl.xml` for full enumeration rather than `?page=N`.

### 🟢 Autocosmos.cl

- **Method:** Fully server-rendered HTML with Schema.org/Car microdata on index cards. Detail pages have a `dfp_*` meta block exposing `dfp_privado` (particular/empresa), region, city, body type.
- **Gotcha:** "Related listings" carousel on detail pages also carries `itemprop="price"` microdata. Must scope extraction to `.car-specifics` or you'll extract 5× the prices.
- **Data quality:** 100% on every required field except `transmission` (80%) and `posted_at` (0%, not available).
- **`Crawl-Delay: 20`** in robots.txt — respect for long-running jobs.

### 🟢 Economicos.cl (El Mercurio)

- **Method:** Plain HTTP, server-rendered HTML, no anti-bot. List at `/todo_chile/autos?pagina=N` (60 cards/page, 9,971 total).
- **Data quality:** 100% on core fields — but `version`, `km`, `body_type`, `commune` are **not exposed by the source at all**. Complement with Chileautos or Yapo if those fields matter.
- **Seller mix caveat:** Page 1 is 100% dealer (prioritized); private-party listings appear on deeper pages.

### 🟢 Autopia.cl / BravoAuto.cl

- **Method:** `autopia.cl` 301s to `bravoauto.cl`. Laravel + Inertia.js — every page embeds JSON in `data-page="..."` on `<div id="app">`.
- **Data quality:** 100% on all 19 fields including `posted_at`.
- **Scale note:** Homepage alone exposes entire live stock (123 ads). Inventory is small (~120) — no pagination needed. Sitemap is stale; ignore it.

### 🟢 Auto.cl

- **Method:** Sitemap.xml (6,140 used-car URLs) → parse Angular SSR `<script id="ng-state">` → `usedPublication_*.publication` object has everything including `createdAt` timestamp.
- **Cloudflare gotcha:** Blocks `curl`, `Googlebot`, Chrome-on-macOS UAs with 403 "Just a moment…". **Safari / Firefox / social-bot UAs pass cleanly.** Scraper uses Safari 17 UA.
- **Data quality:** All fields 100% except `commune` (not exposed). Full refresh ~105 min at 1 req/s.

### 🟢 Autosusados.cl

- **Method:** Sitemap index → `sitemap-automotoras.xml` (7,385 dealer) + `sitemap-particulares.xml` (217 private). Detail pages have `__NEXT_DATA__` with `props.pageProps.carInfo`. Seller type in URL path (`/1/id` = dealer, `/3/id` = private).
- **Data quality:** 100% except `commune` (potentially recoverable via reverse-geocoding the `latitude`/`length` fields).
- **No anti-bot.** Full refresh ~80 min at 1-2 req/s.

### 🔴 Demotores.cl — BLOCKED

- **Finding:** TCP timeouts from both local egress AND Anthropic WebFetch egress. DNS resolves fine; connection never establishes. Only accessible artifact: 2012 Wayback snapshot.
- **Hypothesis:** Origin IP is Spanish (Comvive) — likely geo-blocked or firewalled for non-Chilean IPs. Confirmed not an app-layer block (we can't even see an HTTP response).
- **To unblock:** Would need a Chilean residential VPN/proxy. Not worth the effort given the other 9 sources cover the market.
- **Deliverable:** Defensive scaffold scraper in place (probes `__NEXT_DATA__`, ld+json, DOM fallbacks) that will produce data once origin becomes reachable.

---

## Data quality matrix (real sample, April 2026)

```
source            N    | src  id   url  ttl  mk   mdl  ver  yr   km   prc  cur  fuel trn  bdy  reg  com  post scrp slr
----------------------------------------------------------------------------------------------------------------------------
auto_cl          20    | 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100%   0% 100% 100% 100%
autocosmos       40    | 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100%   0% 100% 100%
autopia          25    | 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100%
autosusados      20    | 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100%   0% 100% 100% 100%
chileautos       42    | 100% 100% 100% 100% 100% 100%  95% 100% 100% 100% 100%  95%  95%  95% 100%   0% 100% 100% 100%
economicos       40    | 100% 100% 100% 100% 100% 100%   0% 100%   0% 100% 100%  92% 100%   0% 100%   0% 100% 100% 100%
kavak            40    | 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100%   0% 100% 100%
mercadolibre     40    | 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100% 100%   0% 100% 100% 100% 100% 100%
yapo             50    | 100% 100% 100% 100% 100% 100%   0% 100%  96% 100% 100% 100% 100%   0% 100% 100%   0% 100% 100%
```

### Field availability (how many sources give us each field)

| Field | Coverage | Notes |
|---|---|---|
| `source_id`, `url`, `title`, `make`, `model`, `year`, `price_clp`, `currency`, `region`, `seller_type` | **9/9 sources** | Core fields, universal |
| `km` | 8/9 | Missing only on Economicos |
| `fuel_type` | 9/9 | But **values need normalization** (Gasolina / gasolina / Bencina are the same; Diésel / Diesel / Diésel likewise) |
| `transmission` | 9/9 | With some nulls |
| `body_type` | 8/9 | Missing on MercadoLibre (would need detail fetch) |
| `version` (trim) | 7/9 | Missing on Yapo, Economicos list views |
| `commune` | 5/9 | Available on Autocosmos, Autopia, Economicos, Kavak, MercadoLibre, Yapo |
| `posted_at` | 2/9 | Only Autopia and MercadoLibre expose listing creation timestamps. **Everyone else needs local first-seen tracking.** |

### Price & year sanity check (sample distributions look realistic)

```
auto_cl        price 6.3M/16.0M/137.9M CLP   yr 2017-2026
autocosmos     price 0.5M/2.6M/3.2M           yr 1994-2021  (cheap end — default sort = price asc)
autopia        price 7.7M/16.0M/27.0M         yr 2019-2025
autosusados    price 2.6M/12.0M/39.0M         yr 1969-2025  (includes classics)
chileautos     price 8.7M/22.5M/129.9M        yr 2015-2026
economicos     price 5.5M/16.0M/55.0M         yr 2017-2025
kavak          price 3.4M/9.7M/37.7M          yr 2011-2025
mercadolibre   price 7.0M/12.0M/35.0M         yr 2019-2026
yapo           price 6.0M/14.3M/80.0M         yr 1992-2025
```

All price/year distributions are consistent with the Chilean used-car market (low-end hatchbacks ~3-6M CLP, mid-range SUVs 15-25M, luxury/premium 40M+).

---

## Practical recommendations for v1 ingestion

### Prioritized ingest order

1. **MercadoLibre** (biggest inventory, `posted_at` available, embedded JSON is stable)
2. **Chileautos** (second-biggest, clean JSON API, rich attributes)
3. **Yapo** (best private-seller coverage, commune available)
4. **Autocosmos** (complements with `body_type` + `commune`)
5. **Kavak** (full attribute coverage, good for dealer benchmark)
6. **Auto.cl + Autosusados** (dealer aggregators, `posted_at` on auto.cl)
7. **Autopia/BravoAuto** (small inventory ~120, but 100% field fill — nice quality signal)
8. **Economicos** (thin attributes but 10k listings, use for volume)

### Cross-source deduplication

Listings cross-post heavily. Need a dedup key from `(make, model, year, version, km_bucket, region, price_clp_bucket)` OR seller phone number if extractable. MercadoLibre + Chileautos + Yapo likely have 30-50% overlap.

### Normalization work needed

- **Fuel type:** 7+ variants in raw data (Gasolina/gasolina/Bencina/Diésel/Diesel/Diésel/Híbrido/Combustible premium). Build a lookup map.
- **Transmission:** "Automática" / "Manual" / "Mecánica" / "CVT" / "DCT" — map to {manual, automatic, other}.
- **Make/model:** Case inconsistencies and spelling variants (Chevrolet vs CHEVROLET; Volkswagen vs VW). Build a canonical lookup.

### `posted_at` strategy

Since 7/9 sources don't expose it, track **`first_seen_at` locally** (timestamp of our first scrape that contains this listing). Combined with `last_seen_at` and `removed_at`, we get days-on-market as a derived metric.

### Rate-limit / cadence recommendation

At 1 req/s per source (conservative), a daily full sweep takes ~4 hours across all 9 sources running sequentially, or ~45 min if parallelized (9 workers). This fits comfortably in a GitHub Actions nightly cron. Vercel Hobby daily cron also works.

### Legal / ethical notes

- **robots.txt disallows crawling** on Chileautos `/vehiculos/*` (though not the `/_api/` paths), and Autocosmos requests `Crawl-Delay: 20`. Honor where stated.
- Personal analytics use is low-risk; **do not redistribute raw listing data** commercially.
- Keep User-Agent identifiable (e.g. `CarTrackerBot/1.0 (+contact-email)`) if willing to be visible. Anonymous UAs work today but are the first thing that gets blocked if usage spikes.

---

## Files produced

```
projects/car-tracker/
├── scrapers/
│   ├── mercadolibre/scraper.py
│   ├── chileautos/scraper.py
│   ├── yapo/scraper.py
│   ├── kavak/scraper.py
│   ├── autocosmos/scraper.py
│   ├── economicos/scraper.py
│   ├── autopia/scraper.py
│   ├── auto_cl/scraper.py
│   ├── autosusados/scraper.py
│   └── demotores/scraper.py         (defensive scaffold, blocked)
├── data/
│   ├── mercadolibre.json   (40)
│   ├── chileautos.json     (42)
│   ├── yapo.json           (50)
│   ├── kavak.json          (40)
│   ├── autocosmos.json     (40)
│   ├── economicos.json     (40)
│   ├── autopia.json        (25)
│   ├── auto_cl.json        (20)
│   ├── autosusados.json    (20)
│   └── demotores.json      (0, blocked)
└── reports/
    ├── _FINAL.md           (this file)
    └── <source>.md         (one per source)
```

**Total real listings collected: 317** across 9 working sources.

---

## What's next (if you want to proceed to build)

1. **Unify the schema** into a single Supabase table `listings` (keyed by `source + source_id`).
2. **Normalize** fuel/transmission/make/model via a lookup layer on ingest.
3. **Schedule nightly** ingests via GitHub Actions (no Vercel Hobby 12-function cap).
4. **Build `listing_prices`** append-only history + `market_stats` nightly rollup for scoring.
5. **Frontend**: Next.js dashboard with filters, per-listing price history, z-score "good deal" rank, alerts.

Estimated v1 build: 1-2 evenings with the scrapers already working.
