# Kavak Chile — scraping feasibility

## Feasibility

**Easy.** Plain `requests` + `beautifulsoup4`. No JS execution, auth, or
proxies needed. All 40 test listings came back fully populated in one pass.

## Method

Kavak is Next.js App-Router, so there's no `__NEXT_DATA__`, but:

1. **List pages** (`/cl/usados?page=N`) stream React Server Component
   payloads inline as escaped JSON. Each card exposes an `analytics`
   sub-object with `car_make`, `car_model`, `car_year`, `car_price`,
   `car_id`, `car_location`, `seller_type`, plus `title`, `subtitle`
   (year / km / version / transmission), `mainPrice`, and `footerInfo`
   (region). A regex anchored on `"id":"<digits>","url":".../cl/venta/..."`
   yields 30 stubs/page cleanly.
2. **VIP pages** (`/cl/venta/{slug}`) embed a proper
   `<script type="application/ld+json">` of type `Car` with `brand`,
   `model`, `bodyType`, `vehicleTransmission`, `vehicleEngine.fuelType`,
   `mileageFromOdometer`, `offers.price` (CLP int), color, and VIN. The
   same HTML carries the hub address, from which commune is extracted.
3. `body_type` is also the penultimate URL slug token — used as fallback.

## Anti-bot

None observed over 80 sequential requests (2 list + 40 VIPs). No
Cloudflare, captcha, or rate-limit headers. `robots.txt` blocks only two
internal `/v1/widgets/supply/*` widgets; `/cl/usados` and `/cl/venta/*`
are fair game. Public sitemap at
`https://www.kavak.com/cl/sitemap-catalog-friendly-cl.xml`.

## Sample count

**40 listings** in `data/kavak.json`.

## Data quality

18 of 19 schema fields populated on all 40 rows. `posted_at` is always
null — Kavak doesn't publish a listing-creation timestamp anywhere. All
rows are `seller_type: "dealer"`, currency `CLP`. Price range 3.41M –
37.73M, years 2011–2025, 20 distinct makes, 3 communes, fuel types
Gasolina / Diesel / Combustible premium.

## Rate limit

0.5–1.0 s jitter, 80 requests in ~80 s, zero errors.

## Scaling recommendation

- Enumerate inventory via the catalog sitemap (`/cl/sitemap-catalog-friendly-cl.xml`)
  rather than `?page=N` — Next.js pagination often caps silently.
- Daily refresh via list-page regex (cheap, price/km deltas); fetch VIP
  only for new `source_id`s.
- Use Kavak's numeric `source_id` as primary key (stable across
  slug changes).
- 0.5–1 s delay + rotating desktop UA is sufficient at this volume; no
  proxy needed. Revisit if Cloudflare appears.
