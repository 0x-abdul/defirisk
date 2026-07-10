"""Shared protocol-assessment validation constants.

These constants are used by both the fragment merge step and the database
importer. Keeping them in one place prevents the process from accepting a value
in one step and rejecting it in the next.
"""

VALID_SCORES = {"green", "yellow", "red", "gray", "not_assessed", "not_applicable"}
VALID_SOURCE_TYPES = {
    "url",
    "github",
    "etherscan",
    "transaction",
    "audit_report",
    "governance_post",
    "docs",
    "partner_feed",
    "curator_note",
    "commit_sha",
}
VALID_COLLECTION_MODES = {"programmatic", "manual", "hybrid"}
VALID_GAP_REASONS = {
    "protocol_opacity",
    "pipeline_unimplemented",
    "external_api_blocked",
    "requires_curator_input",
    "not_applicable",
}
VALID_PROTOCOL_STATUSES = {
    "live",
    "under_assessment_review",
    "under_regulatory_review",
    "deprecated",
}
VALID_SURFACE_STATUSES = {"active", "legacy", "deprecated", "experimental"}
VALID_FACTOR_SCORE_SCOPES = {"family", "surface", "deployment"}

# The 20 critical factors per the current v1.7.0 rubric (PD-001 resolution
# updated by T-14 2026-04-22; unchanged by PD-032 2026-04-23 since none were in
# the dissolved Cat 12). Each must be present in some fragment with a graded
# score, or with score='not_assessed' and an explanatory notes field.
CRITICAL_FACTORS = {
    # Governance (8)
    "RD-F-027",
    "RD-F-028",
    "RD-F-041",
    "RD-F-042",
    "RD-F-043",
    "RD-F-046",
    "RD-F-036",
    "RD-F-039",
    # Code & audits (2)
    "RD-F-022",
    "RD-F-001",
    # Post-deploy hygiene (2)
    "RD-F-143",
    "RD-F-139",
    # Economic (1)
    "RD-F-070",
    # Oracle (2)
    "RD-F-053",
    "RD-F-180",
    # Dev identity (3)
    "RD-F-124",
    "RD-F-125",
    "RD-F-123",
    # Cross-chain (2, only required if protocol has bridge surface)
    "RD-F-151",
    "RD-F-154",
}
CROSS_CHAIN_CRITICAL = {"RD-F-151", "RD-F-154"}

# Fragment file -> expected agent + categories. Drives missing-fragment detection
# and per-fragment scope validation.
FRAGMENT_CONTRACTS = [
    ("01-code-security.factors.json", "code-security-analyst", {1, 8, 12}),
    ("02-governance-admin.factors.json", "governance-admin-analyst", {2, 9}),
    ("03-oracle-deps.factors.json", "oracle-dependency-analyst", {3, 10}),
    ("04-economic.factors.json", "economic-market-analyst", {4}),
    ("05-ops-history.factors.json", "ops-history-analyst", {5, 13}),
    ("06-realtime-intel.factors.json", "realtime-intel-analyst", {6, 11}),
    ("07-dev-identity.factors.json", "dev-identity-analyst", {7}),
]
