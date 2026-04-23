#!/usr/bin/env python3
"""
Economicos.cl used-car scraper.

Strategy:
  1. Crawl listing pages at https://www.economicos.cl/todo_chile/autos?pagina=N
     (60 cards per page, 9k+ total results, no auth required).
  2. Extract detail URLs like /vehiculos/<make>-<model>-<year>-<region>-cod<id>.html
  3. Fetch each detail page and parse the <li><span>Label:</span> Value</li>
     block to get price, make, model, year, fuel, transmission, seller type,
     region, and posted_at.
  4. Normalize into the project schema and emit a JSON array.

Notes on the schema gap:
  * Economicos does NOT expose kilometers, body_type, version, or commune
    for auto listings — only make/model/year/fuel/transmission/region/seller.
  * We fill those fields with None to keep the schema shape consistent.
"""

from __future__ import annotations

import html
import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.economicos.cl"
LIST_URL = BASE + "/todo_chile/autos?pagina={page}"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.6",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

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


def fetch(session: requests.Session, url: str) -> str:
    resp = session.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    # Server declares UTF-8 in Content-Type but sends windows-1252-ish bytes sometimes;
    # requests gets it right from the meta tag, but we force UTF-8 to be safe.
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def listing_links(html_text: str) -> list[str]:
    soup = BeautifulSoup(html_text, "html.parser")
    urls: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if DETAIL_RE.match(href):
            full = urljoin(BASE, href)
            if full not in seen:
                seen.add(full)
                urls.append(full)
    return urls


def parse_detail(url: str, text: str) -> dict | None:
    soup = BeautifulSoup(text, "html.parser")

    # The attribute list uses <li><span>Label:</span> Value</li>
    fields: dict[str, str] = {}
    for li in soup.select("li"):
        span = li.find("span")
        if not span:
            continue
        label = span.get_text(strip=True).rstrip(":").strip().lower()
        # Value is the text after the span
        value = li.get_text(" ", strip=True)
        value = value[len(span.get_text(strip=True)):].strip()
        value = html.unescape(value)
        if label and value:
            fields[label] = value

    # Require at least marca + modelo + año or we drop it
    if not ({"marca", "modelo", "año"} <= set(fields)):
        return None

    match = ID_RE.search(url)
    source_id = match.group(1) if match else None

    # Title from H1 when possible
    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else None
    if title:
        title = re.sub(r"\s+", " ", title)

    # Price parsing: "6.490.000" (CLP) or sometimes a UF amount
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
        # Already ISO-ish: 2026-04-22 22:09:00
        posted_at = fecha.replace(" ", "T")

    return {
        "source": "economicos.cl",
        "source_id": source_id,
        "url": url,
        "title": title,
        "make": fields.get("marca"),
        "model": fields.get("modelo"),
        "version": None,  # not exposed
        "year": year,
        "km": None,  # not exposed
        "price_clp": price_clp if currency == "CLP" else None,
        "currency": currency,
        "fuel_type": fuel or "other" if fields.get("combustible") else None,
        "transmission": trans or "other" if fields.get("transmision") else None,
        "body_type": None,  # not exposed
        "region": fields.get("region"),
        "commune": None,  # not exposed
        "posted_at": posted_at,
        "scraped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seller_type": seller,
    }


def polite_sleep() -> None:
    time.sleep(0.5 + random.random() * 0.5)


def collect(limit: int, max_pages: int = 5, pages: Iterable[int] | None = None) -> list[dict]:
    session = requests.Session()
    results: list[dict] = []
    seen_urls: set[str] = set()

    page_iter = list(pages) if pages is not None else list(range(1, max_pages + 1))
    for page in page_iter:
        list_url = LIST_URL.format(page=page)
        print(f"[list] page {page}: {list_url}", file=sys.stderr)
        try:
            page_html = fetch(session, list_url)
        except requests.HTTPError as exc:
            print(f"[list] HTTP error on page {page}: {exc}", file=sys.stderr)
            break

        links = [u for u in listing_links(page_html) if u not in seen_urls]
        print(f"[list] page {page}: {len(links)} new listing URLs", file=sys.stderr)
        if not links:
            break

        for url in links:
            if len(results) >= limit:
                return results
            seen_urls.add(url)
            polite_sleep()
            try:
                detail_html = fetch(session, url)
            except requests.HTTPError as exc:
                print(f"[detail] skip {url}: {exc}", file=sys.stderr)
                continue
            row = parse_detail(url, detail_html)
            if row is None:
                print(f"[detail] parse miss {url}", file=sys.stderr)
                continue
            results.append(row)
            print(
                f"[detail] {len(results)}/{limit} "
                f"{row['make']} {row['model']} {row['year']} "
                f"{row['price_clp']} {row['currency']}",
                file=sys.stderr,
            )

        polite_sleep()

    return results


def main(argv: list[str]) -> int:
    limit = int(argv[1]) if len(argv) > 1 else 30
    out_path = argv[2] if len(argv) > 2 else None
    # Mix first few pages (new dealer inventory) with deeper pages
    # (older particular listings) so the sample represents the source.
    pages = [1, 2, 50, 100, 150]
    data = collect(limit=limit, max_pages=5, pages=pages)
    dumped = json.dumps(data, ensure_ascii=False, indent=2)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fp:
            fp.write(dumped)
        print(f"[done] wrote {len(data)} rows to {out_path}", file=sys.stderr)
    else:
        print(dumped)
        print(f"[done] {len(data)} rows", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
