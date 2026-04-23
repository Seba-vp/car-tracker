"""Thin Supabase PostgREST client — no extra dependencies beyond `requests`."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Iterable

import requests


def _env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"Missing env var: {name}")
    return v


def _url() -> str:
    return _env("SUPABASE_URL").rstrip("/")


def _key() -> str:
    return _env("SUPABASE_SERVICE_ROLE_KEY")


SCHEMA = os.environ.get("SUPABASE_SCHEMA", "car_tracker")


def _headers(prefer: str = "return=representation") -> dict[str, str]:
    k = _key()
    return {
        "apikey": k,
        "Authorization": f"Bearer {k}",
        "Content-Type": "application/json",
        "Prefer": prefer,
        "Accept-Profile": SCHEMA,
        "Content-Profile": SCHEMA,
    }


def _log(msg: str) -> None:
    print(f"[db] {msg}", file=sys.stderr, flush=True)


def upsert_listings(rows: list[dict], chunk_size: int = 200) -> list[dict]:
    """Upsert listings. Returns the server's representation of each row (incl. id + first_seen_at).

    Uses on_conflict=(source, source_id). Stamps last_seen_at = now() server-side via the row itself.
    """
    if not rows:
        return []
    url = _url()
    now_iso = datetime.now(timezone.utc).isoformat()
    endpoint = f"{url}/rest/v1/listings?on_conflict=source,source_id"
    results: list[dict] = []
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        for r in chunk:
            r["last_seen_at"] = now_iso
        r = requests.post(endpoint, headers=_headers(), data=json.dumps(chunk), timeout=60)
        if r.status_code >= 400:
            _log(f"upsert failed {r.status_code}: {r.text[:500]}")
            r.raise_for_status()
        results.extend(r.json() if r.text else [])
    return results


def fetch_existing_prices(listing_ids: Iterable[int]) -> dict[int, int]:
    """Return {listing_id: latest_price_clp} for a batch of listings."""
    ids = list(listing_ids)
    if not ids:
        return {}
    url = _url()
    out: dict[int, int] = {}
    for i in range(0, len(ids), 200):
        chunk = ids[i : i + 200]
        q = f"id=in.({','.join(str(x) for x in chunk)})&select=id,latest_price_clp"
        r = requests.get(f"{url}/rest/v1/listings?{q}", headers=_headers("return=representation"), timeout=60)
        r.raise_for_status()
        for row in r.json():
            if row.get("latest_price_clp") is not None:
                out[row["id"]] = row["latest_price_clp"]
    return out


def insert_price_history(entries: list[dict]) -> int:
    """Append to listing_prices. `entries` items: {listing_id, price_clp, observed_at?}."""
    if not entries:
        return 0
    url = _url()
    endpoint = f"{url}/rest/v1/listing_prices"
    total = 0
    for i in range(0, len(entries), 500):
        chunk = entries[i : i + 500]
        r = requests.post(endpoint, headers=_headers("return=minimal"), data=json.dumps(chunk), timeout=60)
        if r.status_code >= 400:
            _log(f"price insert failed {r.status_code}: {r.text[:500]}")
            r.raise_for_status()
        total += len(chunk)
    return total


def record_scrape_run(
    source: str,
    started_at: str,
    rows_fetched: int,
    rows_upserted: int,
    rows_skipped: int,
    price_changes: int,
    status: str,
    error: str | None = None,
) -> None:
    url = _url()
    payload = {
        "source": source,
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "rows_fetched": rows_fetched,
        "rows_upserted": rows_upserted,
        "rows_skipped": rows_skipped,
        "price_changes": price_changes,
        "status": status,
        "error": (error or "")[:2000] or None,
    }
    r = requests.post(
        f"{url}/rest/v1/scrape_runs",
        headers=_headers("return=minimal"),
        data=json.dumps(payload),
        timeout=30,
    )
    if r.status_code >= 400:
        _log(f"scrape_runs insert failed {r.status_code}: {r.text[:300]}")
