-- Middle-ground taxonomy/aggregation views.
-- Materialized so queries are fast; refreshed in the finalize workflow job
-- via REFRESH MATERIALIZED VIEW CONCURRENTLY (needs a unique index).
--
-- Apply via:
--   ./scripts/supabase-sql.sh izbokfsmplxielwiyvup "$(cat sql/rollup_views.sql)"

-- ---------------------------------------------------------------------------
-- brand_rollup: one row per `make`, with the main market-size signals.
-- ---------------------------------------------------------------------------
DROP MATERIALIZED VIEW IF EXISTS car_tracker.brand_rollup;
CREATE MATERIALIZED VIEW car_tracker.brand_rollup AS
SELECT
    make,
    COUNT(*)::int                                         AS n_listings,
    COUNT(DISTINCT model)::int                            AS n_models,
    MIN(year)                                             AS oldest_year,
    MAX(year)                                             AS newest_year,
    AVG(latest_price_clp)::bigint                         AS avg_price_clp,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY latest_price_clp)::bigint
                                                          AS median_price_clp,
    MIN(latest_price_clp)                                 AS min_price_clp,
    MAX(latest_price_clp)                                 AS max_price_clp,
    COUNT(*) FILTER (WHERE fuel_type = 'gasolina')::int   AS n_gasolina,
    COUNT(*) FILTER (WHERE fuel_type = 'diesel')::int     AS n_diesel,
    COUNT(*) FILTER (WHERE fuel_type = 'hibrido')::int    AS n_hibrido,
    COUNT(*) FILTER (WHERE fuel_type = 'electrico')::int  AS n_electrico,
    COUNT(*) FILTER (WHERE seller_type = 'dealer')::int   AS n_dealer,
    COUNT(*) FILTER (WHERE seller_type = 'private')::int  AS n_private,
    ARRAY_AGG(DISTINCT source ORDER BY source)            AS sources_seen,
    MAX(last_seen_at)                                     AS last_seen_at
FROM car_tracker.listings
WHERE removed_at IS NULL
  AND make IS NOT NULL
  AND latest_price_clp IS NOT NULL
GROUP BY make;

CREATE UNIQUE INDEX IF NOT EXISTS brand_rollup_make_idx
    ON car_tracker.brand_rollup (make);

-- ---------------------------------------------------------------------------
-- model_rollup: one row per (make, model) — the unit most useful for pricing.
-- Includes per-year price distribution as a compact JSON blob.
-- ---------------------------------------------------------------------------
DROP MATERIALIZED VIEW IF EXISTS car_tracker.model_rollup;
CREATE MATERIALIZED VIEW car_tracker.model_rollup AS
WITH yr AS (
    SELECT make, model, year, latest_price_clp, km,
           fuel_type, transmission, body_type, seller_type
    FROM car_tracker.listings
    WHERE removed_at IS NULL
      AND make IS NOT NULL
      AND model IS NOT NULL
      AND latest_price_clp IS NOT NULL
),
per_year AS (
    SELECT make, model, year,
           COUNT(*)::int AS n,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY latest_price_clp)::bigint AS median_price
    FROM yr
    WHERE year IS NOT NULL
    GROUP BY make, model, year
)
SELECT
    y.make,
    y.model,
    COUNT(*)::int AS n_listings,
    MIN(y.year)   AS oldest_year,
    MAX(y.year)   AS newest_year,
    AVG(y.latest_price_clp)::bigint AS avg_price_clp,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY y.latest_price_clp)::bigint AS median_price_clp,
    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY y.latest_price_clp)::bigint AS p25_price_clp,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY y.latest_price_clp)::bigint AS p75_price_clp,
    AVG(y.km)::bigint AS avg_km,
    -- Pick the most common body_type for this model as the consensus value.
    MODE() WITHIN GROUP (ORDER BY y.body_type) AS body_type,
    MODE() WITHIN GROUP (ORDER BY y.fuel_type) AS primary_fuel_type,
    MODE() WITHIN GROUP (ORDER BY y.transmission) AS primary_transmission,
    COUNT(*) FILTER (WHERE y.seller_type = 'dealer')::int   AS n_dealer,
    COUNT(*) FILTER (WHERE y.seller_type = 'private')::int  AS n_private,
    (
        SELECT jsonb_object_agg(py.year::text, jsonb_build_object('n', py.n, 'median', py.median_price))
        FROM per_year py
        WHERE py.make = y.make AND py.model = y.model
    ) AS year_price_json
FROM yr y
GROUP BY y.make, y.model;

CREATE UNIQUE INDEX IF NOT EXISTS model_rollup_make_model_idx
    ON car_tracker.model_rollup (make, model);

-- ---------------------------------------------------------------------------
-- Grants so PostgREST (anon + authenticated + service_role) can read.
-- ---------------------------------------------------------------------------
GRANT SELECT ON car_tracker.brand_rollup TO anon, authenticated, service_role;
GRANT SELECT ON car_tracker.model_rollup TO anon, authenticated, service_role;
