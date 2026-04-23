#!/usr/bin/env python3
"""
Kavak Chile scraper.

Strategy
--------
Kavak's listing page (https://www.kavak.com/cl/usados) is a Next.js App-Router
page: it does NOT expose a classic `__NEXT_DATA__` JSON blob, but it streams
React Server Component (RSC) payloads inline as escaped JSON. Those payloads
contain fully structured "card" objects for every listing on the page,
including an `analytics` sub-object with make / model / year / price / id /
location / seller_type.

Individual listing (VIP) pages embed a clean <script type="application/ld+json">
block with a `Car` schema.org object (brand, model, bodyType, vehicleTransmission,
fuelType, color, VIN, price, mileage), plus another RSC blob with the
physical hub address (commune) and region name.

This scraper:
  1. Pages through /cl/usados?page=N, extracts listing stubs from the RSC blob.
  2. For each stub, fetches the VIP page and merges the JSON-LD Car object +
     hub address/region from the VIP RSC.
  3. Writes a JSON array of normalised listings to stdout (or --out file).

No headless browser is needed.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Iterable

import requests
from bs4 import BeautifulSoup

BASE = "https://www.kavak.com"
LIST_URL = BASE + "/cl/usados"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.2 Safari/605.1.15"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}


# --- helpers ----------------------------------------------------------------

def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def polite_sleep(min_s: float = 0.5, max_s: float = 1.0) -> None:
    time.sleep(random.uniform(min_s, max_s))


def _unescape_rsc(s: str) -> str:
    """RSC payloads use JS string escaping. Turn it into valid JSON chars."""
    return (
        s.replace('\\"', '"')
        .replace("\\u0026", "&")
        .replace("\\u003c", "<")
        .replace("\\u003e", ">")
        .replace("\\/", "/")
    )


def _to_int(s: str | int | None) -> int | None:
    if s is None:
        return None
    if isinstance(s, int):
        return s
    digits = re.sub(r"[^0-9]", "", str(s))
    return int(digits) if digits else None


# --- listing page parser ----------------------------------------------------

_CARD_ANCHOR = re.compile(
    r'\\"id\\":\\"(?P<id>\d+)\\",\\"url\\":\\"(?P<url>https://www\.kavak\.com/cl/venta/[^\\]+)\\"'
)


def parse_list_page(html: str) -> list[dict[str, Any]]:
    """Extract listing stubs from an /cl/usados?page=N response."""
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()

    for m in _CARD_ANCHOR.finditer(html):
        source_id = m.group("id")
        if source_id in seen:
            continue
        seen.add(source_id)

        # Slice from here until the next card anchor or a reasonable cap.
        start = m.start()
        # Look ~4 KB ahead for this card's fields, which is plenty.
        window = html[start : start + 4000]

        def pick(key: str) -> str | None:
            mm = re.search(rf'\\"{key}\\":\\"([^"\\]*)\\"', window)
            return _unescape_rsc(mm.group(1)) if mm else None

        subtitle = pick("subtitle") or ""
        # subtitle is like "2022 • 72.000 km • 1.4 COMFORT • Manual"
        parts = [p.strip() for p in subtitle.split("•")]

        year = _to_int(parts[0]) if parts else None
        km = _to_int(parts[1]) if len(parts) > 1 else None
        version = parts[2] if len(parts) > 2 else None
        transmission = parts[3] if len(parts) > 3 else None

        # analytics sub-object lives inside the card window
        def analytic(key: str) -> str | None:
            mm = re.search(rf'\\"{key}\\":\\"([^"\\]*)\\"', window)
            return _unescape_rsc(mm.group(1)) if mm else None

        make = analytic("car_make")
        model = analytic("car_model")
        region = pick("footerInfo")  # e.g. "Metropolitana de Santiago"

        price_raw = pick("mainPrice") or ""
        price_clp = _to_int(price_raw)

        # bodyType can be recovered from URL slug: .../{make}-{model}-{version}-{body}-{year}
        body = None
        url_m = re.search(r"/cl/venta/([^\"\\]+)", m.group("url"))
        if url_m:
            slug = url_m.group(1)
            slug_parts = slug.split("-")
            if len(slug_parts) >= 2 and re.fullmatch(r"\d{4}", slug_parts[-1]):
                body = slug_parts[-2]

        title = pick("title")  # e.g. "Changan • Alsvin"
        if title:
            title = title.replace(" • ", " ")

        cards.append(
            {
                "source_id": source_id,
                "url": m.group("url"),
                "title": title,
                "make": make,
                "model": model,
                "version": version,
                "year": year,
                "km": km,
                "price_clp": price_clp,
                "transmission": transmission,
                "region": region,
                "body_type": body,
            }
        )
    return cards


# --- VIP page parser --------------------------------------------------------

def _find_car_ld(html: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        graph = data.get("@graph") if isinstance(data, dict) else None
        items = graph if isinstance(graph, list) else [data]
        for item in items:
            if isinstance(item, dict) and item.get("@type") in ("Car", "Vehicle", "Product"):
                return item
    return None


def _find_hub(html: str) -> tuple[str | None, str | None]:
    """Return (region, commune) from VIP RSC payload."""
    region = None
    commune = None

    m = re.search(r'\\"region\\":\\"([^"\\]+)\\"', html)
    if m:
        region = _unescape_rsc(m.group(1))

    # Hub address like "Av. Independencia 565, 8380538 Independencia, Región Metropolitana, Chile"
    m = re.search(r'\\"address\\":\\"([^"\\]+)\\"', html)
    if m:
        addr = _unescape_rsc(m.group(1))
        # commune is usually the token after the postcode in the second segment
        segs = [s.strip() for s in addr.split(",")]
        if len(segs) >= 2:
            cand = segs[1]
            # strip postal code prefix if present
            cand = re.sub(r"^\d+\s*", "", cand)
            commune = cand or None
    return region, commune


def enrich_from_vip(stub: dict[str, Any], html: str) -> dict[str, Any]:
    out = dict(stub)
    car = _find_car_ld(html) or {}

    brand = car.get("brand")
    if isinstance(brand, dict):
        out["make"] = out.get("make") or brand.get("name")
    out["model"] = out.get("model") or car.get("model")
    out["body_type"] = out.get("body_type") or car.get("bodyType")
    out["transmission"] = out.get("transmission") or car.get("vehicleTransmission")

    engine = car.get("vehicleEngine")
    if isinstance(engine, dict):
        out["fuel_type"] = engine.get("fuelType")

    mileage = car.get("mileageFromOdometer")
    if isinstance(mileage, dict) and out.get("km") is None:
        out["km"] = _to_int(mileage.get("value"))

    offers = car.get("offers")
    if isinstance(offers, dict):
        out["price_clp"] = out.get("price_clp") or _to_int(offers.get("price"))
        out["currency"] = offers.get("priceCurrency") or out.get("currency")

    if not out.get("title"):
        out["title"] = car.get("name")

    region, commune = _find_hub(html)
    out["region"] = out.get("region") or region
    out["commune"] = commune
    return out


# --- orchestration ----------------------------------------------------------

def fetch(session: requests.Session, url: str) -> str | None:
    try:
        r = session.get(url, timeout=30)
    except requests.RequestException as e:
        log(f"    ! request error: {e}")
        return None
    if r.status_code != 200:
        log(f"    ! HTTP {r.status_code} for {url}")
        return None
    return r.text


def scrape(target: int, enrich: bool) -> list[dict[str, Any]]:
    session = requests.Session()
    session.headers.update(HEADERS)

    stubs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    page = 1
    while len(stubs) < target and page <= 20:
        url = LIST_URL if page == 1 else f"{LIST_URL}?page={page}"
        log(f"[list] page {page} -> {url}")
        html = fetch(session, url)
        if not html:
            break
        batch = parse_list_page(html)
        log(f"       parsed {len(batch)} cards")
        fresh = [c for c in batch if c["source_id"] not in seen_ids]
        if not fresh:
            log("       no new ids on this page, stopping pagination")
            break
        for c in fresh:
            seen_ids.add(c["source_id"])
            stubs.append(c)
        page += 1
        polite_sleep()

    stubs = stubs[:target]
    log(f"[list] collected {len(stubs)} stubs")

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results: list[dict[str, Any]] = []

    for i, stub in enumerate(stubs, 1):
        log(f"[vip {i}/{len(stubs)}] {stub['url']}")
        record: dict[str, Any] = {
            "source": "kavak",
            "source_id": stub["source_id"],
            "url": stub["url"],
            "title": stub.get("title"),
            "make": stub.get("make"),
            "model": stub.get("model"),
            "version": stub.get("version"),
            "year": stub.get("year"),
            "km": stub.get("km"),
            "price_clp": stub.get("price_clp"),
            "currency": "CLP",
            "fuel_type": None,
            "transmission": stub.get("transmission"),
            "body_type": stub.get("body_type"),
            "region": stub.get("region"),
            "commune": None,
            "posted_at": None,  # Kavak does not publish a listing-creation timestamp.
            "scraped_at": now_iso,
            "seller_type": "dealer",
        }

        if enrich:
            html = fetch(session, stub["url"])
            if html:
                enriched = enrich_from_vip(record, html)
                record.update(
                    {
                        k: enriched.get(k)
                        for k in (
                            "title",
                            "make",
                            "model",
                            "body_type",
                            "transmission",
                            "fuel_type",
                            "km",
                            "price_clp",
                            "currency",
                            "region",
                            "commune",
                        )
                    }
                )
                record["currency"] = record.get("currency") or "CLP"
            polite_sleep()

        results.append(record)

    return results


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Scrape Kavak Chile used car listings.")
    ap.add_argument("--target", type=int, default=40, help="Number of listings to collect (default 40).")
    ap.add_argument("--out", type=str, default="data/kavak.json", help="Output file.")
    ap.add_argument("--no-enrich", action="store_true", help="Skip VIP fetch; list-only data.")
    args = ap.parse_args(list(argv) if argv is not None else None)

    listings = scrape(target=args.target, enrich=not args.no_enrich)
    log(f"[done] {len(listings)} listings")

    payload = json.dumps(listings, ensure_ascii=False, indent=2)
    from pathlib import Path as _P
    _P(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(payload + "\n")
    log(f"[write] {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
