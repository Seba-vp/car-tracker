# car-tracker — Chilean used-car market tracker

Daily scrape of 9 Chilean used-car marketplaces → Supabase → (future) dashboard with
price trends, fuel-type premiums, deal-scoring, and price-drop alerts.

See `reports/_FINAL.md` for the feasibility study that chose the 9 sources.

## Status

- **Data retrieval:** ✅ 10 scrapers written, 9 confirmed working (Demotores geo-blocked).
- **Ingest pipeline:** ✅ unified `ingest.py` normalizes + upserts to Supabase.
- **Automation:** ✅ GitHub Actions daily cron at 07:00 UTC (03:00 Santiago).
- **Dashboard:** ⏳ not started.

## Layout

```
car-tracker/
├── ingest.py                 ← main entry: run scraper + normalize + upsert
├── finalize.py               ← post-sweep: mark stale listings removed
├── requirements.txt
├── shared/
│   ├── normalize.py          ← fuel / transmission / seller / body canonicalizers
│   └── db.py                 ← Supabase PostgREST client
├── sql/
│   └── schema.sql            ← listings, listing_prices, market_stats, scrape_runs
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
│   └── demotores/scraper.py  ← blocked (geo), scaffold only
├── data/                     ← .gitignored; each scraper writes <slug>.json
├── reports/
│   ├── _FINAL.md             ← feasibility master report
│   └── <source>.md           ← per-source report
└── .github/workflows/
    └── scrape.yml
```

## One-time setup (after creating the new Supabase project)

```bash
# 1. Pin commit email (personal GitHub matches Vercel)
git init && git config user.email ssebavillablanca@gmail.com

# 2. Create Supabase project "chile-cars" in sa-east-1
#    Copy ref + service_role key to local .env (use .env.example as template)

# 3. Apply schema
cd ~/Desktop/seba-core
./scripts/supabase-sql.sh <ref> "$(cat projects/car-tracker/sql/schema.sql)"

# 4. Push to GitHub (new repo Seba-vp/car-tracker)

# 5. Add GitHub secrets (Settings → Secrets → Actions):
#    - SUPABASE_URL = https://<ref>.supabase.co
#    - SUPABASE_SERVICE_ROLE_KEY = ey...

# 6. Manually trigger first run (Actions → Daily Chile Car Scrape → Run workflow)
```

## Running locally

```bash
pip install -r requirements.txt

# One source, dry run (no DB writes, uses existing data/<source>.json)
python ingest.py --source yapo --no-upload --file data/yapo.json

# One source, full pipeline (re-scrapes, uploads)
export SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=...
python ingest.py --source yapo

# Nightly finalize (mark stale removed, print per-source counts)
python finalize.py
```

## Data model highlights

- **listings** — one row per `(source, source_id)`, upserted daily. `last_seen_at` ticks every scrape; `removed_at` set by `finalize.py` when a listing is missing for `STALE_DAYS` (default 3).
- **listing_prices** — append-only price history. Every ingest appends one row per observed listing regardless of whether price changed. For deal-scoring, query the latest per listing_id.
- **market_stats** — nightly rollup per `(make, model, year, km_bucket, fuel_type)` with median/p25/p75. Not yet built — aggregation job goes in a future workflow step.
- **scrape_runs** — one row per source per day with counts and status. Easy health check.

## Scraping principles (to stay cautious)

- **1 req/s per source** (some scrapers go faster; tune down if blocked).
- **Sequential sources** via `max-parallel: 3` in GH matrix — no more than 3 sources hit at once from GH's IP.
- **Idempotent**: upsert-by-`(source, source_id)` means re-running is safe.
- **Per-source isolation**: matrix has `fail-fast: false` so one blocked source doesn't kill the sweep.
- **Real User-Agents**: each scraper uses a modern browser UA appropriate for its target (Safari 17 for auto.cl's Cloudflare, Chrome 138 for MercadoLibre's sec-ch-ua checks).

## Known anti-bot behavior per source

| Source | Anti-bot | Current workaround |
|---|---|---|
| auto.cl | Cloudflare blocks Chrome-on-macOS UA | Safari 17 UA |
| chileautos | DataDome on `/vehiculos/*` HTML | Use `/_api/*` JSON endpoints |
| mercadolibre | `_csrf` cookie required on first subdomain hit | 2-step warm-up |
| yapo | Brotli-compressed responses | Don't advertise `Accept-Encoding: br` |
| autocosmos | `Crawl-Delay: 20` in robots.txt | Respected in scraper |
| demotores | TCP-level geo-block (non-CL IPs) | None; skipped |

If a source starts returning 403/429 in production, the fallback toolkit is:
1. Add `curl_cffi` (TLS-fingerprint browser impersonation) — no IP rotation needed
2. Rotate across 3-4 browser UAs per daily run
3. Last resort: Playwright with a GH-hosted self-runner

## Scaling targets

Current scrapers cap at 20-50 listings per source (sample size for feasibility).
Each has a configurable `target` parameter internally — edit the scraper's CLI
invocation or default to increase. Full-inventory estimates:

| Source | Full inventory | Time @ 1 req/s |
|---|---|---|
| chileautos | ~63k | ~18h (split into pages, use pagination) |
| mercadolibre | large | ~2 min for 10k (embedded JSON, no detail fetches needed) |
| yapo | ~36k | ~30 min (list-tile data is enough, skip detail fetches) |
| autocosmos | large | long (crawl-delay 20s) |
| economicos | ~10k | ~2.5h (one detail fetch per listing) |
| auto.cl | ~6k | ~105 min |
| autosusados | ~7.6k | ~80 min |
| kavak | ~1-3k | ~30 min |
| autopia | ~120 | ~1 min |

GitHub Actions free tier (2,000 min/mo private) handles this easily once scaled up.
Public repo = unlimited minutes.

## Secrets (GitHub Actions)

- `SUPABASE_URL` — `https://<ref>.supabase.co`
- `SUPABASE_SERVICE_ROLE_KEY` — service_role JWT (bypasses RLS for server writes)
