#!/usr/bin/env python3
"""
Yapo.cl used-car scraper.

Strategy
--------
1. The category list page at /autos-usados (paginated as /autos-usados.N)
   returns fully server-rendered HTML. Each page contains 30 ad tiles plus a
   per-tile `ga4addata[<adid>] = {...}` JSON blob with canonical make/model/
   fuel/transmission/region/commune fields. Tile HTML carries title, price,
   year, km, and seller type.
2. We extract directly from the listing page — no per-listing fetch needed
   for the schema we care about. This keeps the request count to 1 page per
   30 listings.
3. If richer fields are ever needed, each detail page at
   /autos-usados/<slug>/<adid> exposes schema.org `Car` structured data in
   a <script type="application/ld+json"> block.

Anti-bot status (probed 2026-04-23)
-----------------------------------
- /robots.txt: HTTP 200, permissive for /autos-usados.
- /autos-usados: HTTP 200, ~700 KB HTML, no Cloudflare challenge page.
- /autos-usados/<slug>/<id>: HTTP 200.
- No JS challenge, no 403, no captcha served to a plain UA + es-CL headers.
- Conservative 1.5s delay between page requests to avoid rate-limit warnings.

Output: JSON array at
  projects/car-tracker/data/yapo.json
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

BASE = "https://www.yapo.cl"
LIST_PATH = "/autos-usados"
OUT_PATH = Path("data/yapo.json")
DEFAULT_TARGET = 500
# In SCRAPE_MODE=full we paginate the entire /autos-usados inventory.
# As of 2026 the live stock is ~36k listings; the API serves ~30 tiles/page so
# ~1.2k pages bound the walk. We use a generous safety cap to avoid runaway.
FULL_MODE_TARGET = 50_000
FULL_MODE_MAX_PAGES = 2_500

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
    # Intentionally omit `br`: requests only auto-decodes br when the `brotli`
    # package is installed. gzip/deflate are always supported.
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

REGION_MAP = {
    "chile-es-arica-parinacota": "Arica y Parinacota",
    "chile-es-tarapaca": "Tarapaca",
    "chile-es-antofagasta": "Antofagasta",
    "chile-es-atacama": "Atacama",
    "chile-es-coquimbo": "Coquimbo",
    "chile-es-valparaiso": "Valparaiso",
    "chile-es-region-metropolitana": "Region Metropolitana",
    "chile-es-ohiggins": "O'Higgins",
    "chile-es-maule": "Maule",
    "chile-es-nuble": "Nuble",
    "chile-es-biobio": "Biobio",
    "chile-es-araucania": "Araucania",
    "chile-es-los-rios": "Los Rios",
    "chile-es-los-lagos": "Los Lagos",
    "chile-es-aysen": "Aysen",
    "chile-es-magallanes": "Magallanes",
}


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def fetch(session: requests.Session, url: str, referer: str | None = None) -> str:
    hdrs = dict(HEADERS)
    if referer:
        hdrs["Referer"] = referer
    resp = session.get(url, headers=hdrs, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code} for {url}")
    return resp.text


def parse_price_clp(text: str) -> int | None:
    """Parse '$9.680.000' -> 9680000."""
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    if not digits:
        return None
    try:
        val = int(digits)
    except ValueError:
        return None
    # Filter obvious junk (< 50k CLP is not a car)
    if val < 50_000:
        return None
    return val


def parse_km(text: str) -> int | None:
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def parse_region_commune(province: str, location: str) -> tuple[str | None, str | None]:
    region = REGION_MAP.get(province)
    commune = None
    if location and province and location.startswith(province + "-"):
        slug = location[len(province) + 1 :]
        commune = slug.replace("-", " ").title()
    return region, commune


def _text(el) -> str:
    if el is None:
        return ""
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


def extract_tile(tile, ga4: dict[str, Any], scraped_at: str) -> dict[str, Any] | None:
    # adid + url
    fav = tile.select_one("a.tool-favorite[data-adid]")
    adid = fav.get("data-adid") if fav else None
    a_link = tile.select_one(".d3-ad-tile__description")
    href = a_link.get("href") if a_link else None
    if not adid or not href:
        return None
    url = href if href.startswith("http") else BASE + href

    # title
    title = _text(tile.select_one(".d3-ad-tile__title"))

    # price
    price_el = tile.select_one(".d3-ad-tile__price")
    # only use the direct text, skip the '-2%' sale span
    price_text = ""
    if price_el is not None:
        # clone and remove children that are spans (reduction badge)
        for sub in price_el.find_all("span"):
            sub.extract()
        price_text = _text(price_el)
    price_clp = parse_price_clp(price_text)

    # location (commune as display string)
    location_display = _text(tile.select_one(".d3-ad-tile__location")) or None

    # seller (displayed name)
    seller_el = tile.select_one(".d3-ad-tile__seller span")
    seller_name = _text(seller_el) if seller_el else None
    # seller type via "Profesional" seal
    seller_type = (
        "professional"
        if tile.select_one('.d3-ad-tile__seals img[title="Profesional"]')
        else "private"
    )

    # details list: Year / Fuel / Trans / Mileage (order varies; use icons)
    year = km = None
    fuel_type = transmission = None
    for li in tile.select(".d3-ad-tile__details li"):
        use_el = li.select_one("use")
        icon = (use_el.get("xlink:href") if use_el else "") or ""
        txt = _text(li)
        if "#year" in icon:
            m = re.search(r"\b(19|20)\d{2}\b", txt)
            if m:
                year = int(m.group(0))
        elif "#fuel" in icon:
            fuel_type = txt or None
        elif "#trans" in icon:
            transmission = txt or None
        elif "#mileage" in icon:
            km = parse_km(txt)

    # canonical metadata from ga4 blob (more reliable than tile text)
    meta = ga4.get(adid, {})
    make = meta.get("f_make") or None
    model = meta.get("f_model") or None
    if fuel_type is None:
        fuel_type = meta.get("f_fuel")
    if transmission is None:
        transmission = meta.get("f_trans")
    province = meta.get("province") or ""
    loc_slug = meta.get("location") or ""
    region, commune = parse_region_commune(province, loc_slug)
    if not commune and location_display:
        commune = location_display

    # derive version from the title (tail after make+model if present)
    version = None
    if title and make and model:
        tail = re.sub(r"^\s*" + re.escape(make), "", title, flags=re.I).strip()
        tail = re.sub(r"^\s*" + re.escape(model), "", tail, flags=re.I).strip()
        version = tail or None

    # Images: the tile carousel uses lazy-loaded <img> where `src` is a base64
    # gif placeholder and the real URL is in `data-src`. Collect every carousel
    # photo for this tile.
    image_url: str | None = None
    image_urls: list[str] = []
    for img_el in tile.select("img.d3-photos-carousel__photo"):
        for attr in ("data-src", "data-original", "src"):
            candidate = img_el.get(attr)
            if isinstance(candidate, str) and candidate.startswith("http"):
                candidate = candidate.strip()
                if candidate not in image_urls:
                    image_urls.append(candidate)
                break
    # Fallback to any tile img that starts with http (non-lazy tiles).
    if not image_urls:
        for img_el in tile.find_all("img"):
            for attr in ("data-src", "data-original", "src"):
                candidate = img_el.get(attr)
                if isinstance(candidate, str) and candidate.startswith("http"):
                    candidate = candidate.strip()
                    if candidate not in image_urls:
                        image_urls.append(candidate)
                    break
    if image_urls:
        image_url = image_urls[0]
    # ga4 may expose a primary image for older ads (uncommon today) — merge in.
    meta_img = meta.get("image")
    if isinstance(meta_img, str) and meta_img.strip().startswith("http"):
        if not image_url:
            image_url = meta_img.strip()
        if meta_img.strip() not in image_urls:
            image_urls.append(meta_img.strip())
    meta_imgs = meta.get("images")
    if isinstance(meta_imgs, list):
        for u in meta_imgs:
            if isinstance(u, str) and u.strip().startswith("http") and u.strip() not in image_urls:
                image_urls.append(u.strip())

    return {
        "source": "yapo",
        "source_id": adid,
        "url": url,
        "title": title or None,
        "make": make,
        "model": model,
        "version": version,
        "year": year,
        "km": km,
        "price_clp": price_clp,
        "currency": "CLP",
        "fuel_type": fuel_type,
        "transmission": transmission,
        "body_type": None,  # not exposed on list tile
        "region": region,
        "commune": commune,
        "posted_at": None,  # not on list tile; detail page has no explicit date either
        "scraped_at": scraped_at,
        "seller_type": seller_type,
        "seller_name": seller_name,
        "image_url": image_url,
        "image_urls": image_urls or None,
    }


def extract_ga4_blobs(html: str) -> dict[str, Any]:
    blobs: dict[str, Any] = {}
    for adid, raw in re.findall(
        r"ga4addata\[(\d+)\]\s*=\s*(\{[^}]+\})", html
    ):
        try:
            blobs[adid] = json.loads(raw)
        except json.JSONDecodeError:
            continue
    return blobs


def scrape(max_listings: int = DEFAULT_TARGET, max_pages: int = 40) -> list[dict[str, Any]]:
    session = requests.Session()
    all_rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    # MAX_TEST_ROWS allows tests to cap full-mode runs without spending hours.
    test_cap = None
    test_cap_env = os.environ.get("MAX_TEST_ROWS")
    if test_cap_env:
        try:
            test_cap = int(test_cap_env)
        except ValueError:
            test_cap = None

    prev_url: str | None = None
    empty_pages_in_a_row = 0
    for page in range(1, max_pages + 1):
        path = LIST_PATH if page == 1 else f"{LIST_PATH}.{page}"
        url = BASE + path
        log(f"[yapo] fetching page {page}: {url}")
        try:
            html = fetch(session, url, referer=prev_url)
        except Exception as e:
            log(f"[yapo] page {page} failed: {e}")
            break
        prev_url = url

        ga4 = extract_ga4_blobs(html)
        soup = BeautifulSoup(html, "html.parser")
        tiles = soup.select("div.d3-ad-tile.d3-ads-grid__item")
        log(f"[yapo]   found {len(tiles)} tiles, {len(ga4)} ga4 blobs")
        scraped_at = datetime.now(timezone.utc).isoformat()

        page_new = 0
        for tile in tiles:
            row = extract_tile(tile, ga4, scraped_at)
            if not row:
                continue
            if row["source_id"] in seen_ids:
                continue
            seen_ids.add(row["source_id"])
            all_rows.append(row)
            page_new += 1
            if len(all_rows) >= max_listings:
                break
            if test_cap is not None and len(all_rows) >= test_cap:
                break

        log(f"[yapo]   +{page_new} new (total {len(all_rows)})")
        if len(all_rows) >= max_listings:
            break
        if test_cap is not None and len(all_rows) >= test_cap:
            log(f"[yapo] hit MAX_TEST_ROWS={test_cap}, stopping")
            break

        # Pagination termination: yapo serves an empty/repeat page when we run
        # off the end. Two consecutive zero-yield pages = done.
        if page_new == 0:
            empty_pages_in_a_row += 1
            if empty_pages_in_a_row >= 2:
                log("[yapo] two empty pages in a row — pagination exhausted")
                break
        else:
            empty_pages_in_a_row = 0

        # polite delay between pages
        time.sleep(1.5)

    return all_rows


def main() -> int:
    mode = os.environ.get("SCRAPE_MODE", "fresh").strip().lower() or "fresh"
    if mode == "full":
        target = FULL_MODE_TARGET
        max_pages = FULL_MODE_MAX_PAGES
        log(f"[yapo] SCRAPE_MODE=full (target={target}, max_pages={max_pages})")
    else:
        target = DEFAULT_TARGET
        override = os.environ.get("SCRAPE_TARGET")
        if override:
            try:
                target = int(override)
            except ValueError:
                pass
        # 30 tiles/page -> enough headroom to reach `target` even with losses.
        max_pages = max(5, (target // 25) + 5)
    try:
        rows = scrape(max_listings=target, max_pages=max_pages)
    except Exception as e:
        log(f"[yapo] FATAL: {e}")
        rows = []
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    log(f"[yapo] wrote {len(rows)} listings -> {OUT_PATH}")
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
