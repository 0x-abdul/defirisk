-- Migration 0004: factor_scores.gap_reason column (PD-039, 2026-05-11).
--
-- Rationale (PD-039 — extended GRAY semantics):
--   Specialists annotate each GRAY / not_assessed cell with a reason enum
--   describing WHY it couldn't be measured. The dashboard surfaces this
--   distinction in the UI tooltip ("GRAY — protocol opaque" vs "GRAY —
--   measurement pending") so protocols bear no penalty for our incomplete
--   tooling.
--
--   The PD-039 migration (scripts/migrations/pd-039-gray-gap-reason.py) added
--   the field to the published API JSONs directly. This migration adds the
--   column to the source-of-truth `factor_scores` table so the importer
--   (scripts/import-protocol-assessment.py) can write it through and dump.py
--   regenerates published JSONs WITH gap_reason on every fill.
--
-- Idempotent via IF NOT EXISTS on the column add; the CHECK constraint is
-- ADD CONSTRAINT IF NOT EXISTS via DO block (PostgreSQL idiom).

ALTER TABLE factor_scores
  ADD COLUMN IF NOT EXISTS gap_reason VARCHAR(40) NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'factor_scores_gap_reason_check'
  ) THEN
    ALTER TABLE factor_scores
      ADD CONSTRAINT factor_scores_gap_reason_check
      CHECK (
        gap_reason IS NULL
        OR gap_reason IN (
          'protocol_opacity',
          'pipeline_unimplemented',
          'external_api_blocked',
          'requires_curator_input',
          'not_applicable'
        )
      );
  END IF;
END$$;

COMMENT ON COLUMN factor_scores.gap_reason IS
  'PD-039 (2026-05-11) — why a GRAY / not_assessed cell could not be measured. '
  'NULL on graded scores (green/yellow/red). Required (soft) on gray/not_assessed.';
