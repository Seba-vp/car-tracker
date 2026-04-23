#!/usr/bin/env python3
"""
Chileautos.cl scraper.

Strategy (discovered via investigation):
- Site is protected by DataDome on HTML pages under /vehiculos/*.
- Public-web Next.js JSON "backend-for-frontend" endpoints are reachable without
  a DataDome challenge when hit directly:
    * Search results:  /_api/search-core/?q=<CarsalesQuery>&offset=<int>
    * Listing details: /_api/details-core/<CP-AD-id>
- These return Carsales' "Merlin" UI-as-JSON tree. Listing metadata is embedded
  inside the `tracking` blocks for each tile (search) and the pageLoad tracking
  blob (details).
- Search query used: `(And.(C.Category.autos.)_.State.Usado.)` — category=autos,
  state=used. That covers the "usado" catalog (~62k listings).

We:
  1. Collect listing CP-AD ids + detail URLs by paging through /_api/search-core.
  2. For each id, call /_api/details-core/<id> and extract the pageLoad tracking
     dict which contains make, model, badge, year, price, odometermin, fueltype,
     genericgeartype, bodystyle, sellertype, state, publishDate, etc.
  3. Normalise to our schema. Write JSON array.

If the search API ever gets blocked (DataDome challenges), fallback would be
headless browser (Playwright) — noted in the report.
"""

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = "https://www.chileautos.cl"
SEARCH_API = f"{BASE}/_api/search-core/"
DETAILS_API = f"{BASE}/_api/details-core/"
QUERY = "(And.(C.Category.autos.)_.State.Usado.)"

OUT_PATH = Path(
    "/Users/seba/Desktop/seba-core/projects/car-tracker/data/chileautos.json"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
    "Referer": f"{BASE}/",
}

# Enum normalisation
FUEL_MAP = {
    "bencina": "gasolina",
    "gasolina": "gasolina",
    "diesel": "diesel",
    "diésel": "diesel",
    "hibrido": "hibrido",
    "híbrido": "hibrido",
    "electrico": "electrico",
    "eléctrico": "electrico",
    "gnc": "gnc",
    "gas natural": "gnc",
    "glp": "gnc",
}
TRANS_MAP = {
    "manual": "manual",
    "mecánico": "manual",
    "automatic": "automatic",
    "automático": "automatic",
    "automatica": "automatic",
    "automática": "automatic",
    "cvt": "automatic",
    "tiptronic": "automatic",
    "dsg": "automatic",
    "dct": "automatic",
}
SELLER_MAP = {
    "agencia": "dealer",
    "particular": "private",
    "private": "private",
    "dealer": "dealer",
}


def log(msg):
    print(f"[chileautos] {msg}", file=sys.stderr, flush=True)


def polite_sleep():
    time.sleep(0.7)


def fetch_json(url, session, retries=2):
    for attempt in range(retries + 1):
        try:
            r = session.get(url, headers=HEADERS, timeout=20)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith(
                "application/json"
            ):
                return r.json()
            # DataDome challenge returns text/html 403
            if r.status_code == 403:
                log(f"  403 (likely DataDome) on {url}")
                return None
            log(f"  HTTP {r.status_code} on {url}")
        except Exception as e:
            log(f"  error {e} (attempt {attempt + 1})")
        time.sleep(1.5)
    return None


# --- Carsales Merlin JSON helpers ------------------------------------------------

def walk(node):
    """Yield every dict inside a nested dict/list structure."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


def extract_search_listings(search_json):
    """Return list of {networkId, url, tracking}. One entry per tile."""
    if not search_json:
        return []

    # Gather every dict that has a networkId starting with "CP-AD-"
    by_id = {}
    for d in walk(search_json):
        nid = d.get("networkId")
        if isinstance(nid, str) and nid.startswith("CP-AD-"):
            cur = by_id.setdefault(nid, {})
            # keep all primitive fields we see (later blobs are richer)
            for k, v in d.items():
                if not isinstance(v, (dict, list)) and k not in cur:
                    cur[k] = v

    # Pull the readable detail URLs by recursing instead of regex (json.dumps
    # formatting varies). Any dict with key "url" that matches the detail
    # pattern gives us a pretty URL.
    url_map = {}
    for d in walk(search_json):
        u = d.get("url")
        if isinstance(u, str):
            m = re.match(r"^(/vehiculos/detalles/[a-zA-Z0-9\-]+/(CP-AD-\d+)/)", u)
            if m:
                path, nid = m.group(1), m.group(2)
                url_map.setdefault(nid, path)

    out = []
    for nid, tr in by_id.items():
        path = url_map.get(nid, f"/vehiculos/detalles/{nid}/")
        out.append(
            {"networkId": nid, "url": BASE + path, "tracking": tr}
        )
    return out


def extract_details_tracking(details_json):
    """Return the richest tracking dict (pageLoad) from a details-core response."""
    if not details_json:
        return None
    best = None
    best_score = -1
    for d in walk(details_json):
        if "networkId" in d and "make" in d and "model" in d:
            score = sum(
                1
                for k in (
                    "year",
                    "price",
                    "odometermin",
                    "fueltype",
                    "genericgeartype",
                    "bodystyle",
                    "sellertype",
                    "publishDate",
                    "badge",
                    "state",
                )
                if k in d
            )
            if score > best_score:
                best_score = score
                best = d
    return best


def extract_heading(details_json):
    """The human-readable h1 on the detail page."""
    if not details_json:
        return None
    for d in walk(details_json):
        v = d.get("variant")
        if (
            isinstance(v, str)
            and v.startswith("heading-")
            and isinstance(d.get("value"), str)
            and "$" not in d["value"]
            and len(d["value"]) > 10
        ):
            return d["value"]
    return None


def extract_region_commune(details_json):
    """Pull region + commune from the details JSON key/values."""
    if not details_json:
        return None, None
    text = json.dumps(details_json, ensure_ascii=False)
    # Seller location often appears as "Ubicación" label + value
    region = None
    commune = None
    # Find label "Ubicación" or "Región" pattern
    for m in re.finditer(
        r'"value":"Ubicación"[^}]*?"value":"([^"]+)"', text
    ):
        region = m.group(1)
        break
    return region, commune


# --- Normalisation ---------------------------------------------------------------

def norm_fuel(v):
    if not v:
        return None
    return FUEL_MAP.get(v.strip().lower(), "other")


def norm_trans(v):
    if not v:
        return None
    vl = v.strip().lower()
    return TRANS_MAP.get(vl, "other")


def norm_seller(v):
    if not v:
        return None
    return SELLER_MAP.get(v.strip().lower(), None)


def to_int(v):
    if v is None:
        return None
    if isinstance(v, int):
        return v
    try:
        return int(str(v).replace(".", "").replace(",", "").strip())
    except Exception:
        return None


def normalise(src_listing, details_tracking, heading, url):
    """Merge search+detail tracking into our schema."""
    t = details_tracking or src_listing.get("tracking", {})
    nid = src_listing["networkId"]

    make = (t.get("make") or "").title() or None
    model = (t.get("model") or "").title() or None
    version = t.get("badge") or None
    year = to_int(t.get("year"))
    price = to_int(t.get("price"))
    km = to_int(t.get("odometermin"))

    published = t.get("publishDate")
    posted_at = None
    if published and isinstance(published, str):
        # e.g. 2025-11-24t21:05:48
        try:
            posted_at = datetime.fromisoformat(published.replace("t", "T")).isoformat()
        except Exception:
            posted_at = published

    title = heading or " ".join(
        x for x in [str(year or ""), make or "", model or "", version or ""] if x
    ).strip()

    region = (t.get("state") or "").title() or None

    return {
        "source": "chileautos.cl",
        "source_id": nid,
        "url": url,
        "title": title,
        "make": make,
        "model": model,
        "version": version,
        "year": year,
        "km": km,
        "price_clp": price,
        "currency": "CLP",
        "fuel_type": norm_fuel(t.get("fueltype")),
        "transmission": norm_trans(t.get("genericgeartype")),
        "body_type": (t.get("bodystyle") or None),
        "region": region,
        "commune": None,
        "posted_at": posted_at,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "seller_type": norm_seller(t.get("sellertype")),
    }


# --- Main -----------------------------------------------------------------------

def collect_listing_ids(session, target_count=50, max_pages=8):
    """Page through search-core collecting unique listing refs."""
    seen = {}  # networkId -> {url, tracking}
    offset = 0
    for page in range(max_pages):
        url = f"{SEARCH_API}?q={QUERY}&offset={offset}"
        log(f"search page {page + 1} offset={offset}")
        j = fetch_json(url, session)
        if not j:
            log("  search fetch failed; stopping")
            break
        tiles = extract_search_listings(j)
        new = 0
        for t in tiles:
            if t["networkId"] not in seen:
                seen[t["networkId"]] = t
                new += 1
        log(f"  +{new} new  (total {len(seen)})")
        if len(seen) >= target_count:
            break
        if new == 0:
            log("  no new results, stopping")
            break
        offset += 20  # step partially through the tile list
        polite_sleep()
    return list(seen.values())


def scrape(target_count=40):
    session = requests.Session()
    session.headers.update(HEADERS)

    # warm the session (get DataDome cookies from homepage — homepage returns 200)
    try:
        session.get(BASE + "/", timeout=20)
    except Exception:
        pass

    log("=== Step 1: enumerate listings via /_api/search-core ===")
    refs = collect_listing_ids(session, target_count=target_count)
    log(f"collected {len(refs)} listing refs total")

    log("=== Step 2: fetch each detail via /_api/details-core ===")
    out = []
    for i, ref in enumerate(refs, 1):
        nid = ref["networkId"]
        api_url = f"{DETAILS_API}{nid}"
        log(f"[{i}/{len(refs)}] {nid}")
        dj = fetch_json(api_url, session)
        if not dj:
            # Fall back to search-time tracking (less complete)
            log("  using search-tile tracking only")
            out.append(normalise(ref, None, None, ref["url"]))
            polite_sleep()
            continue
        det = extract_details_tracking(dj)
        heading = extract_heading(dj)
        out.append(normalise(ref, det, heading, ref["url"]))
        polite_sleep()

    return out


def main():
    target = 40
    if len(sys.argv) > 1:
        try:
            target = int(sys.argv[1])
        except ValueError:
            pass
    listings = scrape(target_count=target)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(listings, ensure_ascii=False, indent=2))
    log(f"wrote {len(listings)} listings to {OUT_PATH}")


if __name__ == "__main__":
    main()
