-- Risk Dashboard v1 — Baseline Migration
-- Source: eng-schema-v0.sql (2026-04-24)
-- Note: This file was hand-written to match the Drizzle schema in db/schema.ts.
--       Run `npm run db:generate` to regenerate if schema drift is suspected.
--> statement-breakpoint

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
--> statement-breakpoint

-- ── Enums ─────────────────────────────────────────────────────────────────────

CREATE TYPE "source_type" AS ENUM (
  'url', 'github', 'etherscan', 'transaction', 'audit_report',
  'governance_post', 'docs', 'partner_feed', 'curator_note', 'commit_sha'
);
--> statement-breakpoint
CREATE TYPE "factor_score_value" AS ENUM (
  'green', 'yellow', 'red', 'gray', 'not_assessed', 'not_applicable'
);
--> statement-breakpoint
CREATE TYPE "collection_mode" AS ENUM ('programmatic', 'manual', 'hybrid');
--> statement-breakpoint
CREATE TYPE "protocol_status" AS ENUM (
  'live', 'under_assessment_review', 'under_regulatory_review', 'deprecated'
);
--> statement-breakpoint
CREATE TYPE "incident_severity" AS ENUM ('advisory', 'critical');
--> statement-breakpoint
CREATE TYPE "incident_status" AS ENUM ('open', 'closed');
--> statement-breakpoint

-- ── Rubric Versioning ─────────────────────────────────────────────────────────

CREATE TABLE "rubric_versions" (
  "version"       text PRIMARY KEY NOT NULL,
  "frozen_at"     timestamp with time zone NOT NULL,
  "changelog_url" text NOT NULL,
  "is_active"     boolean NOT NULL DEFAULT false,
  "notes"         text
);
--> statement-breakpoint
CREATE UNIQUE INDEX "rubric_versions_one_active"
  ON "rubric_versions" ("is_active")
  WHERE is_active = true;
--> statement-breakpoint

-- ── Taxonomy ──────────────────────────────────────────────────────────────────

CREATE TABLE "categories" (
  "id"           smallint PRIMARY KEY NOT NULL,
  "slug"         text UNIQUE NOT NULL,
  "name"         text NOT NULL,
  "is_core_five" boolean NOT NULL,
  "factor_count" smallint NOT NULL,
  "description"  text NOT NULL
);
--> statement-breakpoint

CREATE TABLE "factors" (
  "id"                   text PRIMARY KEY NOT NULL,
  "category_id"          smallint NOT NULL REFERENCES "categories"("id"),
  "name"                 text NOT NULL,
  "description"          text NOT NULL,
  "scoring_methodology"  text NOT NULL,
  "is_critical"          boolean NOT NULL DEFAULT false,
  "curation_archetype"   text NOT NULL,
  "measurement"          text,
  "data_source"          text,
  "method"               text,
  "output_format"        text,
  "cadence"              text,
  "evidence_artifact"    text,
  "confidence_signal"    text,
  "introduced_in_rubric" text NOT NULL REFERENCES "rubric_versions"("version"),
  "deprecated_in_rubric" text REFERENCES "rubric_versions"("version"),
  "created_at"           timestamp with time zone NOT NULL DEFAULT now(),
  "updated_at"           timestamp with time zone NOT NULL DEFAULT now()
);
--> statement-breakpoint
CREATE INDEX "factors_category_idx" ON "factors" ("category_id");
--> statement-breakpoint
CREATE INDEX "factors_critical_idx" ON "factors" ("is_critical") WHERE is_critical = true;
--> statement-breakpoint
CREATE INDEX "factors_introduced_rubric_idx" ON "factors" ("introduced_in_rubric");
--> statement-breakpoint
CREATE INDEX "factors_deprecated_rubric_idx" ON "factors" ("deprecated_in_rubric") WHERE deprecated_in_rubric IS NOT NULL;
--> statement-breakpoint

-- ── Protocols + Deployments ──────────────────────────────────────────────────

CREATE TABLE "protocols" (
  "slug"                    text PRIMARY KEY NOT NULL,
  "display_name"            text NOT NULL,
  "description"             text,
  "homepage_url"            text,
  "github_org"              text,
  "defillama_slug"          text,
  "protocol_type"           text NOT NULL,
  "primary_chain"           text NOT NULL,
  "launched_at"             date,
  "headline_grade"          char(1),
  "headline_badge"          text,
  "total_value_secured_usd" numeric(20, 2),
  "graded_at"               timestamp with time zone,
  "rubric_version"          text REFERENCES "rubric_versions"("version"),
  "status"                  "protocol_status" NOT NULL DEFAULT 'live',
  "has_active_incident"     boolean NOT NULL DEFAULT false,
  "created_at"              timestamp with time zone NOT NULL DEFAULT now(),
  "updated_at"              timestamp with time zone NOT NULL DEFAULT now()
);
--> statement-breakpoint
CREATE INDEX "protocols_grade_idx"  ON "protocols" ("headline_grade") WHERE headline_grade IS NOT NULL;
--> statement-breakpoint
CREATE INDEX "protocols_status_idx" ON "protocols" ("status");
--> statement-breakpoint
CREATE INDEX "protocols_type_idx"   ON "protocols" ("protocol_type");
--> statement-breakpoint
CREATE INDEX "protocols_rubric_version_idx" ON "protocols" ("rubric_version") WHERE rubric_version IS NOT NULL;
--> statement-breakpoint

CREATE TABLE "deployments" (
  "id"             uuid PRIMARY KEY NOT NULL DEFAULT gen_random_uuid(),
  "protocol_slug"  text NOT NULL REFERENCES "protocols"("slug") ON DELETE CASCADE,
  "chain"          text NOT NULL,
  "anchor_address" text,
  "display_name"   text,
  "tvs_usd"        numeric(20, 2),
  "tvs_share"      numeric(5, 4),
  "letter"         char(1),
  "badge"          text,
  "category_grid"  jsonb NOT NULL DEFAULT '{}'::jsonb,
  "deployed_at"    date,
  "created_at"     timestamp with time zone NOT NULL DEFAULT now(),
  "updated_at"     timestamp with time zone NOT NULL DEFAULT now()
);
--> statement-breakpoint
CREATE UNIQUE INDEX "deployments_protocol_chain_unique" ON "deployments" ("protocol_slug", "chain");
--> statement-breakpoint
CREATE INDEX "deployments_protocol_idx" ON "deployments" ("protocol_slug");
--> statement-breakpoint
CREATE INDEX "deployments_chain_idx"    ON "deployments" ("chain");
--> statement-breakpoint

-- ── Sources ───────────────────────────────────────────────────────────────────

CREATE TABLE "sources" (
  "id"           uuid PRIMARY KEY NOT NULL DEFAULT gen_random_uuid(),
  "source_type"  "source_type" NOT NULL,
  "url"          text,
  "reference"    text NOT NULL,
  "title"        text,
  "retrieved_at" timestamp with time zone NOT NULL,
  "retrieved_by" text NOT NULL,
  "is_archived"  boolean NOT NULL DEFAULT false,
  "archive_url"  text,
  "notes"        text,
  "created_at"   timestamp with time zone NOT NULL DEFAULT now()
);
--> statement-breakpoint
CREATE UNIQUE INDEX "sources_dedup_idx"
  ON "sources" ("source_type", COALESCE("url", ''), "reference");
--> statement-breakpoint
CREATE INDEX "sources_url_idx"          ON "sources" ("url") WHERE url IS NOT NULL;
--> statement-breakpoint
CREATE INDEX "sources_type_idx"         ON "sources" ("source_type");
--> statement-breakpoint
CREATE INDEX "sources_retrieved_at_idx" ON "sources" ("retrieved_at" DESC);
--> statement-breakpoint

-- ── Factor Scores ─────────────────────────────────────────────────────────────

CREATE TABLE "factor_scores" (
  "id"               uuid PRIMARY KEY NOT NULL DEFAULT gen_random_uuid(),
  "protocol_slug"    text NOT NULL REFERENCES "protocols"("slug") ON DELETE CASCADE,
  "deployment_id"    uuid REFERENCES "deployments"("id") ON DELETE CASCADE,
  "factor_id"        text NOT NULL REFERENCES "factors"("id"),
  "rubric_version"   text NOT NULL REFERENCES "rubric_versions"("version"),
  "score"            "factor_score_value" NOT NULL,
  "evidence_summary" text NOT NULL,
  "evidence_detail"  text,
  "collection_mode"  "collection_mode" NOT NULL,
  "collected_at"     timestamp with time zone NOT NULL,
  "collected_by"     text NOT NULL,
  "data_as_of"       timestamp with time zone NOT NULL,
  "is_current"       boolean NOT NULL DEFAULT true,
  "superseded_by"    uuid REFERENCES "factor_scores"("id"),
  "notes"            text
);
--> statement-breakpoint
CREATE UNIQUE INDEX "factor_scores_current_unique"
  ON "factor_scores" ("protocol_slug", COALESCE("deployment_id"::text, ''), "factor_id", "rubric_version")
  WHERE is_current = true;
--> statement-breakpoint
CREATE INDEX "factor_scores_protocol_current_idx"
  ON "factor_scores" ("protocol_slug") WHERE is_current = true;
--> statement-breakpoint
CREATE INDEX "factor_scores_factor_current_idx"
  ON "factor_scores" ("factor_id") WHERE is_current = true;
--> statement-breakpoint
CREATE INDEX "factor_scores_red_idx"
  ON "factor_scores" ("score") WHERE is_current = true AND score IN ('red', 'yellow');
--> statement-breakpoint
CREATE INDEX "factor_scores_rubric_version_idx" ON "factor_scores" ("rubric_version");
--> statement-breakpoint
CREATE INDEX "factor_scores_superseded_by_idx" ON "factor_scores" ("superseded_by") WHERE superseded_by IS NOT NULL;
--> statement-breakpoint
CREATE INDEX "factor_scores_deployment_idx" ON "factor_scores" ("deployment_id") WHERE deployment_id IS NOT NULL;
--> statement-breakpoint

CREATE TABLE "factor_score_sources" (
  "factor_score_id" uuid NOT NULL REFERENCES "factor_scores"("id") ON DELETE CASCADE,
  "source_id"       uuid NOT NULL REFERENCES "sources"("id"),
  "relation"        text NOT NULL DEFAULT 'primary',
  PRIMARY KEY ("factor_score_id", "source_id")
);
--> statement-breakpoint
CREATE INDEX "factor_score_sources_source_idx" ON "factor_score_sources" ("source_id");
--> statement-breakpoint

-- ── Hacks Ledger + Factor Linkage ────────────────────────────────────────────

CREATE TABLE "hacks" (
  "id"                  text PRIMARY KEY NOT NULL,
  "protocol_slug"       text REFERENCES "protocols"("slug"),
  "protocol_name"       text NOT NULL,
  "occurred_at"         date NOT NULL,
  "loss_usd"            numeric(20, 2),
  "category"            text,
  "root_cause"          text NOT NULL,
  "description"         text NOT NULL,
  "postmortem_url"      text,
  "funds_recovered_pct" numeric(5, 2),
  "is_active"           boolean NOT NULL DEFAULT false,
  "status"              text NOT NULL DEFAULT 'closed'
);
--> statement-breakpoint
CREATE INDEX "hacks_occurred_idx" ON "hacks" ("occurred_at" DESC);
--> statement-breakpoint
CREATE INDEX "hacks_protocol_idx" ON "hacks" ("protocol_slug");
--> statement-breakpoint
CREATE INDEX "hacks_active_idx"   ON "hacks" ("is_active") WHERE is_active = true;
--> statement-breakpoint

CREATE TABLE "hack_factor_links" (
  "hack_id"   text NOT NULL REFERENCES "hacks"("id") ON DELETE CASCADE,
  "factor_id" text NOT NULL REFERENCES "factors"("id"),
  "relevance" text NOT NULL,
  "notes"     text,
  "source_id" uuid REFERENCES "sources"("id"),
  PRIMARY KEY ("hack_id", "factor_id")
);
--> statement-breakpoint
CREATE INDEX "hack_factor_links_factor_idx" ON "hack_factor_links" ("factor_id");
--> statement-breakpoint
CREATE INDEX "hack_factor_links_source_idx" ON "hack_factor_links" ("source_id") WHERE source_id IS NOT NULL;
--> statement-breakpoint

-- ── Active Incident Banner ───────────────────────────────────────────────────

CREATE TABLE "active_incidents" (
  "id"            uuid PRIMARY KEY NOT NULL DEFAULT gen_random_uuid(),
  "protocol_slug" text NOT NULL REFERENCES "protocols"("slug") ON DELETE CASCADE,
  "hack_id"       text REFERENCES "hacks"("id"),
  "severity"      "incident_severity" NOT NULL,
  "headline"      text NOT NULL,
  "detail_url"    text,
  "opened_at"     timestamp with time zone NOT NULL,
  "closed_at"     timestamp with time zone,
  "status"        "incident_status" NOT NULL DEFAULT 'open'
);
--> statement-breakpoint
CREATE INDEX "active_incidents_open_idx"
  ON "active_incidents" ("protocol_slug") WHERE status = 'open';
--> statement-breakpoint
CREATE INDEX "active_incidents_hack_idx" ON "active_incidents" ("hack_id") WHERE hack_id IS NOT NULL;
--> statement-breakpoint

-- ── Grade History ─────────────────────────────────────────────────────────────

CREATE TABLE "grade_history" (
  "id"                    uuid PRIMARY KEY NOT NULL DEFAULT gen_random_uuid(),
  "protocol_slug"         text NOT NULL REFERENCES "protocols"("slug") ON DELETE CASCADE,
  "deployment_id"         uuid REFERENCES "deployments"("id"),
  "rubric_version"        text NOT NULL REFERENCES "rubric_versions"("version"),
  "letter"                char(1) NOT NULL,
  "badge"                 text NOT NULL,
  "critical_flag_count"   smallint NOT NULL,
  "red_category_count"    smallint NOT NULL,
  "yellow_category_count" smallint NOT NULL,
  "gray_on_core_five"     boolean NOT NULL,
  "graded_at"             timestamp with time zone NOT NULL,
  "triggered_by"          text NOT NULL,
  "notes"                 text
);
--> statement-breakpoint
CREATE INDEX "grade_history_protocol_idx" ON "grade_history" ("protocol_slug", "graded_at" DESC);
--> statement-breakpoint
CREATE INDEX "grade_history_rubric_idx"   ON "grade_history" ("rubric_version");
--> statement-breakpoint
CREATE INDEX "grade_history_deployment_idx" ON "grade_history" ("deployment_id") WHERE deployment_id IS NOT NULL;
--> statement-breakpoint

-- ── Service Providers ────────────────────────────────────────────────────────

CREATE TABLE "service_providers" (
  "id"           uuid PRIMARY KEY NOT NULL DEFAULT gen_random_uuid(),
  "slug"         text UNIQUE NOT NULL,
  "name"         text NOT NULL,
  "category"     text NOT NULL,
  "homepage_url" text
);
--> statement-breakpoint

CREATE TABLE "protocol_service_providers" (
  "protocol_slug" text NOT NULL REFERENCES "protocols"("slug") ON DELETE CASCADE,
  "provider_id"   uuid NOT NULL REFERENCES "service_providers"("id"),
  "relationship"  text NOT NULL,
  "source_id"     uuid REFERENCES "sources"("id"),
  "notes"         text,
  PRIMARY KEY ("protocol_slug", "provider_id", "relationship")
);
--> statement-breakpoint
CREATE INDEX "protocol_service_providers_provider_idx" ON "protocol_service_providers" ("provider_id");
--> statement-breakpoint
CREATE INDEX "protocol_service_providers_source_idx" ON "protocol_service_providers" ("source_id") WHERE source_id IS NOT NULL;
--> statement-breakpoint

-- ── Change Log ───────────────────────────────────────────────────────────────

CREATE TABLE "change_log" (
  "id"          uuid PRIMARY KEY NOT NULL DEFAULT gen_random_uuid(),
  "changed_at"  timestamp with time zone NOT NULL DEFAULT now(),
  "changed_by"  text NOT NULL,
  "entity_type" text NOT NULL,
  "entity_id"   text NOT NULL,
  "diff"        jsonb NOT NULL,
  "reason"      text
);
--> statement-breakpoint
CREATE INDEX "change_log_entity_idx" ON "change_log" ("entity_type", "entity_id");
--> statement-breakpoint
CREATE INDEX "change_log_recent_idx" ON "change_log" ("changed_at" DESC);
--> statement-breakpoint

-- ── Pipeline Runs ────────────────────────────────────────────────────────────

CREATE TABLE "pipeline_runs" (
  "id"                 uuid PRIMARY KEY NOT NULL DEFAULT gen_random_uuid(),
  "run_at"             timestamp with time zone NOT NULL DEFAULT now(),
  "script_name"        text NOT NULL,
  "cadence_bucket"     text,
  "protocols_touched"  smallint NOT NULL DEFAULT 0,
  "fetchers_invoked"   jsonb NOT NULL DEFAULT '[]'::jsonb,
  "success_count"      smallint NOT NULL DEFAULT 0,
  "error_count"        smallint NOT NULL DEFAULT 0,
  "duration_seconds"   integer,
  "triggered_by"       text NOT NULL,
  "error_summary"      jsonb,
  "notes"              text
);
--> statement-breakpoint
CREATE INDEX "pipeline_runs_recent_idx"  ON "pipeline_runs" ("run_at" DESC);
--> statement-breakpoint
CREATE INDEX "pipeline_runs_script_idx"  ON "pipeline_runs" ("script_name", "run_at" DESC);
--> statement-breakpoint

-- ── Row Level Security ───────────────────────────────────────────────────────
-- Applied here for Supabase compatibility. On local Docker these are no-ops
-- (no anon/service_role distinction) but harmless to include.

ALTER TABLE "rubric_versions"           ENABLE ROW LEVEL SECURITY;
ALTER TABLE "categories"                ENABLE ROW LEVEL SECURITY;
ALTER TABLE "factors"                   ENABLE ROW LEVEL SECURITY;
ALTER TABLE "protocols"                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE "deployments"               ENABLE ROW LEVEL SECURITY;
ALTER TABLE "sources"                   ENABLE ROW LEVEL SECURITY;
ALTER TABLE "factor_scores"             ENABLE ROW LEVEL SECURITY;
ALTER TABLE "factor_score_sources"      ENABLE ROW LEVEL SECURITY;
ALTER TABLE "hacks"                     ENABLE ROW LEVEL SECURITY;
ALTER TABLE "hack_factor_links"         ENABLE ROW LEVEL SECURITY;
ALTER TABLE "active_incidents"          ENABLE ROW LEVEL SECURITY;
ALTER TABLE "grade_history"             ENABLE ROW LEVEL SECURITY;
ALTER TABLE "service_providers"         ENABLE ROW LEVEL SECURITY;
ALTER TABLE "protocol_service_providers" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "change_log"                ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint

CREATE POLICY public_read ON "rubric_versions"            FOR SELECT USING (true);
CREATE POLICY public_read ON "categories"                 FOR SELECT USING (true);
CREATE POLICY public_read ON "factors"                    FOR SELECT USING (true);
CREATE POLICY public_read ON "protocols"                  FOR SELECT USING (true);
CREATE POLICY public_read ON "deployments"                FOR SELECT USING (true);
CREATE POLICY public_read ON "sources"                    FOR SELECT USING (true);
CREATE POLICY public_read ON "factor_scores"              FOR SELECT USING (is_current = true);
CREATE POLICY public_read ON "factor_score_sources"       FOR SELECT USING (true);
CREATE POLICY public_read ON "hacks"                      FOR SELECT USING (true);
CREATE POLICY public_read ON "hack_factor_links"          FOR SELECT USING (true);
CREATE POLICY public_read ON "active_incidents"           FOR SELECT USING (true);
CREATE POLICY public_read ON "grade_history"              FOR SELECT USING (true);
CREATE POLICY public_read ON "service_providers"          FOR SELECT USING (true);
CREATE POLICY public_read ON "protocol_service_providers" FOR SELECT USING (true);
-- change_log intentionally excluded: service_role only
