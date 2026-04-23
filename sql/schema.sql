-- chile-cars Supabase schema
-- Apply via: ./scripts/supabase-sql.sh <ref> "$(cat sql/schema.sql)"

CREATE TABLE IF NOT EXISTS listings (
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
  ON listings (make, model, year) WHERE removed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_listings_last_seen
  ON listings (last_seen_at);
CREATE INDEX IF NOT EXISTS idx_listings_price_live
  ON listings (latest_price_clp) WHERE removed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_listings_source_id
  ON listings (source, source_id);

CREATE TABLE IF NOT EXISTS listing_prices (
  listing_id   bigint NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
  price_clp    bigint NOT NULL,
  observed_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (listing_id, observed_at)
);

CREATE INDEX IF NOT EXISTS idx_listing_prices_observed
  ON listing_prices (observed_at);

CREATE TABLE IF NOT EXISTS market_stats (
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

CREATE TABLE IF NOT EXISTS scrape_runs (
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
  ON scrape_runs (source, started_at DESC);

-- RLS: lock writes to service_role, allow authenticated read-only
ALTER TABLE listings         ENABLE ROW LEVEL SECURITY;
ALTER TABLE listing_prices   ENABLE ROW LEVEL SECURITY;
ALTER TABLE market_stats     ENABLE ROW LEVEL SECURITY;
ALTER TABLE scrape_runs      ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "read_listings"       ON listings;
DROP POLICY IF EXISTS "read_listing_prices" ON listing_prices;
DROP POLICY IF EXISTS "read_market_stats"   ON market_stats;

CREATE POLICY "read_listings"       ON listings       FOR SELECT TO authenticated USING (true);
CREATE POLICY "read_listing_prices" ON listing_prices FOR SELECT TO authenticated USING (true);
CREATE POLICY "read_market_stats"   ON market_stats   FOR SELECT TO authenticated USING (true);
