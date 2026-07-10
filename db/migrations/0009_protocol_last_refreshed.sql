-- Migration 0009: protocol data refresh date.
--
-- This records a successful curator-approved full refresh or accepted data
-- update. It is distinct from the oldest factor evidence timestamp.

ALTER TABLE protocols
  ADD COLUMN IF NOT EXISTS last_refreshed date;

UPDATE protocols
SET last_refreshed = DATE '2026-05-01'
WHERE last_refreshed IS NULL;

COMMENT ON COLUMN protocols.last_refreshed IS
  'Date of the latest successful curator-approved protocol data refresh.';

CREATE INDEX IF NOT EXISTS protocols_last_refreshed_idx
  ON protocols (last_refreshed);
