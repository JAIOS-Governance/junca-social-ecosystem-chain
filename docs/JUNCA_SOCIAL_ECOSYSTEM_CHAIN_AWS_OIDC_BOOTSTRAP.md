# AWS OIDC Bootstrap — Retired

Status: **RETIRED_NON_EXECUTABLE**

The former CloudFormation bootstrap and inventory-role templates were removed.
They encoded an environment-only GitHub OIDC subject and IAM capabilities that
do not satisfy the current workflow-ref, hosted-runner, role-separation, and
non-OIDC administration boundaries.

Do not reconstruct, deploy, or copy either retired template:

- `infrastructure/aws/bootstrap/github-oidc.yaml`
- `infrastructure/aws/bootstrap/public-testnet-inventory-role.yaml`

The old canonical-inventory workflow is also retired. The JSON file at
`infrastructure/aws/public-testnet-oidc-trust-handoff.json` is an audit
tombstone only; it contains no trust-policy patch, AWS command, rollback
command, workflow rerun URL, or executable target-role list.

Current contracts:

- `config/junca_public_testnet_cloud_role_policy.json` — exact role/workflow
  subjects, complete AWS credential-call inventory, and repository-global
  cutover blocks;
- `docs/runbooks/junca-public-testnet-iam-role-separation.md` — non-OIDC
  Security Bootstrap, staged trust migration, strict readback, and rollback;
- `docs/runbooks/junca-public-testnet-fixed-ssm-launch-design.md` — blocked
  validator mutation and launch contract pending fixed SSM implementation.

Repository code is not evidence that AWS was changed. OIDC template cutover,
role activation, validator mutation, and recovery remain blocked until the
required external readbacks agree.

- Mainnet changed: **false**
- Assets moved: **false**
- Bridge activated: **false**
