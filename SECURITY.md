# Security Policy

defirisk.co is a publication product. It does not custody user funds, hold user
credentials, or process payments. The security surface is the web application,
the build pipeline, the published data, and the public static API.

## Reporting a vulnerability

**Preferred:** use GitHub Private Vulnerability Reporting on this repository
from the Security tab. This keeps the report private, gives maintainers an
audit trail, and lets us coordinate a fix before public disclosure.

**Alternative:** contact the maintainer through the channel listed on
[defirisk.co/about](https://defirisk.co/about/).

Please include, where applicable:

- a description of the issue and its security impact
- steps to reproduce, ideally with a minimal proof of concept
- affected versions or commit SHA
- your name or handle for public acknowledgment, if you want one

Tell us if you prefer to remain anonymous.

## Scope

In scope:

- the Astro site under `site/`
- the scoring pipeline scripts under `scripts/`
- the public read API and JSON envelopes under `data/api/`
- dependency vulnerabilities and build supply-chain integrity
- CI workflows under `.github/workflows/`
- issues that allow false or unverified factor data to enter the published
  dataset

Out of scope:

- findings against forks or unauthorized mirrors
- disagreements with a protocol's risk grade, which should use the public
  correction and dispute channels in
  [CONTRIBUTING.md](CONTRIBUTING.md#corrections-and-disputes)
- theoretical issues without a working reproduction
- social-engineering tests against maintainers without prior agreement
- findings that depend on physical access to a maintainer's machine

## Response

We aim to acknowledge a report within five business days. For confirmed issues,
we aim to land a fix or publish a mitigation note within 30 days. Critical
issues are prioritized over non-security work, especially issues that allow
remote code execution, published-data corruption, or impersonation of
defirisk.co.

We will:

1. Acknowledge receipt and confirm whether the report is in scope.
2. Triage and assign severity.
3. Develop a fix privately when disclosure timing matters.
4. Coordinate disclosure with the reporter.
5. Land the fix and publish a brief note when the issue affected published
   data or user trust.

We will not:

- pursue legal action against good-faith researchers who follow this policy
- publish identifying details about a reporter without permission

## Data integrity reports

Because the published dataset is the product, some data issues are
security-relevant:

- a factor score that demonstrably contradicts its cited sources
- a protocol page that misrepresents a deployment, multisig threshold, or
  oracle posture
- evidence that a protocol team submitted false data through the review path

Reports of this kind can be filed publicly through a
[Factual Correction](.github/ISSUE_TEMPLATE/factual-correction.md). If the
reporter has a reason to keep the issue confidential, use the private
vulnerability channel instead.

## Acknowledgments

We maintain a public list of researchers who responsibly disclose issues. The
list will be added here when the first report lands.
