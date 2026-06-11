-- Migration 0006: Dashboard publish flag (2026-05-18).
--
-- Adds is_published to protocols so the data pipeline can gate which protocols
-- appear in the public-facing index.json while individual {slug}.json files
-- remain accessible for internal review and protocol-team outreach.
--
-- Separation of concerns:
--   protocols.status  — real-world lifecycle state (live / deprecated / under_review)
--   protocols.is_published — editorial decision: should this appear on the dashboard?
--
-- Default FALSE: all existing protocols start unpublished.
-- Use set_published.py (or direct SQL) to flip individual slugs when ready.
-- Idempotent via IF NOT EXISTS.

ALTER TABLE protocols
  ADD COLUMN IF NOT EXISTS is_published boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN protocols.is_published IS
  'When true this protocol appears in index.json and is rendered on the '
  'live dashboard. Defaults to false so new protocols can be collected, '
  'graded, and shared for outreach review before going public.';

CREATE INDEX IF NOT EXISTS protocols_is_published_idx
  ON protocols (is_published);
