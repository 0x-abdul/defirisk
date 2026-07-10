-- Synthetic pre-family fixture used only by CI migration replay.
INSERT INTO rubric_versions (version, frozen_at, changelog_url, is_active)
VALUES ('v1.7.0', now(), 'https://example.invalid/rubric', true);

INSERT INTO categories (id, slug, name, is_core_five, factor_count, description)
VALUES (1, 'fixture', 'Fixture category', true, 2, 'Synthetic migration fixture.');

INSERT INTO factors (
  id, category_id, name, description, scoring_methodology, is_critical,
  curation_archetype, introduced_in_rubric
)
VALUES
  ('RD-F-001', 1, 'Fixture factor one', 'Synthetic.', 'Synthetic.', true, 'manual', 'v1.7.0'),
  ('RD-F-002', 1, 'Fixture factor two', 'Synthetic.', 'Synthetic.', false, 'manual', 'v1.7.0');

INSERT INTO protocols (
  slug, display_name, protocol_type, primary_chain, headline_grade,
  total_value_secured_usd, graded_at, rubric_version, risk_score,
  category_severities, cap_applied, cap_reason, is_published
)
VALUES
  (
    'fixture-family', 'Fixture Family', 'lending', 'ethereum', 'B',
    1000000, now(), 'v1.7.0', 18.50, '{"1": 18.5}', 'none', NULL, true
  ),
  (
    'fixture-peer', 'Fixture Peer', 'lending', 'base', 'C',
    500000, now(), 'v1.7.0', 28.00, '{"1": 28}', 'none', NULL, true
  );

INSERT INTO deployments (
  id, protocol_slug, chain, anchor_address, display_name, tvs_usd, tvs_share
)
VALUES
  (
    '00000000-0000-0000-0000-000000000101', 'fixture-family', 'ethereum',
    '0x0000000000000000000000000000000000000001', 'Fixture Ethereum', 1000000, 1
  ),
  (
    '00000000-0000-0000-0000-000000000102', 'fixture-peer', 'base',
    '0x0000000000000000000000000000000000000002', 'Fixture Base', 500000, 1
  );

INSERT INTO factor_scores (
  id, protocol_slug, deployment_id, factor_id, rubric_version, score,
  evidence_summary, collection_mode, collected_at, collected_by,
  data_as_of, is_current
)
VALUES
  (
    '00000000-0000-0000-0000-000000000201', 'fixture-family', NULL,
    'RD-F-001', 'v1.7.0', 'green', 'Synthetic surface score.', 'manual',
    now(), 'migration-fixture', now(), true
  ),
  (
    '00000000-0000-0000-0000-000000000202', 'fixture-family',
    '00000000-0000-0000-0000-000000000101', 'RD-F-002', 'v1.7.0',
    'yellow', 'Synthetic deployment score.', 'manual', now(),
    'migration-fixture', now(), true
  );

INSERT INTO grade_history (
  id, protocol_slug, deployment_id, rubric_version, letter,
  critical_flag_count, red_category_count, yellow_category_count,
  gray_on_core_five, graded_at, triggered_by, risk_score,
  category_severities, cap_applied
)
VALUES
  (
    '00000000-0000-0000-0000-000000000301', 'fixture-family', NULL,
    'v1.7.0', 'B', 0, 0, 1, false, now(), 'migration-fixture',
    18.50, '{"1": 18.5}', 'none'
  ),
  (
    '00000000-0000-0000-0000-000000000302', 'fixture-family',
    '00000000-0000-0000-0000-000000000101', 'v1.7.0', 'C',
    0, 0, 1, false, now(), 'migration-fixture', 25.00, '{"1": 25}', 'none'
  );

INSERT INTO protocol_grade_history (
  id, protocol_slug, snapshot_at, snapshot_date, rubric_version,
  grade_letter, critical_count, red_count, yellow_count, gray_core_five
)
VALUES (
  '00000000-0000-0000-0000-000000000401', 'fixture-family', now(),
  CURRENT_DATE, 'v1.7.0', 'B', 0, 0, 1, false
);

INSERT INTO factor_score_history (
  id, protocol_slug, factor_id, snapshot_at, snapshot_date, score_color,
  rubric_version
)
VALUES (
  '00000000-0000-0000-0000-000000000501', 'fixture-family', 'RD-F-001',
  now(), CURRENT_DATE, 'green', 'v1.7.0'
);

INSERT INTO grade_changes (
  id, protocol_slug, from_grade, to_grade, rubric_version,
  snapshot_date_before, snapshot_date_after, is_upgrade
)
VALUES (
  '00000000-0000-0000-0000-000000000601', 'fixture-family', 'C', 'B',
  'v1.7.0', CURRENT_DATE - 1, CURRENT_DATE, true
);
