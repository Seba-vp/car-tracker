-- Per-listing price-change signal computed from the append-only
-- listing_prices table. Materialized so the /price-drops dashboard page is
-- a single fast lookup; refreshed in rollup.py after every workflow run.
--
-- Apply via:
--   ./scripts/supabase-sql.sh izbokfsmplxielwiyvup "$(cat sql/price_changes.sql)"

DROP MATERIALIZED VIEW IF EXISTS car_tracker.price_changes;
CREATE MATERIALIZED VIEW car_tracker.price_changes AS
WITH per_listing AS (
    SELECT
        listing_id,
        MIN(price_clp)                                                  AS lowest_price,
        MAX(price_clp)                                                  AS highest_price,
        MIN(observed_at)                                                AS first_observed,
        MAX(observed_at)                                                AS last_observed,
        (ARRAY_AGG(price_clp ORDER BY observed_at ASC))[1]              AS first_price,
        (ARRAY_AGG(price_clp ORDER BY observed_at DESC))[1]             AS latest_price,
        (ARRAY_AGG(observed_at ORDER BY observed_at DESC))[1]           AS latest_observed,
        COUNT(DISTINCT price_clp)::int                                   AS distinct_prices,
        COUNT(*)::int                                                    AS observations
    FROM car_tracker.listing_prices
    GROUP BY listing_id
)
SELECT
    pl.listing_id,
    pl.first_price,
    pl.latest_price,
    pl.lowest_price,
    pl.highest_price,
    pl.first_observed,
    pl.latest_observed,
    pl.distinct_prices,
    pl.observations,
    (pl.latest_price - pl.first_price)                                  AS abs_change,
    CASE
        WHEN pl.first_price > 0
        THEN ((pl.latest_price - pl.first_price)::numeric / pl.first_price * 100)
        ELSE NULL
    END                                                                  AS pct_change,
    (pl.lowest_price - pl.first_price)                                  AS max_drop_abs,
    CASE
        WHEN pl.first_price > 0
        THEN ((pl.lowest_price - pl.first_price)::numeric / pl.first_price * 100)
        ELSE NULL
    END                                                                  AS max_drop_pct
FROM per_listing pl
WHERE pl.distinct_prices > 1;  -- only rows with an actual change

CREATE UNIQUE INDEX IF NOT EXISTS price_changes_listing_idx
    ON car_tracker.price_changes (listing_id);

CREATE INDEX IF NOT EXISTS price_changes_pct_idx
    ON car_tracker.price_changes (pct_change);

CREATE INDEX IF NOT EXISTS price_changes_recent_idx
    ON car_tracker.price_changes (latest_observed DESC);

GRANT SELECT ON car_tracker.price_changes TO anon, authenticated, service_role;
