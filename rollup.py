"""Compute market_stats from the current listings table.

Runs in the same GH Actions workflow after finalize.py. Groups active
listings by (make, model, year, km_bucket, fuel_type), computes
median/p25/p75/mean/stddev/count, and appends a new row to market_stats
with a fresh `computed_at` timestamp. Old rows are kept so we can chart
market trajectories over time.

Bucket sizes:
    km_bucket = floor(km / 20000)   -> 0 = 0-19k, 1 = 20-39k, ...
    year:       exact
"""

from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import requests

SCHEMA = os.environ.get("SUPABASE_SCHEMA", "car_tracker")
MIN_SAMPLES = int(os.environ.get("MARKET_STATS_MIN_SAMPLES", "3"))
KM_BUCKET_SIZE = int(os.environ.get("MARKET_STATS_KM_BUCKET", "20000"))


def log(msg: str) -> None:
    print(f"[rollup] {msg}", file=sys.stderr, flush=True)


def headers(key: str, prefer: str = "return=minimal") -> dict[str, str]:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": prefer,
        "Accept-Profile": SCHEMA,
        "Content-Profile": SCHEMA,
    }


def fetch_listings(url: str, key: str) -> list[dict[str, Any]]:
    """Page through all active listings with the minimal columns we need."""
    out: list[dict[str, Any]] = []
    page_size = 1000
    offset = 0
    while True:
        q = (
            f"?select=make,model,year,km,fuel_type,latest_price_clp"
            f"&removed_at=is.null"
            f"&make=not.is.null&model=not.is.null&year=not.is.null"
            f"&latest_price_clp=not.is.null"
            f"&order=id.asc"
            f"&offset={offset}&limit={page_size}"
        )
        r = requests.get(
            f"{url}/rest/v1/listings{q}",
            headers={**headers(key, "return=representation"), "Prefer": "count=exact"},
            timeout=60,
        )
        r.raise_for_status()
        rows = r.json()
        out.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    log(f"fetched {len(out)} active listings")
    return out


def quantile(sorted_vals: list[int], q: float) -> int:
    if not sorted_vals:
        return 0
    idx = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[idx]


def stddev(vals: list[int]) -> float:
    n = len(vals)
    if n < 2:
        return 0.0
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / (n - 1)
    return math.sqrt(var)


def compute_stats(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple, list[int]] = defaultdict(list)
    for row in listings:
        make = (row.get("make") or "").strip()
        model = (row.get("model") or "").strip()
        year = row.get("year")
        price = row.get("latest_price_clp")
        km = row.get("km")
        fuel = (row.get("fuel_type") or "unknown").strip() or "unknown"
        if not make or not model or year is None or price is None:
            continue
        km_bucket = km // KM_BUCKET_SIZE if isinstance(km, int) and km >= 0 else -1
        buckets[(make, model, year, km_bucket, fuel)].append(int(price))

    now = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for (make, model, year, km_bucket, fuel), prices in buckets.items():
        if len(prices) < MIN_SAMPLES:
            continue
        s = sorted(prices)
        rows.append(
            {
                "make": make,
                "model": model,
                "year": year,
                "km_bucket": km_bucket,
                "fuel_type": fuel,
                "median_price": quantile(s, 0.5),
                "p25": quantile(s, 0.25),
                "p75": quantile(s, 0.75),
                "mean_price": round(sum(s) / len(s), 2),
                "stddev": round(stddev(s), 2),
                "n_samples": len(s),
                "computed_at": now,
            }
        )
    log(f"{len(rows)} buckets meeting min_samples={MIN_SAMPLES}")
    return rows


def insert_stats(url: str, key: str, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    endpoint = f"{url}/rest/v1/market_stats"
    inserted = 0
    for i in range(0, len(rows), 500):
        chunk = rows[i : i + 500]
        r = requests.post(
            endpoint,
            headers=headers(key, "return=minimal"),
            data=json.dumps(chunk),
            timeout=60,
        )
        if r.status_code >= 400:
            log(f"insert failed {r.status_code}: {r.text[:500]}")
            r.raise_for_status()
        inserted += len(chunk)
    return inserted


def main() -> int:
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

    listings = fetch_listings(url, key)
    rows = compute_stats(listings)
    inserted = insert_stats(url, key, rows)
    log(f"inserted {inserted} market_stats rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
