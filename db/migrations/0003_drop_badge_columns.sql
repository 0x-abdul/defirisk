-- Migration 0003: drop badge columns from public tables (PD-036, 2026-05-05).
--
-- Rationale (PD-035 UI retirement → PD-036 backend kill):
--   - protocols.headline_badge: dropped entirely; no reader since dump.py
--     stopped emitting `headline_badge` in v1.6.0.
--   - deployments.badge: dropped entirely; never written by compose.py and no
--     longer surfaced by dump.py.
--   - grade_history.badge / protocol_grade_history.badge: NOT NULL relaxed.
--     compose.py stops writing; historical rows preserved as audit record of
--     what badge values *were* surfaced under the v1.5.x rubric.
--   - grade_changes.from_badge / to_badge: NOT NULL ALTERs included for
--     idempotence (already nullable per 0002_grade_changes.sql); historical
--     transitions preserved; dump.py no longer publishes these fields in
--     /api/v1.6.0/changes.json.
--
-- Run once against the target Supabase project; idempotent via IF EXISTS.

ALTER TABLE protocols                DROP COLUMN IF EXISTS headline_badge;
ALTER TABLE deployments              DROP COLUMN IF EXISTS badge;

ALTER TABLE grade_history            ALTER COLUMN badge DROP NOT NULL;
ALTER TABLE protocol_grade_history   ALTER COLUMN badge DROP NOT NULL;

ALTER TABLE grade_changes            ALTER COLUMN from_badge DROP NOT NULL;
ALTER TABLE grade_changes            ALTER COLUMN to_badge   DROP NOT NULL;
