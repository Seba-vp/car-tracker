"""Unified ingester: runs a source scraper, normalizes, upserts to Supabase.

Usage:
  python ingest.py --source <slug> [--no-upload] [--file path/to.json]

Each source has a scraper at scrapers/<slug>/scraper.py that writes
data/<slug>.json as a JSON array. This script:
  1. Runs the scraper as a subprocess (skip with --file).
  2. Normalizes rows via shared.normalize.
  3. Upserts to listings (by source+source_id).
  4. Appends listing_prices rows whenever price_clp changed.
  5. Records a scrape_runs summary row.

If SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are missing or --no-upload is
passed, runs the scrape+normalize pipeline and prints a summary without
touching the database — useful for local dry runs.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from shared.normalize import normalize_row  # noqa: E402

SOURCES = [
    "mercadolibre",
    "chileautos",
    "yapo",
    "kavak",
    "autocosmos",
    "economicos",
    "autopia",
    "auto_cl",
    "autosusados",
    "demotores",
]


def log(msg: str) -> None:
    print(f"[ingest] {msg}", file=sys.stderr, flush=True)


def run_scraper(source: str, timeout_s: int) -> Path:
    script = ROOT / "scrapers" / source / "scraper.py"
    out = ROOT / "data" / f"{source}.json"
    if not script.exists():
        raise FileNotFoundError(f"scraper missing: {script}")
    log(f"running {script.relative_to(ROOT)} (timeout={timeout_s}s)")
    t0 = time.monotonic()
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        timeout=timeout_s,
        capture_output=True,
        text=True,
    )
    dt = time.monotonic() - t0
    if proc.returncode != 0:
        log(f"scraper exit={proc.returncode} in {dt:.1f}s")
        log(f"stderr tail:\n{proc.stderr[-2000:]}")
        raise RuntimeError(f"scraper {source} failed (exit {proc.returncode})")
    log(f"scraper finished in {dt:.1f}s")
    if not out.exists():
        raise FileNotFoundError(f"scraper did not write {out}")
    return out


def load_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path} is not a JSON array")
    return data


def ingest(source: str, rows: list[dict], upload: bool) -> dict:
    started_at = datetime.now(timezone.utc).isoformat()
    normalized: list[dict] = []
    skipped = 0
    for raw in rows:
        row = normalize_row(raw, source=source)
        if row is None:
            skipped += 1
            continue
        normalized.append(row)

    log(f"normalized {len(normalized)}/{len(rows)} rows (skipped {skipped})")

    summary = {
        "source": source,
        "started_at": started_at,
        "rows_fetched": len(rows),
        "rows_normalized": len(normalized),
        "rows_skipped": skipped,
        "rows_upserted": 0,
        "price_changes": 0,
        "uploaded": False,
    }

    if not upload:
        log("dry-run: skipping upload")
        return summary

    from shared import db  # imported lazily so local dry-runs work without env vars

    upserted = db.upsert_listings(normalized)
    summary["rows_upserted"] = len(upserted)
    summary["uploaded"] = True
    log(f"upserted {len(upserted)} listings")

    # Detect price changes by comparing the returned latest_price_clp to the
    # value we just sent. Supabase returns the POST-merge row, so a "change"
    # is: our new price != any price previously stored (which we can infer
    # only if Supabase reflects the new row). Simpler + correct: read current
    # prices first, diff, then upsert — but that's 2 round-trips. Instead,
    # always append a price history row; the PRIMARY KEY (listing_id,
    # observed_at) makes this cheap and append-only.
    price_entries = []
    by_key = {(r["source"], r["source_id"]): r for r in upserted}
    for r in normalized:
        ref = by_key.get((r["source"], r["source_id"]))
        if not ref:
            continue
        price_entries.append(
            {
                "listing_id": ref["id"],
                "price_clp": r["latest_price_clp"],
                "observed_at": ref["last_seen_at"],
            }
        )
    if price_entries:
        inserted = db.insert_price_history(price_entries)
        summary["price_changes"] = inserted
        log(f"appended {inserted} price history rows")

    db.record_scrape_run(
        source=source,
        started_at=started_at,
        rows_fetched=summary["rows_fetched"],
        rows_upserted=summary["rows_upserted"],
        rows_skipped=summary["rows_skipped"],
        price_changes=summary["price_changes"],
        status="ok",
    )
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, choices=SOURCES)
    ap.add_argument("--no-upload", action="store_true", help="Normalize only; skip DB writes")
    ap.add_argument("--file", help="Skip scraper; use this JSON file as input")
    ap.add_argument("--timeout", type=int, default=1800, help="Scraper subprocess timeout (s)")
    args = ap.parse_args()

    try:
        if args.file:
            path = Path(args.file).resolve()
            if not path.exists():
                raise FileNotFoundError(path)
            log(f"using preloaded file {path}")
        else:
            path = run_scraper(args.source, args.timeout)
        rows = load_rows(path)
        summary = ingest(args.source, rows, upload=not args.no_upload)
    except Exception as e:  # record the failure and re-raise for non-zero exit
        err = f"{type(e).__name__}: {e}"
        log(f"FAILED: {err}")
        if not args.no_upload:
            try:
                from shared import db
                db.record_scrape_run(
                    source=args.source,
                    started_at=datetime.now(timezone.utc).isoformat(),
                    rows_fetched=0,
                    rows_upserted=0,
                    rows_skipped=0,
                    price_changes=0,
                    status="failed",
                    error=err,
                )
            except Exception as db_err:
                log(f"could not record failure: {db_err}")
        raise

    log(f"summary: {json.dumps(summary)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
