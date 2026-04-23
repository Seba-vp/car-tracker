# Demotores.cl — Scraping feasibility

- **Feasibility: BLOCKED** (for this environment)
- **Source slug**: `demotores`
- **Date of investigation**: 2026-04-23

## What happened

From this investigation's network egress (and also from Anthropic's
WebFetch egress, which is a separate cloud IP range), every connection
to `www.demotores.cl` timed out at the TCP layer:

- DNS resolved fine:
  `www.demotores.cl` → `5.22.145.16`, `5.22.145.121`, plus IPv6
  `2a00:18e0:5:2:…`, `2a00:18e0:5:3:…` (Google Public DNS over HTTPS).
- `nc -zv 5.22.145.121 443` and `nc -zv 5.22.145.16 443` both failed
  with "Operation timed out".
- `curl --max-time 20 https://www.demotores.cl/` → exit 28
  (connect timeout), IPv4 and IPv6.
- WebFetch (Anthropic's own egress) returned "timeout of 60000ms
  exceeded" for `/`, `/robots.txt` and `/vehiculos/usados`.
- `robots.txt` body came back empty on one opportunistic retry.
- `archive.org/wayback` has no recent snapshot — the only closest
  capture is from 2012.

The IP range `5.22.145.0/24` belongs to **Comvive Servidores / Spain**.
The most plausible explanations are:

1. The origin firewalls non-Chilean IP ranges at the edge, or
2. It drops all non-residential traffic, or
3. It is transiently down for the specific networks I can reach from.

I could not distinguish between these three without access to a
Chilean-residential egress, a VPN, or a managed-proxy service. In every
case the net effect from here is the same: no HTTP response of any
kind, ever.

## Method attempted

- Direct `requests.get` with realistic UA, Accept-Language, Sec-Fetch-*
  headers, and `Referer` set to the origin.
- Curl with the same headers, both IPv4 and IPv6, with and without
  `www.` prefix.
- Anthropic WebFetch (different cloud egress).
- DoH (Google) for DNS sanity.
- Wayback Machine (no usable snapshot).

## Anti-bot encountered

Unknown — connection never completes, so we never saw a body. There is
no evidence either way about Cloudflare / DataDome / PerimeterX. The
IP-level block (or outage) precedes any app-layer challenge we could
fingerprint.

## Sample count retrieved

**0 listings.** `data/demotores.json` contains an empty array. No
synthetic or fabricated rows were written.

## Data quality per field

N/A — no data.

## Rate limit observed

N/A — zero successful requests.

## Scaling recommendation

Not feasible from a non-Chilean cloud egress as things stand. To unblock
the work, in decreasing order of effort:

1. **Cheapest first**: try again from a Chilean residential connection
   (mobile hotspot, friend's home IP) to confirm whether the block is
   geo/IP-based or a real outage. A one-off `curl -I` is enough.
2. If geo-blocked, route through a Chilean **residential proxy**
   (Bright Data / Oxylabs / Smartproxy offer CL pools). Cost is ~$2-5
   per GB but traffic is low; probably <$1/day for ~100 listings.
3. Or a **datacenter proxy in Chile** (cheaper) — if the origin only
   filters foreign *countries* rather than foreign *hosting ASNs*.
4. As a last resort, consider a headless browser in a CL-based cloud
   region (GCP `southamerica-west1`, AWS `sa-east-1`).

The scraper at `scrapers/demotores/scraper.py` is a defensive scaffold:
it first probes `robots.txt`, aborts cleanly if unreachable, and has
fallback parsers for `__NEXT_DATA__`, `ld+json`, and DOM scraping.
It will start producing data the moment the origin becomes reachable,
with selector tuning based on whatever shape the response turns out to
have.
