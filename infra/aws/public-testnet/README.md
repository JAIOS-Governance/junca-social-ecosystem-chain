# AWS Public Testnet Infrastructure

Canonical infrastructure for **JUNCA Social Ecosystem Chain**, managed under **JAIOS Institutional Governance**.

## Network boundary

- Public Testnet / No Monetary Value
- three validators in three distinct AWS Availability Zones
- validator JSON-RPC is loopback/private and never exposed directly
- two private read-only RPC replicas behind an HTTPS Application Load Balancer
- two finalized-only explorer replicas
- Route 53 DNS and ACM TLS
- signer references are existing KMS or CloudHSM resources
- no validator private key, mnemonic or signer secret is stored in source, user data or Terraform state
- bridge remains paused
- mainnet changed: false
- assets moved: false
- bridge activated: false

## Fail-closed binding

`config/junca_social_ecosystem_chain_aws_binding.pending.json` remains `BLOCKED` until read-only AWS evidence confirms the exact account, organization, region, hosted zone, three Availability Zones, state backend, OIDC deployment principal and three signer resources.

The AWS provider uses `allowed_account_ids`, and Terraform preconditions reject account or hosted-zone mismatch before resource creation.

## Execution sequence

1. Read back the authenticated AWS caller identity and Organization account.
2. Read back the acquired domain and public Route 53 hosted zone.
3. Select three distinct Availability Zones in the canonical region.
4. Confirm the dedicated encrypted S3 state backend and DynamoDB locking table.
5. Confirm the repository-scoped OIDC deployment role.
6. Confirm three distinct KMS/CloudHSM signer resource ARNs without reading secret material.
7. Supply an approved immutable AMI, genesis SHA-256 and node artifact SHA-256.
8. Run `terraform init -backend-config=...`, `terraform validate`, `terraform plan`.
9. Apply validators 01, 02 and 03; verify quorum before enabling public endpoints.
10. Run Runtime Acceptance v2 and non-production rollback acceptance.

Do not record deployment as accepted until every live acceptance gate passes.
