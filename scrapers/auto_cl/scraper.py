#!/usr/bin/env python3
"""
auto.cl scraper (focus: used cars).

Method:
  1. Fetch /sitemap.xml -> filter to /usados/* detail URLs.
  2. For each detail page, fetch HTML and extract the Angular SSR
     state embedded as <script id="ng-state">...</script>.
     That blob contains a `publication` object with every field we need
     (brand, model, version, year, km, price, region, sellerType, etc.).
  3. Normalize into the common listing schema.

Anti-bot notes:
  auto.cl is fronted by Cloudflare with a managed challenge that returns
  HTTP 403 + JS challenge for the default python/requests/curl UAs AND for
  the common Chrome-on-macOS UA. It DOES serve plain HTML (HTTP 200) for
  Safari-style UAs and for social-media fetchers (facebookexternalhit,
  Twitterbot, WhatsApp). We use a Safari UA.

Output: JSON array on stdout. Progress on stderr.
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any

# Cloudflare blocks stdlib requests (TLS fingerprint). curl_cffi's
# Safari impersonation passes. API-compatible with `requests`.
from curl_cffi import requests  # type: ignore

SOURCE_SLUG = "auto_cl"
BASE = "https://www.auto.cl"
SITEMAP = f"{BASE}/sitemap.xml"

# Safari UA: confirmed to pass Cloudflare without JS execution.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    ),
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Map auto.cl fuelType / transmission code -> display value (Spanish-friendly)
FUEL_MAP = {
    "gasoline": "Gasolina",
    "diesel": "Diésel",
    "hybrid": "Híbrido",
    "electric": "Eléctrico",
    "gas": "Gas",
    "plugin-hybrid": "Híbrido enchufable",
}
TRANS_MAP = {
    "automatic": "Automática",
    "manual": "Mecánica",
    "cvt": "CVT",
    "semi-automatic": "Semi-automática",
}


def log(msg: str) -> None:
    print(f"[auto_cl] {msg}", file=sys.stderr, flush=True)


def polite_sleep() -> None:
    time.sleep(random.uniform(0.5, 1.0))


def get_used_urls(session: requests.Session) -> list[str]:
    r = session.get(SITEMAP, headers=HEADERS, timeout=30)
    r.raise_for_status()
    locs = re.findall(r"<loc>([^<]+)</loc>", r.text)
    # Used detail URLs match: /usados/<slug>-YYYY-<base64>
    detail = [
        u
        for u in locs
        if u.startswith(f"{BASE}/usados/")
        and re.search(r"-\d{4}-[A-Za-z0-9]{10,}$", u)
    ]
    return detail


def extract_publication(html: str) -> dict[str, Any] | None:
    m = re.search(r'<script id="ng-state"[^>]*>([\s\S]*?)</script>', html)
    if not m:
        return None
    try:
        state = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(state, dict):
        return None
    for key, val in state.items():
        if not key.startswith("usedPublication_"):
            continue
        if isinstance(val, dict) and isinstance(val.get("publication"), dict):
            return val["publication"]
    return None


def ms_to_iso(ms: int | None) -> str | None:
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def parse_listing(url: str, html: str) -> dict[str, Any] | None:
    pub = extract_publication(html)
    if not pub:
        return None

    price_clp = None
    price = pub.get("price")
    if isinstance(price, dict):
        val = price.get("CLP")
        try:
            price_clp = int(val) if val is not None else None
        except (TypeError, ValueError):
            price_clp = None

    region = None
    reg = pub.get("region")
    if isinstance(reg, dict):
        region = reg.get("name") or reg.get("shortName")

    fuel_raw = pub.get("fuelType")
    if isinstance(fuel_raw, str):
        fuel_raw = fuel_raw.lower()
    trans_raw = pub.get("transmission")
    if isinstance(trans_raw, str):
        trans_raw = trans_raw.lower()

    km = pub.get("kilometers")
    try:
        km_int = int(km) if km is not None else None
    except (TypeError, ValueError):
        km_int = None

    source_id = pub.get("publicationSlug") or url.rsplit("/", 1)[-1]

    brand = pub.get("brandName")
    model = pub.get("modelName")
    version = pub.get("versionName")
    year = pub.get("year")
    title_parts = [str(x).strip() for x in [brand, model, version, year] if x]
    title = " ".join(dict.fromkeys(title_parts))  # dedupe while keeping order

    seller_type = pub.get("sellerType")  # already "dealer" / "private" usage

    # Images: `sourceImages` is a list of URL strings; `mainImage` is a single URL.
    image_urls: list[str] = []
    src_imgs = pub.get("sourceImages")
    if isinstance(src_imgs, list):
        image_urls.extend([u for u in src_imgs if isinstance(u, str) and u.startswith("http")])
    main_img = pub.get("mainImage")
    if isinstance(main_img, str) and main_img.startswith("http") and main_img not in image_urls:
        image_urls.insert(0, main_img)
    # Dedupe preserving order
    seen_img: set[str] = set()
    image_urls = [u for u in image_urls if not (u in seen_img or seen_img.add(u))]
    image_url = image_urls[0] if image_urls else None

    return {
        "source": SOURCE_SLUG,
        "source_id": source_id,
        "url": url,
        "title": title or None,
        "make": brand,
        "model": model,
        "version": version,
        "year": year,
        "km": km_int,
        "price_clp": price_clp,
        "currency": "CLP",
        "fuel_type": FUEL_MAP.get(fuel_raw, fuel_raw),
        "transmission": TRANS_MAP.get(trans_raw, trans_raw),
        "body_type": pub.get("bodyType"),
        "region": region,
        "commune": None,  # not present in publication blob
        "posted_at": ms_to_iso(pub.get("createdAt")),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "seller_type": seller_type,
        "image_url": image_url,
        "image_urls": image_urls or None,
    }


def main(limit: int = 20) -> None:
    session = requests.Session(impersonate="safari17_0")
    log("loading sitemap")
    urls = get_used_urls(session)
    log(f"{len(urls)} used detail URLs in sitemap")
    random.shuffle(urls)

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
        if "Just a moment" in r.text[:500]:
            log(f"  {attempts:02d} CF_CHALLENGE {url}")
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
    out = _P("data/auto_cl.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    log(f"[write] {out}")


DEFAULT_TARGET = 300


if __name__ == "__main__":
    if len(sys.argv) > 1:
        n = int(sys.argv[1])
    else:
        n = DEFAULT_TARGET
        override = os.environ.get("SCRAPE_TARGET")
        if override:
            try:
                n = int(override)
            except ValueError:
                pass
    main(n)
