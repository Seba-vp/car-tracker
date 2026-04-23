#!/usr/bin/env python3
"""
Autopia.cl / BravoAuto.cl scraper.

Notes on source:
- `autopia.cl` 301-redirects to `bravoauto.cl` (same platform).
- Stack: Laravel + Inertia.js. Every page embeds a JSON blob in the
  `data-page` attribute on `<div id="app">` which contains all props
  server-rendered for the page. No separate API call is needed.
- Homepage component `Home` exposes `props.data.ads[]` with ~120 ads
  that cover the full live stock (same cars as the sitemap + a few more).
- Detail pages (component `CarDetail`) expose `props.data` with extras
  like `regionID`, `specification.color`, `latitude`/`length`, and
  `clientName` (the dealership branch, commonly named after the commune).

Strategy:
1) Fetch the homepage; that Inertia payload carries the full live stock
   (~120 ads) in `props.data.ads[]` plus `publicationDate` per ad.
   (The sitemap_autos.xml is often months stale, so we do not rely on it.)
2) Reconstruct each detail URL from ad fields and fetch the detail page
   to pick up `regionID` and `clientName` (used to derive commune).
3) Parse into the target schema.
"""
from __future__ import annotations

import html as html_mod
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import requests
from bs4 import BeautifulSoup

SOURCE_SLUG = "autopia"
BASE = "https://www.bravoauto.cl"
SITEMAP = f"{BASE}/sitemap_autos.xml"
HOME = f"{BASE}/"

CHILE_REGIONS = {
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

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def log(msg: str) -> None:
    print(f"[autopia] {msg}", file=sys.stderr, flush=True)


def fetch(session: requests.Session, url: str, timeout: int = 30) -> Optional[str]:
    try:
        r = session.get(url, timeout=timeout)
        if r.status_code != 200:
            log(f"GET {url} -> {r.status_code}")
            return None
        return r.text
    except requests.RequestException as exc:
        log(f"GET {url} -> ERROR {exc}")
        return None


def extract_inertia(html: str) -> Optional[dict[str, Any]]:
    """Pull the Inertia page payload out of `data-page`."""
    soup = BeautifulSoup(html, "html.parser")
    node = soup.find(attrs={"data-page": True})
    if node is None:
        return None
    try:
        return json.loads(html_mod.unescape(node["data-page"]))
    except (json.JSONDecodeError, KeyError):
        # Fallback: regex if BeautifulSoup stripped something oddly.
        m = re.search(r'data-page="([^"]+)"', html)
        if not m:
            return None
        try:
            return json.loads(html_mod.unescape(m.group(1)))
        except json.JSONDecodeError:
            return None


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s


def build_detail_url(ad: dict[str, Any]) -> Optional[str]:
    """Reconstruct the canonical /auto-usado/.../{carId} URL from an ad dict.

    Verified against sitemap entries: brand, model, category and transmission
    are lower-cased and ascii-slugified; the transmission portion is prefixed
    by 'transmision-'."""
    try:
        brand = _slug(ad["brand"])
        model = _slug(ad["model"])
        category = _slug(ad["category"])
        year = int(ad["year"])
        trans_raw = _slug(ad.get("transmissionType") or "")
        # 'transmision-automatica' vs 'transmision-mecanica'
        trans_key = trans_raw.replace("transmision-", "")
        if not trans_key:
            trans_key = "automatica"  # reasonable default; rare missing case
        car_id = int(ad["carId"])
        return (
            f"{BASE}/auto-usado/{brand}/{model}/{category}/{year}/"
            f"transmision-{trans_key}/{car_id}"
        )
    except (KeyError, TypeError, ValueError):
        return None


def sitemap_urls(session: requests.Session) -> list[str]:
    xml = fetch(session, SITEMAP)
    if not xml:
        return []
    urls = re.findall(r"<loc>(https://www\.bravoauto\.cl/auto-usado/[^<]+)</loc>", xml)
    # De-duplicate, preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def homepage_ads(session: requests.Session) -> dict[int, dict[str, Any]]:
    """Map carId -> ad dict from the homepage Inertia payload."""
    html = fetch(session, HOME)
    if not html:
        return {}
    payload = extract_inertia(html)
    if not payload:
        return {}
    ads = (
        payload.get("props", {})
        .get("data", {})
        .get("ads", [])
        or []
    )
    out: dict[int, dict[str, Any]] = {}
    for ad in ads:
        cid = ad.get("carId")
        if cid is not None:
            out[int(cid)] = ad
    log(f"homepage listing ads: {len(out)}")
    return out


def infer_commune(client_name: Optional[str]) -> Optional[str]:
    """BravoAuto branches are named after their commune, e.g.
    'Bravoauto Las Condes' -> 'Las Condes'. Not foolproof but reasonable."""
    if not client_name:
        return None
    name = client_name.strip()
    # Strip leading 'Bravoauto ' prefix (any case)
    m = re.match(r"(?i)^bravoauto\s+(.*)$", name)
    return m.group(1).strip() if m else None


def to_iso(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    # Homepage publicationDate looks like '2025-05-26 16:32:39' (CL local time, no tz).
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        return dt.isoformat()
    except ValueError:
        return s


def parse_detail(
    url: str,
    payload: dict[str, Any],
    homepage_index: dict[int, dict[str, Any]],
) -> Optional[dict[str, Any]]:
    props = payload.get("props", {})
    data = props.get("data") or {}
    if not data:
        return None

    auto_id = data.get("autoID")
    spec = data.get("specification") or {}
    # fuel / transmission / body from spec (cleaner dicts)
    fuel = (spec.get("fuel") or {}).get("name") or data.get("fuelName")
    transmission = (spec.get("transmission") or {}).get("name") or data.get("transmissionName")
    body_type = (spec.get("bodyWork") or {}).get("name")
    category = (spec.get("category") or {}).get("name") or data.get("categoryName")

    hp_ad = homepage_index.get(int(auto_id)) if auto_id is not None else None
    posted_at = to_iso(hp_ad.get("publicationDate")) if hp_ad else None
    # bodyType from homepage is the short code ('SUV'), prefer that over carrocería
    body_type = (hp_ad or {}).get("bodyType") or body_type or category

    region_id = data.get("regionID")
    region = CHILE_REGIONS.get(region_id) if region_id else None
    commune = infer_commune(data.get("clientName"))

    price = data.get("price")
    title_parts = [
        str(data.get("brandName") or "").strip(),
        str(data.get("modelName") or "").strip(),
        str(data.get("version") or "").strip(),
        str(data.get("year") or "").strip(),
    ]
    title = " ".join(p for p in title_parts if p)

    return {
        "source": SOURCE_SLUG,
        "source_id": str(auto_id) if auto_id is not None else None,
        "url": url,
        "title": title or None,
        "make": data.get("brandName"),
        "model": data.get("modelName"),
        "version": data.get("version"),
        "year": data.get("year"),
        "km": data.get("kilometers"),
        "price_clp": price if isinstance(price, (int, float)) and price > 0 else None,
        "currency": "CLP" if data.get("currency") in ("$", "CLP") else data.get("currency"),
        "fuel_type": fuel,
        "transmission": transmission,
        "body_type": body_type,
        "region": region,
        "commune": commune,
        "posted_at": posted_at,
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seller_type": "dealer",
    }


def scrape(limit: int = 25, delay: float = 0.7) -> list[dict[str, Any]]:
    session = requests.Session()
    session.headers.update(HEADERS)

    hp_index = homepage_ads(session)
    if not hp_index:
        log("no homepage ads available, aborting")
        return []

    # Seed from homepage ads (authoritative live stock).
    # Sort by publicationDate DESC so the sample skews toward fresh stock
    # and isn't dominated by one brand from early carIds.
    sm = set(sitemap_urls(session))
    ads_sorted = sorted(
        hp_index.values(),
        key=lambda a: a.get("publicationDate") or "",
        reverse=True,
    )
    seeds: list[tuple[str, dict[str, Any]]] = []
    for ad in ads_sorted:
        url = build_detail_url(ad)
        if url is None:
            continue
        seeds.append((url, ad))
    log(f"homepage-seeded URLs: {len(seeds)} (sitemap had {len(sm)})")

    records: list[dict[str, Any]] = []
    n = min(limit, len(seeds))
    for i, (url, _ad) in enumerate(seeds[:n], 1):
        log(f"[{i}/{n}] {url}")
        html = fetch(session, url)
        if not html:
            time.sleep(delay)
            continue
        payload = extract_inertia(html)
        if not payload or payload.get("component") != "CarDetail":
            log("  no CarDetail payload, skipping")
            time.sleep(delay)
            continue
        rec = parse_detail(url, payload, hp_index)
        if rec:
            records.append(rec)
        time.sleep(delay)

    log(f"parsed {len(records)} records")
    return records


def main() -> int:
    out_path = sys.argv[1] if len(sys.argv) > 1 else "data/autopia.json"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 25
    records = scrape(limit=limit)
    from pathlib import Path as _P
    _P(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(records, fh, ensure_ascii=False, indent=2)
    log(f"wrote {len(records)} records -> {out_path}")
    return 0 if records else 1


if __name__ == "__main__":
    sys.exit(main())
