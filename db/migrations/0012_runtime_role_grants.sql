-- Migration 0012: keep runtime application grants reproducible.
--
-- Migration 0011 remains reserved for the deferred review-token hardening
-- work. Gaps in migration numbers are intentional and ordered lexically.

DO $migration$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rdapp') THEN
    EXECUTE 'GRANT USAGE ON SCHEMA public TO rdapp';
    EXECUTE 'REVOKE ALL PRIVILEGES '
            'ON TABLE protocol_families, protocol_surfaces FROM rdapp';
    EXECUTE 'GRANT SELECT '
            'ON TABLE protocol_families, protocol_surfaces TO rdapp';
  END IF;
END
$migration$;

COMMENT ON TABLE protocol_families IS
  'Canonical protocol-family metadata. Runtime grants are managed by migration 0012.';

COMMENT ON TABLE protocol_surfaces IS
  'Version/product surfaces within a protocol family. Runtime grants are managed by migration 0012.';
