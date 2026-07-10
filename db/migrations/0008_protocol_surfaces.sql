-- Migration 0008: protocol families + protocol surfaces.
--
-- Multi-version coverage keeps the public protocol/family page stable while
-- making the version/surface the default grading unit. Existing protocol rows
-- are backfilled into one family + one default surface, so current single
-- surface pages keep their old shape until curated family merges are added.
-- The explicit transaction boundary makes direct psql -f application atomic.

BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'protocol_surface_status') THEN
    CREATE TYPE protocol_surface_status AS ENUM (
      'active',
      'legacy',
      'deprecated',
      'experimental'
    );
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS protocol_families (
  family_slug               text PRIMARY KEY NOT NULL REFERENCES protocols(slug) ON DELETE CASCADE,
  display_name              text NOT NULL,
  description               text,
  homepage_url              text,
  protocol_type             text NOT NULL,
  primary_chain             text NOT NULL,
  primary_surface_id        uuid,
  headline_grade            char(1),
  total_value_secured_usd   numeric(20, 2),
  risk_score                numeric(5, 2),
  category_severities       jsonb,
  cap_applied               text,
  cap_reason                text,
  graded_at                 timestamptz,
  rubric_version            text REFERENCES rubric_versions(version),
  status                    protocol_status NOT NULL DEFAULT 'live',
  has_active_incident       boolean NOT NULL DEFAULT false,
  is_published              boolean NOT NULL DEFAULT false,
  review_token              text NOT NULL DEFAULT substr(md5(random()::text || clock_timestamp()::text), 1, 8),
  legacy_caveat             text,
  created_at                timestamptz NOT NULL DEFAULT now(),
  updated_at                timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS protocol_families_review_token_key
  ON protocol_families (review_token);

CREATE INDEX IF NOT EXISTS protocol_families_published_idx
  ON protocol_families (is_published);

CREATE INDEX IF NOT EXISTS protocol_families_primary_surface_idx
  ON protocol_families (primary_surface_id)
  WHERE primary_surface_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS protocol_surfaces (
  surface_id                uuid PRIMARY KEY NOT NULL DEFAULT gen_random_uuid(),
  family_slug               text NOT NULL REFERENCES protocol_families(family_slug) ON DELETE CASCADE,
  surface_slug              text NOT NULL,
  display_name              text NOT NULL,
  status                    protocol_surface_status NOT NULL DEFAULT 'active',
  launched_at               date,
  primary_chain             text NOT NULL,
  tvs_usd                   numeric(20, 2),
  headline_grade            char(1),
  risk_score                numeric(5, 2),
  category_severities       jsonb,
  cap_applied               text,
  cap_reason                text,
  graded_at                 timestamptz,
  rubric_version            text REFERENCES rubric_versions(version),
  scope_note                text,
  is_primary                boolean NOT NULL DEFAULT false,
  -- Compatibility alias for existing route/API slugs such as aave-v3.
  legacy_slug               text UNIQUE,
  created_at                timestamptz NOT NULL DEFAULT now(),
  updated_at                timestamptz NOT NULL DEFAULT now(),
  UNIQUE (family_slug, surface_slug)
);

CREATE UNIQUE INDEX IF NOT EXISTS protocol_surfaces_one_primary
  ON protocol_surfaces (family_slug)
  WHERE is_primary = true;

CREATE INDEX IF NOT EXISTS protocol_surfaces_family_idx
  ON protocol_surfaces (family_slug, status, surface_slug);

CREATE UNIQUE INDEX IF NOT EXISTS protocol_surfaces_family_surface_id_unique
  ON protocol_surfaces (family_slug, surface_id);

ALTER TABLE protocol_families
  DROP CONSTRAINT IF EXISTS protocol_families_primary_surface_fk;

ALTER TABLE protocol_families
  ADD CONSTRAINT protocol_families_primary_surface_fk
  FOREIGN KEY (family_slug, primary_surface_id)
  REFERENCES protocol_surfaces(family_slug, surface_id)
  DEFERRABLE INITIALLY DEFERRED;

-- Backfill one family + one default surface for every existing protocol.
INSERT INTO protocol_families (
  family_slug, display_name, description, homepage_url, protocol_type,
  primary_chain, headline_grade, total_value_secured_usd, risk_score,
  category_severities, cap_applied, cap_reason, graded_at, rubric_version,
  status, has_active_incident, is_published, review_token
)
SELECT
  p.slug, p.display_name, p.description, p.homepage_url, p.protocol_type,
  p.primary_chain, p.headline_grade, p.total_value_secured_usd, p.risk_score,
  p.category_severities, p.cap_applied, p.cap_reason, p.graded_at, p.rubric_version,
  p.status, p.has_active_incident, p.is_published, p.review_token
FROM protocols p
ON CONFLICT (family_slug) DO NOTHING;

INSERT INTO protocol_surfaces (
  family_slug, surface_slug, display_name, status, launched_at,
  primary_chain, tvs_usd, headline_grade, risk_score, category_severities,
  cap_applied, cap_reason, graded_at, rubric_version, is_primary, legacy_slug
)
SELECT
  p.slug, 'default', p.display_name,
  CASE WHEN p.status = 'deprecated' THEN 'deprecated'::protocol_surface_status ELSE 'active'::protocol_surface_status END,
  p.launched_at, p.primary_chain, p.total_value_secured_usd, p.headline_grade,
  p.risk_score, p.category_severities, p.cap_applied, p.cap_reason,
  p.graded_at, p.rubric_version, true, p.slug
FROM protocols p
WHERE NOT EXISTS (
  SELECT 1
  FROM protocol_surfaces existing
  WHERE existing.family_slug = p.slug
)
ON CONFLICT (family_slug, surface_slug) DO UPDATE SET
  display_name              = EXCLUDED.display_name,
  status                    = EXCLUDED.status,
  launched_at               = COALESCE(EXCLUDED.launched_at, protocol_surfaces.launched_at),
  primary_chain             = EXCLUDED.primary_chain,
  tvs_usd                   = EXCLUDED.tvs_usd,
  headline_grade            = EXCLUDED.headline_grade,
  risk_score                = EXCLUDED.risk_score,
  category_severities       = EXCLUDED.category_severities,
  cap_applied               = EXCLUDED.cap_applied,
  cap_reason                = EXCLUDED.cap_reason,
  graded_at                 = EXCLUDED.graded_at,
  rubric_version            = EXCLUDED.rubric_version,
  is_primary                = true,
  legacy_slug               = COALESCE(protocol_surfaces.legacy_slug, EXCLUDED.legacy_slug),
  updated_at                = now();

UPDATE protocol_families pf
SET primary_surface_id = ps.surface_id,
    updated_at = now()
FROM protocol_surfaces ps
WHERE ps.family_slug = pf.family_slug
  AND ps.is_primary = true
  AND pf.primary_surface_id IS DISTINCT FROM ps.surface_id;

-- The primary-surface FK is deferrable so family/surface bootstrap can happen
-- in one migration. Force it to check now before later ALTER TABLE statements,
-- otherwise PostgreSQL can report pending trigger events on protocol_families.
SET CONSTRAINTS protocol_families_primary_surface_fk IMMEDIATE;

-- Deployments now belong to a surface. deployment_key lets a surface carry
-- multiple same-chain anchors without the old one-row-per-chain collapse.
ALTER TABLE deployments
  ADD COLUMN IF NOT EXISTS surface_id uuid,
  ADD COLUMN IF NOT EXISTS deployment_key text NOT NULL DEFAULT 'primary';

UPDATE deployments d
SET surface_id = ps.surface_id
FROM protocol_surfaces ps
WHERE ps.legacy_slug = d.protocol_slug
  AND d.surface_id IS NULL;
ALTER TABLE deployments
  ALTER COLUMN surface_id SET NOT NULL;

ALTER TABLE deployments
  DROP CONSTRAINT IF EXISTS deployments_surface_fk;

ALTER TABLE deployments
  ADD CONSTRAINT deployments_surface_fk
  FOREIGN KEY (protocol_slug, surface_id)
  REFERENCES protocol_surfaces(family_slug, surface_id) ON DELETE CASCADE;

DROP INDEX IF EXISTS deployments_protocol_chain_unique;

CREATE UNIQUE INDEX IF NOT EXISTS deployments_surface_chain_key_unique
  ON deployments (surface_id, chain, deployment_key);

CREATE UNIQUE INDEX IF NOT EXISTS deployments_protocol_surface_id_unique
  ON deployments (protocol_slug, surface_id, id);

CREATE INDEX IF NOT EXISTS deployments_surface_idx
  ON deployments (surface_id);

-- Score scope. Existing current rows become surface-scoped rows on the default
-- surface for their protocol.
ALTER TABLE factor_scores
  ADD COLUMN IF NOT EXISTS scope_level text NOT NULL DEFAULT 'surface',
  ADD COLUMN IF NOT EXISTS family_slug text REFERENCES protocol_families(family_slug) ON DELETE CASCADE,
  ADD COLUMN IF NOT EXISTS surface_id uuid REFERENCES protocol_surfaces(surface_id) ON DELETE CASCADE;

UPDATE factor_scores fs
SET surface_id = ps.surface_id,
    scope_level = 'surface',
    family_slug = NULL
FROM protocol_surfaces ps
WHERE ps.legacy_slug = fs.protocol_slug
  AND fs.surface_id IS NULL
  AND fs.family_slug IS NULL
  AND fs.scope_level = 'surface'
  AND fs.deployment_id IS NULL;

UPDATE factor_scores fs
SET scope_level = 'deployment',
    surface_id = d.surface_id,
    family_slug = NULL
FROM deployments d
WHERE fs.deployment_id = d.id;

ALTER TABLE factor_scores
  DROP CONSTRAINT IF EXISTS factor_scores_scope_level_check,
  DROP CONSTRAINT IF EXISTS factor_scores_scope_target_check,
  DROP CONSTRAINT IF EXISTS factor_scores_surface_owner_fk,
  DROP CONSTRAINT IF EXISTS factor_scores_deployment_owner_fk;

ALTER TABLE factor_scores
  ADD CONSTRAINT factor_scores_scope_level_check
    CHECK (scope_level IN ('family', 'surface', 'deployment')),
  ADD CONSTRAINT factor_scores_scope_target_check
    CHECK (
      (scope_level = 'family' AND family_slug = protocol_slug AND surface_id IS NULL AND deployment_id IS NULL)
      OR
      (scope_level = 'surface' AND surface_id IS NOT NULL AND family_slug IS NULL AND deployment_id IS NULL)
      OR
      (scope_level = 'deployment' AND deployment_id IS NOT NULL AND surface_id IS NOT NULL AND family_slug IS NULL)
    ),
  ADD CONSTRAINT factor_scores_surface_owner_fk
    FOREIGN KEY (protocol_slug, surface_id)
    REFERENCES protocol_surfaces(family_slug, surface_id) ON DELETE CASCADE,
  ADD CONSTRAINT factor_scores_deployment_owner_fk
    FOREIGN KEY (protocol_slug, surface_id, deployment_id)
    REFERENCES deployments(protocol_slug, surface_id, id) ON DELETE CASCADE;

DROP INDEX IF EXISTS factor_scores_current_unique;

CREATE UNIQUE INDEX IF NOT EXISTS factor_scores_current_scoped_unique
  ON factor_scores (
    protocol_slug,
    scope_level,
    COALESCE(family_slug, ''),
    COALESCE(surface_id::text, ''),
    COALESCE(deployment_id::text, ''),
    factor_id,
    rubric_version
  )
  WHERE is_current = true;

CREATE INDEX IF NOT EXISTS factor_scores_surface_current_idx
  ON factor_scores (surface_id)
  WHERE is_current = true AND surface_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS factor_scores_family_current_idx
  ON factor_scores (family_slug)
  WHERE is_current = true AND family_slug IS NOT NULL;

-- History mirrors the scoped write path. The old protocol_slug remains for
-- compatibility with existing feeds and public URLs.
ALTER TABLE grade_history
  ADD COLUMN IF NOT EXISTS scope_level text NOT NULL DEFAULT 'surface',
  ADD COLUMN IF NOT EXISTS family_slug text REFERENCES protocol_families(family_slug) ON DELETE CASCADE,
  ADD COLUMN IF NOT EXISTS surface_id uuid REFERENCES protocol_surfaces(surface_id) ON DELETE CASCADE;

UPDATE grade_history gh
SET surface_id = ps.surface_id,
    scope_level = 'surface',
    family_slug = NULL
FROM protocol_surfaces ps
WHERE ps.legacy_slug = gh.protocol_slug
  AND gh.surface_id IS NULL
  AND gh.family_slug IS NULL
  AND gh.scope_level = 'surface'
  AND gh.deployment_id IS NULL;

UPDATE grade_history gh
SET surface_id = d.surface_id,
    scope_level = 'deployment',
    family_slug = NULL
FROM deployments d
WHERE gh.deployment_id = d.id;

ALTER TABLE grade_history
  DROP CONSTRAINT IF EXISTS grade_history_scope_level_check,
  DROP CONSTRAINT IF EXISTS grade_history_scope_target_check,
  DROP CONSTRAINT IF EXISTS grade_history_surface_owner_fk,
  DROP CONSTRAINT IF EXISTS grade_history_deployment_owner_fk;

ALTER TABLE grade_history
  ADD CONSTRAINT grade_history_scope_level_check
    CHECK (scope_level IN ('family', 'surface', 'deployment')),
  ADD CONSTRAINT grade_history_scope_target_check
    CHECK (
      (scope_level = 'family' AND family_slug = protocol_slug AND surface_id IS NULL AND deployment_id IS NULL)
      OR
      (scope_level = 'surface' AND surface_id IS NOT NULL AND family_slug IS NULL AND deployment_id IS NULL)
      OR
      (scope_level = 'deployment' AND deployment_id IS NOT NULL AND surface_id IS NOT NULL AND family_slug IS NULL)
    ),
  ADD CONSTRAINT grade_history_surface_owner_fk
    FOREIGN KEY (protocol_slug, surface_id)
    REFERENCES protocol_surfaces(family_slug, surface_id) ON DELETE CASCADE,
  ADD CONSTRAINT grade_history_deployment_owner_fk
    FOREIGN KEY (protocol_slug, surface_id, deployment_id)
    REFERENCES deployments(protocol_slug, surface_id, id) ON DELETE CASCADE;

ALTER TABLE protocol_grade_history
  ADD COLUMN IF NOT EXISTS scope_level text NOT NULL DEFAULT 'surface',
  ADD COLUMN IF NOT EXISTS family_slug text REFERENCES protocol_families(family_slug) ON DELETE CASCADE,
  ADD COLUMN IF NOT EXISTS surface_id uuid REFERENCES protocol_surfaces(surface_id) ON DELETE CASCADE;

UPDATE protocol_grade_history pgh
SET surface_id = ps.surface_id,
    scope_level = 'surface',
    family_slug = NULL
FROM protocol_surfaces ps
WHERE ps.legacy_slug = pgh.protocol_slug
  AND pgh.surface_id IS NULL
  AND pgh.family_slug IS NULL
  AND pgh.scope_level = 'surface';

ALTER TABLE protocol_grade_history
  DROP CONSTRAINT IF EXISTS protocol_grade_history_scope_level_check,
  DROP CONSTRAINT IF EXISTS protocol_grade_history_scope_target_check,
  DROP CONSTRAINT IF EXISTS protocol_grade_history_surface_owner_fk;

ALTER TABLE protocol_grade_history
  ADD CONSTRAINT protocol_grade_history_scope_level_check
    CHECK (scope_level IN ('family', 'surface')),
  ADD CONSTRAINT protocol_grade_history_scope_target_check
    CHECK (
      (scope_level = 'family' AND family_slug = protocol_slug AND surface_id IS NULL)
      OR
      (scope_level = 'surface' AND surface_id IS NOT NULL AND family_slug IS NULL)
    ),
  ADD CONSTRAINT protocol_grade_history_surface_owner_fk
    FOREIGN KEY (protocol_slug, surface_id)
    REFERENCES protocol_surfaces(family_slug, surface_id) ON DELETE CASCADE;

DROP INDEX IF EXISTS protocol_grade_hist_daily_uniq;

CREATE UNIQUE INDEX IF NOT EXISTS protocol_grade_hist_daily_scoped_uniq
  ON protocol_grade_history (
    protocol_slug,
    scope_level,
    COALESCE(family_slug, ''),
    COALESCE(surface_id::text, ''),
    snapshot_date
  );

ALTER TABLE factor_score_history
  ADD COLUMN IF NOT EXISTS scope_level text NOT NULL DEFAULT 'surface',
  ADD COLUMN IF NOT EXISTS family_slug text REFERENCES protocol_families(family_slug) ON DELETE CASCADE,
  ADD COLUMN IF NOT EXISTS surface_id uuid REFERENCES protocol_surfaces(surface_id) ON DELETE CASCADE,
  ADD COLUMN IF NOT EXISTS deployment_id uuid REFERENCES deployments(id) ON DELETE CASCADE;

UPDATE factor_score_history fsh
SET surface_id = ps.surface_id,
    scope_level = 'surface',
    family_slug = NULL
FROM protocol_surfaces ps
WHERE ps.legacy_slug = fsh.protocol_slug
  AND fsh.surface_id IS NULL
  AND fsh.family_slug IS NULL
  AND fsh.scope_level = 'surface';

ALTER TABLE factor_score_history
  DROP CONSTRAINT IF EXISTS factor_score_history_scope_level_check,
  DROP CONSTRAINT IF EXISTS factor_score_history_scope_target_check,
  DROP CONSTRAINT IF EXISTS factor_score_history_surface_owner_fk,
  DROP CONSTRAINT IF EXISTS factor_score_history_deployment_owner_fk;

ALTER TABLE factor_score_history
  ADD CONSTRAINT factor_score_history_scope_level_check
    CHECK (scope_level IN ('family', 'surface', 'deployment')),
  ADD CONSTRAINT factor_score_history_scope_target_check
    CHECK (
      (scope_level = 'family' AND family_slug = protocol_slug AND surface_id IS NULL AND deployment_id IS NULL)
      OR
      (scope_level = 'surface' AND surface_id IS NOT NULL AND family_slug IS NULL AND deployment_id IS NULL)
      OR
      (scope_level = 'deployment' AND deployment_id IS NOT NULL AND surface_id IS NOT NULL AND family_slug IS NULL)
    ),
  ADD CONSTRAINT factor_score_history_surface_owner_fk
    FOREIGN KEY (protocol_slug, surface_id)
    REFERENCES protocol_surfaces(family_slug, surface_id) ON DELETE CASCADE,
  ADD CONSTRAINT factor_score_history_deployment_owner_fk
    FOREIGN KEY (protocol_slug, surface_id, deployment_id)
    REFERENCES deployments(protocol_slug, surface_id, id) ON DELETE CASCADE;

DROP INDEX IF EXISTS factor_score_hist_daily_uniq;

CREATE UNIQUE INDEX IF NOT EXISTS factor_score_hist_daily_scoped_uniq
  ON factor_score_history (
    protocol_slug,
    scope_level,
    COALESCE(family_slug, ''),
    COALESCE(surface_id::text, ''),
    COALESCE(deployment_id::text, ''),
    factor_id,
    snapshot_date
  );

-- Grade-change events follow the same scope as their source snapshots so
-- sibling surfaces cannot be interleaved into false transitions.
ALTER TABLE grade_changes
  ADD COLUMN IF NOT EXISTS scope_level text NOT NULL DEFAULT 'surface',
  ADD COLUMN IF NOT EXISTS family_slug text REFERENCES protocol_families(family_slug) ON DELETE CASCADE,
  ADD COLUMN IF NOT EXISTS surface_id uuid REFERENCES protocol_surfaces(surface_id) ON DELETE CASCADE,
  ADD COLUMN IF NOT EXISTS deployment_id uuid REFERENCES deployments(id) ON DELETE CASCADE;

UPDATE grade_changes gc
SET surface_id = ps.surface_id,
    scope_level = 'surface',
    family_slug = NULL,
    deployment_id = NULL
FROM protocol_surfaces ps
WHERE ps.legacy_slug = gc.protocol_slug
  AND gc.surface_id IS NULL
  AND gc.family_slug IS NULL
  AND gc.scope_level = 'surface';

ALTER TABLE grade_changes
  DROP CONSTRAINT IF EXISTS grade_changes_scope_level_check,
  DROP CONSTRAINT IF EXISTS grade_changes_scope_target_check,
  DROP CONSTRAINT IF EXISTS grade_changes_surface_owner_fk,
  DROP CONSTRAINT IF EXISTS grade_changes_deployment_owner_fk;

ALTER TABLE grade_changes
  ADD CONSTRAINT grade_changes_scope_level_check
    CHECK (scope_level IN ('family', 'surface', 'deployment')),
  ADD CONSTRAINT grade_changes_scope_target_check
    CHECK (
      (scope_level = 'family' AND family_slug = protocol_slug AND surface_id IS NULL AND deployment_id IS NULL)
      OR
      (scope_level = 'surface' AND surface_id IS NOT NULL AND family_slug IS NULL AND deployment_id IS NULL)
      OR
      (scope_level = 'deployment' AND deployment_id IS NOT NULL AND surface_id IS NOT NULL AND family_slug IS NULL)
    ),
  ADD CONSTRAINT grade_changes_surface_owner_fk
    FOREIGN KEY (protocol_slug, surface_id)
    REFERENCES protocol_surfaces(family_slug, surface_id) ON DELETE CASCADE,
  ADD CONSTRAINT grade_changes_deployment_owner_fk
    FOREIGN KEY (protocol_slug, surface_id, deployment_id)
    REFERENCES deployments(protocol_slug, surface_id, id) ON DELETE CASCADE;

DROP INDEX IF EXISTS grade_changes_transition_uniq;

CREATE UNIQUE INDEX IF NOT EXISTS grade_changes_transition_scoped_uniq
  ON grade_changes (
    protocol_slug,
    scope_level,
    COALESCE(family_slug, ''),
    COALESCE(surface_id::text, ''),
    COALESCE(deployment_id::text, ''),
    snapshot_date_before,
    snapshot_date_after
  );

-- primary_surface_id and protocol_surfaces.is_primary form one deferred
-- invariant. Deferral permits a new family and its first surface to be
-- created in the same transaction without ever allowing divergent committed
-- state.
CREATE OR REPLACE FUNCTION enforce_protocol_family_primary_surface()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  family_key text;
  family_keys text[];
  primary_count integer;
  primary_id uuid;
BEGIN
  IF TG_OP = 'INSERT' THEN
    family_keys := ARRAY[NEW.family_slug];
  ELSIF TG_OP = 'DELETE' THEN
    family_keys := ARRAY[OLD.family_slug];
  ELSE
    family_keys := ARRAY[NEW.family_slug, OLD.family_slug];
  END IF;

  FOREACH family_key IN ARRAY family_keys LOOP
    CONTINUE WHEN family_key IS NULL;
    SELECT pf.primary_surface_id
    INTO primary_id
    FROM protocol_families pf
    WHERE pf.family_slug = family_key;

    CONTINUE WHEN NOT FOUND;

    SELECT count(*)
    INTO primary_count
    FROM protocol_surfaces ps
    WHERE ps.family_slug = family_key
      AND ps.is_primary = true;

    IF primary_id IS NULL OR primary_count <> 1 OR NOT EXISTS (
      SELECT 1
      FROM protocol_surfaces ps
      WHERE ps.family_slug = family_key
        AND ps.surface_id = primary_id
        AND ps.is_primary = true
    ) THEN
      RAISE EXCEPTION
        'family % must point to its one primary surface (pointer %, primary rows %)',
        family_key, primary_id, primary_count
        USING ERRCODE = '23514';
    END IF;
  END LOOP;

  RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS protocol_families_primary_surface_guard ON protocol_families;
CREATE CONSTRAINT TRIGGER protocol_families_primary_surface_guard
AFTER INSERT OR UPDATE OR DELETE ON protocol_families
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION enforce_protocol_family_primary_surface();

DROP TRIGGER IF EXISTS protocol_surfaces_primary_surface_guard ON protocol_surfaces;
CREATE CONSTRAINT TRIGGER protocol_surfaces_primary_surface_guard
AFTER INSERT OR UPDATE OR DELETE ON protocol_surfaces
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION enforce_protocol_family_primary_surface();

ALTER TABLE protocol_families ENABLE ROW LEVEL SECURITY;
ALTER TABLE protocol_surfaces ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS public_read ON protocol_families;
DROP POLICY IF EXISTS public_read ON protocol_surfaces;

CREATE POLICY public_read ON protocol_families FOR SELECT USING (true);
CREATE POLICY public_read ON protocol_surfaces FOR SELECT USING (true);

COMMENT ON TABLE protocol_families IS
  'Public grouping entity for multi-version protocol coverage. Mirrors primary surface grade for compatibility.';

COMMENT ON TABLE protocol_surfaces IS
  'Version/surface entity used as the default grading unit under a protocol family.';

COMMIT;
