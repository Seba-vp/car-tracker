-- Per-user watchlist. One row per (user, listing) they've starred.
-- RLS scopes all access to the owning user via their JWT `auth.uid()`.
--
-- Apply via:
--   ./scripts/supabase-sql.sh izbokfsmplxielwiyvup "$(cat sql/watchlist.sql)"

CREATE TABLE IF NOT EXISTS car_tracker.watchlist (
    user_id     uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    listing_id  bigint NOT NULL REFERENCES car_tracker.listings(id) ON DELETE CASCADE,
    added_at    timestamptz NOT NULL DEFAULT now(),
    notes       text,
    PRIMARY KEY (user_id, listing_id)
);

CREATE INDEX IF NOT EXISTS idx_watchlist_user
    ON car_tracker.watchlist (user_id, added_at DESC);

ALTER TABLE car_tracker.watchlist ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "own_watchlist_select" ON car_tracker.watchlist;
DROP POLICY IF EXISTS "own_watchlist_insert" ON car_tracker.watchlist;
DROP POLICY IF EXISTS "own_watchlist_update" ON car_tracker.watchlist;
DROP POLICY IF EXISTS "own_watchlist_delete" ON car_tracker.watchlist;

CREATE POLICY "own_watchlist_select" ON car_tracker.watchlist
    FOR SELECT TO authenticated
    USING (auth.uid() = user_id);

CREATE POLICY "own_watchlist_insert" ON car_tracker.watchlist
    FOR INSERT TO authenticated
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "own_watchlist_update" ON car_tracker.watchlist
    FOR UPDATE TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "own_watchlist_delete" ON car_tracker.watchlist
    FOR DELETE TO authenticated
    USING (auth.uid() = user_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON car_tracker.watchlist TO authenticated;
