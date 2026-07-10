DO $$
DECLARE
  family_count integer;
  surface_count integer;
  bad_count integer;
BEGIN
  SELECT count(*) INTO family_count FROM protocol_families;
  SELECT count(*) INTO surface_count FROM protocol_surfaces;
  IF family_count <> (SELECT count(*) FROM protocols) THEN
    RAISE EXCEPTION 'family count % does not match protocol count', family_count;
  END IF;
  IF surface_count <> (SELECT count(*) FROM protocols) THEN
    RAISE EXCEPTION 'surface count % does not match protocol count', surface_count;
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
     OR ps.is_primary IS NOT true;
  IF bad_count <> 0 THEN
    RAISE EXCEPTION 'invalid primary surface mappings: %', bad_count;
  END IF;

  SELECT count(*) INTO bad_count
  FROM (
    SELECT family_slug
    FROM protocol_surfaces
    GROUP BY family_slug
    HAVING count(*) FILTER (WHERE is_primary) <> 1
  ) invalid_primary_counts;
  IF bad_count <> 0 THEN
    RAISE EXCEPTION 'families without exactly one primary surface: %', bad_count;
  END IF;

  SELECT count(*) INTO bad_count
  FROM deployments d
  JOIN protocol_surfaces ps ON ps.surface_id = d.surface_id
  WHERE d.protocol_slug <> ps.family_slug;
  IF bad_count <> 0 THEN
    RAISE EXCEPTION 'deployment/surface family mismatch: %', bad_count;
  END IF;

  SELECT count(*) INTO bad_count
  FROM factor_scores fs
  LEFT JOIN deployments d ON d.id = fs.deployment_id
  LEFT JOIN protocol_surfaces ps ON ps.surface_id = fs.surface_id
  WHERE fs.is_current
    AND (
      (fs.deployment_id IS NULL AND (
        fs.scope_level <> 'surface' OR fs.surface_id IS NULL OR ps.family_slug <> fs.protocol_slug
      ))
      OR
      (fs.deployment_id IS NOT NULL AND (
        fs.scope_level <> 'deployment'
        OR fs.surface_id IS DISTINCT FROM d.surface_id
        OR d.protocol_slug <> fs.protocol_slug
      ))
    );
  IF bad_count <> 0 THEN
    RAISE EXCEPTION 'invalid scoped factor-score backfill: %', bad_count;
  END IF;

  SELECT count(*) INTO bad_count
  FROM grade_history gh
  LEFT JOIN deployments d ON d.id = gh.deployment_id
  LEFT JOIN protocol_surfaces ps ON ps.surface_id = gh.surface_id
  WHERE (gh.deployment_id IS NULL AND (
      gh.scope_level <> 'surface' OR gh.surface_id IS NULL OR ps.family_slug <> gh.protocol_slug
    ))
     OR (gh.deployment_id IS NOT NULL AND (
       gh.scope_level <> 'deployment'
       OR gh.surface_id IS DISTINCT FROM d.surface_id
       OR d.protocol_slug <> gh.protocol_slug
     ));
  IF bad_count <> 0 THEN
    RAISE EXCEPTION 'invalid scoped grade-history backfill: %', bad_count;
  END IF;

  SELECT count(*) INTO bad_count
  FROM protocol_grade_history pgh
  LEFT JOIN protocol_surfaces ps ON ps.surface_id = pgh.surface_id
  WHERE pgh.scope_level <> 'surface'
     OR pgh.surface_id IS NULL
     OR ps.family_slug <> pgh.protocol_slug;
  IF bad_count <> 0 THEN
    RAISE EXCEPTION 'invalid protocol-grade-history backfill: %', bad_count;
  END IF;

  SELECT count(*) INTO bad_count
  FROM factor_score_history fsh
  LEFT JOIN protocol_surfaces ps ON ps.surface_id = fsh.surface_id
  WHERE fsh.scope_level <> 'surface'
     OR fsh.surface_id IS NULL
     OR fsh.deployment_id IS NOT NULL
     OR ps.family_slug <> fsh.protocol_slug;
  IF bad_count <> 0 THEN
    RAISE EXCEPTION 'invalid factor-score-history backfill: %', bad_count;
  END IF;

  SELECT count(*) INTO bad_count
  FROM protocols p
  JOIN protocol_families pf ON pf.family_slug = p.slug
  JOIN protocol_surfaces ps ON ps.surface_id = pf.primary_surface_id
  WHERE p.headline_grade IS DISTINCT FROM pf.headline_grade
     OR p.headline_grade IS DISTINCT FROM ps.headline_grade
     OR p.risk_score IS DISTINCT FROM pf.risk_score
     OR p.risk_score IS DISTINCT FROM ps.risk_score;
  IF bad_count <> 0 THEN
    RAISE EXCEPTION 'single-surface grade mirrors changed: %', bad_count;
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

  SELECT count(*) INTO bad_count
  FROM grade_changes
  WHERE scope_level <> 'surface' OR surface_id IS NULL;
  IF bad_count <> 0 THEN
    RAISE EXCEPTION 'grade_changes were not surface-scoped: %', bad_count;
  END IF;

  BEGIN
    UPDATE factor_scores
    SET surface_id = (
      SELECT surface_id FROM protocol_surfaces WHERE family_slug = 'fixture-peer'
    )
    WHERE id = '00000000-0000-0000-0000-000000000201';
    RAISE EXCEPTION 'cross-family factor score was accepted';
  EXCEPTION
    WHEN foreign_key_violation THEN NULL;
  END;

  BEGIN
    UPDATE factor_scores
    SET surface_id = (
      SELECT surface_id FROM protocol_surfaces WHERE family_slug = 'fixture-peer'
    )
    WHERE id = '00000000-0000-0000-0000-000000000202';
    RAISE EXCEPTION 'deployment score with mismatched surface was accepted';
  EXCEPTION
    WHEN foreign_key_violation THEN NULL;
  END;
END $$;
