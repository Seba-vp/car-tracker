# Autopia.cl (BravoAuto) — Scraping feasibility

- **Feasibility: HIGH**
- **Source slug**: `autopia`
- **Date of investigation**: 2026-04-23

## Method used

`autopia.cl` 301-redirects to `www.bravoauto.cl`, a Laravel + Inertia.js
stack. Every page server-renders the full view model into a single
`data-page="..."` attribute on `<div id="app">` — HTML-entity-encoded
JSON, no separate API call required.

Flow used by the scraper:

1. `GET /` once — the homepage's `Home` component exposes
   `props.data.ads[]` with the entire live stock (123 ads on inspection)
   and includes `publicationDate`, `price`, `brand/model/version`,
   `mileage`, `fuelType`, `transmissionType`, `bodyType`, `year`,
   `sellerName`, `carId`, `category`.
2. Sort ads by `publicationDate DESC` (fresh first).
3. Reconstruct each detail URL from ad fields (brand/model/category/year
   slugified + `transmision-{automatica|mecanica}` + carId). Verified
   against 98 sitemap URLs.
4. `GET` each detail page to collect the extras the listing omits:
   `regionID` (Chilean region 1–16) and `clientName` (dealership branch
   ≈ commune).
5. Parse into schema and write JSON.

Sitemap exists at `/sitemap_autos.xml` (98 URLs) but its `lastmod` is
months old and only overlaps the live homepage by 3 cars — it is kept
as a cross-check, not the primary seed.

## Anti-bot encountered

None. No Cloudflare / DataDome / PerimeterX. No CAPTCHA wall on listing
pages. Each response sets an `XSRF-TOKEN` / `bravoauto_session` cookie
but neither is required for GETs. User-Agent/Accept-Language were set
to realistic values, but even the default `python-requests/*` UA is
likely to work. There is a reCAPTCHA key embedded in `recaptcha_site_key`
but it only protects the quote form, not the read-only content.

## Sample count retrieved

**25 / 25** listings parsed successfully.

## Data quality per field (25/25 = 100%)

| Field | Fill | Notes |
|---|---|---|
| source, source_id, url, title | 25/25 | |
| make, model, version, year | 25/25 | |
| km, price_clp, currency | 25/25 | Currency normalised `$` → `CLP` |
| fuel_type, transmission, body_type | 25/25 | Spanish strings (`Gasolina`, `Transmisión Automática`, `SUV`) |
| region | 25/25 | Mapped from `regionID` (Chile INE codes 1-16) |
| commune | 25/25 | Inferred from `clientName` by stripping the `Bravoauto ` prefix. Caveat: some branches are named after shopping malls (`Movicenter`) rather than communes — downstream code should treat this as "branch location" rather than strict INE commune. |
| posted_at | 25/25 | ISO-8601 from ad `publicationDate` (assumed CL local, no tz applied) |
| scraped_at | 25/25 | UTC ISO-8601 |
| seller_type | 25/25 | Hardcoded `dealer` (BravoAuto is an all-dealer network) |

Sample (truncated):

```json
{
  "source": "autopia",
  "source_id": "1228962",
  "title": "CHANGAN UNI-T 1.5 ELITE AT 2024",
  "make": "CHANGAN", "model": "UNI-T", "version": "1.5 ELITE AT",
  "year": 2024, "km": 32367, "price_clp": 15590000, "currency": "CLP",
  "fuel_type": "Gasolina", "transmission": "Transmisión Automática",
  "body_type": "SUV", "region": "Metropolitana de Santiago",
  "commune": "Movicenter", "posted_at": "2025-05-26T16:32:39",
  "seller_type": "dealer"
}
```

## Rate limit observed

At 0.7 s inter-request delay, 25 sequential detail fetches plus two
seed GETs completed in ~48 s with zero non-200 responses and no
throttling. The site sits behind CloudFront but returned `x-cache: Miss`
for each unique URL without a challenge.

## Scaling recommendation

Full live stock is ~120 cars per snapshot — trivial at any reasonable
politeness. Recommended:

- **Delay**: 0.5–1.0 s is plenty. No need for rotating proxies.
- **Schedule**: daily, ~1 min wall-clock. Cron-friendly on Vercel Hobby.
- **Dedupe key**: `carId` is a stable integer.
- **Change detection**: compare `publicationDate` + `price` per carId.
- **Incremental approach**: parse the homepage once, diff the set of
  `carId` values against what's stored; only re-fetch details for new
  IDs. The homepage alone fills every schema field except `region`
  and `commune`, so 99% of runs would need zero detail GETs.
- **Resilience**: if the Inertia version string bumps, parsing still
  works because we read `data-page` regardless of version. The main
  brittle point is URL reconstruction — falling back to the homepage's
  shape for data extraction would still succeed even if URL shape
  changes.
