-- Migration 0014: least-privileged topology writes for the nightly ingest.
--
-- The runtime role retains SELECT-only table access. These functions expose
-- only the two synchronized writes required by refresh-continuous.py and
-- compose.py. Fully qualified objects and a fixed search_path keep the
-- SECURITY DEFINER boundary independent of caller-controlled schemas.

DO $role$
DECLARE
  v_role_oid oid;
BEGIN
  SELECT oid INTO v_role_oid
  FROM pg_catalog.pg_roles
  WHERE rolname = 'rdapp_nightly_owner';

  IF NOT FOUND THEN
    EXECUTE 'CREATE ROLE rdapp_nightly_owner NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD NULL';
  ELSE
    IF EXISTS (
      SELECT 1
      FROM pg_catalog.pg_roles
      WHERE oid = v_role_oid
        AND (
          rolsuper OR rolcreatedb OR rolcreaterole OR rolcanlogin OR
          rolreplication OR rolinherit OR rolbypassrls
        )
    ) THEN
      RAISE EXCEPTION 'refusing to adopt an unsafe pre-existing rdapp_nightly_owner role'
        USING ERRCODE = '42501';
    END IF;
    IF (
      SELECT count(*)
      FROM pg_catalog.pg_proc
      WHERE oid IN (
        pg_catalog.to_regprocedure('public.refresh_sync_family_tvl(text,numeric)'),
        pg_catalog.to_regprocedure('public.refresh_update_surface_grade(text,uuid,text,text,timestamp with time zone,numeric,jsonb,text,text)')
      )
        AND proowner = v_role_oid
    ) <> 2 THEN
      RAISE EXCEPTION 'refusing to adopt a pre-existing rdapp_nightly_owner role'
        USING ERRCODE = '42501';
    END IF;
    IF EXISTS (
      SELECT 1
      FROM pg_catalog.pg_auth_members
      WHERE roleid = v_role_oid OR member = v_role_oid
    ) THEN
      RAISE EXCEPTION 'rdapp_nightly_owner must not have role memberships'
        USING ERRCODE = '42501';
    END IF;
    IF EXISTS (
      SELECT 1
      FROM pg_catalog.pg_shdepend AS d
      WHERE d.refclassid = 'pg_catalog.pg_authid'::regclass
        AND d.refobjid = v_role_oid
        AND d.deptype = 'o'
        AND NOT (
          d.dbid = (
            SELECT oid FROM pg_catalog.pg_database
            WHERE datname = pg_catalog.current_database()
          )
          AND d.classid = 'pg_catalog.pg_proc'::regclass
          AND (
            d.objid = pg_catalog.to_regprocedure(
              'public.refresh_sync_family_tvl(text,numeric)'
            )
            OR d.objid = pg_catalog.to_regprocedure(
              'public.refresh_update_surface_grade(text,uuid,text,text,timestamp with time zone,numeric,jsonb,text,text)'
            )
          )
        )
    ) THEN
      RAISE EXCEPTION 'rdapp_nightly_owner owns unexpected database objects'
        USING ERRCODE = '42501';
    END IF;
    IF EXISTS (
      SELECT 1
      FROM pg_catalog.pg_stat_activity
      WHERE usesysid = v_role_oid
        AND pid <> pg_catalog.pg_backend_pid()
    ) THEN
      RAISE EXCEPTION 'rdapp_nightly_owner has active sessions'
        USING ERRCODE = '55006';
    END IF;
    EXECUTE 'ALTER ROLE rdapp_nightly_owner NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD NULL';
  END IF;
END
$role$;

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM rdapp_nightly_owner;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM rdapp_nightly_owner;
REVOKE ALL ON SCHEMA public FROM rdapp_nightly_owner;

DO $column_acl$
DECLARE
  v_grant record;
BEGIN
  FOR v_grant IN
    SELECT n.nspname, c.relname, a.attname, acl.privilege_type
    FROM pg_catalog.pg_attribute AS a
    JOIN pg_catalog.pg_class AS c ON c.oid = a.attrelid
    JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
    CROSS JOIN LATERAL pg_catalog.aclexplode(a.attacl) AS acl
    JOIN pg_catalog.pg_roles AS r ON r.oid = acl.grantee
    WHERE n.nspname = 'public'
      AND r.rolname = 'rdapp_nightly_owner'
  LOOP
    EXECUTE pg_catalog.format(
      'REVOKE %s (%I) ON TABLE %I.%I FROM rdapp_nightly_owner',
      v_grant.privilege_type,
      v_grant.attname,
      v_grant.nspname,
      v_grant.relname
    );
  END LOOP;
END
$column_acl$;

GRANT USAGE ON SCHEMA public TO rdapp_nightly_owner;
GRANT SELECT (family_slug, primary_surface_id)
  ON TABLE public.protocol_families TO rdapp_nightly_owner;
GRANT UPDATE (
  total_value_secured_usd, headline_grade, rubric_version, graded_at,
  risk_score, category_severities, cap_applied, cap_reason, updated_at
) ON TABLE public.protocol_families TO rdapp_nightly_owner;
GRANT SELECT (surface_id, family_slug, is_primary)
  ON TABLE public.protocol_surfaces TO rdapp_nightly_owner;
GRANT UPDATE (
  tvs_usd, headline_grade, rubric_version, graded_at, risk_score,
  category_severities, cap_applied, cap_reason, updated_at
) ON TABLE public.protocol_surfaces TO rdapp_nightly_owner;

DROP POLICY IF EXISTS nightly_owner_update ON public.protocol_families;
DROP POLICY IF EXISTS nightly_owner_update ON public.protocol_surfaces;
CREATE POLICY nightly_owner_update ON public.protocol_families
  FOR UPDATE TO rdapp_nightly_owner USING (true) WITH CHECK (true);
CREATE POLICY nightly_owner_update ON public.protocol_surfaces
  FOR UPDATE TO rdapp_nightly_owner USING (true) WITH CHECK (true);

CREATE OR REPLACE FUNCTION public.refresh_sync_family_tvl(
  p_family_slug text,
  p_tvl_usd numeric
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
  v_primary_surface_id uuid;
  v_rows integer;
BEGIN
  IF p_family_slug IS NULL OR btrim(p_family_slug) = '' THEN
    RAISE EXCEPTION 'family slug is required' USING ERRCODE = '22023';
  END IF;
  IF p_tvl_usd IS NULL OR p_tvl_usd < 0 OR p_tvl_usd::text IN ('NaN', 'Infinity') THEN
    RAISE EXCEPTION 'TVL must be a finite non-negative number' USING ERRCODE = '22023';
  END IF;

  SELECT pf.primary_surface_id
  INTO v_primary_surface_id
  FROM public.protocol_families AS pf
  WHERE pf.family_slug = p_family_slug
  FOR UPDATE;

  IF NOT FOUND OR v_primary_surface_id IS NULL THEN
    RAISE EXCEPTION 'family % has no primary surface', p_family_slug
      USING ERRCODE = '23514';
  END IF;

  PERFORM 1
  FROM public.protocol_surfaces AS ps
  WHERE ps.surface_id = v_primary_surface_id
    AND ps.family_slug = p_family_slug
    AND ps.is_primary = true
  FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'family % primary surface linkage is invalid', p_family_slug
      USING ERRCODE = '23514';
  END IF;

  UPDATE public.protocol_families
  SET total_value_secured_usd = p_tvl_usd,
      updated_at = pg_catalog.now()
  WHERE family_slug = p_family_slug;
  GET DIAGNOSTICS v_rows = ROW_COUNT;
  IF v_rows <> 1 THEN
    RAISE EXCEPTION 'expected one family update for %, got %', p_family_slug, v_rows
      USING ERRCODE = 'P0001';
  END IF;

  UPDATE public.protocol_surfaces
  SET tvs_usd = p_tvl_usd,
      updated_at = pg_catalog.now()
  WHERE surface_id = v_primary_surface_id
    AND family_slug = p_family_slug
    AND is_primary = true;
  GET DIAGNOSTICS v_rows = ROW_COUNT;
  IF v_rows <> 1 THEN
    RAISE EXCEPTION 'expected one primary surface update for %, got %', p_family_slug, v_rows
      USING ERRCODE = 'P0001';
  END IF;
END
$function$;

CREATE OR REPLACE FUNCTION public.refresh_update_surface_grade(
  p_family_slug text,
  p_surface_id uuid,
  p_letter text,
  p_rubric_version text,
  p_graded_at timestamptz,
  p_risk_score numeric,
  p_category_severities jsonb,
  p_cap_applied text,
  p_cap_reason text
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
  v_is_primary boolean;
  v_primary_surface_id uuid;
  v_rows integer;
BEGIN
  IF p_family_slug IS NULL OR btrim(p_family_slug) = '' OR p_surface_id IS NULL THEN
    RAISE EXCEPTION 'family slug and surface id are required' USING ERRCODE = '22023';
  END IF;
  IF p_letter IS NULL OR p_letter NOT IN ('A', 'B', 'C', 'D', 'F') THEN
    RAISE EXCEPTION 'grade letter is invalid' USING ERRCODE = '22023';
  END IF;
  IF p_rubric_version IS NULL OR btrim(p_rubric_version) = '' OR p_graded_at IS NULL THEN
    RAISE EXCEPTION 'rubric version and graded timestamp are required' USING ERRCODE = '22023';
  END IF;
  IF p_risk_score IS NOT NULL
     AND (p_risk_score < 0 OR p_risk_score > 100 OR p_risk_score::text = 'NaN') THEN
    RAISE EXCEPTION 'risk score must be between 0 and 100' USING ERRCODE = '22023';
  END IF;
  IF p_category_severities IS NOT NULL
     AND pg_catalog.jsonb_typeof(p_category_severities) <> 'object' THEN
    RAISE EXCEPTION 'category severities must be a JSON object' USING ERRCODE = '22023';
  END IF;

  SELECT pf.primary_surface_id
  INTO v_primary_surface_id
  FROM public.protocol_families AS pf
  WHERE pf.family_slug = p_family_slug
  FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'family % does not exist', p_family_slug
      USING ERRCODE = '23503';
  END IF;

  SELECT ps.is_primary
  INTO v_is_primary
  FROM public.protocol_surfaces AS ps
  WHERE ps.surface_id = p_surface_id
    AND ps.family_slug = p_family_slug
  FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'surface % is not linked to family %', p_surface_id, p_family_slug
      USING ERRCODE = '23503';
  END IF;
  IF v_is_primary IS DISTINCT FROM (v_primary_surface_id = p_surface_id) THEN
    RAISE EXCEPTION 'family % primary surface linkage is invalid', p_family_slug
      USING ERRCODE = '23514';
  END IF;

  UPDATE public.protocol_surfaces
  SET headline_grade = p_letter,
      rubric_version = p_rubric_version,
      graded_at = p_graded_at,
      risk_score = p_risk_score,
      category_severities = p_category_severities,
      cap_applied = p_cap_applied,
      cap_reason = p_cap_reason,
      updated_at = pg_catalog.now()
  WHERE surface_id = p_surface_id
    AND family_slug = p_family_slug;
  GET DIAGNOSTICS v_rows = ROW_COUNT;
  IF v_rows <> 1 THEN
    RAISE EXCEPTION 'expected one surface update for %, got %', p_surface_id, v_rows
      USING ERRCODE = 'P0001';
  END IF;

  IF v_is_primary THEN
    UPDATE public.protocol_families
    SET headline_grade = p_letter,
        rubric_version = p_rubric_version,
        graded_at = p_graded_at,
        risk_score = p_risk_score,
        category_severities = p_category_severities,
        cap_applied = p_cap_applied,
        cap_reason = p_cap_reason,
        updated_at = pg_catalog.now()
    WHERE family_slug = p_family_slug
      AND primary_surface_id = p_surface_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    IF v_rows <> 1 THEN
      RAISE EXCEPTION 'expected one primary family update for %, got %', p_family_slug, v_rows
        USING ERRCODE = 'P0001';
    END IF;
  END IF;
END
$function$;

ALTER FUNCTION public.refresh_sync_family_tvl(text, numeric)
  OWNER TO rdapp_nightly_owner;
ALTER FUNCTION public.refresh_update_surface_grade(
  text, uuid, text, text, timestamptz, numeric, jsonb, text, text
) OWNER TO rdapp_nightly_owner;

REVOKE ALL ON FUNCTION public.refresh_sync_family_tvl(text, numeric) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.refresh_update_surface_grade(
  text, uuid, text, text, timestamptz, numeric, jsonb, text, text
) FROM PUBLIC;

DO $acl$
DECLARE
  v_function text;
  v_grantee text;
BEGIN
  FOR v_function, v_grantee IN
    SELECT pg_catalog.format(
             '%I.%I(%s)',
             n.nspname,
             p.proname,
             pg_catalog.pg_get_function_identity_arguments(p.oid)
           ),
           pg_catalog.pg_get_userbyid(acl.grantee)
    FROM pg_catalog.pg_proc AS p
    JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
    CROSS JOIN LATERAL pg_catalog.aclexplode(
      COALESCE(p.proacl, pg_catalog.acldefault('f', p.proowner))
    ) AS acl
    WHERE p.oid IN (
      'public.refresh_sync_family_tvl(text,numeric)'::regprocedure,
      'public.refresh_update_surface_grade(text,uuid,text,text,timestamp with time zone,numeric,jsonb,text,text)'::regprocedure
    )
      AND acl.privilege_type = 'EXECUTE'
      AND acl.grantee <> 0
      AND acl.grantee <> p.proowner
  LOOP
    EXECUTE pg_catalog.format('REVOKE ALL ON FUNCTION %s FROM %I', v_function, v_grantee);
  END LOOP;
END
$acl$;

DO $migration$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'rdapp') THEN
    REVOKE GRANT OPTION FOR EXECUTE ON FUNCTION
      public.refresh_sync_family_tvl(text, numeric) FROM rdapp;
    REVOKE GRANT OPTION FOR EXECUTE ON FUNCTION
      public.refresh_update_surface_grade(
        text, uuid, text, text, timestamptz, numeric, jsonb, text, text
      ) FROM rdapp;
    GRANT EXECUTE ON FUNCTION public.refresh_sync_family_tvl(text, numeric) TO rdapp;
    GRANT EXECUTE ON FUNCTION public.refresh_update_surface_grade(
      text, uuid, text, text, timestamptz, numeric, jsonb, text, text
    ) TO rdapp;
  END IF;
END
$migration$;

COMMENT ON FUNCTION public.refresh_sync_family_tvl(text, numeric) IS
  'Synchronize family and primary-surface TVL without granting runtime table updates.';
COMMENT ON FUNCTION public.refresh_update_surface_grade(
  text, uuid, text, text, timestamptz, numeric, jsonb, text, text
) IS
  'Update one surface grade and mirror it to the family only for the primary surface.';
