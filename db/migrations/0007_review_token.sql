-- Migration 0007: Per-protocol review token (2026-05-27).
--
-- Adds review_token to protocols so unpublished protocols can be shared at an
-- unguessable URL like /unpublished/<slug>-<token>/ during the pre-publication
-- review window. The token is stable for the lifetime of the protocol — it
-- does not rotate when is_published flips.
--
-- 8 hex chars (4 random bytes) gives ~4.3B possibilities — adequate for
-- "obscure, not authenticated"; combined with robots noindex + sitemap
-- exclusion the unpublished surface is unreachable by crawlers.
--
-- Backfill: existing rows get a fresh random token.
-- Idempotent via IF NOT EXISTS / DO blocks.

ALTER TABLE protocols
  ADD COLUMN IF NOT EXISTS review_token text;

UPDATE protocols
  SET review_token = encode(gen_random_bytes(4), 'hex')
  WHERE review_token IS NULL;

ALTER TABLE protocols
  ALTER COLUMN review_token SET NOT NULL,
  ALTER COLUMN review_token SET DEFAULT encode(gen_random_bytes(4), 'hex');

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'protocols_review_token_key'
  ) THEN
    ALTER TABLE protocols
      ADD CONSTRAINT protocols_review_token_key UNIQUE (review_token);
  END IF;
END $$;

COMMENT ON COLUMN protocols.review_token IS
  'Unguessable 8-hex-char token used in /unpublished/<slug>-<token>/ URLs '
  'during pre-publication review. Stable for the lifetime of the row.';
