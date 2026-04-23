# Economicos.cl — Scraping Feasibility

**Feasibility: HIGH**

## Method

Plain HTTP + HTML. No JS, no auth, no tokens.

1. List: `GET /todo_chile/autos?pagina=N` — 60 cards/page, server-rendered.
   Site advertises **9,971 auto listings** across 249 pages.
2. Detail: `GET /vehiculos/<slug>-cod<id>.html`. Attributes in a
   `<li><span>Label:</span> Value</li>` block (Precio, Marca, Modelo, Año,
   Combustible, Transmision, Vende, Region, Fecha Publicación). Parsed with
   BeautifulSoup.

`robots.txt` disallows named bots (Bingbot, Ahrefs, Semrush, claudebot…) but
allows generic UAs.

## Anti-bot

None. No 403/429, no CAPTCHA, no Cloudflare, no JS gate, no cookie wall.
Stack is nginx + Payara (Java). `JSESSIONID` is set but not required.

## Sample count

**40 listings** end-to-end in ~45 s including 0.5–1.0 s per-request jitter.
Saved to `data/economicos.json`.

## Data quality

| Field | Coverage | Notes |
|---|---|---|
| source, source_id, url, title, scraped_at | 100% | |
| make, model, year, region | 100% | Clean values |
| price_clp, currency | 100% | All CLP; code handles UF too |
| transmission | 100% | Mecánica→manual, Automática→automatic |
| posted_at | 100% | `YYYY-MM-DD HH:MM:SS` |
| seller_type | 100% | All dealer — page 1 is dealer-heavy; `particular` appears on deeper pages (alphanumeric IDs) |
| fuel_type | 92% | 3 listings omit it; Bencina→gasolina |
| version, km, body_type, commune | **0%** | **Not exposed by source** |

Price range 5.49M–54.99M CLP (median 15.99M), years 2017–2025, 7 regions.

## Rate limit

None at ~1 req/s over 41 requests. All HTTP 200.

## Scaling recommendation

- Safe at 1 req/s with jitter; likely fine at 2 req/s.
- Full ~10k-listing crawl: ~3 h at 1 req/s.
- Daily incremental: pages 1–10 (≈600 newest) plus `posted_at` filter.
- Older listings (alphanumeric IDs, >~1 yr old) often lack fuel/transmission/
  seller — parser returns `None` gracefully.
- **For km / version / body_type, pair with chileautos.cl or yapo.cl.**
  Economicos is an excellent low-cost backbone for price × make × model ×
  year × region × posted_at, but insufficient alone for km-based valuation.
