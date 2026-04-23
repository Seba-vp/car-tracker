"""Post-sweep housekeeping: mark stale listings as removed, print daily summary.

Runs once after all per-source ingest jobs complete.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

STALE_DAYS = int(os.environ.get("STALE_DAYS", "3"))
SCHEMA = os.environ.get("SUPABASE_SCHEMA", "car_tracker")


def log(msg: str) -> None:
    print(f"[finalize] {msg}", file=sys.stderr, flush=True)


def headers(key: str) -> dict[str, str]:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation,count=exact",
        "Accept-Profile": SCHEMA,
        "Content-Profile": SCHEMA,
    }


def main() -> int:
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=STALE_DAYS)).isoformat()

    log(f"marking removed_at for listings last_seen_at<{cutoff} and removed_at IS NULL")
    r = requests.patch(
        f"{url}/rest/v1/listings",
        params={
            "last_seen_at": f"lt.{cutoff}",
            "removed_at": "is.null",
        },
        headers=headers(key),
        data=json.dumps({"removed_at": now.isoformat()}),
        timeout=120,
    )
    r.raise_for_status()
    removed = len(r.json()) if r.text else 0
    log(f"marked {removed} listings as removed")

    # Summary: active counts per source
    r = requests.get(
        f"{url}/rest/v1/listings",
        params={"select": "source", "removed_at": "is.null", "limit": "1"},
        headers={**headers(key), "Prefer": "count=exact"},
        timeout=60,
    )
    r.raise_for_status()
    total = int(r.headers.get("Content-Range", "0-0/0").split("/")[-1])
    log(f"active listings total: {total}")

    # Per-source breakdown via PostgREST "group by" workaround (fetch min id grouped):
    # Simpler: just fetch distinct sources + their counts via repeated HEADs
    for source in [
        "mercadolibre", "chileautos", "yapo", "kavak", "autocosmos",
        "economicos", "autopia", "auto_cl", "autosusados",
    ]:
        rr = requests.get(
            f"{url}/rest/v1/listings",
            params={"select": "id", "removed_at": "is.null", "source": f"eq.{source}", "limit": "1"},
            headers={**headers(key), "Prefer": "count=exact"},
            timeout=30,
        )
        cnt = int(rr.headers.get("Content-Range", "0-0/0").split("/")[-1]) if rr.ok else -1
        log(f"  {source}: {cnt}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
