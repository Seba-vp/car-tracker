#!/usr/bin/env python3
"""
Kavak Chile scraper — Playwright edition.

Kavak's listing page is a Next.js App-Router page that streams React Server
Component (RSC) payloads inline. We can still parse those with the same
regexes as before — the difference is that we fetch them through a real
Chromium instance (full TLS + JS fingerprint) instead of stdlib requests.

Flow:
  1. Launch headless Chromium.
  2. For each page of /cl/usados, navigate, let the RSC payload stream in,
     extract listing stubs from the rendered HTML.
  3. For each stub, fetch the VIP page (same browser context) and merge
     JSON-LD Car data + hub region/commune.
  4. Cap at target listings, write JSON.

Graceful-fail: any IP-level block -> write [] + exit 0.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Iterable

BASE = "https://www.kavak.com"
LIST_URL = BASE + "/cl/usados"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.2 Safari/605.1.15"
)


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def polite_sleep(min_s: float = 0.5, max_s: float = 1.0) -> None:
    time.sleep(random.uniform(min_s, max_s))


def _unescape_rsc(s: str) -> str:
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


_CARD_ANCHOR = re.compile(
    r'\\"id\\":\\"(?P<id>\d+)\\",\\"url\\":\\"(?P<url>https://www\.kavak\.com/cl/venta/[^\\]+)\\"'
)


def parse_list_page(html: str) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()

    for m in _CARD_ANCHOR.finditer(html):
        source_id = m.group("id")
        if source_id in seen:
            continue
        seen.add(source_id)

        start = m.start()
        window = html[start : start + 4000]

        def pick(key: str) -> str | None:
            mm = re.search(rf'\\"{key}\\":\\"([^"\\]*)\\"', window)
            return _unescape_rsc(mm.group(1)) if mm else None

        subtitle = pick("subtitle") or ""
        parts = [p.strip() for p in subtitle.split("•")]

        year = _to_int(parts[0]) if parts else None
        km = _to_int(parts[1]) if len(parts) > 1 else None
        version = parts[2] if len(parts) > 2 else None
        transmission = parts[3] if len(parts) > 3 else None

        def analytic(key: str) -> str | None:
            mm = re.search(rf'\\"{key}\\":\\"([^"\\]*)\\"', window)
            return _unescape_rsc(mm.group(1)) if mm else None

        make = analytic("car_make")
        model = analytic("car_model")
        region = pick("footerInfo")

        price_raw = pick("mainPrice") or ""
        price_clp = _to_int(price_raw)

        body = None
        url_m = re.search(r"/cl/venta/([^\"\\]+)", m.group("url"))
        if url_m:
            slug = url_m.group(1)
            slug_parts = slug.split("-")
            if len(slug_parts) >= 2 and re.fullmatch(r"\d{4}", slug_parts[-1]):
                body = slug_parts[-2]

        title = pick("title")
        if title:
            title = title.replace(" • ", " ")

        img = None
        for mi in re.finditer(
            r'\\"(?:image|photo|thumbnail|src)\\":\\"(https?://[^"\\]+)\\"',
            window,
        ):
            candidate = _unescape_rsc(mi.group(1))
            if any(x in candidate for x in ("cloudinary", "kavak", "images/")):
                img = candidate
                break

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
                "image_url": img,
            }
        )
    return cards


def _find_car_ld(html_text: str) -> dict[str, Any] | None:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_text, "html.parser")
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


def _find_hub(html_text: str) -> tuple[str | None, str | None]:
    region = None
    commune = None

    m = re.search(r'\\"region\\":\\"([^"\\]+)\\"', html_text)
    if m:
        region = _unescape_rsc(m.group(1))

    m = re.search(r'\\"address\\":\\"([^"\\]+)\\"', html_text)
    if m:
        addr = _unescape_rsc(m.group(1))
        segs = [s.strip() for s in addr.split(",")]
        if len(segs) >= 2:
            cand = segs[1]
            cand = re.sub(r"^\d+\s*", "", cand)
            commune = cand or None
    return region, commune


def enrich_from_vip(stub: dict[str, Any], html_text: str) -> dict[str, Any]:
    out = dict(stub)
    car = _find_car_ld(html_text) or {}

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

    region, commune = _find_hub(html_text)
    out["region"] = out.get("region") or region
    out["commune"] = commune

    image = car.get("image")
    image_urls: list[str] = []
    if isinstance(image, str):
        image_urls.append(image)
    elif isinstance(image, list):
        image_urls.extend([u for u in image if isinstance(u, str)])
    seen: set[str] = set()
    image_urls = [u for u in image_urls if not (u in seen or seen.add(u))]
    if image_urls:
        out["image_url"] = out.get("image_url") or image_urls[0]
        out["image_urls"] = image_urls
    return out


def _nav(page, url: str, timeout_ms: int = 30_000) -> str | None:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception as e:
        log(f"    ! goto {url}: {e}")
        return None
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except Exception:
        pass
    try:
        return page.content()
    except Exception as e:
        log(f"    ! content() {url}: {e}")
        return None


def scrape(target: int, enrich: bool) -> list[dict[str, Any]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        log(f"playwright not installed: {e}")
        return []

    results: list[dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            user_agent=UA,
            locale="es-CL",
            timezone_id="America/Santiago",
            viewport={"width": 1366, "height": 900},
            extra_http_headers={
                "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
            },
        )
        page = context.new_page()

        try:
            stubs: list[dict[str, Any]] = []
            seen_ids: set[str] = set()

            page_n = 1
            while len(stubs) < target and page_n <= 60:
                url = LIST_URL if page_n == 1 else f"{LIST_URL}?page={page_n}"
                log(f"[list] page {page_n} -> {url}")
                html = _nav(page, url)
                if not html or len(html) < 2_000:
                    log(f"    ! empty/tiny response (size={len(html or '')})")
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
                page_n += 1
                polite_sleep()

            stubs = stubs[:target]
            log(f"[list] collected {len(stubs)} stubs")

            now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

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
                    "posted_at": None,
                    "scraped_at": now_iso,
                    "seller_type": "dealer",
                    "image_url": stub.get("image_url"),
                    "image_urls": None,
                }

                if enrich:
                    vip_html = _nav(page, stub["url"])
                    if vip_html:
                        enriched = enrich_from_vip(record, vip_html)
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
                                    "image_url",
                                    "image_urls",
                                )
                            }
                        )
                        record["currency"] = record.get("currency") or "CLP"
                    polite_sleep()

                results.append(record)
        finally:
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass

    return results


DEFAULT_TARGET = 100


def main(argv: Iterable[str] | None = None) -> int:
    env_default = DEFAULT_TARGET
    override = os.environ.get("SCRAPE_TARGET")
    if override:
        try:
            env_default = int(override)
        except ValueError:
            pass
    ap = argparse.ArgumentParser(description="Scrape Kavak Chile used car listings (Playwright).")
    ap.add_argument("--target", type=int, default=env_default, help=f"Number of listings to collect (default {DEFAULT_TARGET}).")
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
