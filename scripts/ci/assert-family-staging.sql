\set ON_ERROR_STOP on

-- Read-only assertions for applying 0008_protocol_surfaces.sql to a clone of
-- an existing single-surface database. Synthetic fixture mutation checks live
-- in assert-family-backfill.sql; this file is safe to run against staging.
DO $$
DECLARE
  bad_count integer;
BEGIN
  IF (SELECT count(*) FROM protocol_families) <> (SELECT count(*) FROM protocols) THEN
    RAISE EXCEPTION 'family count does not match protocol count';
  END IF;

  IF (SELECT count(*) FROM protocol_surfaces) <> (SELECT count(*) FROM protocols) THEN
    RAISE EXCEPTION 'surface count does not match protocol count';
  END IF;

  SELECT count(*) INTO bad_count
  FROM protocols p
  FULL JOIN protocol_families pf ON pf.family_slug = p.slug
  WHERE p.slug IS NULL OR pf.family_slug IS NULL;
  IF bad_count <> 0 THEN
    RAISE EXCEPTION 'protocol/family key sets differ: % unmatched rows', bad_count;
  END IF;

  SELECT count(*) INTO bad_count
  FROM protocol_families pf
  LEFT JOIN protocol_surfaces ps
    ON ps.surface_id = pf.primary_surface_id
   AND ps.family_slug = pf.family_slug
  WHERE pf.primary_surface_id IS NULL
     OR ps.surface_id IS NULL
     OR ps.surface_slug <> 'default'
     OR ps.legacy_slug <> pf.family_slug
     OR ps.is_primary IS NOT true;
  IF bad_count <> 0 THEN
    RAISE EXCEPTION 'invalid primary/default surface mappings: %', bad_count;
  END IF;

  SELECT count(*) INTO bad_count
  FROM (
    SELECT family_slug
    FROM protocol_surfaces
    GROUP BY family_slug
    HAVING count(*) <> 1 OR count(*) FILTER (WHERE is_primary) <> 1
  ) invalid_surface_counts;
  IF bad_count <> 0 THEN
    RAISE EXCEPTION 'families without exactly one primary surface: %', bad_count;
  END IF;

  SELECT count(*) INTO bad_count
  FROM deployments d
  LEFT JOIN protocol_surfaces ps ON ps.surface_id = d.surface_id
  WHERE d.surface_id IS NULL OR ps.family_slug IS DISTINCT FROM d.protocol_slug;
  IF bad_count <> 0 THEN
    RAISE EXCEPTION 'deployment/surface family mismatch: %', bad_count;
  END IF;

  SELECT count(*) INTO bad_count
  FROM factor_scores fs
  LEFT JOIN deployments d ON d.id = fs.deployment_id
  LEFT JOIN protocol_surfaces ps ON ps.surface_id = fs.surface_id
  WHERE (fs.deployment_id IS NULL AND (
      fs.scope_level <> 'surface'
      OR fs.surface_id IS NULL
      OR fs.family_slug IS NOT NULL
      OR ps.family_slug IS DISTINCT FROM fs.protocol_slug
    ))
     OR (fs.deployment_id IS NOT NULL AND (
       fs.scope_level <> 'deployment'
       OR fs.family_slug IS NOT NULL
       OR fs.surface_id IS DISTINCT FROM d.surface_id
       OR d.protocol_slug IS DISTINCT FROM fs.protocol_slug
     ));
  IF bad_count <> 0 THEN
    RAISE EXCEPTION 'invalid scoped factor-score backfill: %', bad_count;
  END IF;

  SELECT count(*) INTO bad_count
  FROM grade_history gh
  LEFT JOIN deployments d ON d.id = gh.deployment_id
  LEFT JOIN protocol_surfaces ps ON ps.surface_id = gh.surface_id
  WHERE (gh.deployment_id IS NULL AND (
      gh.scope_level <> 'surface'
      OR gh.surface_id IS NULL
      OR gh.family_slug IS NOT NULL
      OR ps.family_slug IS DISTINCT FROM gh.protocol_slug
    ))
     OR (gh.deployment_id IS NOT NULL AND (
       gh.scope_level <> 'deployment'
       OR gh.family_slug IS NOT NULL
       OR gh.surface_id IS DISTINCT FROM d.surface_id
       OR d.protocol_slug IS DISTINCT FROM gh.protocol_slug
     ));
  IF bad_count <> 0 THEN
    RAISE EXCEPTION 'invalid scoped grade-history backfill: %', bad_count;
  END IF;

  SELECT count(*) INTO bad_count
  FROM protocol_grade_history pgh
  LEFT JOIN protocol_surfaces ps ON ps.surface_id = pgh.surface_id
  WHERE pgh.scope_level <> 'surface'
     OR pgh.surface_id IS NULL
     OR pgh.family_slug IS NOT NULL
     OR ps.family_slug IS DISTINCT FROM pgh.protocol_slug;
  IF bad_count <> 0 THEN
    RAISE EXCEPTION 'invalid protocol-grade-history backfill: %', bad_count;
  END IF;

  SELECT count(*) INTO bad_count
  FROM factor_score_history fsh
  LEFT JOIN protocol_surfaces ps ON ps.surface_id = fsh.surface_id
  WHERE fsh.scope_level <> 'surface'
     OR fsh.surface_id IS NULL
     OR fsh.family_slug IS NOT NULL
     OR fsh.deployment_id IS NOT NULL
     OR ps.family_slug IS DISTINCT FROM fsh.protocol_slug;
  IF bad_count <> 0 THEN
    RAISE EXCEPTION 'invalid factor-score-history backfill: %', bad_count;
  END IF;

  SELECT count(*) INTO bad_count
  FROM grade_changes gc
  LEFT JOIN protocol_surfaces ps ON ps.surface_id = gc.surface_id
  WHERE gc.scope_level <> 'surface'
     OR gc.surface_id IS NULL
     OR gc.family_slug IS NOT NULL
     OR gc.deployment_id IS NOT NULL
     OR ps.family_slug IS DISTINCT FROM gc.protocol_slug;
  IF bad_count <> 0 THEN
    RAISE EXCEPTION 'invalid grade-change backfill: %', bad_count;
  END IF;

  SELECT count(*) INTO bad_count
  FROM protocols p
  JOIN protocol_families pf ON pf.family_slug = p.slug
  JOIN protocol_surfaces ps ON ps.surface_id = pf.primary_surface_id
  WHERE p.display_name IS DISTINCT FROM pf.display_name
     OR p.description IS DISTINCT FROM pf.description
     OR p.homepage_url IS DISTINCT FROM pf.homepage_url
     OR p.protocol_type IS DISTINCT FROM pf.protocol_type
     OR p.primary_chain IS DISTINCT FROM pf.primary_chain
     OR p.headline_grade IS DISTINCT FROM pf.headline_grade
     OR p.total_value_secured_usd IS DISTINCT FROM pf.total_value_secured_usd
     OR p.risk_score IS DISTINCT FROM pf.risk_score
     OR p.category_severities IS DISTINCT FROM pf.category_severities
     OR p.cap_applied IS DISTINCT FROM pf.cap_applied
     OR p.cap_reason IS DISTINCT FROM pf.cap_reason
     OR p.graded_at IS DISTINCT FROM pf.graded_at
     OR p.rubric_version IS DISTINCT FROM pf.rubric_version
     OR p.status IS DISTINCT FROM pf.status
     OR p.has_active_incident IS DISTINCT FROM pf.has_active_incident
     OR p.is_published IS DISTINCT FROM pf.is_published
     OR p.review_token IS DISTINCT FROM pf.review_token
     OR p.display_name IS DISTINCT FROM ps.display_name
     OR p.launched_at IS DISTINCT FROM ps.launched_at
     OR p.primary_chain IS DISTINCT FROM ps.primary_chain
     OR p.total_value_secured_usd IS DISTINCT FROM ps.tvs_usd
     OR p.headline_grade IS DISTINCT FROM ps.headline_grade
     OR p.risk_score IS DISTINCT FROM ps.risk_score
     OR p.category_severities IS DISTINCT FROM ps.category_severities
     OR p.cap_applied IS DISTINCT FROM ps.cap_applied
     OR p.cap_reason IS DISTINCT FROM ps.cap_reason
     OR p.graded_at IS DISTINCT FROM ps.graded_at
     OR p.rubric_version IS DISTINCT FROM ps.rubric_version;
  IF bad_count <> 0 THEN
    RAISE EXCEPTION 'single-surface protocol/family/surface mirrors changed: %', bad_count;
  END IF;

  IF to_regclass('public.factor_scores_current_scoped_unique') IS NULL
     OR to_regclass('public.protocol_grade_hist_daily_scoped_uniq') IS NULL
     OR to_regclass('public.factor_score_hist_daily_scoped_uniq') IS NULL
     OR to_regclass('public.grade_changes_transition_scoped_uniq') IS NULL THEN
    RAISE EXCEPTION 'required scoped uniqueness index missing';
  END IF;

  SELECT count(*) INTO bad_count
  FROM (
    VALUES
      ('protocol_families_family_slug_fkey'),
      ('protocol_families_primary_surface_fk'),
      ('deployments_surface_fk'),
      ('factor_scores_scope_target_check'),
      ('factor_scores_surface_owner_fk'),
      ('factor_scores_deployment_owner_fk'),
      ('grade_history_scope_target_check'),
      ('grade_history_surface_owner_fk'),
      ('grade_history_deployment_owner_fk'),
      ('protocol_grade_history_scope_target_check'),
      ('protocol_grade_history_surface_owner_fk'),
      ('factor_score_history_scope_target_check'),
      ('factor_score_history_surface_owner_fk'),
      ('factor_score_history_deployment_owner_fk'),
      ('grade_changes_scope_target_check'),
      ('grade_changes_surface_owner_fk'),
      ('grade_changes_deployment_owner_fk')
  ) expected(name)
  LEFT JOIN pg_constraint c ON c.conname = expected.name
  WHERE c.oid IS NULL OR c.convalidated IS NOT true;
  IF bad_count <> 0 THEN
    RAISE EXCEPTION 'required validated scope constraints missing: %', bad_count;
  END IF;

  SELECT count(*) INTO bad_count
  FROM (
    VALUES
      ('protocol_families_primary_surface_guard'),
      ('protocol_surfaces_primary_surface_guard')
  ) expected(name)
  LEFT JOIN pg_trigger t ON t.tgname = expected.name AND NOT t.tgisinternal
  WHERE t.oid IS NULL;
  IF bad_count <> 0 THEN
    RAISE EXCEPTION 'primary-surface constraint triggers missing: %', bad_count;
  END IF;

  SELECT count(*) INTO bad_count
  FROM pg_class
  WHERE relname IN ('protocol_families', 'protocol_surfaces')
    AND relrowsecurity IS true;
  IF bad_count <> 2 THEN
    RAISE EXCEPTION 'family/surface RLS is not enabled on both tables';
  END IF;

  SELECT count(*) INTO bad_count
  FROM pg_policies
  WHERE schemaname = 'public'
    AND tablename IN ('protocol_families', 'protocol_surfaces')
    AND policyname = 'public_read'
    AND cmd = 'SELECT';
  IF bad_count <> 2 THEN
    RAISE EXCEPTION 'family/surface public read policies missing';
  END IF;
END $$;

SELECT
  (SELECT count(*) FROM protocols) AS protocols,
  (SELECT count(*) FROM protocol_families) AS families,
  (SELECT count(*) FROM protocol_surfaces) AS surfaces,
  (SELECT count(*) FROM deployments) AS deployments,
  (SELECT count(*) FROM factor_scores) AS factor_scores,
  (SELECT count(*) FROM grade_history) AS grade_history,
  (SELECT count(*) FROM protocol_grade_history) AS protocol_grade_history,
  (SELECT count(*) FROM factor_score_history) AS factor_score_history,
  (SELECT count(*) FROM grade_changes) AS grade_changes;
