-- Migration 0013: checksum ledger for explicitly managed database migrations.

CREATE TABLE IF NOT EXISTS schema_migrations (
  filename          text PRIMARY KEY,
  sha256            text NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
  applied_at        timestamptz NOT NULL DEFAULT now(),
  applied_by        text NOT NULL DEFAULT current_user,
  authorization_id  text NOT NULL
);

ALTER TABLE schema_migrations ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE schema_migrations IS
  'Checksums recorded by the explicit receipt-gated migration runner; not a public runtime table.';
