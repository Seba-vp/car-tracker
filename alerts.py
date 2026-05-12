"""Evaluate alert_rules against the current listing set and deliver Telegram pings.

Runs after rollup in the GH Actions workflow. For each enabled rule:
  1. Resolve the user's telegram_chat_id (skip if unset).
  2. Build a PostgREST query from `criteria` JSONB to pull matching listings.
  3. Depending on `trigger_type`:
       below_median / below_mean — compute cohort stat in Python, find
           listings whose price ≤ stat * (1 - threshold_pct/100).
       price_drop — pull from car_tracker.price_changes, find listings
           whose pct_change ≤ -threshold_pct in the last 14 days.
  4. Deduplicate against alert_notifications (never alert (rule, listing) twice).
  5. Send Telegram message; record sent/failed in alert_notifications.

Env:
  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY  — DB writes
  TELEGRAM_BOT_TOKEN                       — bot for Telegram sendMessage
  ALERTS_MAX_PER_RULE                      — cap per evaluation (default 5)
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

import requests

SCHEMA = os.environ.get("SUPABASE_SCHEMA", "car_tracker")
MAX_PER_RULE = int(os.environ.get("ALERTS_MAX_PER_RULE", "5"))
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def log(msg: str) -> None:
    print(f"[alerts] {msg}", file=sys.stderr, flush=True)


def db_headers(key: str, prefer: str = "return=representation") -> dict[str, str]:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": prefer,
        "Accept-Profile": SCHEMA,
        "Content-Profile": SCHEMA,
    }


def get_enabled_rules(url: str, key: str) -> list[dict]:
    r = requests.get(
        f"{url}/rest/v1/alert_rules",
        params={"select": "*", "enabled": "is.true"},
        headers=db_headers(key),
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def get_user_settings(url: str, key: str, user_id: str) -> dict | None:
    r = requests.get(
        f"{url}/rest/v1/user_settings",
        params={"user_id": f"eq.{user_id}", "select": "*", "limit": "1"},
        headers=db_headers(key),
        timeout=30,
    )
    r.raise_for_status()
    rows = r.json()
    return rows[0] if rows else None


def fetch_listings(url: str, key: str, criteria: dict, limit: int = 2000) -> list[dict]:
    """Apply criteria-as-filters to active listings; returns the matching set."""
    params: dict[str, Any] = {
        "select": "id,source,url,title,make,model,version,year,km,latest_price_clp,region,image_url,first_seen_at",
        "removed_at": "is.null",
        "latest_price_clp": "not.is.null",
        "order": "latest_price_clp.asc",
        "limit": str(limit),
    }
    c = criteria or {}
    if c.get("make"):       params["make"]              = f"ilike.{c['make']}"
    if c.get("model"):      params["model"]             = f"ilike.%{c['model']}%"
    if c.get("yearMin"):    params["year"]              = f"gte.{c['yearMin']}"
    if c.get("yearMax"):
        # already used year= if yearMin? PostgREST allows multiple via comma in same key
        cur = params.get("year")
        params["year"] = (cur + "," if cur else "") + f"lte.{c['yearMax']}"
    if c.get("kmMin"):      params["km"]                = f"gte.{c['kmMin']}"
    if c.get("kmMax"):
        cur = params.get("km")
        params["km"] = (cur + "," if cur else "") + f"lte.{c['kmMax']}"
    if c.get("priceMin"):
        cur = params.get("latest_price_clp")
        params["latest_price_clp"] = (
            (cur.replace("not.is.null", "") + "," if cur and cur != "not.is.null" else "")
            + f"gte.{c['priceMin']}"
        )
    if c.get("priceMax"):
        cur = params.get("latest_price_clp")
        params["latest_price_clp"] = (
            (cur + "," if cur and cur != "not.is.null" else "")
            + f"lte.{c['priceMax']}"
        )
    if c.get("fuel"):       params["fuel_type"]         = f"eq.{c['fuel']}"
    if c.get("region"):     params["region"]            = f"ilike.%{c['region']}%"
    if c.get("source"):     params["source"]            = f"eq.{c['source']}"

    r = requests.get(
        f"{url}/rest/v1/listings",
        params=params,
        headers=db_headers(key),
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def median(vals: list[int]) -> int:
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return 0
    return s[n // 2]


def already_notified_ids(url: str, key: str, rule_id: int) -> set[int]:
    r = requests.get(
        f"{url}/rest/v1/alert_notifications",
        params={"select": "listing_id", "rule_id": f"eq.{rule_id}"},
        headers=db_headers(key),
        timeout=30,
    )
    r.raise_for_status()
    return {row["listing_id"] for row in r.json()}


def fetch_price_drops(url: str, key: str, threshold_pct: float) -> list[dict]:
    """Get all listings with a drop ≥ threshold_pct in the last 14 days."""
    cutoff = (datetime.now(timezone.utc).timestamp() - 14 * 86400)
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
    r = requests.get(
        f"{url}/rest/v1/price_changes",
        params={
            "select": "listing_id,first_price,latest_price,pct_change",
            "pct_change": f"lt.-{abs(threshold_pct)}",
            "latest_observed": f"gte.{cutoff_iso}",
            "order": "pct_change.asc",
            "limit": "5000",
        },
        headers=db_headers(key),
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def send_telegram(token: str, chat_id: str, text: str) -> tuple[bool, str | None]:
    try:
        r = requests.post(
            TELEGRAM_API.format(token=token),
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=15,
        )
        if r.status_code == 200 and r.json().get("ok"):
            return True, None
        return False, r.text[:300]
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def fmt_clp(n: int | None) -> str:
    if n is None:
        return "—"
    return f"$ {n:,}".replace(",", ".")


def make_message(rule: dict, listing: dict, extra: dict | None = None) -> str:
    title = listing.get("title") or f"{listing.get('make','')} {listing.get('model','')}".strip()
    price = fmt_clp(listing.get("latest_price_clp"))
    year = listing.get("year") or "?"
    km = listing.get("km")
    km_s = f"{km:,} km".replace(",", ".") if km else "—"
    region = listing.get("region") or ""
    src = listing.get("source") or ""
    extra_line = ""
    if extra and "median" in extra:
        delta = ((listing["latest_price_clp"] - extra["median"]) / extra["median"]) * 100
        extra_line = (
            f"\n📊 Cohort median: {fmt_clp(extra['median'])} ({delta:+.1f}%) over {extra['n']} listings"
        )
    if extra and "pct_change" in extra:
        extra_line = (
            f"\n📉 Was {fmt_clp(extra['first_price'])} → {price} "
            f"({extra['pct_change']:+.1f}%)"
        )
    return (
        f"🚗 <b>{rule['name']}</b>\n"
        f"<a href=\"{listing.get('url','')}\">{title}</a>\n"
        f"💰 {price}  ·  {year}  ·  {km_s}  ·  {region} ({src}){extra_line}"
    )


def insert_notification(
    url: str, key: str, rule_id: int, listing_id: int,
    delivery: str, error: str | None,
) -> None:
    r = requests.post(
        f"{url}/rest/v1/alert_notifications",
        headers={**db_headers(key), "Prefer": "return=minimal"},
        data=json.dumps({
            "rule_id": rule_id,
            "listing_id": listing_id,
            "delivery": delivery,
            "error": error,
        }),
        timeout=15,
    )
    if r.status_code >= 400 and "23505" not in r.text:  # ignore unique-violation
        log(f"  notify-insert failed {r.status_code}: {r.text[:300]}")


def touch_rule(url: str, key: str, rule_id: int) -> None:
    requests.patch(
        f"{url}/rest/v1/alert_rules",
        params={"id": f"eq.{rule_id}"},
        headers={**db_headers(key), "Prefer": "return=minimal"},
        data=json.dumps({"last_evaluated_at": datetime.now(timezone.utc).isoformat()}),
        timeout=15,
    )


def evaluate_rule(
    url: str, key: str, token: str, rule: dict, chat_id: str,
) -> tuple[int, int]:
    """Return (n_candidates, n_sent)."""
    trigger = rule.get("trigger_type") or "below_median"
    threshold = float(rule.get("threshold_pct") or 10)
    notified = already_notified_ids(url, key, rule["id"])

    if trigger == "price_drop":
        # Pull candidates from price_changes view.
        drops = fetch_price_drops(url, key, threshold)
        if not drops:
            return 0, 0
        # Intersect with criteria-filtered listings.
        candidate_ids = {d["listing_id"]: d for d in drops}
        listings = fetch_listings(url, key, rule.get("criteria") or {})
        candidates = [
            (l, candidate_ids[l["id"]]) for l in listings
            if l["id"] in candidate_ids and l["id"] not in notified
        ]
        candidates.sort(key=lambda x: x[1]["pct_change"])  # biggest drops first
        candidates = candidates[:MAX_PER_RULE]

        sent = 0
        for l, drop in candidates:
            text = make_message(rule, l, extra={
                "first_price": drop["first_price"],
                "pct_change": drop["pct_change"],
            })
            ok, err = send_telegram(token, chat_id, text)
            insert_notification(
                url, key, rule["id"], l["id"],
                "sent" if ok else "failed", err,
            )
            sent += 1 if ok else 0
            time.sleep(0.4)  # Telegram rate limit safety
        return len(candidates), sent

    # below_median / below_mean
    listings = fetch_listings(url, key, rule.get("criteria") or {})
    prices = [l["latest_price_clp"] for l in listings if l.get("latest_price_clp")]
    if len(prices) < 4:
        return 0, 0
    stat = (
        median(prices) if trigger == "below_median"
        else int(sum(prices) / len(prices))
    )
    cutoff = stat * (1 - threshold / 100)
    candidates = [l for l in listings if l["latest_price_clp"] <= cutoff and l["id"] not in notified]
    candidates.sort(key=lambda l: l["latest_price_clp"])
    candidates = candidates[:MAX_PER_RULE]

    sent = 0
    for l in candidates:
        text = make_message(rule, l, extra={"median": stat, "n": len(prices)})
        ok, err = send_telegram(token, chat_id, text)
        insert_notification(
            url, key, rule["id"], l["id"],
            "sent" if ok else "failed", err,
        )
        sent += 1 if ok else 0
        time.sleep(0.4)
    return len(candidates), sent


def main() -> int:
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        log("TELEGRAM_BOT_TOKEN missing — skipping alert evaluation")
        return 0

    rules = get_enabled_rules(url, key)
    log(f"evaluating {len(rules)} enabled rules")
    summary = {"rules": 0, "candidates": 0, "sent": 0, "skipped_no_chat": 0}
    for rule in rules:
        settings = get_user_settings(url, key, rule["user_id"])
        chat_id = (settings or {}).get("telegram_chat_id")
        if not chat_id:
            summary["skipped_no_chat"] += 1
            continue
        try:
            c, s = evaluate_rule(url, key, token, rule, chat_id)
            summary["rules"] += 1
            summary["candidates"] += c
            summary["sent"] += s
            log(f"  rule #{rule['id']} '{rule['name']}': {c} candidates, {s} sent")
        except Exception as e:
            log(f"  rule #{rule['id']} failed: {type(e).__name__}: {e}")
        finally:
            touch_rule(url, key, rule["id"])

    log(f"summary: {json.dumps(summary)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
