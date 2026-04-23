-- car-tracker schema
-- Hosted inside the prop-wizard Supabase project (shared-free-tier workaround).
-- See CLAUDE.md for the "split to own DB" migration plan.
--
-- Apply via: ./scripts/supabase-sql.sh <prop-wizard-ref> "$(cat sql/schema.sql)"

CREATE SCHEMA IF NOT EXISTS car_tracker;

-- Allow Supabase's standard roles to see + operate within the schema.
GRANT USAGE ON SCHEMA car_tracker TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA car_tracker GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA car_tracker GRANT SELECT ON TABLES TO authenticated;

CREATE TABLE IF NOT EXISTS car_tracker.listings (
  id                  bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  source              text NOT NULL,
  source_id           text NOT NULL,
  url                 text NOT NULL,
  title               text,
  make                text,
  model               text,
  version             text,
  year                integer,
  km                  integer,
  fuel_type           text,
  transmission        text,
  body_type           text,
  region              text,
  commune             text,
  seller_type         text,
  currency            text NOT NULL DEFAULT 'CLP',
  latest_price_clp    bigint,
  first_seen_at       timestamptz NOT NULL DEFAULT now(),
  last_seen_at        timestamptz NOT NULL DEFAULT now(),
  removed_at          timestamptz,
  source_posted_at    timestamptz,
  raw                 jsonb,
  UNIQUE (source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_listings_make_model_year
  ON car_tracker.listings (make, model, year) WHERE removed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_listings_last_seen
  ON car_tracker.listings (last_seen_at);
CREATE INDEX IF NOT EXISTS idx_listings_price_live
  ON car_tracker.listings (latest_price_clp) WHERE removed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_listings_source_id
  ON car_tracker.listings (source, source_id);

CREATE TABLE IF NOT EXISTS car_tracker.listing_prices (
  listing_id   bigint NOT NULL REFERENCES car_tracker.listings(id) ON DELETE CASCADE,
  price_clp    bigint NOT NULL,
  observed_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (listing_id, observed_at)
);

CREATE INDEX IF NOT EXISTS idx_listing_prices_observed
  ON car_tracker.listing_prices (observed_at);

CREATE TABLE IF NOT EXISTS car_tracker.market_stats (
  make          text NOT NULL,
  model         text NOT NULL,
  year          integer NOT NULL,
  km_bucket     integer NOT NULL,
  fuel_type     text NOT NULL,
  median_price  bigint,
  p25           bigint,
  p75           bigint,
  mean_price    numeric,
  stddev        numeric,
  n_samples     integer,
  computed_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (make, model, year, km_bucket, fuel_type, computed_at)
);

CREATE TABLE IF NOT EXISTS car_tracker.scrape_runs (
  id              bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  source          text NOT NULL,
  started_at      timestamptz NOT NULL DEFAULT now(),
  finished_at     timestamptz,
  rows_fetched    integer,
  rows_upserted   integer,
  rows_skipped    integer,
  price_changes   integer,
  status          text,
  error           text
);

CREATE INDEX IF NOT EXISTS idx_scrape_runs_source_started
  ON car_tracker.scrape_runs (source, started_at DESC);

-- RLS: service_role bypasses it; authenticated is read-only.
ALTER TABLE car_tracker.listings         ENABLE ROW LEVEL SECURITY;
ALTER TABLE car_tracker.listing_prices   ENABLE ROW LEVEL SECURITY;
ALTER TABLE car_tracker.market_stats     ENABLE ROW LEVEL SECURITY;
ALTER TABLE car_tracker.scrape_runs      ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "read_listings"       ON car_tracker.listings;
DROP POLICY IF EXISTS "read_listing_prices" ON car_tracker.listing_prices;
DROP POLICY IF EXISTS "read_market_stats"   ON car_tracker.market_stats;

CREATE POLICY "read_listings"       ON car_tracker.listings       FOR SELECT TO authenticated USING (true);
CREATE POLICY "read_listing_prices" ON car_tracker.listing_prices FOR SELECT TO authenticated USING (true);
CREATE POLICY "read_market_stats"   ON car_tracker.market_stats   FOR SELECT TO authenticated USING (true);
