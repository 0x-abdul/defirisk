# Security Policy

The Risk Dashboard is a publication product — it does not custody user funds,
hold user credentials, or process payments. The security surface is therefore
the web application, the build pipeline, the published data, and the public
API. We take vulnerabilities in any of these seriously.

## Reporting a vulnerability

**Preferred:** Use GitHub's Private Vulnerability Reporting on this repository
(Security tab → "Report a vulnerability"). This keeps the report private,
gives us an audit trail, and lets us coordinate a fix before any public
disclosure.

**Alternative:** Email the maintainer at the address listed in the repository
profile.

Please include, where applicable:

- A description of the issue and its security impact.
- Steps to reproduce, ideally with a minimal proof-of-concept.
- Affected versions / commit SHA.
- Your name or handle for the public acknowledgement (if you want one) — or
  let us know if you'd prefer to remain anonymous.

## Scope

In scope:

- The site under `site/` (Astro frontend, API routes).
- The data pipeline under `risk-dashboard/scripts/data-pipeline/` and the
  composer/dump scripts under `scripts/`.
- The public read API and JSON envelopes under `data/api/`.
- Dependency vulnerabilities and supply-chain integrity of the build.
- The CI workflows under `.github/workflows/`.
- Issues that allow injection of false or unverified factor data into the
  published dataset.

Out of scope:

- Findings against forks or unauthorised mirrors.
- Disagreements with a protocol's risk grade (these go through the public
  dispute path described in [CONTRIBUTING.md](CONTRIBUTING.md#disputes-and-issue-flags)).
- Theoretical issues without a working reproduction.
- Social-engineering tests against maintainers without prior agreement.
- Findings that depend on physical access to a maintainer's machine.

## Response

We aim to acknowledge a report within five business days, and to land a fix
or a public mitigation note within thirty days for confirmed issues. Critical
issues — those that allow remote code execution, data corruption of the
published dataset, or impersonation of the dashboard — are prioritised over
non-security work.

We will:

1. Acknowledge receipt and confirm the report is in scope.
2. Triage and assign severity.
3. Develop a fix in a private branch.
4. Coordinate disclosure with the reporter.
5. Land the fix and publish a brief post-mortem in `docs/methodology/changelog.md`
   if the issue affected published data.

We will not:

- Pursue legal action against good-faith researchers who follow this policy.
- Publish identifying details about a reporter without their permission.

## Data integrity reports

Because the published dataset is the product, we treat the following as
security-relevant:

- A factor score that demonstrably contradicts its cited sources.
- A protocol page that misrepresents a deployment, multisig threshold, or
  oracle posture.
- Evidence that a protocol team submitted false data through the verified
  self-service path (per `risk-dashboard/research/outputs/06-oss-posture.md`
  §4.3).

Reports of this kind can be filed publicly via the issue-flag path or
privately via the channel above if the reporter has reason to keep it
confidential.

## Acknowledgements

We maintain a public list of researchers who have responsibly disclosed
issues at `docs/security/acknowledgements.md` (created when the first report
lands).
