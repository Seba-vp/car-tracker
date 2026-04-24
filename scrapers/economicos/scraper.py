#!/usr/bin/env python3
"""
Economicos.cl used-car scraper — Playwright edition.

The stdlib requests / curl_cffi approach is now hard-403'd by economicos.cl.
A real headless Chromium passes through where curl_cffi doesn't (full TLS
stack + JS runtime + navigator profile).

Flow:
  1. Launch headless Chromium (es-CL locale, desktop UA).
  2. For a small set of pages (1, 2, 50, 100), navigate to
     https://www.economicos.cl/todo_chile/autos?pagina=N and collect the
     detail URLs.
  3. For each detail URL, navigate and parse the <li><span>Label:</span>
     Value</li> attribute block (same parser as before).
  4. Cap at `limit` listings, write JSON, exit 0.

Graceful-fail: any IP-level block (403 / challenge) -> write [] + exit 0.
"""

from __future__ import annotations

import html
import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urljoin

BASE = "https://www.economicos.cl"
LIST_URL = BASE + "/todo_chile/autos?pagina={page}"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)

FUEL_MAP = {
    "bencina": "gasolina",
    "gasolina": "gasolina",
    "diesel": "diesel",
    "diésel": "diesel",
    "hibrido": "hibrido",
    "híbrido": "hibrido",
    "electrico": "electrico",
    "eléctrico": "electrico",
    "gas": "gnc",
    "gnv": "gnc",
    "gnc": "gnc",
}
TRANS_MAP = {
    "mecánica": "manual",
    "mecanica": "manual",
    "manual": "manual",
    "automática": "automatic",
    "automatica": "automatic",
    "automático": "automatic",
    "automatico": "automatic",
}
SELLER_MAP = {
    "concesionario": "dealer",
    "automotora": "dealer",
    "empresa": "dealer",
    "particular": "private",
    "persona": "private",
}

ID_RE = re.compile(r"cod([A-Za-z0-9]+)\.html", re.I)
DETAIL_RE = re.compile(r"^/vehiculos/[^/]+cod[A-Za-z0-9]+\.html$")


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def polite_sleep() -> None:
    time.sleep(0.5 + random.random() * 0.5)


def _nav(page, url: str, timeout_ms: int = 30_000) -> str | None:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception as e:
        log(f"  ! goto {url}: {e}")
        return None
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except Exception:
        pass
    try:
        return page.content()
    except Exception as e:
        log(f"  ! content() {url}: {e}")
        return None


def listing_links(html_text: str) -> list[str]:
    # Lightweight regex extraction to avoid BeautifulSoup re-parse cost.
    urls: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r'href=["\'](/vehiculos/[^"\']+cod[A-Za-z0-9]+\.html)["\']', html_text):
        full = urljoin(BASE, m.group(1))
        if full not in seen:
            seen.add(full)
            urls.append(full)
    return urls


def parse_detail(url: str, text: str) -> dict | None:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(text, "html.parser")

    fields: dict[str, str] = {}
    for li in soup.select("li"):
        span = li.find("span")
        if not span:
            continue
        label = span.get_text(strip=True).rstrip(":").strip().lower()
        value = li.get_text(" ", strip=True)
        value = value[len(span.get_text(strip=True)) :].strip()
        value = html.unescape(value)
        if label and value:
            fields[label] = value

    if not ({"marca", "modelo", "año"} <= set(fields)):
        return None

    match = ID_RE.search(url)
    source_id = match.group(1) if match else None

    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else None
    if title:
        title = re.sub(r"\s+", " ", title)

    price_raw = fields.get("precio", "")
    price_clp: int | None = None
    currency = "CLP"
    digits = re.sub(r"[^\d]", "", price_raw)
    if digits:
        price_clp = int(digits)
    if "uf" in price_raw.lower():
        currency = "UF"

    year_raw = fields.get("año", "")
    year: int | None = None
    m = re.search(r"(19|20)\d{2}", year_raw)
    if m:
        year = int(m.group(0))

    fuel = FUEL_MAP.get(fields.get("combustible", "").strip().lower())
    trans = TRANS_MAP.get(fields.get("transmision", "").strip().lower())
    seller = SELLER_MAP.get(fields.get("vende", "").strip().lower())

    posted_at = None
    fecha = fields.get("fecha publicación") or fields.get("fecha publicacion")
    if fecha:
        posted_at = fecha.replace(" ", "T")

    return {
        "source": "economicos.cl",
        "source_id": source_id,
        "url": url,
        "title": title,
        "make": fields.get("marca"),
        "model": fields.get("modelo"),
        "version": None,
        "year": year,
        "km": None,
        "price_clp": price_clp if currency == "CLP" else None,
        "currency": currency,
        "fuel_type": fuel or "other" if fields.get("combustible") else None,
        "transmission": trans or "other" if fields.get("transmision") else None,
        "body_type": None,
        "region": fields.get("region"),
        "commune": None,
        "posted_at": posted_at,
        "scraped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seller_type": seller,
    }


DEFAULT_LIMIT = 100
DEFAULT_PAGES = [1, 2, 50, 100]


def collect(limit: int, pages: Iterable[int]) -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        log(f"playwright not installed: {e}")
        return []

    results: list[dict] = []
    seen_urls: set[str] = set()

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
            for pg in pages:
                if len(results) >= limit:
                    break
                list_url = LIST_URL.format(page=pg)
                log(f"[list] page {pg}: {list_url}")
                page_html = _nav(page, list_url)
                if not page_html or len(page_html) < 2_000:
                    log(f"[list] empty/tiny response page {pg} (size={len(page_html or '')}) — may be blocked")
                    continue
                links = [u for u in listing_links(page_html) if u not in seen_urls]
                log(f"[list] page {pg}: {len(links)} new listing URLs")
                if not links:
                    continue

                for url in links:
                    if len(results) >= limit:
                        break
                    seen_urls.add(url)
                    polite_sleep()
                    detail_html = _nav(page, url)
                    if not detail_html:
                        continue
                    row = parse_detail(url, detail_html)
                    if row is None:
                        log(f"[detail] parse miss {url}")
                        continue
                    results.append(row)
                    log(
                        f"[detail] {len(results)}/{limit} "
                        f"{row['make']} {row['model']} {row['year']} "
                        f"{row['price_clp']} {row['currency']}"
                    )
                polite_sleep()
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


def main(argv: list[str]) -> int:
    limit = int(argv[1]) if len(argv) > 1 else DEFAULT_LIMIT
    out_path = argv[2] if len(argv) > 2 else "data/economicos.json"
    data = collect(limit=limit, pages=DEFAULT_PAGES)
    dumped = json.dumps(data, ensure_ascii=False, indent=2)
    from pathlib import Path as _P

    _P(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fp:
        fp.write(dumped)
    log(f"[done] wrote {len(data)} rows to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
