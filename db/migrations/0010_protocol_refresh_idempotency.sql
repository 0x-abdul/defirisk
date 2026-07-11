-- Migration 0010: reserve one production apply per protocol refresh artifact.

CREATE UNIQUE INDEX IF NOT EXISTS pipeline_runs_protocol_refresh_trigger_unique
  ON pipeline_runs (triggered_by)
  WHERE script_name = 'apply-protocol-refresh.py';

COMMENT ON INDEX pipeline_runs_protocol_refresh_trigger_unique IS
  'Idempotency key for approved protocol refresh apply artifacts.';
