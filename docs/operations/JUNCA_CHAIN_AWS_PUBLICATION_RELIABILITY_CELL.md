# JUNCA Chain AWS Publication Reliability Cell

Status: ACTIVE  
Scope: `docs.jaios-governance.org` publication only  
Repository: `JAIOS-Governance/junca-social-ecosystem-chain`

## Mission

Maintain the AWS publication path for the JUNCA Social Ecosystem Chain technical reference without coupling source QA, AWS bootstrap, DNS delegation, and production readback into one all-or-nothing step.

## Immutable boundaries

- Network label: `Public Testnet / No Monetary Value`
- Institutional manager: `JAIOS Institutional Governance`
- Mainnet, assets, bridge, validator, KMS/HSM, EC2, RDS, EKS, NAT Gateway: out of scope
- AWS access keys: prohibited
- GitHub deployment: OIDC only
- Secrets and authentication values: never recorded in evidence
- DNS record inventory must be captured before delegation or record changes

## Cell responsibilities

1. Root-cause classification: source, CI, GitHub binding, AWS identity, DNS, ACM, CloudFront, S3, or client rendering.
2. Minimal repair: modify only the failed layer and preserve verified artifacts.
3. Independent readback: verify every changed layer through its own API or public endpoint.
4. Evidence update: record exact SHA, run URL, AWS resource state, DNS state, and rollback point.
5. Repetition prevention: convert every repeated failure into a deterministic preflight or explicit gate.

## Operating state machine

| State | Entry evidence | Allowed work | Exit evidence |
| --- | --- | --- | --- |
| SOURCE_READY | main SHA and CI success | Build and IaC validation | Exact artifact and template pass |
| AWS_IDENTITY_READY | STS caller and role match | Resource readback | Account, caller, OIDC, alias recorded |
| DNS_INVENTORIED | Full authoritative record inventory | Hosted zone preparation | Hosted zone ID, NS set, record snapshot |
| INFRA_READY | Stack complete | GitHub environment binding | S3, ACM, CloudFront, role outputs |
| DEPLOYED | Production workflow success | Public QA | Invalidation completed and manifest match |
| ACCEPTED | Eight routes return HTTP 200 | Maintenance only | TLS, canonical, desktop, tablet, mobile pass |

## Anti-stall policy

- A Console or connector failure affects only its own state. Source QA and public DNS/TLS checks continue.
- AWS Console 5xx or certificate-time errors are classified as a client-path incident until reproduced from AWS API or GitHub OIDC.
- Login and MFA are authentication gates, not code defects.
- Missing OIDC role binding is reported as `AWS_BINDING_PENDING`; it must not be reported as an application failure.
- The production workflow remains fail-closed. It may deploy only when the configured role ARN matches the actual STS account and publication role.
- No scheduled workflow is created. Checks are manually dispatched to avoid recurring compute or credit use.

## Recovery routes

1. Primary: GitHub OIDC production workflow.
2. Bootstrap: AWS CloudShell with `infra/aws/docs-publication/bootstrap.sh`.
3. DNS: Route 53 inventory and XServer nameserver delegation with pre-change snapshot.
4. Public acceptance: independent HTTPS readback of all eight routes.

## Completion evidence

- ACM `ISSUED`
- CloudFront `Deployed`
- S3 versioning `Enabled`
- Route 53 A and AAAA aliases present
- Invalidation `Completed`
- Exact release manifest matches
- Eight routes HTTP 200
- Canonical URL and `Public Testnet` label present
- Desktop, tablet, and mobile visual QA pass

