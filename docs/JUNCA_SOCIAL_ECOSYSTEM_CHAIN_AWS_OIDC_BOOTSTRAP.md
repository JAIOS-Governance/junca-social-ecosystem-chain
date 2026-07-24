# AWS OIDC Bootstrap

This package establishes the one-time, short-lived credential boundary between
GitHub Actions and the canonical AWS account for JUNCA Social Ecosystem Chain.

It creates only:

- the GitHub Actions OIDC identity provider;
- one repository- and environment-scoped deployment role;
- an encrypted, private, versioned Terraform state bucket;
- an encrypted Terraform lock table with point-in-time recovery.

It does not create validators, RPC, Explorer, KMS keys, bridge resources,
mainnet resources, tokens, NFTs, or asset-transfer routes.

## Fixed public boundary

- Official Chain Name: `JUNCA Social Ecosystem Chain`
- Governance: `JAIOS Institutional Governance`
- Network: `Public Testnet / No Monetary Value`
- Mainnet Changed=false
- Assets Moved=false
- Bridge Activated=false

## Bootstrap

Run the CloudFormation template once in the canonical AWS account and the
canonically selected region. Record only the non-secret stack outputs:

- `AccountId`
- `Region`
- `DeploymentRoleArn`
- `TerraformStateBucket`
- `TerraformLockTable`

Do not create or store AWS access keys. The trust policy accepts only the
`JAIOS-Governance/junca-social-ecosystem-chain` repository using the
`public-testnet` GitHub Environment.

After independent output readback, manually run
`JUNCA Social Ecosystem Chain AWS Canonical Readback`. The workflow verifies
the expected account and region, uploads 90-day redacted evidence, and keeps
`deployment_enabled=false`.

Actual Terraform apply remains a separate release gate.
