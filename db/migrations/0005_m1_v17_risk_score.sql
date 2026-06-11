-- Migration 0005: M1 v4 rubric columns — risk_score, cap_applied, cap_reason,
--                 category_severities (PD-042, 2026-05-12).
--
-- Rationale (M1 v4 / v1.7.0 rubric migration):
--   The v1.7.0 rubric replaces the deterministic-integer letter-grade with a
--   continuous 0–100 risk score computed from per-category severity values and
--   a core-five-weighted average. The single-category cap override persists a
--   human-readable reason when it fires. All four values are materialized into
--   grade_history on every compose run so the audit trail is complete.
--
--   protocols.risk_score is a denormalized mirror (like headline_grade)
--   refreshed by compose.py on every grade run. Enables efficient list-sort
--   queries without a join to grade_history.
--
-- Non-breaking: all new columns are nullable. Old rows (v1.6.0 and earlier)
-- naturally retain NULL in these fields. Rollback: add a 0006_*.sql that
-- DROPs these four columns — no data loss to existing rows.
--
-- Idempotent via IF NOT EXISTS on every column add.

-- ── grade_history ─────────────────────────────────────────────────────────────

ALTER TABLE grade_history
  ADD COLUMN IF NOT EXISTS risk_score          numeric(5,2) NULL,
  ADD COLUMN IF NOT EXISTS cap_applied         text         NULL,
  ADD COLUMN IF NOT EXISTS cap_reason          text         NULL,
  ADD COLUMN IF NOT EXISTS category_severities jsonb        NULL;

COMMENT ON COLUMN grade_history.risk_score IS
  'M1 v4 (v1.7.0) — protocol risk score 0–100 (2 d.p.). NULL on rows '
  'written before v1.7.0.';

COMMENT ON COLUMN grade_history.cap_applied IS
  'M1 v4 (v1.7.0) — single-category cap that overrode the natural letter. '
  'Values: ''none'' | ''D'' | ''F''. NULL on rows written before v1.7.0.';

COMMENT ON COLUMN grade_history.cap_reason IS
  'M1 v4 (v1.7.0) — human-readable explanation of the cap, e.g. '
  '"Cat 5 severity 67 >= 60 (core-five cap)". NULL when no cap fired.';

COMMENT ON COLUMN grade_history.category_severities IS
  'M1 v4 (v1.7.0) — jsonb object keyed by cat_id (1–13, as text), '
  'values are numeric severity 0–100. Example: {"1": 33.33, "2": 0, ...}. '
  'NULL on rows written before v1.7.0.';

-- ── protocols (denormalized mirror — refreshed on every compose run) ──────────

ALTER TABLE protocols
  ADD COLUMN IF NOT EXISTS risk_score          numeric(5,2) NULL,
  ADD COLUMN IF NOT EXISTS category_severities jsonb        NULL,
  ADD COLUMN IF NOT EXISTS cap_applied         text         NULL,
  ADD COLUMN IF NOT EXISTS cap_reason          text         NULL;

COMMENT ON COLUMN protocols.risk_score IS
  'M1 v4 (v1.7.0) — denormalized mirror of the most recent grade_history '
  'risk_score for this protocol. Refreshed by compose.py alongside '
  'headline_grade and graded_at. NULL until first v1.7.0 compose run.';

COMMENT ON COLUMN protocols.category_severities IS
  'M1 v4 (v1.7.0) — denormalized mirror of the most recent grade_history '
  'category_severities jsonb for this protocol. Keyed by cat_id (1–13 as '
  'text), values are numeric severity 0–100. NULL until first v1.7.0 compose run.';

COMMENT ON COLUMN protocols.cap_applied IS
  'M1 v4 (v1.7.0) — denormalized mirror of the cap that overrode the natural '
  'letter on the most recent compose run. Values: ''none'' | ''D'' | ''F''. '
  'NULL until first v1.7.0 compose run.';

COMMENT ON COLUMN protocols.cap_reason IS
  'M1 v4 (v1.7.0) — human-readable explanation of the cap on the most recent '
  'compose run, e.g. "Cat 5 severity 67 >= 60 (core-five cap)". '
  'NULL when no cap fired or before first v1.7.0 compose run.';

-- Optional covering index: allows fast ORDER BY risk_score without
-- sorting NULL rows into the list (protocols awaiting first grade run).
CREATE INDEX IF NOT EXISTS protocols_risk_score_idx
  ON protocols (risk_score)
  WHERE risk_score IS NOT NULL;
