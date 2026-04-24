export type Listing = {
  id: number;
  source: string;
  source_id: string;
  url: string;
  title: string | null;
  make: string | null;
  model: string | null;
  version: string | null;
  year: number | null;
  km: number | null;
  fuel_type: string | null;
  transmission: string | null;
  body_type: string | null;
  region: string | null;
  commune: string | null;
  seller_type: string | null;
  currency: string;
  latest_price_clp: number | null;
  first_seen_at: string;
  last_seen_at: string;
  removed_at: string | null;
  source_posted_at: string | null;
  image_url: string | null;
  image_urls: string[] | null;
};

export type ScrapeRun = {
  id: number;
  source: string;
  started_at: string;
  finished_at: string | null;
  rows_fetched: number | null;
  rows_upserted: number | null;
  rows_skipped: number | null;
  price_changes: number | null;
  status: string | null;
  error: string | null;
};

export type ListingPrice = {
  listing_id: number;
  price_clp: number;
  observed_at: string;
};

export const SOURCES = [
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
] as const;

export type Source = (typeof SOURCES)[number];
