# Public data boundary

This repository contains the public application, methodology, rubric, schemas,
and the complete reviewed projection for protocols that have been approved for
publication. It is not the protocol research or production control plane.

## Publication states

Three events are deliberately separate:

1. A protocol is inserted into the production database as unpublished. This is
   private and creates no public issue or pull request.
2. Research, assessment, review, and approval happen privately. A sanitized
   projection may be prepared only after a signed private approval receipt
   binds the protocol, snapshot, schema, and export scope.
3. Exactly one public publication pull request adds the approved public data.
   After that pull request is merged and an inactive release is validated, a
   separately approved private transaction changes the database publication
   flag and atomically promotes the already-validated release. No second issue
   or pull request is created for that flag change or promotion.

Public Git presence records reviewed publication content. It must never be used
as evidence that unpublished material was approved merely because it was
previously disclosed.

## Repository ownership

Public:

- application and static-site source;
- public API schemas and deterministic build inputs;
- rubric, methodology, and factor definitions;
- reviewed protocol assessments and their sanitized public history;
- Git-versioned assessment snapshot metadata; and
- fail-closed public boundary validation.

Private:

- unpublished research, assessments, evidence, and review routes;
- reviewer identities, notes, approvals, signatures, and receipts;
- database exporting and publication controls;
- deployment, backup, rollback, and recovery controls;
- production credentials, topology, and internal runbooks; and
- live operational telemetry generation.

Operational material is intentionally ignored under `docs/ops/` and rejected by
CI if force-added.

## Deployment contract

Production releases are built from a clean checkout of one reviewed public Git
SHA. The committed `data/api/**` tree participates in source hashes, build
validation, promotion, and rollback checks. Deployment must not query a
database, run an exporter, copy API files from a previous release, or create a
runtime protocol-data overlay.

Live operational telemetry is a separate service surface. It is not part of the
claim that the checked-in assessment API is reproducible.
