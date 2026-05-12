"""Post-sweep housekeeping: active re-check stale listings + daily summary.

Instead of the old "if last_seen_at < N days, mark removed" heuristic
(which was producing ~50% false positives because we sample, not crawl,
each source's full inventory), this script HEADs each candidate's detail
URL and only marks `removed_at` on 404/410. A 200 response refreshes
`last_seen_at` so the listing isn't re-checked next run.

Tunables (env vars):
    STALE_DAYS         oldest-allowed last_seen_at before re-check (default 7)
    RECHECK_LIMIT      max URLs probed per run (default 500)
    RECHECK_DELAY      seconds between probes (default 0.4)

Blocked sources (mercadolibre, economicos, kavak, demotores) are skipped —
their anti-bot rejects our probes regardless of listing state.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

STALE_DAYS = int(os.environ.get("STALE_DAYS", "7"))
SCHEMA = os.environ.get("SUPABASE_SCHEMA", "car_tracker")
RECHECK_LIMIT = int(os.environ.get("RECHECK_LIMIT", "500"))
RECHECK_DELAY = float(os.environ.get("RECHECK_DELAY", "0.4"))

# Per-source UA known to pass anti-bot at scrape time.
SOURCE_UA = {
    "yapo": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "chileautos": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "autocosmos": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "autopia": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "auto_cl": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    ),
    "autosusados": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

SKIP_RECHECK = {"mercadolibre", "economicos", "kavak", "demotores"}


def log(msg: str) -> None:
    print(f"[finalize] {msg}", file=sys.stderr, flush=True)


def headers(key: str) -> dict[str, str]:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
        "Accept-Profile": SCHEMA,
        "Content-Profile": SCHEMA,
    }


def make_session(source: str):
    """Pick the right HTTP client for the source.

    auto_cl is fronted by Cloudflare and needs curl_cffi's TLS impersonation
    (same as the scraper). Others work with stdlib requests.
    """
    if source == "auto_cl":
        try:
            from curl_cffi import requests as cffi  # type: ignore
            return cffi.Session(impersonate="safari17_0")
        except ImportError:
            log("curl_cffi missing; auto_cl rechecks will likely 403")
    return requests.Session()


def probe(session, url: str, source: str) -> int:
    """Return HTTP status code from a HEAD (or GET fallback) request."""
    hdrs = {"User-Agent": SOURCE_UA.get(source, "")}
    try:
        r = session.head(url, headers=hdrs, timeout=10, allow_redirects=False)
        if r.status_code in (405, 501):  # method not supported
            r = session.get(url, headers=hdrs, timeout=10, allow_redirects=False, stream=True)
            r.close()
        return r.status_code
    except Exception as e:
        log(f"  probe error {source} {url[:80]}: {type(e).__name__}")
        return 0


def fetch_candidates(url: str, key: str, cutoff_iso: str) -> list[dict]:
    """Fetch the oldest-not-recently-seen, not-already-removed listings."""
    sources_filter = ",".join(
        f'"{s}"' for s in SOURCE_UA.keys() if s not in SKIP_RECHECK
    )
    r = requests.get(
        f"{url}/rest/v1/listings",
        params={
            "select": "id,source,url,last_seen_at",
            "last_seen_at": f"lt.{cutoff_iso}",
            "removed_at": "is.null",
            "source": f"in.({sources_filter})",
            "order": "last_seen_at.asc",
            "limit": str(RECHECK_LIMIT),
        },
        headers=headers(key),
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def patch_listing(url: str, key: str, listing_id: int, body: dict) -> None:
    r = requests.patch(
        f"{url}/rest/v1/listings",
        params={"id": f"eq.{listing_id}"},
        headers={**headers(key), "Prefer": "return=minimal"},
        data=json.dumps(body),
        timeout=30,
    )
    if r.status_code >= 400:
        log(f"  PATCH {listing_id} failed {r.status_code}: {r.text[:200]}")


def active_recheck(url: str, key: str) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    cutoff_iso = (now - timedelta(days=STALE_DAYS)).isoformat()
    log(f"finding candidates last_seen_at < {cutoff_iso}, limit {RECHECK_LIMIT}")

    candidates = fetch_candidates(url, key, cutoff_iso)
    log(f"{len(candidates)} candidates to verify")

    counts = {"probed": 0, "removed": 0, "refreshed": 0, "skipped": 0}
    sessions: dict[str, object] = {}

    for c in candidates:
        source = c["source"]
        if source in SKIP_RECHECK:
            counts["skipped"] += 1
            continue
        if source not in sessions:
            sessions[source] = make_session(source)
        if not c.get("url"):
            counts["skipped"] += 1
            continue

        status = probe(sessions[source], c["url"], source)
        counts["probed"] += 1

        if status in (404, 410):
            patch_listing(url, key, c["id"], {"removed_at": now.isoformat()})
            counts["removed"] += 1
        elif status == 200:
            patch_listing(url, key, c["id"], {"last_seen_at": now.isoformat()})
            counts["refreshed"] += 1
        else:
            counts["skipped"] += 1

        time.sleep(RECHECK_DELAY)

    log(
        f"recheck done: probed={counts['probed']} "
        f"removed={counts['removed']} refreshed={counts['refreshed']} "
        f"skipped={counts['skipped']}"
    )
    return counts


def summary(url: str, key: str) -> None:
    """Per-source active counts for the run log."""
    for source in [
        "mercadolibre", "chileautos", "yapo", "kavak", "autocosmos",
        "economicos", "autopia", "auto_cl", "autosusados",
    ]:
        rr = requests.get(
            f"{url}/rest/v1/listings",
            params={
                "select": "id",
                "removed_at": "is.null",
                "source": f"eq.{source}",
                "limit": "1",
            },
            headers={**headers(key), "Prefer": "count=exact"},
            timeout=30,
        )
        cnt = int(rr.headers.get("Content-Range", "0-0/0").split("/")[-1]) if rr.ok else -1
        log(f"  {source}: {cnt} active")


def main() -> int:
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

    active_recheck(url, key)
    summary(url, key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
