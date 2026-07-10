# Protocol Refresh Change Record

- Refresh ID: `<refresh-id>`
- Protocol family: `<family-slug>`
- Surfaces: `<surface-slugs>`
- Effective date: `<YYYY-MM-DD>`
- Rubric version: `<version>`
- Public issue: `<issue-url>`
- Public payload SHA-256: `<sha256>`

## Scope

List the exact public fields and factor IDs changed. Every other protocol,
surface, factor, deployment, and field is out of scope.

## Accepted Changes

Summarize only publishable facts and primary public sources. Do not include
review tokens, local paths, internal notes, unpublished URLs, credentials, or
curator identities.

## Verification

- Approved payload checksum matched: `<yes/no>`
- Family/surface/factor scope validated: `<yes/no>`
- Unrelated generated API semantic changes: `<none or explanation>`
- Production backup and rollback rehearsal reference: `<public-safe reference>`
- Production state verified: `<pending/verified>`
- Live family and surface output verified: `<pending/verified>`

## Result

Record the final public result and any remaining limitation. Do not state that
the refresh is deployed or complete until production and live verification
have succeeded.
