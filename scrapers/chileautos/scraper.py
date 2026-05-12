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
import os
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

OUT_PATH = Path("data/chileautos.json")

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


def _extract_gallery_images(tile_node):
    """Return a list of non-placeholder image URLs from a ListingCard's gallery."""
    urls = []
    gal = tile_node.get("gallery") if isinstance(tile_node, dict) else None
    if not isinstance(gal, dict):
        return urls
    for ch in gal.get("children") or []:
        if isinstance(ch, dict) and ch.get("type") == "Image":
            u = ch.get("url")
            if isinstance(u, str) and "pxcrush" in u and "placeholder" not in u:
                urls.append(u)
    return urls


def _walk_find_listing_cards(node):
    """Yield each ListingCard dict found anywhere in the tree."""
    if isinstance(node, dict):
        if node.get("type") == "ListingCard":
            yield node
        for v in node.values():
            yield from _walk_find_listing_cards(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_find_listing_cards(v)


def extract_search_listings(search_json):
    """Return list of {networkId, url, tracking, images}. One entry per tile."""
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

    # Images come straight from the ListingCard gallery. Match card -> nid by
    # finding the nearest networkId descendant of each card.
    image_map: dict[str, list[str]] = {}
    for card in _walk_find_listing_cards(search_json):
        # Find this card's networkId
        nid = None
        for sub in walk(card):
            n = sub.get("networkId")
            if isinstance(n, str) and n.startswith("CP-AD-"):
                nid = n
                break
        if not nid:
            continue
        imgs = _extract_gallery_images(card)
        if imgs and nid not in image_map:
            image_map[nid] = imgs

    out = []
    for nid, tr in by_id.items():
        path = url_map.get(nid, f"/vehiculos/detalles/{nid}/")
        out.append(
            {
                "networkId": nid,
                "url": BASE + path,
                "tracking": tr,
                "images": image_map.get(nid, []),
            }
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


def extract_detail_images(details_json):
    """Collect pxcrush car image URLs from a details-core response."""
    if not details_json:
        return []
    urls = []
    seen = set()
    for d in walk(details_json):
        if d.get("type") == "Image" and isinstance(d.get("url"), str):
            u = d["url"]
            if "pxcrush" in u and "placeholder" not in u and "/cars/" in u:
                if u not in seen:
                    seen.add(u)
                    urls.append(u)
    return urls


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


def normalise(src_listing, details_tracking, heading, url, detail_images=None):
    """Merge search+detail tracking into our schema."""
    t = details_tracking or src_listing.get("tracking", {})
    nid = src_listing["networkId"]

    # Images: prefer detail (richer) but fall back to the search-tile gallery.
    images = list(detail_images or [])
    if not images:
        images = list(src_listing.get("images") or [])
    # Dedupe while preserving order
    seen_img = set()
    images = [u for u in images if not (u in seen_img or seen_img.add(u))]
    image_url = images[0] if images else None

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
        "image_url": image_url,
        "image_urls": images or None,
    }


# --- Main -----------------------------------------------------------------------

REGIONS = [
    "metropolitana-de-santiago",
    "valparaiso",
    "biobio",
    "maule",
    "ohiggins",
    "araucania",
    "los-lagos",
    "coquimbo",
    "antofagasta",
    "los-rios",
    "atacama",
    "nuble",
    "tarapaca",
    "arica-parinacota",
    "magallanes",
    "aysen",
]

MAKES = [
    "toyota", "chevrolet", "nissan", "hyundai", "kia", "mazda", "suzuki",
    "ford", "mitsubishi", "peugeot", "volkswagen", "honda", "jeep",
    "subaru", "mercedes-benz", "bmw", "audi", "renault", "mg",
    "great-wall", "dongfeng", "chery", "changan", "jac", "jetour",
]

# Year buckets in 3-year windows covering modern used inventory.
# Each tuple is (lo_year, hi_year_inclusive).
YEAR_BUCKETS = [
    (1990, 2000),
    (2001, 2005),
    (2006, 2008),
    (2009, 2011),
    (2012, 2014),
    (2015, 2017),
    (2018, 2020),
    (2021, 2023),
    (2024, 2026),
]

# Price buckets in CLP. The last open-ended bucket uses a very high cap.
PRICE_BUCKETS = [
    (0, 5_000_000),
    (5_000_000, 10_000_000),
    (10_000_000, 15_000_000),
    (15_000_000, 20_000_000),
    (20_000_000, 30_000_000),
    (30_000_000, 50_000_000),
    (50_000_000, 1_000_000_000),
]


def collect_listing_ids(session, target_count=50, max_pages=60):
    """Page through search-core collecting unique listing refs.

    The Carsales Merlin API caps unique results per query at ~35-50 regardless
    of offset (offset only reshuffles featured tiles). To reach the target we
    shard the query by region and then by make, which surfaces different tile
    sets each time.
    """
    seen = {}  # networkId -> tile dict

    def _collect(q, limit_calls=6):
        """Walk offsets for a single query until no new results."""
        offset = 0
        for _ in range(limit_calls):
            url = f"{SEARCH_API}?q={q}&offset={offset}"
            j = fetch_json(url, session)
            if not j:
                return False  # stop on error
            tiles = extract_search_listings(j)
            new = 0
            for t in tiles:
                if t["networkId"] not in seen:
                    seen[t["networkId"]] = t
                    new += 1
            log(f"  q={q[:60]}... off={offset}: +{new} (total {len(seen)})")
            if len(seen) >= target_count:
                return True
            if new == 0:
                break
            offset += 31
            polite_sleep()
        return True

    # 1. Base query (covers featured tiles, ~40-50 unique).
    log("shard: all usados")
    if not _collect(QUERY):
        return list(seen.values())
    if len(seen) >= target_count:
        return list(seen.values())

    # 2. Region shards. Chile's 16 regions; list the 8 with most stock first.
    for region in REGIONS:
        if len(seen) >= target_count:
            break
        q = f"(And.(C.Category.autos.)_.State.Usado._.Region.{region}.)"
        log(f"shard region={region}")
        if not _collect(q, limit_calls=3):
            break

    # 3. Make shards for the most common brands (top ~25 in Chile).
    for make in MAKES:
        if len(seen) >= target_count:
            break
        q = f"(And.(C.Category.autos.)_.State.Usado._.Make.{make}.)"
        log(f"shard make={make}")
        if not _collect(q, limit_calls=3):
            break

    return list(seen.values())


def collect_listing_ids_full(session, target_count=5000, test_cap=None):
    """Full-mode sharding to defeat the ~140-result-per-query API ceiling.

    Strategy: for each (region, make, year-bucket, price-bucket) tuple, issue
    a small Carsales-query and dedupe by networkId. The four-dimensional
    shard grid surfaces thousands of unique listings.

    `target_count` is a soft stop: we exit once unique count reaches it. With
    ~16 regions × ~25 makes × 9 year-buckets × 7 price-buckets the upper
    bound is ~25k shard calls — far more than needed, so we order shards by
    expected stock density and stop early.
    """
    seen: dict[str, dict] = {}

    def _record(tiles):
        new = 0
        for t in tiles:
            if t["networkId"] not in seen:
                seen[t["networkId"]] = t
                new += 1
        return new

    def _query_once(q):
        """Single API call. Returns True on success (no transport error)."""
        url = f"{SEARCH_API}?q={q}&offset=0"
        j = fetch_json(url, session)
        if not j:
            return False
        tiles = extract_search_listings(j)
        new = _record(tiles)
        log(f"  q={q[:80]}... +{new} new (total {len(seen)})")
        polite_sleep()
        return True

    # Phase 0: broad warm-up (gets featured stock).
    log("=== chileautos full-mode shard expansion ===")
    log("phase 0: baseline + region + make shards (existing strategy)")
    _query_once(QUERY)
    for region in REGIONS:
        if len(seen) >= target_count or (test_cap and len(seen) >= test_cap):
            return list(seen.values())
        q = f"(And.(C.Category.autos.)_.State.Usado._.Region.{region}.)"
        _query_once(q)
    for make in MAKES:
        if len(seen) >= target_count or (test_cap and len(seen) >= test_cap):
            return list(seen.values())
        q = f"(And.(C.Category.autos.)_.State.Usado._.Make.{make}.)"
        _query_once(q)

    # Phase 1: year × make shards (cheap, breaks ~140 ceiling per make).
    log("phase 1: make × year-bucket shards")
    for make in MAKES:
        if len(seen) >= target_count or (test_cap and len(seen) >= test_cap):
            return list(seen.values())
        for ylo, yhi in YEAR_BUCKETS:
            if len(seen) >= target_count or (test_cap and len(seen) >= test_cap):
                return list(seen.values())
            q = (
                f"(And.(C.Category.autos.)_.State.Usado."
                f"_.Make.{make}._.Year.range({ylo}..{yhi}).)"
            )
            _query_once(q)

    # Phase 2: price × make shards.
    log("phase 2: make × price-bucket shards")
    for make in MAKES:
        if len(seen) >= target_count or (test_cap and len(seen) >= test_cap):
            return list(seen.values())
        for plo, phi in PRICE_BUCKETS:
            if len(seen) >= target_count or (test_cap and len(seen) >= test_cap):
                return list(seen.values())
            q = (
                f"(And.(C.Category.autos.)_.State.Usado."
                f"_.Make.{make}._.Price.range({plo}..{phi}).)"
            )
            _query_once(q)

    # Phase 3: full 4-dimensional grid. Only reach this if earlier phases
    # haven't surfaced the target. Iterate region × make × year × price.
    log("phase 3: full region × make × year × price grid")
    for region in REGIONS:
        for make in MAKES:
            for ylo, yhi in YEAR_BUCKETS:
                for plo, phi in PRICE_BUCKETS:
                    if len(seen) >= target_count or (test_cap and len(seen) >= test_cap):
                        return list(seen.values())
                    q = (
                        f"(And.(C.Category.autos.)_.State.Usado."
                        f"_.Region.{region}._.Make.{make}"
                        f"._.Year.range({ylo}..{yhi})"
                        f"._.Price.range({plo}..{phi}).)"
                    )
                    _query_once(q)

    return list(seen.values())


def scrape(target_count=40, full_mode=False, test_cap=None):
    session = requests.Session()
    session.headers.update(HEADERS)

    # warm the session (get DataDome cookies from homepage — homepage returns 200)
    try:
        session.get(BASE + "/", timeout=20)
    except Exception:
        pass

    log("=== Step 1: enumerate listings via /_api/search-core ===")
    if full_mode:
        refs = collect_listing_ids_full(
            session, target_count=target_count, test_cap=test_cap
        )
    else:
        refs = collect_listing_ids(session, target_count=target_count)
    log(f"collected {len(refs)} listing refs total")

    # Apply MAX_TEST_ROWS to detail fetches too (don't burn time fetching
    # thousands of detail pages during local tests).
    if test_cap is not None:
        refs = refs[:test_cap]
        log(f"MAX_TEST_ROWS applied to detail step: capped to {len(refs)} refs")

    log("=== Step 2: fetch each detail via /_api/details-core ===")
    out = []
    for i, ref in enumerate(refs, 1):
        nid = ref["networkId"]
        api_url = f"{DETAILS_API}{nid}/"
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
        det_imgs = extract_detail_images(dj)
        out.append(normalise(ref, det, heading, ref["url"], detail_images=det_imgs))
        polite_sleep()

    return out


DEFAULT_TARGET = 500
# Full sweep target: at least 5k unique listings via shard expansion.
FULL_MODE_TARGET = 8_000


def main():
    mode = os.environ.get("SCRAPE_MODE", "fresh").strip().lower() or "fresh"
    full_mode = mode == "full"
    if full_mode:
        target = FULL_MODE_TARGET
        log(f"SCRAPE_MODE=full (target={target})")
    else:
        target = DEFAULT_TARGET
    override = os.environ.get("SCRAPE_TARGET")
    if override:
        try:
            target = int(override)
        except ValueError:
            pass
    if len(sys.argv) > 1:
        try:
            target = int(sys.argv[1])
        except ValueError:
            pass
    test_cap = None
    test_cap_env = os.environ.get("MAX_TEST_ROWS")
    if test_cap_env:
        try:
            test_cap = int(test_cap_env)
        except ValueError:
            test_cap = None

    listings = scrape(target_count=target, full_mode=full_mode, test_cap=test_cap)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(listings, ensure_ascii=False, indent=2))
    log(f"wrote {len(listings)} listings to {OUT_PATH}")


if __name__ == "__main__":
    main()
