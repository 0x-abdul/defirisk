-- Migration 0002: grade_changes table (E-34 grade-change feed)
-- Run once against the target Supabase project.

CREATE TABLE IF NOT EXISTS grade_changes (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    protocol_slug       TEXT NOT NULL REFERENCES protocols(slug) ON DELETE CASCADE,
    detected_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    from_grade          TEXT NOT NULL,
    to_grade            TEXT NOT NULL,
    from_badge          TEXT,
    to_badge            TEXT,
    rubric_version      TEXT NOT NULL REFERENCES rubric_versions(version),
    snapshot_date_before DATE NOT NULL,
    snapshot_date_after  DATE NOT NULL,
    reason              TEXT,
    is_upgrade          BOOLEAN NOT NULL,
    source_run_id       UUID REFERENCES pipeline_runs(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS grade_changes_transition_uniq
    ON grade_changes (protocol_slug, snapshot_date_before, snapshot_date_after);

CREATE INDEX IF NOT EXISTS grade_changes_protocol_idx
    ON grade_changes (protocol_slug, detected_at DESC);

CREATE INDEX IF NOT EXISTS grade_changes_detected_idx
    ON grade_changes (detected_at DESC);

ALTER TABLE grade_changes ENABLE ROW LEVEL SECURITY;

CREATE POLICY "public_read_grade_changes"
    ON grade_changes FOR SELECT USING (true);
