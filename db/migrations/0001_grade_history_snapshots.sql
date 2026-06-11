-- Migration 0001: Snapshot history tables (E-32)
-- Adds daily time-series snapshots for grades and factor scores.
-- These power E-34 (grade-change feed) and E-35 (analytics charts).
-- Collection must start before launch so charts have data by launch+30d.

-- ── protocol_grade_history ───────────────────────────────────────────────────

CREATE TABLE protocol_grade_history (
  id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  protocol_slug   text        NOT NULL REFERENCES protocols(slug) ON DELETE CASCADE,
  snapshot_at     timestamptz NOT NULL,
  snapshot_date   date        NOT NULL,
  rubric_version  text        NOT NULL REFERENCES rubric_versions(version),
  grade_letter    text        NOT NULL,
  badge           text        NOT NULL,
  critical_count  smallint    NOT NULL,
  red_count       smallint    NOT NULL,
  yellow_count    smallint    NOT NULL,
  gray_core_five  boolean     NOT NULL,
  source_run_id   uuid        REFERENCES pipeline_runs(id),
  notes           text
);

CREATE UNIQUE INDEX protocol_grade_hist_daily_uniq
  ON protocol_grade_history (protocol_slug, snapshot_date);

CREATE INDEX protocol_grade_hist_protocol_idx
  ON protocol_grade_history (protocol_slug, snapshot_at DESC);

-- RLS: public read, service-role write
ALTER TABLE protocol_grade_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "public_read_protocol_grade_history"
  ON protocol_grade_history FOR SELECT
  USING (true);

-- ── factor_score_history ─────────────────────────────────────────────────────

CREATE TABLE factor_score_history (
  id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  protocol_slug   text        NOT NULL REFERENCES protocols(slug) ON DELETE CASCADE,
  factor_id       text        NOT NULL REFERENCES factors(id),
  snapshot_at     timestamptz NOT NULL,
  snapshot_date   date        NOT NULL,
  score_color     text        NOT NULL,
  score_value     text,
  rubric_version  text        NOT NULL REFERENCES rubric_versions(version),
  source_run_id   uuid        REFERENCES pipeline_runs(id),
  notes           text
);

CREATE UNIQUE INDEX factor_score_hist_daily_uniq
  ON factor_score_history (protocol_slug, factor_id, snapshot_date);

CREATE INDEX factor_score_hist_protocol_idx
  ON factor_score_history (protocol_slug, snapshot_at DESC);

-- RLS: public read, service-role write
ALTER TABLE factor_score_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "public_read_factor_score_history"
  ON factor_score_history FOR SELECT
  USING (true);
