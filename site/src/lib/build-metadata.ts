import status from '../../../data/api/v1.7.0/status.json';
import contentMetadata from '../content-metadata.json';

const projectionTimestamp = status.data.assessment_snapshot.projection_timestamp;

if (!Number.isFinite(Date.parse(projectionTimestamp))) {
  throw new Error('Committed assessment projection timestamp is invalid');
}

/**
 * Build-visible timestamps come from the reviewed assessment snapshot.
 * They must never depend on the wall clock of the machine performing the build.
 */
export const PUBLIC_SNAPSHOT_TIMESTAMP = projectionTimestamp;
export const PUBLIC_SNAPSHOT_RFC_822 = new Date(projectionTimestamp).toUTCString();
export const CONTENT_LAST_UPDATED = Object.freeze(contentMetadata.last_updated);
