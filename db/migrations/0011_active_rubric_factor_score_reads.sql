-- Migration 0011: expose only current scores from the sole active rubric.

DROP POLICY IF EXISTS public_read ON factor_scores;

CREATE POLICY public_read ON factor_scores
  FOR SELECT
  USING (
    is_current = true
    AND rubric_version = (
      SELECT rv.version
      FROM rubric_versions rv
      WHERE rv.is_active = true
      GROUP BY rv.version
      HAVING count(*) = 1
    )
  );

COMMENT ON POLICY public_read ON factor_scores IS
  'Public reads include only current rows from the sole active rubric.';
