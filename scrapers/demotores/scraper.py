#!/usr/bin/env python3
"""
Demotores.cl scraper — CURRENTLY BLOCKED.

Connectivity note (as of 2026-04-23):
- DNS for www.demotores.cl resolves to 5.22.145.{16,121} (Comvive Spain).
- TCP connects to :443 time out from both this environment's egress and
  Anthropic's WebFetch egress (tested multiple times, >20s timeouts).
- The only archive.org snapshot is from 2012, so we cannot reconstruct
  the current DOM from the Wayback Machine either.
- Most likely cause: the origin firewalls non-Chilean residential/ISP
  traffic, or the host is down entirely for our IP ranges.

This script is written defensively so it can start producing data the
moment the origin becomes reachable again (e.g. from a Chilean-residential
egress, a VPN, or a proxy service like ScraperAPI / Zyte / Bright Data).

Expected strategy (based on typical Chilean classifieds + quick DNS probe):
1) GET /robots.txt and /sitemap.xml to enumerate listing URLs.
2) If the homepage is a Next.js app, look for the `__NEXT_DATA__` <script>
   blob and extract `pageProps` or `apolloState`.
3) Otherwise fall back to ld+json on detail pages (Product / Vehicle) and
   to DOM scraping of visible fields (precio, km, año, combustible).

The parsing code is a scaffold — adjust selectors after a successful fetch.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup

SOURCE_SLUG = "demotores"
BASE = "https://www.demotores.cl"
CANDIDATE_INDEX_PATHS = [
    "/autos-usados",
    "/vehiculos/usados",
    "/autos/usados",
    "/",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": f"{BASE}/",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Upgrade-Insecure-Requests": "1",
}


def log(msg: str) -> None:
    print(f"[demotores] {msg}", file=sys.stderr, flush=True)


def fetch(session: requests.Session, url: str, timeout: int = 25) -> Optional[str]:
    try:
        r = session.get(url, timeout=timeout)
        log(f"GET {url} -> {r.status_code} ({len(r.content)} bytes)")
        if r.status_code == 200:
            return r.text
    except requests.RequestException as exc:
        log(f"GET {url} -> ERROR {exc}")
    return None


def check_reachable(session: requests.Session) -> bool:
    """Quick liveness probe. Returns False if we cannot reach the origin."""
    try:
        r = session.get(f"{BASE}/robots.txt", timeout=12)
        return r.status_code < 500
    except requests.RequestException as exc:
        log(f"reachability probe failed: {exc}")
        return False


def discover_listing_urls(session: requests.Session) -> list[str]:
    # 1) sitemap(s)
    for sm_path in ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-autos.xml"):
        xml = fetch(session, BASE + sm_path)
        if xml and "<loc>" in xml:
            urls = re.findall(r"<loc>([^<]+)</loc>", xml)
            # Heuristic: keep URLs that look like detail pages
            detail = [u for u in urls if re.search(r"/(auto|vehiculo)s?-?usad|/ficha|/\d{5,}", u)]
            if detail:
                log(f"sitemap {sm_path} -> {len(detail)} detail-ish URLs")
                return detail
    # 2) fallback: crawl index
    for path in CANDIDATE_INDEX_PATHS:
        html = fetch(session, BASE + path)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        anchors = soup.select("a[href]")
        hrefs = {a["href"] for a in anchors if a.has_attr("href")}
        detail = [
            h if h.startswith("http") else BASE + h
            for h in hrefs
            if re.search(r"/(auto|vehiculo)s?-?usad|/ficha|/\d{5,}", h)
        ]
        if detail:
            log(f"index {path} -> {len(detail)} candidate detail URLs")
            return sorted(set(detail))
    return []


def extract_next_data(html: str) -> Optional[dict[str, Any]]:
    m = re.search(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html,
        flags=re.S,
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def extract_ld_json(html: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in re.finditer(
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
        html,
        flags=re.S,
    ):
        try:
            obj = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(obj, list):
            out.extend(x for x in obj if isinstance(x, dict))
        elif isinstance(obj, dict):
            out.append(obj)
    return out


def parse_detail(url: str, html: str) -> Optional[dict[str, Any]]:
    """Best-effort parser. Prioritises __NEXT_DATA__, then ld+json, then DOM."""
    nd = extract_next_data(html)
    rec: dict[str, Any] = {
        "source": SOURCE_SLUG,
        "source_id": None,
        "url": url,
        "title": None,
        "make": None,
        "model": None,
        "version": None,
        "year": None,
        "km": None,
        "price_clp": None,
        "currency": "CLP",
        "fuel_type": None,
        "transmission": None,
        "body_type": None,
        "region": None,
        "commune": None,
        "posted_at": None,
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seller_type": "dealer",
    }

    if nd:
        # Probe common shapes; will need tuning once we see a real response.
        props = (nd.get("props") or {}).get("pageProps") or {}
        vehicle = (
            props.get("vehicle")
            or props.get("ad")
            or props.get("listing")
            or props.get("publication")
            or {}
        )
        if isinstance(vehicle, dict) and vehicle:
            rec["source_id"] = str(vehicle.get("id") or vehicle.get("slug") or "") or None
            rec["title"] = vehicle.get("title") or vehicle.get("name")
            rec["make"] = vehicle.get("brand") or (vehicle.get("make") or {}).get("name")
            rec["model"] = vehicle.get("model") if isinstance(vehicle.get("model"), str) \
                else (vehicle.get("model") or {}).get("name")
            rec["version"] = vehicle.get("version") or vehicle.get("trim")
            rec["year"] = vehicle.get("year")
            rec["km"] = vehicle.get("km") or vehicle.get("mileage") or vehicle.get("kilometers")
            rec["price_clp"] = vehicle.get("price") or vehicle.get("priceCLP")
            rec["fuel_type"] = vehicle.get("fuel") or vehicle.get("fuelType")
            rec["transmission"] = vehicle.get("transmission")
            rec["body_type"] = vehicle.get("bodyType") or vehicle.get("body")
            rec["region"] = vehicle.get("region") or (vehicle.get("location") or {}).get("region")
            rec["commune"] = vehicle.get("commune") or (vehicle.get("location") or {}).get("commune")
            rec["posted_at"] = vehicle.get("publishedAt") or vehicle.get("createdAt")
            return rec

    for obj in extract_ld_json(html):
        tp = obj.get("@type")
        if tp in ("Vehicle", "Car", "Product"):
            rec["title"] = obj.get("name") or rec["title"]
            rec["make"] = (obj.get("brand") or {}).get("name") if isinstance(obj.get("brand"), dict) else obj.get("brand")
            rec["model"] = obj.get("model")
            rec["year"] = obj.get("vehicleModelDate") or obj.get("productionDate")
            rec["km"] = (obj.get("mileageFromOdometer") or {}).get("value") if isinstance(obj.get("mileageFromOdometer"), dict) else obj.get("mileageFromOdometer")
            offers = obj.get("offers") or {}
            if isinstance(offers, dict):
                rec["price_clp"] = offers.get("price") or rec["price_clp"]
                rec["currency"] = offers.get("priceCurrency") or rec["currency"]
            rec["fuel_type"] = obj.get("fuelType") or rec["fuel_type"]
            rec["transmission"] = obj.get("vehicleTransmission") or rec["transmission"]
            rec["body_type"] = obj.get("bodyType") or rec["body_type"]
            break

    # ID fallback from URL
    if not rec["source_id"]:
        m = re.search(r"/(\d{4,})(?:/?$|[/?#])", url)
        if m:
            rec["source_id"] = m.group(1)
    return rec


def scrape(limit: int = 25, delay: float = 0.7) -> list[dict[str, Any]]:
    session = requests.Session()
    session.headers.update(HEADERS)

    if not check_reachable(session):
        log(
            "origin unreachable — aborting. See module docstring for context. "
            "Retry from a Chilean egress or via a residential proxy."
        )
        return []

    urls = discover_listing_urls(session)
    if not urls:
        log("no listing URLs discovered")
        return []

    records: list[dict[str, Any]] = []
    n = min(limit, len(urls))
    for i, url in enumerate(urls[:n], 1):
        log(f"[{i}/{n}] {url}")
        html = fetch(session, url)
        if html:
            rec = parse_detail(url, html)
            if rec:
                records.append(rec)
        time.sleep(delay)

    log(f"parsed {len(records)} records")
    return records


def main() -> int:
    out_path = sys.argv[1] if len(sys.argv) > 1 else "data/demotores.json"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 25
    records = scrape(limit=limit)
    from pathlib import Path as _P
    _P(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(records, fh, ensure_ascii=False, indent=2)
    log(f"wrote {len(records)} records -> {out_path}")
    return 0 if records else 2  # exit 2 = blocked, not a bug


if __name__ == "__main__":
    sys.exit(main())
