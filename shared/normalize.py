"""Canonicalize raw scraper output into the listings schema."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _norm_key(s: Any) -> str:
    if not isinstance(s, str):
        return ""
    return _strip_accents(s).lower().strip()


FUEL_MAP = {
    "gasolina": "gasolina",
    "bencina": "gasolina",
    "bencinera": "gasolina",
    "combustible premium": "gasolina",
    "petroleo": "diesel",
    "diesel": "diesel",
    "electrico": "electrico",
    "electric": "electrico",
    "hibrido": "hibrido",
    "hybrid": "hibrido",
    "hibrido enchufable": "hibrido",
    "gnc": "gnc",
    "glp": "gnc",
    "gas": "gnc",
}

TRANS_MAP = {
    "manual": "manual",
    "mecanica": "manual",
    "transmision mecanica": "manual",
    "automatica": "automatic",
    "automatico": "automatic",
    "automatic": "automatic",
    "transmision automatica": "automatic",
    "cvt": "automatic",
    "dct": "automatic",
    "dsg": "automatic",
    "tiptronic": "automatic",
    "secuencial": "automatic",
    "semi-automatica": "automatic",
}

SELLER_MAP = {
    "dealer": "dealer",
    "professional": "dealer",
    "empresa": "dealer",
    "concesionario": "dealer",
    "automotora": "dealer",
    "comercial": "dealer",
    "private": "private",
    "particular": "private",
    "privado": "private",
}

BODY_MAP = {
    "suv": "suv",
    "crossover": "suv",
    "sedan": "sedan",
    "hatchback": "hatchback",
    "coupe": "coupe",
    "deportivo": "coupe",
    "sport": "coupe",
    "convertible": "convertible",
    "cabriolet": "convertible",
    "station wagon": "station_wagon",
    "wagon": "station_wagon",
    "minivan": "minivan",
    "van": "van",
    "furgon": "van",
    "comercial": "van",
    "pickup": "pickup",
    "pick-up": "pickup",
    "doble cabina": "pickup",
    "cabina simple": "pickup",
    "camioneta": "pickup",
}

MAKE_ALIASES = {
    "vw": "Volkswagen",
    "volkswagen": "Volkswagen",
    "mb": "Mercedes-Benz",
    "mercedes benz": "Mercedes-Benz",
    "mercedes-benz": "Mercedes-Benz",
    "mercedes": "Mercedes-Benz",
    "bmw": "BMW",
    "mg": "MG",
    "kia motors": "Kia",
    "chevrolet": "Chevrolet",
    "chevy": "Chevrolet",
    "great wall": "Great Wall",
    "land rover": "Land Rover",
    "range rover": "Land Rover",
    "alfa romeo": "Alfa Romeo",
    "mini cooper": "MINI",
    "mini": "MINI",
}


def norm_fuel(v: Any) -> str | None:
    k = _norm_key(v)
    if not k:
        return None
    if k in FUEL_MAP:
        return FUEL_MAP[k]
    for needle, canonical in FUEL_MAP.items():
        if needle in k:
            return canonical
    return "other"


def norm_transmission(v: Any) -> str | None:
    k = _norm_key(v)
    if not k:
        return None
    if k in TRANS_MAP:
        return TRANS_MAP[k]
    for needle, canonical in TRANS_MAP.items():
        if needle in k:
            return canonical
    return "other"


def norm_seller(v: Any) -> str | None:
    k = _norm_key(v)
    if not k:
        return None
    return SELLER_MAP.get(k, k)


def norm_body(v: Any) -> str | None:
    k = _norm_key(v)
    if not k:
        return None
    if k in BODY_MAP:
        return BODY_MAP[k]
    for needle, canonical in BODY_MAP.items():
        if needle in k:
            return canonical
    return k


def norm_make(v: Any) -> str | None:
    if not isinstance(v, str) or not v.strip():
        return None
    raw = v.strip()
    key = _norm_key(raw)
    if key in MAKE_ALIASES:
        return MAKE_ALIASES[key]
    # Default: title-case unless looks like an acronym
    if raw.isupper() and len(raw) <= 4:
        return raw
    return " ".join(w.capitalize() for w in raw.split())


def norm_model(v: Any) -> str | None:
    if not isinstance(v, str) or not v.strip():
        return None
    return v.strip()


def norm_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        digits = re.sub(r"[^\d]", "", v)
        return int(digits) if digits else None
    return None


def norm_year(v: Any) -> int | None:
    y = norm_int(v)
    if y is None:
        return None
    return y if 1950 <= y <= datetime.now(timezone.utc).year + 1 else None


def norm_ts(v: Any) -> str | None:
    if not v:
        return None
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(v, tz=timezone.utc).isoformat()
        except (OSError, ValueError):
            return None
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            return datetime.fromisoformat(s).astimezone(timezone.utc).isoformat()
        except ValueError:
            return None
    return None


def normalize_row(raw: dict, source: str) -> dict | None:
    """Transform a raw scraper row into a canonical listings row.

    Returns None if the row is unusable (missing source_id or price).
    """
    source_id = raw.get("source_id")
    if source_id is None:
        return None
    source_id = str(source_id).strip()
    if not source_id:
        return None

    price = norm_int(raw.get("price_clp"))
    if not price or price <= 0:
        return None

    # Image URLs: primary + full gallery. Pass-through; don't invent values.
    image_url_raw = raw.get("image_url")
    image_url = image_url_raw.strip() if isinstance(image_url_raw, str) and image_url_raw.strip() else None

    image_urls_raw = raw.get("image_urls")
    image_urls: list[str] | None = None
    if isinstance(image_urls_raw, list):
        cleaned = [u.strip() for u in image_urls_raw if isinstance(u, str) and u.strip()]
        image_urls = cleaned or None

    return {
        "source": source,
        "source_id": source_id,
        "url": (raw.get("url") or "").strip() or None,
        "title": (raw.get("title") or "").strip() or None,
        "make": norm_make(raw.get("make")),
        "model": norm_model(raw.get("model")),
        "version": (raw.get("version") or "").strip() or None if isinstance(raw.get("version"), str) else None,
        "year": norm_year(raw.get("year")),
        "km": norm_int(raw.get("km")),
        "fuel_type": norm_fuel(raw.get("fuel_type")),
        "transmission": norm_transmission(raw.get("transmission")),
        "body_type": norm_body(raw.get("body_type")),
        "region": (raw.get("region") or "").strip() or None if isinstance(raw.get("region"), str) else None,
        "commune": (raw.get("commune") or "").strip() or None if isinstance(raw.get("commune"), str) else None,
        "seller_type": norm_seller(raw.get("seller_type")),
        "currency": (raw.get("currency") or "CLP").upper(),
        "source_posted_at": norm_ts(raw.get("posted_at")),
        "latest_price_clp": price,
        "image_url": image_url,
        "image_urls": image_urls,
        "raw": raw,
    }
