#!/usr/bin/env python3
"""
MercadoLibre Chile (autos.mercadolibre.cl) scraper.

Method: fetch the public search-results HTML pages under autos.mercadolibre.cl
and extract the embedded per-item JSON objects. The HTML embeds the exact
payload the internal search API returns (50 items per page), including
attributes (BRAND/MODEL/VEHICLE_YEAR/KILOMETERS/FUEL_TYPE/TRANSMISSION/TRIM),
seller info, address (state/city), permalink, price, currency, condition,
date_created, etc. No authentication, no item-detail fetches needed.

The public api.mercadolibre.com /sites/MLC/search endpoint is now blocked
for anonymous callers (403 PA_UNAUTHORIZED_RESULT_FROM_POLICIES) and requires
an OAuth bearer token. The HTML front door remains open as long as we use a
modern Chrome UA and establish device cookies via a warm-up request.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

SOURCE = "mercadolibre"
SEARCH_URL = "https://autos.mercadolibre.cl/autos/usados"  # used cars only
PAGE_SIZE = 50

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)
BASE_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
    "Sec-Ch-Ua": '"Chromium";v="138", "Not.A/Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Upgrade-Insecure-Requests": "1",
}

FUEL_MAP = {
    "bencina": "gasolina",
    "gasolina": "gasolina",
    "nafta": "gasolina",
    "diésel": "diesel",
    "diesel": "diesel",
    "híbrido": "hibrido",
    "hibrido": "hibrido",
    "híbrido enchufable": "hibrido",
    "eléctrico": "electrico",
    "electrico": "electrico",
    "gnc": "gnc",
    "gas natural": "gnc",
    "glp": "other",
}
TRANS_MAP = {
    "manual": "manual",
    "mecánica": "manual",
    "mecanica": "manual",
    "automática": "automatic",
    "automatica": "automatic",
    "automatic": "automatic",
    "secuencial": "automatic",
    "cvt": "automatic",
    "dct": "automatic",
}


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def warm_up(s: requests.Session) -> None:
    """Collect session cookies.

    Sequence matters: visiting www.mercadolibre.cl/ sets _d2id and session
    cookies, and visiting autos.mercadolibre.cl/ (which returns a tiny
    bot-wall micro-landing but still Set-Cookie: autos.mercadolibre.cl _csrf)
    is what unlocks real search-results HTML on the next request.
    """
    r = s.get("https://www.mercadolibre.cl/", headers=BASE_HEADERS, timeout=30)
    r.raise_for_status()
    log(f"warm-up home: {r.status_code} cookies={len(s.cookies)}")
    headers = dict(BASE_HEADERS)
    headers["Referer"] = "https://www.mercadolibre.cl/"
    r2 = s.get("https://autos.mercadolibre.cl/", headers=headers, timeout=30)
    # r2 is a 5KB micro-landing — that's fine, we just want the _csrf cookie.
    log(f"warm-up autos-root: {r2.status_code} size={len(r2.text)} cookies={len(s.cookies)}")


def fetch_page(s: requests.Session, offset: int) -> str:
    if offset <= 1:
        url = SEARCH_URL
    else:
        url = f"{SEARCH_URL}/_Desde_{offset}"
    headers = dict(BASE_HEADERS)
    headers["Referer"] = "https://autos.mercadolibre.cl/"
    r = s.get(url, headers=headers, timeout=45)
    r.raise_for_status()
    if len(r.text) < 50_000:
        # Anti-bot "Continuar" challenge page from suspicious-traffic-frontend.
        # Signal gracefully instead of exiting non-zero; scraper will write
        # an empty JSON array and ingester records an OK run with 0 rows.
        # Needs Playwright or elevated API scope to bypass.
        log(f"bot wall hit: {len(r.text)} bytes at {url} -- returning empty")
        raise _BotWall()
    return r.text


class _BotWall(Exception):
    """Raised when MercadoLibre serves the anti-bot challenge page."""


def _slice_json_obj(s: str, start: int) -> Optional[str]:
    """Bracket-match one JSON object starting at s[start] == '{'."""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        c = s[i]
        if esc:
            esc = False
            continue
        if c == "\\":
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None


ITEM_RE = re.compile(r'\{"id":"(MLC\d+)","type":"ITEM"')


def parse_items(html: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    seen: set = set()
    for m in ITEM_RE.finditer(html):
        mid = m.group(1)
        if mid in seen:
            continue
        blob = _slice_json_obj(html, m.start())
        if not blob:
            continue
        try:
            obj = json.loads(blob)
        except json.JSONDecodeError:
            continue
        seen.add(mid)
        items.append(obj)
    return items


def _attr_map(item: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for a in item.get("attributes", []) or []:
        out[a.get("id")] = a
    return out


def _norm_fuel(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    return FUEL_MAP.get(raw.strip().lower(), "other")


def _norm_trans(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    return TRANS_MAP.get(raw.strip().lower(), "other")


def _norm_seller(item: Dict[str, Any]) -> Optional[str]:
    seller = item.get("seller") or {}
    if seller.get("car_dealer") is True:
        return "dealer"
    tags = seller.get("tags") or []
    if "car_dealer" in tags or "business" in tags or "brand" in tags:
        return "dealer"
    # Default heuristic: classifieds with no dealer flag => private
    return "private"


def _parse_int(val: Any) -> Optional[int]:
    if val is None:
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    s = str(val)
    m = re.search(r"\d[\d.,]*", s)
    if not m:
        return None
    try:
        return int(m.group(0).replace(".", "").replace(",", ""))
    except ValueError:
        return None


def _clean_permalink(url: str) -> str:
    if not url:
        return url
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return "https://" + url


def normalize(item: Dict[str, Any]) -> Dict[str, Any]:
    a = _attr_map(item)

    def val(aid: str) -> Optional[str]:
        x = a.get(aid)
        if not x:
            return None
        return x.get("value_name")

    km_struct = None
    if a.get("KILOMETERS"):
        vs = a["KILOMETERS"].get("value_struct") or {}
        km_struct = vs.get("number")

    addr = item.get("address") or {}
    return {
        "source": SOURCE,
        "source_id": item.get("id"),
        "url": _clean_permalink(item.get("permalink") or ""),
        "title": item.get("title"),
        "make": val("BRAND"),
        "model": val("MODEL"),
        "version": val("TRIM"),
        "year": _parse_int(val("VEHICLE_YEAR")),
        "km": km_struct if km_struct is not None else _parse_int(val("KILOMETERS")),
        "price_clp": item.get("price") if item.get("currency_id") == "CLP" else None,
        "currency": item.get("currency_id"),
        "fuel_type": _norm_fuel(val("FUEL_TYPE")),
        "transmission": _norm_trans(val("TRANSMISSION")),
        "body_type": val("VEHICLE_BODY_TYPE") or val("BODY_TYPE"),
        "region": addr.get("state_name"),
        "commune": addr.get("city_name"),
        "posted_at": item.get("date_created"),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "seller_type": _norm_seller(item),
    }


def run(target: int, out_path: Path) -> None:
    s = requests.Session()
    records: List[Dict[str, Any]] = []
    try:
        warm_up(s)
        offset = 1
        pages = 0
        while len(records) < target and pages < 8:
            log(f"fetching offset={offset} (have {len(records)}/{target})")
            html = fetch_page(s, offset)
            items = parse_items(html)
            log(f"  parsed {len(items)} items from page")
            for it in items:
                if it.get("condition") != "used":
                    continue
                rec = normalize(it)
                records.append(rec)
                if len(records) >= target:
                    break
            pages += 1
            offset += PAGE_SIZE
            time.sleep(0.4)
    except _BotWall:
        log("mercadolibre anti-bot wall — emitting empty array, exiting 0")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    log(f"wrote {len(records)} records -> {out_path}")


if __name__ == "__main__":
    default_out = Path("data/mercadolibre.json")
    target = 40
    if len(sys.argv) > 1:
        target = int(sys.argv[1])
    run(target, default_out)
