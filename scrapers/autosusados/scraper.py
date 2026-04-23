#!/usr/bin/env python3
"""
autosusados.cl scraper.

Method:
  1. Fetch sitemap index, pull per-category sub-sitemaps.
  2. Sample listing URLs (mix of automotoras + particulares).
  3. GET each detail page, extract __NEXT_DATA__ (Next.js) and ld+json.
  4. Normalize into the common listing schema.

Output: JSON array on stdout. Progress on stderr.
"""
from __future__ import annotations

import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any

import requests
from bs4 import BeautifulSoup

SOURCE_SLUG = "autosusados"
BASE = "https://autosusados.cl"
SITEMAP_INDEX = f"{BASE}/sitemap.xml"
SUB_SITEMAPS = [
    f"{BASE}/sitemaps/sitemap-automotoras.xml",
    f"{BASE}/sitemaps/sitemap-particulares.xml",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Chile official region codes (1..16). Used for carInfo.regionID -> region name.
REGION_BY_ID: dict[int, str] = {
    1: "Tarapacá",
    2: "Antofagasta",
    3: "Atacama",
    4: "Coquimbo",
    5: "Valparaíso",
    6: "O'Higgins",
    7: "Maule",
    8: "Biobío",
    9: "Araucanía",
    10: "Los Lagos",
    11: "Aysén",
    12: "Magallanes",
    13: "Metropolitana de Santiago",
    14: "Los Ríos",
    15: "Arica y Parinacota",
    16: "Ñuble",
}

BODY_BY_CATEGORY_SLUG: dict[str, str] = {
    "autos": "sedan",
    "suv": "suv",
    "camionetas": "pickup",
    "camiones": "truck",
    "furgones": "van",
    "motos": "motorcycle",
    "buses": "bus",
    "maquinarias": "machinery",
}


def log(msg: str) -> None:
    print(f"[autosusados] {msg}", file=sys.stderr, flush=True)


def polite_sleep() -> None:
    time.sleep(random.uniform(0.5, 1.0))


def fetch_sitemap_urls(session: requests.Session, sitemap_url: str) -> list[str]:
    r = session.get(sitemap_url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return re.findall(r"<loc>([^<]+)</loc>", r.text)


def collect_listing_urls(session: requests.Session, limit: int) -> list[str]:
    """Collect roughly limit URLs, mixing dealer + private sitemaps."""
    urls: list[str] = []
    per_sitemap = max(limit // len(SUB_SITEMAPS), 1) * 4  # overshoot then sample
    for sm in SUB_SITEMAPS:
        log(f"loading sub-sitemap {sm}")
        try:
            all_locs = fetch_sitemap_urls(session, sm)
        except Exception as e:
            log(f"  sub-sitemap failed: {e}")
            continue
        listings = [u for u in all_locs if re.search(r"/\d+/?$", u)]
        log(f"  {len(listings)} listing URLs found")
        random.shuffle(listings)
        urls.extend(listings[:per_sitemap])
        polite_sleep()
    random.shuffle(urls)
    return urls[:limit]


def extract_next_data(html: str) -> dict[str, Any] | None:
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.S,
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def extract_ldjson_car(html: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            d = json.loads(tag.string or "")
        except Exception:
            continue
        if isinstance(d, dict) and d.get("@type") == "Car":
            return d
    return None


def parse_listing(url: str, html: str) -> dict[str, Any] | None:
    nd = extract_next_data(html)
    if not nd:
        return None
    try:
        ci = nd["props"]["pageProps"]["carInfo"]
    except (KeyError, TypeError):
        return None
    if not isinstance(ci, dict):
        return None

    ldj = extract_ldjson_car(html) or {}

    # Derive body type from URL category slug as a fallback
    category_slug = url.split("/")[3] if len(url.split("/")) > 3 else ""
    body_from_url = BODY_BY_CATEGORY_SLUG.get(category_slug)
    body = ci.get("carBodyName") or ldj.get("bodyType") or body_from_url

    region_id = ci.get("regionID")
    region = REGION_BY_ID.get(region_id) if isinstance(region_id, int) else None

    # seller: sitemap path distinguishes dealers (automotoras) from privates
    # path ending /1/ID is automotora, /3/ID is particular per observed data
    seller_type = "dealer"
    parts = url.rstrip("/").split("/")
    if len(parts) >= 2 and parts[-2] == "3":
        seller_type = "private"

    posted_at = ci.get("publicationDate")  # already ISO 8601 UTC

    price = ci.get("price")
    try:
        price_clp = int(price) if price is not None else None
    except (TypeError, ValueError):
        price_clp = None

    km = ci.get("kilometers")
    try:
        km_int = int(km) if km is not None else None
    except (TypeError, ValueError):
        km_int = None

    source_id = str(ci.get("autoID") or nd["props"]["pageProps"].get("id") or "")

    title_parts = [
        str(ci.get("brandName") or "").strip(),
        str(ci.get("modelName") or "").strip(),
        str(ci.get("version") or "").strip(),
        str(ci.get("year") or "").strip(),
    ]
    title = " ".join(p for p in title_parts if p) or ldj.get("name")

    return {
        "source": SOURCE_SLUG,
        "source_id": source_id,
        "url": url,
        "title": title,
        "make": ci.get("brandName"),
        "model": ci.get("modelName"),
        "version": ci.get("version"),
        "year": ci.get("year"),
        "km": km_int,
        "price_clp": price_clp,
        "currency": "CLP" if ci.get("currency") in ("$", "CLP", None) else ci.get("currency"),
        "fuel_type": ci.get("fuelName"),
        "transmission": ci.get("transmissionName"),
        "body_type": body,
        "region": region,
        "commune": None,  # not available in carInfo
        "posted_at": posted_at,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "seller_type": seller_type,
    }


def main(limit: int = 20) -> None:
    session = requests.Session()
    urls = collect_listing_urls(session, limit * 2)
    log(f"collected {len(urls)} candidate URLs; targeting {limit} successful parses")

    results: list[dict[str, Any]] = []
    attempts = 0
    for url in urls:
        if len(results) >= limit:
            break
        attempts += 1
        try:
            r = session.get(url, headers=HEADERS, timeout=30)
        except Exception as e:
            log(f"  {attempts:02d} ERROR {url}: {e}")
            polite_sleep()
            continue
        if r.status_code != 200:
            log(f"  {attempts:02d} HTTP {r.status_code} {url}")
            polite_sleep()
            continue
        parsed = parse_listing(url, r.text)
        if parsed is None:
            log(f"  {attempts:02d} NO_DATA {url}")
            polite_sleep()
            continue
        results.append(parsed)
        log(
            f"  {attempts:02d} OK  {parsed['make']} {parsed['model']} "
            f"{parsed['year']} ${parsed['price_clp']} ({parsed['region']})"
        )
        polite_sleep()

    log(f"done: {len(results)} listings parsed (from {attempts} attempts)")
    from pathlib import Path as _P
    out = _P("data/autosusados.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    log(f"[write] {out}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    main(n)
