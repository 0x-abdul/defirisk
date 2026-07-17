-- Migration 0014: least-privileged topology writes for the nightly ingest.
--
-- The runtime role retains SELECT-only table access. These functions expose
-- only the two synchronized writes required by refresh-continuous.py and
-- compose.py. Fully qualified objects and a fixed search_path keep the
-- SECURITY DEFINER boundary independent of caller-controlled schemas.

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
  IF p_tvl_usd IS NULL OR p_tvl_usd < 0 OR p_tvl_usd::text = 'NaN' THEN
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
    SELECT pf.primary_surface_id
    INTO v_primary_surface_id
    FROM public.protocol_families AS pf
    WHERE pf.family_slug = p_family_slug
    FOR UPDATE;
    IF NOT FOUND OR v_primary_surface_id IS DISTINCT FROM p_surface_id THEN
      RAISE EXCEPTION 'family % primary surface linkage is invalid', p_family_slug
        USING ERRCODE = '23514';
    END IF;

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

REVOKE ALL ON FUNCTION public.refresh_sync_family_tvl(text, numeric) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.refresh_update_surface_grade(
  text, uuid, text, text, timestamptz, numeric, jsonb, text, text
) FROM PUBLIC;

DO $migration$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'rdapp') THEN
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
