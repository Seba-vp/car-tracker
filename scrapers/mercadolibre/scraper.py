#!/usr/bin/env python3
"""
MercadoLibre Chile (autos.mercadolibre.cl) scraper — Playwright edition.

The stdlib requests / curl_cffi approach hits a "suspicious-traffic-frontend"
challenge page (~21 KB) that requires the user to click "Continuar" before the
real search results render. A real Chromium instance handles it trivially.

Flow:
  1. Launch headless Chromium with a realistic UA + locale es-CL.
  2. Navigate to https://autos.mercadolibre.cl/autos/usados
  3. If we land on a /sentry/ challenge (or small HTML), try to click the
     Continuar button and wait for the real listings page to render.
  4. Extract embedded JSON objects from the page HTML (same regex + bracket
     matcher as the previous scraper).
  5. Paginate by appending /_Desde_<offset>.
  6. Normalize rows to the project schema.

Graceful-fail: if we still can't get real listings (e.g. IP-based block),
write an empty array + exit 0.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SOURCE = "mercadolibre"
SEARCH_URL = "https://autos.mercadolibre.cl/autos/usados"
PAGE_SIZE = 50
DEFAULT_TARGET = 200

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)

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


def _slice_json_obj(s: str, start: int) -> Optional[str]:
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


def _get_listings_html(page, url: str) -> str:
    """Navigate to url, handle Continuar challenge if present, return HTML."""
    log(f"  goto {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    except Exception as e:
        log(f"  ! goto failed: {e}")
        return ""

    # If we landed on a /sentry/ challenge, try to click Continuar and wait.
    curr = page.url
    if "/sentry/" in curr or "suspicious" in curr.lower():
        log(f"  challenge page: {curr}")
        clicked = False
        for sel in (
            'button:has-text("Continuar")',
            'input[type="submit"][value*="Continuar"]',
            'button[type="submit"]',
        ):
            try:
                el = page.query_selector(sel)
                if el:
                    el.click()
                    clicked = True
                    log(f"  clicked selector: {sel}")
                    break
            except Exception as e:
                log(f"  click {sel!r} failed: {e}")
        if clicked:
            try:
                page.wait_for_url(
                    lambda u: "/sentry/" not in u, timeout=30_000
                )
            except Exception as e:
                log(f"  wait_for_url post-click failed: {e}")

    # Wait for listings to actually render.
    try:
        page.wait_for_load_state("networkidle", timeout=20_000)
    except Exception:
        pass

    try:
        html = page.content()
    except Exception as e:
        log(f"  ! content() failed: {e}")
        return ""

    if len(html) < 50_000 or "/sentry/" in page.url:
        log(f"  bot wall / tiny page: url={page.url} size={len(html)}")
        return ""
    return html


def run(target: int, out_path: Path) -> None:
    records: List[Dict[str, Any]] = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        log(f"playwright not installed: {e}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("[]\n", encoding="utf-8")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
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
            # Warm-up: visit mercadolibre.cl home first to collect cookies.
            try:
                page.goto("https://www.mercadolibre.cl/", wait_until="domcontentloaded", timeout=30_000)
                log(f"warm-up home: {page.url}")
            except Exception as e:
                log(f"warm-up home failed: {e}")

            offset = 1
            pages_fetched = 0
            while len(records) < target and pages_fetched < 8:
                url = SEARCH_URL if offset <= 1 else f"{SEARCH_URL}/_Desde_{offset}"
                log(f"fetching offset={offset} (have {len(records)}/{target})")
                html = _get_listings_html(page, url)
                if not html:
                    log("  empty HTML — stopping pagination")
                    break
                items = parse_items(html)
                log(f"  parsed {len(items)} items from page")
                if not items:
                    break
                for it in items:
                    if it.get("condition") != "used":
                        continue
                    records.append(normalize(it))
                    if len(records) >= target:
                        break
                pages_fetched += 1
                offset += PAGE_SIZE
                time.sleep(0.4)
        finally:
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    log(f"wrote {len(records)} records -> {out_path}")


if __name__ == "__main__":
    default_out = Path("data/mercadolibre.json")
    target = DEFAULT_TARGET
    if len(sys.argv) > 1:
        target = int(sys.argv[1])
    run(target, default_out)
