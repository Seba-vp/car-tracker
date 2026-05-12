-- Telegram alerts: per-user rules + delivery audit + per-user settings.
-- Apply via: ./scripts/supabase-sql.sh izbokfsmplxielwiyvup "$(cat sql/alerts.sql)"

-- User chat ID + simple settings (one row per user).
CREATE TABLE IF NOT EXISTS car_tracker.user_settings (
    user_id           uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    telegram_chat_id  text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE car_tracker.user_settings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "own_settings_select" ON car_tracker.user_settings;
DROP POLICY IF EXISTS "own_settings_upsert" ON car_tracker.user_settings;
DROP POLICY IF EXISTS "own_settings_update" ON car_tracker.user_settings;

CREATE POLICY "own_settings_select" ON car_tracker.user_settings
    FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "own_settings_upsert" ON car_tracker.user_settings
    FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);
CREATE POLICY "own_settings_update" ON car_tracker.user_settings
    FOR UPDATE TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

GRANT SELECT, INSERT, UPDATE ON car_tracker.user_settings TO authenticated;

-- Alert rules: filters + threshold + trigger type.
-- criteria JSONB shape (subset of /listings query params):
--   { make, model, yearMin, yearMax, kmMin, kmMax, fuel, region, source }
-- trigger_type:
--   'below_median'  → fire when listing price ≤ cohort_median * (1 - threshold_pct/100)
--   'below_mean'    → same vs mean
--   'price_drop'    → fire when listing's pct_change ≤ -threshold_pct
CREATE TABLE IF NOT EXISTS car_tracker.alert_rules (
    id                bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id           uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    name              text NOT NULL,
    criteria          jsonb NOT NULL DEFAULT '{}'::jsonb,
    threshold_pct     numeric NOT NULL DEFAULT 10,
    trigger_type      text NOT NULL DEFAULT 'below_median',
    enabled           boolean NOT NULL DEFAULT true,
    created_at        timestamptz NOT NULL DEFAULT now(),
    last_evaluated_at timestamptz
);

CREATE INDEX IF NOT EXISTS alert_rules_user_idx
    ON car_tracker.alert_rules (user_id, enabled);

ALTER TABLE car_tracker.alert_rules ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "own_rules_all" ON car_tracker.alert_rules;
CREATE POLICY "own_rules_all" ON car_tracker.alert_rules
    FOR ALL TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON car_tracker.alert_rules TO authenticated;

-- Notification audit: ensures we never alert the same (rule, listing) twice
-- and lets the dashboard show "your rule fired N times".
CREATE TABLE IF NOT EXISTS car_tracker.alert_notifications (
    id          bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    rule_id     bigint NOT NULL REFERENCES car_tracker.alert_rules(id) ON DELETE CASCADE,
    listing_id  bigint NOT NULL REFERENCES car_tracker.listings(id) ON DELETE CASCADE,
    fired_at    timestamptz NOT NULL DEFAULT now(),
    delivery    text NOT NULL DEFAULT 'sent',  -- sent | failed
    error       text,
    UNIQUE (rule_id, listing_id)
);

CREATE INDEX IF NOT EXISTS alert_notifications_rule_idx
    ON car_tracker.alert_notifications (rule_id, fired_at DESC);

ALTER TABLE car_tracker.alert_notifications ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "own_notifications_select" ON car_tracker.alert_notifications;
CREATE POLICY "own_notifications_select" ON car_tracker.alert_notifications
    FOR SELECT TO authenticated
    USING (EXISTS (
        SELECT 1 FROM car_tracker.alert_rules r
        WHERE r.id = alert_notifications.rule_id AND r.user_id = auth.uid()
    ));

GRANT SELECT ON car_tracker.alert_notifications TO authenticated;
