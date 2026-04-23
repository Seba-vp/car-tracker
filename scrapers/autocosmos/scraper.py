#!/usr/bin/env python3
"""
Autocosmos.cl used-car listings scraper.

Strategy
--------
1. Fetch paginated index at /auto/usado?p=N (48 listings/page, server-rendered HTML
   with Schema.org/Car microdata inside <article class="card listing-card">).
2. For each card, extract: detail URL, title, brand, model, version, year, km,
   price, currency, region, commune.
3. For each detail page, extract the dfp_* meta block which adds: body_type
   (segmentoNick), seller_type (dfp_privado: empresa->dealer, particular->private).
   Also scrape Combustible / Transmisión rows from the model catalog tables as
   fuel_type and transmission (these reflect the model's spec, not a per-listing
   selector, but Autocosmos does not publish a per-listing fuel/trans field).
4. Write JSON array to --out path.

No JS execution needed. No API calls (site is fully SSR).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.autocosmos.cl"
INDEX_PATH = "/auto/usado"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.6",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

FUEL_MAP = {
    "bencina": "gasolina",
    "gasolina": "gasolina",
    "nafta": "gasolina",
    "diesel": "diesel",
    "diésel": "diesel",
    "petróleo": "diesel",
    "petroleo": "diesel",
    "híbrido": "hibrido",
    "hibrido": "hibrido",
    "eléctrico": "electrico",
    "electrico": "electrico",
    "gnc": "gnc",
    "glp": "gnc",
}

TRANS_MAP_PREFIX = {
    "manual": "manual",
    "automátic": "automatic",
    "automatic": "automatic",
    "secuencial": "automatic",
    "cvt": "automatic",
    "tiptronic": "automatic",
    "dsg": "automatic",
    "steptronic": "automatic",
}


def eprint(*args: Any, **kw: Any) -> None:
    print(*args, file=sys.stderr, **kw)


def normalize_fuel(raw: str | None) -> str:
    if not raw:
        return "other"
    r = raw.strip().lower()
    for k, v in FUEL_MAP.items():
        if k in r:
            return v
    return "other"


def normalize_transmission(raw: str | None) -> str:
    if not raw:
        return "other"
    r = raw.strip().lower()
    for k, v in TRANS_MAP_PREFIX.items():
        if k in r:
            return v
    return "other"


def parse_price(raw: str | None) -> int | None:
    if not raw:
        return None
    digits = re.sub(r"[^0-9]", "", raw)
    if not digits:
        return None
    try:
        val = int(digits)
    except ValueError:
        return None
    # Filter out bogus "pie" (down-payment) values that are too small
    if val < 500_000:
        return None
    return val


def parse_km(raw: str | None) -> int | None:
    if not raw:
        return None
    m = re.search(r"([\d\.\,]+)", raw)
    if not m:
        return None
    digits = re.sub(r"[^0-9]", "", m.group(1))
    return int(digits) if digits else None


def session_with_retries() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def fetch(s: requests.Session, url: str, tries: int = 3, backoff: float = 2.0) -> str | None:
    for i in range(tries):
        try:
            r = s.get(url, timeout=20)
            if r.status_code == 200:
                return r.text
            eprint(f"  [warn] {url} -> HTTP {r.status_code}")
        except requests.RequestException as e:
            eprint(f"  [warn] {url} -> {e.__class__.__name__}: {e}")
        time.sleep(backoff * (i + 1))
    return None


def parse_index_cards(html: str) -> list[dict]:
    """Each listing-card on an index page is a <article itemtype=.../Car>."""
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("article.listing-card")
    out: list[dict] = []
    for c in cards:
        a = c.find("a", itemprop="url")
        if not a or not a.get("href"):
            continue
        url = urljoin(BASE, a["href"])

        brand_el = c.find(itemprop="brand")
        model_el = c.select_one(".listing-card__model")
        version_el = c.select_one(".listing-card__version")
        year_el = c.find(itemprop="modelDate")
        km_el = c.find(itemprop="mileageFromOdometer")
        # Prefer non-anticipo total price; fall back to "pie" price if needed.
        price_el = None
        for p in c.find_all(attrs={"itemprop": "price"}):
            if p.find_parent(class_=re.compile(r"m-anticipo|anticipo", re.I)):
                continue
            price_el = p
            break
        currency_el = c.find(itemprop="priceCurrency")
        city_el = c.find(itemprop="addressLocality")
        region_el = c.find(itemprop="addressRegion")

        title_meta = c.find("meta", itemprop="description")
        title = None
        if title_meta and title_meta.get("content"):
            title = title_meta["content"]
        else:
            name_meta = c.find("meta", itemprop="name")
            if name_meta:
                title = name_meta.get("content")

        km_raw = None
        if km_el:
            km_raw = km_el.get("content") or km_el.text
        price_raw = None
        if price_el is not None:
            price_raw = price_el.get("content") or price_el.get_text(strip=True)

        out.append(
            {
                "url": url,
                "title": title,
                "make": brand_el.text.strip() if brand_el else None,
                "model": model_el.text.strip() if model_el else None,
                "version": version_el.text.strip() if version_el else None,
                "year": int(year_el.text.strip()) if year_el and year_el.text.strip().isdigit() else None,
                "km": parse_km(km_raw),
                "price_clp": parse_price(price_raw),
                "currency": (currency_el.get("content") if currency_el else None) or "CLP",
                "commune": city_el.text.strip().rstrip("|").strip() if city_el else None,
                "region": region_el.text.strip() if region_el else None,
            }
        )
    return out


def parse_detail(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, Any] = {}

    # dfp_* meta tags - the most reliable per-listing source
    dfp: dict[str, str] = {}
    for m in soup.find_all("meta"):
        name = m.get("name", "")
        if name.startswith("dfp_"):
            dfp[name] = m.get("content", "")

    out["body_type"] = dfp.get("dfp_segmentoNick") or None
    privado = (dfp.get("dfp_privado") or "").strip().lower()
    if privado == "particular":
        out["seller_type"] = "private"
    elif privado in {"empresa", "concesionario", "agencia"}:
        out["seller_type"] = "dealer"
    else:
        out["seller_type"] = None

    if dfp.get("dfp_anio", "").isdigit():
        out["year"] = int(dfp["dfp_anio"])
    if dfp.get("dfp_region"):
        out["region"] = dfp["dfp_region"].title()
    if dfp.get("dfp_city"):
        out["commune"] = dfp["dfp_city"].title()

    # Fuel / transmission rows from spec tables (model catalog - shared between
    # all listings of the same trim, which is acceptable for our use case)
    fuel_raw = None
    trans_raw = None
    for tr in soup.find_all("tr"):
        tds = tr.find_all(["th", "td"])
        if len(tds) < 2:
            continue
        label = tds[0].get_text(" ", strip=True).lower()
        val = tds[1].get_text(" ", strip=True)
        if fuel_raw is None and label.startswith("combustible"):
            fuel_raw = val
        if trans_raw is None and label.startswith("transmisi"):
            trans_raw = val
    out["fuel_type"] = normalize_fuel(fuel_raw)
    out["transmission"] = normalize_transmission(trans_raw)

    # IMPORTANT: detail pages embed a "related listings" carousel with cards
    # that also expose itemprop="brand"/"price"/etc. Scope everything we scrape
    # here to the .car-specifics block to avoid picking up sibling listings.
    specifics = soup.select_one(".car-specifics")
    if specifics is None:
        specifics = soup  # fallback (degraded)

    brand = specifics.find(itemprop="brand")
    model_el = specifics.select_one(".car-specifics__model")
    version_el = specifics.select_one(".car-specifics__version")
    if brand:
        out["make"] = brand.get_text(strip=True)
    if model_el:
        out["model"] = model_el.get_text(strip=True)
    if version_el:
        out["version"] = version_el.get_text(strip=True)

    # Canonical listing price: inside .car-specifics, prefer a price that is
    # NOT inside a "m-anticipo" (down payment) block.
    listing_price: int | None = None
    anticipo_price: int | None = None
    for p in specifics.find_all(itemprop="price"):
        content = p.get("content")
        val = parse_price(content or p.get_text())
        if val is None:
            continue
        if p.find_parent(class_=re.compile(r"m-anticipo|anticipo", re.I)):
            if anticipo_price is None:
                anticipo_price = val
            continue
        if listing_price is None:
            listing_price = val
    if listing_price is not None:
        out["price_clp"] = listing_price
    elif anticipo_price is not None:
        # All-financed listing; expose the down-payment as price with a flag
        out["price_clp"] = anticipo_price
        out["_price_is_anticipo"] = True

    city_el = specifics.find(itemprop="addressLocality")
    region_el = specifics.find(itemprop="addressRegion")
    if city_el:
        out["commune"] = city_el.get_text(strip=True).rstrip("|").strip()
    if region_el:
        out["region"] = region_el.get_text(strip=True)

    return out


def source_id_from_url(url: str) -> str:
    m = re.search(r"/([a-f0-9]{32})(?:[/?#]|$)", url)
    if m:
        return m.group(1)
    return hashlib.sha1(url.encode()).hexdigest()[:32]


def merge(card: dict, detail: dict) -> dict:
    merged = dict(card)
    for k, v in detail.items():
        if v not in (None, "", []):
            merged[k] = v
    return merged


def scrape(
    target: int,
    out_path: str,
    delay: float,
    max_pages: int,
) -> list[dict]:
    s = session_with_retries()
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    collected: list[dict] = []
    seen_urls: set[str] = set()
    page = 1

    while len(collected) < target and page <= max_pages:
        idx_url = f"{BASE}{INDEX_PATH}?p={page}"
        eprint(f"[index] GET {idx_url}")
        html = fetch(s, idx_url)
        if not html:
            eprint(f"[index] failed page {page}, stopping")
            break
        cards = parse_index_cards(html)
        eprint(f"[index] page {page}: {len(cards)} cards")
        if not cards:
            break

        for card in cards:
            if len(collected) >= target:
                break
            url = card["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)

            time.sleep(delay)
            eprint(f"  [detail {len(collected)+1}/{target}] {url}")
            dhtml = fetch(s, url)
            detail = parse_detail(dhtml) if dhtml else {}
            row = merge(card, detail)

            record = {
                "source": "autocosmos.cl",
                "source_id": source_id_from_url(url),
                "url": url,
                "title": row.get("title"),
                "make": row.get("make"),
                "model": row.get("model"),
                "version": row.get("version"),
                "year": row.get("year"),
                "km": row.get("km"),
                "price_clp": row.get("price_clp"),
                "currency": row.get("currency") or "CLP",
                "fuel_type": row.get("fuel_type") or "other",
                "transmission": row.get("transmission") or "other",
                "body_type": row.get("body_type"),
                "region": row.get("region"),
                "commune": row.get("commune"),
                "posted_at": None,   # not exposed on public listing
                "scraped_at": now,
                "seller_type": row.get("seller_type"),
            }
            collected.append(record)

        page += 1
        time.sleep(delay)

    eprint(f"[done] collected {len(collected)} listings")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(collected, f, ensure_ascii=False, indent=2)
    eprint(f"[done] wrote {out_path}")
    return collected


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=40)
    ap.add_argument(
        "--out",
        default="/Users/seba/Desktop/seba-core/projects/car-tracker/data/autocosmos.json",
    )
    ap.add_argument("--delay", type=float, default=0.8)
    ap.add_argument("--max-pages", type=int, default=5)
    a = ap.parse_args()
    scrape(a.target, a.out, a.delay, a.max_pages)


if __name__ == "__main__":
    main()
