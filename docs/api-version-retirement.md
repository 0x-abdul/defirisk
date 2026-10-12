# API version retirement

The supported public API version is `v1.7.0`. The local release candidate retires
`v1.5.0` and `v1.6.0`; deploying that candidate is a separate operation.

When that candidate is deployed with its qualified routing, every request to `/api/v1.5.0`, `/api/v1.6.0`, either trailing-slash root, or any
descendant returns HTTP **410 Gone** with `Content-Type: application/json` and
this version-specific body:

```json
{"error":"api_version_retired","api_version":"v1.6.0","migration_url":"/data/"}
```

The same contract covers previously known file routes and unknown descendants.
It does not redirect, serve a stale legacy file, recompute historical grades,
or substitute a current assessment. Clients must explicitly choose the current
version and inspect its status and available data. Versioned paths do not promise
indefinite retention.

Retirement is producer metadata (`retired_api_versions`) in a qualified API
candidate. Retired source trees and authentic evidence remain retained privately;
they are excluded from the candidate's serving roster. Removing files or writing
static-host redirect metadata alone does not prove the HTTP status. Local routing
must be exercised against a real Caddy listener, including all known routes,
roots, unknown descendants, and neighboring non-retired prefixes. Production
routing and publication remain separate from local qualification.

The qualified build runner supports `DEFIRISK_COMPILER_BACKEND=wasi`, using the
compiler package's published `NAPI_RS_FORCE_WASI=1` loader setting. It never
modifies native binaries or operating-system policy. A direct compile must pass,
and the wrapper exports must be identical to the selected cached WASI binding;
otherwise qualification fails. Unrelated native build dependencies retain their
existing backend. An external private
`<build-receipt>.invocation.json` binds the actual Node executable, selected
compiler and dependency file hashes, frozen build inputs, and output receipt.

Ordinary builds of the frozen API snapshot retain the main validator and its
four build stages. Their local receipt is `public-build/frozen-v1-local/v1`; it
does not establish strict candidate output qualification. Explicit API input
overrides select the complete candidate/output boundary and its separate receipt.
