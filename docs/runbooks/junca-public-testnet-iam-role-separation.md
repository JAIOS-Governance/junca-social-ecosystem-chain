# JUNCA Public Testnet IAM Separation and Recovery

This is a Security Bootstrap migration, not a normal OIDC deployment.
Mainnet changes, asset movement, and bridge activation remain prohibited.

The final Foundation policy explicitly denies `ec2:RunInstances`,
`iam:PassRole`, and `ssm:SendCommand`. Validator SSM Core is detached while
fixed documents are unavailable. Validator replacement and remote root
commands therefore remain:

`BLOCKED_PENDING_ATTESTED_LAUNCH_AND_SSM_CONTRACT`

Do not weaken those denies to restore service. A later Security Bootstrap
change must introduce the six fixed SSM documents
(`FinalityInspect`, `FinalitySet`, `BootstrapReadiness`,
`RuntimeObservation`, `RestartHealth`, `HealthReadback`) and the
SecurityBootstrap-owned `JuncaPTReplaceValidator` Automation with an immutable,
non-overridable launch contract before rollout can resume.

Foundation also explicitly denies unbound snapshot, volume, subnet,
route-table, security-group, and VPC-endpoint creation. Those multi-resource
APIs can otherwise consume an unrelated parent VPC or snapshot even when the
new resource receives correct request tags. The required existing network and
storage parents must be externally pre-provisioned/imported, or a later policy
must bind every source/parent and destination resource separately. Request tags
alone are never sufficient.

## Canonical identities

| Boundary | Canonical role |
| --- | --- |
| Security Bootstrap | `arn:aws:iam::595710543956:role/JuncaChainSecurityBootstrap` |
| Security remediation | `arn:aws:iam::595710543956:role/JuncaChainSecurityBootstrapRemediation` |
| Foundation | `arn:aws:iam::595710543956:role/JuncaChainPublicTestnetDeployment` |
| AMI Builder | `arn:aws:iam::595710543956:role/JuncaChainPublicTestnetAmiBuilder` |
| Observer | `arn:aws:iam::595710543956:role/JuncaChainPublicTestnetObserver` |
| Image Builder worker | `arn:aws:iam::595710543956:role/JuncaChainPublicTestnetImageBuilder` |

The historical Deployment ARN is retained only as the narrowed Foundation
compatibility alias.

## 0. Freeze and inventory the repository-wide OIDC cutover

The repository subject-template API is global to the repository. Changing it
affects every AWS workflow, not only the seven JSEC workflows. At the baseline
audit, 60 tracked workflows referenced AWS credentials, an OIDC token, or the
OIDC customization API. The final cutover inventory must be generated from the
exact reviewed commit because workflow retirement can change that count.

Freeze all AWS/OIDC dispatches, scheduled runs, `workflow_run` consumers, and
protected-environment approvals. Do not change the template until each
affected role and workflow has an owner in the cutover matrix.

```bash
set -euo pipefail
JSEC_REPOSITORY=JAIOS-Governance/junca-social-ecosystem-chain
CUTOVER_SHA="$(git rev-parse HEAD)"
test "$(git branch --show-current)" = main
test "$(git status --porcelain | wc -l)" = 0

git grep -l -E \
  'aws-actions/configure-aws-credentials|ACTIONS_ID_TOKEN_REQUEST_URL|actions/oidc' \
  "$CUTOVER_SHA" -- '.github/workflows/*.yml' '.github/workflows/*.yaml' |
  sed "s/^${CUTOVER_SHA}://" |
  sort -u >oidc-affected-workflows.txt
test -s oidc-affected-workflows.txt
sha256sum oidc-affected-workflows.txt >oidc-affected-workflows.txt.sha256

gh api \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  "repos/${JSEC_REPOSITORY}/actions/oidc/customization/sub" \
  >oidc-template-before.json
jq -e '
  (.use_default | type) == "boolean" and
  (.include_claim_keys | type) == "array" and
  (
    (has("use_immutable_subject") | not) or
    (.use_immutable_subject == true or .use_immutable_subject == false)
  )
' oidc-template-before.json
jq -cSj . oidc-template-before.json |
  sha256sum |
  cut -d" " -f1 >oidc-template-before.sha256
```

Create a reviewed `oidc-role-cutover-matrix.json` that maps every inventory
entry to its exact role ARN, current subject, future subject, workflow path,
and test owner. The matrix is blocking if any workflow is unmapped.

Before template mutation, Security Bootstrap must stage each future exact
subject on every non-JSEC AWS role in the matrix. Wildcards are forbidden.
For JSEC, the `stage` plan removes the legacy environment-only subject, installs
only future exact subjects, enforces explicit denies, and purges unmanaged
inline/attached policies in the same apply. This intentionally creates a short
JSEC OIDC outage until the repository template is changed. Never add the
environment-only subject to AMI Builder or Observer, and never retain it beside
the new subjects. After template mutation, obtain and test one live token from
every matrix entry. The `finalize` plan is evidence-only closure: it must not
introduce a new trust or permission mutation.

Restoring `oidc-template-before.json` is allowed only while all of these are
true:

- the repository-wide AWS freeze is still active;
- no new-template-only workflow has been resumed or accepted;
- every legacy role trust remains exactly inventoried and reviewed;
- Security Bootstrap remains active and the coordinated role-trust rollback
  is ready.

Once any new-template workflow is resumed, any new-only trust is accepted, or
legacy trust is removed, restoring the old template is prohibited. Forward-fix
all role trusts with Security Bootstrap instead. JSEC-only acceptance is never
sufficient to lift the repository-wide freeze.

## 1. Prove the non-OIDC Security Bootstrap session

The role name is pinned in Terraform. Its trust must contain one statement:
an exact same-account IAM user with hardware MFA, ExternalId, and the single
session tag `JuncaChangeBoundary=SecurityBootstrap`. Maximum session duration
is one hour. The exact attached policies are
`JuncaChainSecurityBootstrapCore` and `JuncaChainSecurityBootstrapState`;
inline policies are empty. Both committed policy documents are below the IAM
6,144-character managed-policy limit. Neither policy can version, replace,
tag, or delete either Security Bootstrap policy.

```bash
set -euo pipefail
AWS_ACCOUNT_ID=595710543956
AWS_REGION=us-east-1
SECURITY_BOOTSTRAP_PRINCIPAL_ARN=\
arn:aws:iam::595710543956:role/JuncaChainSecurityBootstrap
SECURITY_BOOTSTRAP_TRUSTED_ADMIN_PRINCIPAL_ARN=\
arn:aws:iam::595710543956:user/REPLACE_WITH_HARDWARE_MFA_ADMIN_USER
SECURITY_BOOTSTRAP_EXTERNAL_ID=REPLACE_WITH_APPROVED_EXTERNAL_ID

caller_json="$(aws sts get-caller-identity --output json)"
jq -e --arg account "$AWS_ACCOUNT_ID" '
  .Account == $account and
  (.Arn | startswith(
    "arn:aws:sts::595710543956:assumed-role/" +
    "JuncaChainSecurityBootstrap/"
  ))
' <<<"$caller_json"

aws iam get-role \
  --role-name JuncaChainSecurityBootstrap \
  >security-bootstrap-role.json
jq -e \
  --arg admin "$SECURITY_BOOTSTRAP_TRUSTED_ADMIN_PRINCIPAL_ARN" \
  --arg external_id "$SECURITY_BOOTSTRAP_EXTERNAL_ID" '
  (.Role.MaxSessionDuration <= 3600) and
  (.Role.Tags | any(
    .Key == "RoleBoundary" and .Value == "SecurityBootstrap"
  )) and
  (.Role.AssumeRolePolicyDocument.Statement | length) == 1 and
  .Role.AssumeRolePolicyDocument.Statement[0] == {
    Effect: "Allow",
    Principal: {AWS: $admin},
    Action: ["sts:AssumeRole", "sts:TagSession"],
    Condition: {
      Bool: {"aws:MultiFactorAuthPresent": "true"},
      StringEquals: {
        "sts:ExternalId": $external_id,
        "aws:RequestTag/JuncaChangeBoundary": "SecurityBootstrap"
      },
      "ForAllValues:StringEquals": {
        "aws:TagKeys": ["JuncaChangeBoundary"]
      }
    }
  }
' security-bootstrap-role.json

SECURITY_BOOTSTRAP_EXTERNAL_ID_SHA256="$(
  printf %s "$SECURITY_BOOTSTRAP_EXTERNAL_ID" | sha256sum | cut -d" " -f1
)"

aws iam list-attached-role-policies \
  --role-name JuncaChainSecurityBootstrap \
  >security-bootstrap-attached.json
aws iam list-role-policies \
  --role-name JuncaChainSecurityBootstrap \
  >security-bootstrap-inline.json
jq -n \
  --slurpfile attached security-bootstrap-attached.json \
  --slurpfile inline security-bootstrap-inline.json '
  {
    attached_policy_arns:
      ($attached[0].AttachedPolicies | map(.PolicyArn) | sort),
    inline_policy_names: ($inline[0].PolicyNames | sort)
  }
' >security-bootstrap-policy-allowlist.json
jq -e '
  . == {
    attached_policy_arns: [
      "arn:aws:iam::595710543956:policy/JuncaChainSecurityBootstrapCore",
      "arn:aws:iam::595710543956:policy/JuncaChainSecurityBootstrapState"
    ],
    inline_policy_names: []
  }
' security-bootstrap-policy-allowlist.json
SECURITY_BOOTSTRAP_POLICY_READBACK_SHA256="$(
  jq -cSj . security-bootstrap-policy-allowlist.json |
    sha256sum |
    cut -d" " -f1
)"

for policy_name in \
  JuncaChainSecurityBootstrapCore \
  JuncaChainSecurityBootstrapState
do
  policy_arn="arn:aws:iam::595710543956:policy/${policy_name}"
  version_id="$(
    aws iam get-policy --policy-arn "$policy_arn" |
      jq -er .Policy.DefaultVersionId
  )"
  aws iam get-policy-version \
    --policy-arn "$policy_arn" \
    --version-id "$version_id" \
    >"${policy_name}.live.json"
  jq -cSj .PolicyVersion.Document "${policy_name}.live.json" \
    >"${policy_name}.canonical.json"
  sha256sum "${policy_name}.canonical.json" \
    >"${policy_name}.canonical.json.sha256"
done

SECURITY_BOOTSTRAP_CORE_POLICY_DOCUMENT_SHA256="$(
  cut -d" " -f1 JuncaChainSecurityBootstrapCore.canonical.json.sha256
)"
SECURITY_BOOTSTRAP_STATE_POLICY_DOCUMENT_SHA256="$(
  cut -d" " -f1 JuncaChainSecurityBootstrapState.canonical.json.sha256
)"

test "$SECURITY_BOOTSTRAP_CORE_POLICY_DOCUMENT_SHA256" = "$(
  jq -cSj . infra/aws/bootstrap/policies/security-bootstrap-core.json |
    sha256sum |
    cut -d" " -f1
)"
test "$SECURITY_BOOTSTRAP_STATE_POLICY_DOCUMENT_SHA256" = "$(
  jq -cSj . infra/aws/bootstrap/policies/security-bootstrap-state.json |
    sha256sum |
    cut -d" " -f1
)"

aws iam list-roles --path-prefix / >protected-prefix-roles.live.json
aws iam list-instance-profiles --path-prefix / \
  >protected-prefix-instance-profiles.live.json
jq -nS \
  --slurpfile roles protected-prefix-roles.live.json \
  --slurpfile profiles protected-prefix-instance-profiles.live.json '
  {
    role_names: (
      $roles[0].Roles |
      map(.RoleName) |
      map(select(test(
        "^(JuncaChainPublicTestnet.*|" +
        "junca-social-ecosystem-chain-testnet-validator-.*)$"
      ))) |
      sort
    ),
    instance_profile_names: (
      $profiles[0].InstanceProfiles |
      map(.InstanceProfileName) |
      map(select(test(
        "^(JuncaChainPublicTestnet.*|" +
        "junca-social-ecosystem-chain-testnet-validator-.*)$"
      ))) |
      sort
    ),
    instance_profile_roles: (
      $profiles[0].InstanceProfiles |
      map(select(
        .InstanceProfileName |
        test(
          "^(JuncaChainPublicTestnet.*|" +
          "junca-social-ecosystem-chain-testnet-validator-.*)$"
        )
      )) |
      sort_by(.InstanceProfileName) |
      map({
        key: .InstanceProfileName,
        value: (.Roles | map(.RoleName) | sort)
      }) |
      from_entries
    )
  }
' >protected-iam-prefix-inventory.json
jq -e '
  . == {
    role_names: [
      "JuncaChainPublicTestnetAmiBuilder",
      "JuncaChainPublicTestnetDeployment",
      "JuncaChainPublicTestnetImageBuilder",
      "JuncaChainPublicTestnetObserver",
      "junca-social-ecosystem-chain-testnet-validator-1",
      "junca-social-ecosystem-chain-testnet-validator-2",
      "junca-social-ecosystem-chain-testnet-validator-3"
    ],
    instance_profile_names: [
      "JuncaChainPublicTestnetImageBuilder",
      "junca-social-ecosystem-chain-testnet-validator-1",
      "junca-social-ecosystem-chain-testnet-validator-2",
      "junca-social-ecosystem-chain-testnet-validator-3"
    ],
    instance_profile_roles: {
      "JuncaChainPublicTestnetImageBuilder": [
        "JuncaChainPublicTestnetImageBuilder"
      ],
      "junca-social-ecosystem-chain-testnet-validator-1": [
        "junca-social-ecosystem-chain-testnet-validator-1"
      ],
      "junca-social-ecosystem-chain-testnet-validator-2": [
        "junca-social-ecosystem-chain-testnet-validator-2"
      ],
      "junca-social-ecosystem-chain-testnet-validator-3": [
        "junca-social-ecosystem-chain-testnet-validator-3"
      ]
    }
  }
' protected-iam-prefix-inventory.json
PROTECTED_IAM_PREFIX_INVENTORY_READBACK_SHA256="$(
  jq -cSj . protected-iam-prefix-inventory.json |
    sha256sum |
    cut -d" " -f1
)"
```

Read the CloudTrail event for the current `AssumeRole` session and require the
exact session tag, MFA, and approved source principal. Archive
`sourceIdentity` when the upstream administrator emits it, but this revision
does not claim that the Security Bootstrap trust enforces it. A successful
`iam:GetRole` under the canonical policy is also a
direct session-tag probe because every action except `sts:GetCallerIdentity`
is explicitly denied when the tag is absent.

Security Bootstrap may update trust only on the three exact OIDC controller
roles (Foundation, AMI Builder controller, and Observer). It is explicitly
denied `iam:UpdateAssumeRolePolicy` on the Image Builder worker and each of the
three exact Validator roles, so it cannot replace Validator EC2 trust, assume a
signer identity, and bypass its own `kms:Sign` deny. It is also explicitly
denied creating a protected instance profile or adding/removing any Image
Builder/Validator role-profile membership; exact bindings are an external
prerequisite, not a Bootstrap repair path. No Validator role or
instance-profile wildcard is present in either attached policy. The protected
prefix inventory above must equal exactly seven roles and four profiles; any
residual or newly introduced matching name blocks both phases.

```bash
aws iam simulate-principal-policy \
  --policy-source-arn "$SECURITY_BOOTSTRAP_PRINCIPAL_ARN" \
  --action-names iam:UpdateAssumeRolePolicy \
  --resource-arns \
    arn:aws:iam::595710543956:role/JuncaChainPublicTestnetImageBuilder \
    arn:aws:iam::595710543956:role/junca-social-ecosystem-chain-testnet-validator-1 \
    arn:aws:iam::595710543956:role/junca-social-ecosystem-chain-testnet-validator-2 \
    arn:aws:iam::595710543956:role/junca-social-ecosystem-chain-testnet-validator-3 \
  --context-entries \
    ContextKeyName=aws:PrincipalTag/JuncaChangeBoundary,ContextKeyValues=SecurityBootstrap,ContextKeyType=string \
  >security-bootstrap-workload-trust-negative-simulation.json
jq -e '
  (.EvaluationResults | length) == 1 and
  (.EvaluationResults[0].ResourceSpecificResults | length) == 4 and
  all(
    .EvaluationResults[0].ResourceSpecificResults[];
    .EvalResourceDecision == "explicitDeny"
  )
' security-bootstrap-workload-trust-negative-simulation.json

aws iam simulate-principal-policy \
  --policy-source-arn "$SECURITY_BOOTSTRAP_PRINCIPAL_ARN" \
  --action-names \
    iam:AddRoleToInstanceProfile \
    iam:CreateInstanceProfile \
    iam:RemoveRoleFromInstanceProfile \
  --resource-arns \
    arn:aws:iam::595710543956:role/JuncaChainPublicTestnetImageBuilder \
    arn:aws:iam::595710543956:role/junca-social-ecosystem-chain-testnet-validator-1 \
    arn:aws:iam::595710543956:role/junca-social-ecosystem-chain-testnet-validator-2 \
    arn:aws:iam::595710543956:role/junca-social-ecosystem-chain-testnet-validator-3 \
    arn:aws:iam::595710543956:instance-profile/JuncaChainPublicTestnetImageBuilder \
    arn:aws:iam::595710543956:instance-profile/junca-social-ecosystem-chain-testnet-validator-1 \
    arn:aws:iam::595710543956:instance-profile/junca-social-ecosystem-chain-testnet-validator-2 \
    arn:aws:iam::595710543956:instance-profile/junca-social-ecosystem-chain-testnet-validator-3 \
  --context-entries \
    ContextKeyName=aws:PrincipalTag/JuncaChangeBoundary,ContextKeyValues=SecurityBootstrap,ContextKeyType=string \
  >security-bootstrap-workload-profile-negative-simulation.json
jq -e '
  (.EvaluationResults | length) == 3 and
  all(
    .EvaluationResults[];
    (.ResourceSpecificResults | length) == 8 and
    all(
      .ResourceSpecificResults[];
      .EvalResourceDecision == "explicitDeny"
    )
  )
' security-bootstrap-workload-profile-negative-simulation.json
```

Archive both default versions and require independent approval. Run IAM Access
Analyzer `ValidatePolicy` and positive/negative `SimulatePrincipalPolicy` for
both documents. Stop on
`AssumeRoleWithWebIdentity`, a federated principal, missing MFA/session-tag
conditions, any other attached policy, any inline policy, self-policy version
permission, unrestricted `iam:AttachRolePolicy`, `kms:Sign`, or signer
`kms:CreateGrant`.

The Foundation attachment allow contains only its five exact customer-managed
policies. A separate Image Builder worker statement contains only
`EC2InstanceProfileForImageBuilder` and `AmazonSSMManagedInstanceCore`; no
role×policy Cartesian product is permitted.

Do not substitute an IAM role or Identity Center role session for the trusted
user. `aws:MultiFactorAuthPresent` does not reliably carry through role
chaining. A role-based administrator requires a separately designed upstream
tag/SourceIdentity contract and is outside this recovery.

### 1.1 External remediation prerequisite

Before any stage plan, a separately owned
`JuncaChainSecurityBootstrapRemediation` role must exist. It is normally
disabled, non-OIDC, hardware-MFA protected, two-person/JIT approved, limited
to a 15-minute session, and requires exact ticket and source-identity tags.
Its policy may repair only Security Bootstrap trust/policies and state
control-plane policy. It must explicitly deny KMS signing, state object data
plane, application mutation, OIDC assumption, and asset/mainnet/bridge
operations. CloudTrail and SNS alerts are mandatory for assume, policy
mutation, and denial.

Two independent reviewers must archive its trust, permissions, permissions
boundary, disabled-by-default state, and a negative simulation suite. A canary
use must end with session revocation and an exact post-use readback. The state
bucket policy recognizes this remediation ARN for control-plane repair but
explicitly denies its object data plane. If this independently owned role is
absent or its signed evidence is stale, both migration phases are blocked.

The externally owned boundary default versions must canonicalize exactly to:

- `infra/aws/bootstrap/policies/foundation-boundary.json`
- `infra/aws/bootstrap/policies/ami-builder-boundary.json`
- `infra/aws/bootstrap/policies/observer-boundary.json`
- `infra/aws/bootstrap/policies/security-remediation-boundary.json`, rendered
  with the four exact imported live key ARNs
- configured `JuncaChainPublicTestnetImageBuilderBoundary`
- configured `JuncaChainPublicTestnetValidator01Boundary`
- configured `JuncaChainPublicTestnetValidator02Boundary`
- configured `JuncaChainPublicTestnetValidator03Boundary`

Hash each live default-version document with newline-free sorted JSON and pass
the exact eight-name digest object to Terraform. The first three boundaries are
intentionally deny-all in this recovery revision. They permit STS trust
attestation but no AWS operation; therefore this revision is not operational.
The remediation boundary permits only the separately controlled repair plane
and explicitly denies signing, grants, state objects, and application mutation.
Its two `CreateKey` statements are purpose-separated: state requires
`ENCRYPT_DECRYPT`/`SYMMETRIC_DEFAULT`; validators require
`SIGN_VERIFY`/`ECC_SECG_P256K1`. Both require `MultiRegion=false` and the exact
purpose-specific tag-key set, and neither permits bypassing the key-policy
lockout safety check. Existing key mutation is limited to the four live key
ARNs resolved from the state and Validator01–03 aliases; rotation operations
are additionally limited to the state key. Alias
mutation is explicitly denied after that binding; a broken alias returns to
the independent pre-provisioning authority. The literal `${...}` placeholders
in the source file must never be installed.
Security Bootstrap can read these boundaries but is explicitly denied every
policy-version/default/deletion/tag mutation. Boundary evolution is a separate
two-person remediation change.

```bash
declare -A BOUNDARY_POLICY_ARNS=(
  [foundation]=arn:aws:iam::595710543956:policy/JuncaChainPublicTestnetFoundationBoundary
  [ami_builder]=arn:aws:iam::595710543956:policy/JuncaChainPublicTestnetAmiBuilderBoundary
  [observer]=arn:aws:iam::595710543956:policy/JuncaChainPublicTestnetObserverBoundary
  [remediation]=arn:aws:iam::595710543956:policy/JuncaChainSecurityBootstrapRemediationBoundary
  [image_builder_worker]=arn:aws:iam::595710543956:policy/JuncaChainPublicTestnetImageBuilderBoundary
  [validator01]=arn:aws:iam::595710543956:policy/JuncaChainPublicTestnetValidator01Boundary
  [validator02]=arn:aws:iam::595710543956:policy/JuncaChainPublicTestnetValidator02Boundary
  [validator03]=arn:aws:iam::595710543956:policy/JuncaChainPublicTestnetValidator03Boundary
)

for boundary_name in "${!BOUNDARY_POLICY_ARNS[@]}"
do
  policy_arn="${BOUNDARY_POLICY_ARNS[$boundary_name]}"
  default_version="$(
    aws iam get-policy --policy-arn "$policy_arn" |
      jq -er .Policy.DefaultVersionId
  )"
  aws iam get-policy-version \
    --policy-arn "$policy_arn" \
    --version-id "$default_version" \
    >"boundary-${boundary_name}.live.json"
  jq -cSj .PolicyVersion.Document "boundary-${boundary_name}.live.json" \
    >"boundary-${boundary_name}.canonical.json"
  sha256sum "boundary-${boundary_name}.canonical.json" |
    cut -d" " -f1 >"boundary-${boundary_name}.sha256"
done

jq -nS \
  --arg foundation "$(cat boundary-foundation.sha256)" \
  --arg ami_builder "$(cat boundary-ami_builder.sha256)" \
  --arg observer "$(cat boundary-observer.sha256)" \
  --arg remediation "$(cat boundary-remediation.sha256)" \
  --arg image_builder_worker "$(cat boundary-image_builder_worker.sha256)" \
  --arg validator01 "$(cat boundary-validator01.sha256)" \
  --arg validator02 "$(cat boundary-validator02.sha256)" \
  --arg validator03 "$(cat boundary-validator03.sha256)" \
  '{
    foundation: $foundation,
    ami_builder: $ami_builder,
    observer: $observer,
    remediation: $remediation,
    image_builder_worker: $image_builder_worker,
    validator01: $validator01,
    validator02: $validator02,
    validator03: $validator03
  }' >external-boundary-policy-readback-sha256.json
EXTERNAL_BOUNDARY_POLICY_READBACK_SHA256="$(
  jq -c . external-boundary-policy-readback-sha256.json
)"
EXTERNAL_BOUNDARY_POLICY_READBACK_OBJECT_SHA256="$(
  jq -cSj . external-boundary-policy-readback-sha256.json |
    sha256sum |
    cut -d" " -f1
)"
```

AWS CLI returns the URL-decoded policy `Document`; do not hash the enclosing
version metadata. Include the eight-name object hash in both phase manifests.

## 2. Read exact runtime LockIDs and KMS grants

Foundation may mutate only the runtime state LockID and its `-md5` checksum
item. It may not mutate the bootstrap-state lock. The checksum row is stable;
the lock row exists only while Terraform intentionally holds the lock. A scan
that expects two rows while no operation is active is invalid evidence. Values
must come from a controlled live lock observation plus CloudTrail; do not
construct them from memory.

```bash
set -euo pipefail
STATE_BUCKET_NAME=\
junca-social-ecosystem-chain-tfstate-595710543956-us-east-1
LOCK_TABLE_NAME=junca-social-ecosystem-chain-testnet-lock

RUNTIME_STATE_KEY="${STATE_BUCKET_NAME}/public-testnet/terraform.tfstate"
RUNTIME_CHECKSUM_KEY="${RUNTIME_STATE_KEY}-md5"

aws dynamodb get-item \
  --table-name "$LOCK_TABLE_NAME" \
  --consistent-read \
  --key "$(jq -cn --arg key "$RUNTIME_CHECKSUM_KEY" \
    '{LockID:{S:$key}}')" \
  >runtime-checksum-row.json
jq -e --arg key "$RUNTIME_CHECKSUM_KEY" \
  '.Item.LockID.S == $key' runtime-checksum-row.json

# With the repository frozen, start the reviewed no-apply Terraform lock probe.
# While that process deliberately holds the runtime backend lock, capture:
aws dynamodb get-item \
  --table-name "$LOCK_TABLE_NAME" \
  --consistent-read \
  --key "$(jq -cn --arg key "$RUNTIME_STATE_KEY" \
    '{LockID:{S:$key}}')" \
  >runtime-lock-row.json
jq -e --arg key "$RUNTIME_STATE_KEY" \
  '.Item.LockID.S == $key and (.Item.Info.S | length > 0)' \
  runtime-lock-row.json

# Stop the probe normally and prove DeleteItem for the same key in CloudTrail.
# Never synthesize the row with aws dynamodb put-item.
jq -cnS \
  --arg lock "$(jq -r .Item.LockID.S runtime-lock-row.json)" \
  --arg checksum "$(jq -r .Item.LockID.S runtime-checksum-row.json)" \
  '[$lock, $checksum] | sort' \
  >runtime-state-lock-ids.json
RUNTIME_STATE_LOCK_IDS="$(
  jq -c . runtime-state-lock-ids.json
)"
RUNTIME_STATE_LOCK_READBACK_SHA256="$(
  jq -cSj . runtime-state-lock-ids.json |
    sha256sum |
    cut -d" " -f1
)"
```

The independent remediation role, not Security Bootstrap, externally provisions
the state key, three signer keys, and four aliases. Import them at the exact
indexed Terraform addresses before stage:

- `aws_kms_key.terraform_state`
- `aws_kms_alias.terraform_state`
- `aws_kms_key.validator_signer[0..2]`
- `aws_kms_alias.validator_signer[0..2]`

Resolve every alias through live KMS, require the exact purpose metadata and
tag set, and bind the alias-to-KeyId/KeyArn map into both phase plans:

```bash
declare -A CANONICAL_KMS_ALIASES=(
  [state]=alias/junca-social-ecosystem-chain-testnet-state
  [validator01]=alias/junca-social-ecosystem-chain-testnet-validator-01
  [validator02]=alias/junca-social-ecosystem-chain-testnet-validator-02
  [validator03]=alias/junca-social-ecosystem-chain-testnet-validator-03
)

for key_name in state validator01 validator02 validator03
do
  aws kms describe-key \
    --key-id "${CANONICAL_KMS_ALIASES[$key_name]}" \
    >"kms-alias-${key_name}.json"
  key_arn="$(jq -er .KeyMetadata.Arn "kms-alias-${key_name}.json")"
  aws kms list-resource-tags \
    --key-id "$key_arn" \
    >"kms-alias-${key_name}-tags.json"
done

jq -e '
  .KeyMetadata |
  .KeyManager == "CUSTOMER" and
  .Origin == "AWS_KMS" and
  .KeyUsage == "ENCRYPT_DECRYPT" and
  .KeySpec == "SYMMETRIC_DEFAULT" and
  .MultiRegion == false
' kms-alias-state.json
jq -e '
  (.Tags | map({key: .TagKey, value: .TagValue}) | from_entries) == {
    Governance: "JAIOS Institutional Governance",
    ManagedBy: "TerraformBootstrap",
    MonetaryUse: "None",
    Network: "Public Testnet",
    Project: "JUNCA Social Ecosystem Chain",
    Purpose: "TerraformState"
  }
' kms-alias-state-tags.json

for key_name in validator01 validator02 validator03
do
  validator_id="${key_name#validator}"
  jq -e '
    .KeyMetadata |
    .KeyManager == "CUSTOMER" and
    .Origin == "AWS_KMS" and
    .KeyUsage == "SIGN_VERIFY" and
    .KeySpec == "ECC_SECG_P256K1" and
    .MultiRegion == false
  ' "kms-alias-${key_name}.json"
  jq -e --arg validator "$validator_id" '
    (.Tags | map({key: .TagKey, value: .TagValue}) | from_entries) == {
      Governance: "JAIOS Institutional Governance",
      ManagedBy: "TerraformBootstrap",
      MonetaryUse: "None",
      Network: "Public Testnet",
      Project: "JUNCA Social Ecosystem Chain",
      Purpose: "ValidatorSigner",
      Validator: $validator
    }
  ' "kms-alias-${key_name}-tags.json"
done

jq -nS \
  --slurpfile state kms-alias-state.json \
  --slurpfile validator01 kms-alias-validator01.json \
  --slurpfile validator02 kms-alias-validator02.json \
  --slurpfile validator03 kms-alias-validator03.json '
  {
    "alias/junca-social-ecosystem-chain-testnet-state": {
      key_id: $state[0].KeyMetadata.KeyId,
      key_arn: $state[0].KeyMetadata.Arn
    },
    "alias/junca-social-ecosystem-chain-testnet-validator-01": {
      key_id: $validator01[0].KeyMetadata.KeyId,
      key_arn: $validator01[0].KeyMetadata.Arn
    },
    "alias/junca-social-ecosystem-chain-testnet-validator-02": {
      key_id: $validator02[0].KeyMetadata.KeyId,
      key_arn: $validator02[0].KeyMetadata.Arn
    },
    "alias/junca-social-ecosystem-chain-testnet-validator-03": {
      key_id: $validator03[0].KeyMetadata.KeyId,
      key_arn: $validator03[0].KeyMetadata.Arn
    }
  }
' >canonical-kms-alias-target-readback.json
CANONICAL_KMS_ALIAS_TARGET_READBACK_SHA256="$(
  jq -cSj . canonical-kms-alias-target-readback.json |
    sha256sum |
    cut -d" " -f1
)"

STATE_KEY_ARN="$(jq -er .KeyMetadata.Arn kms-alias-state.json)"
VALIDATOR01_KEY_ARN="$(jq -er .KeyMetadata.Arn kms-alias-validator01.json)"
VALIDATOR02_KEY_ARN="$(jq -er .KeyMetadata.Arn kms-alias-validator02.json)"
VALIDATOR03_KEY_ARN="$(jq -er .KeyMetadata.Arn kms-alias-validator03.json)"
jq -cSj \
  --arg state "$STATE_KEY_ARN" \
  --arg validator01 "$VALIDATOR01_KEY_ARN" \
  --arg validator02 "$VALIDATOR02_KEY_ARN" \
  --arg validator03 "$VALIDATOR03_KEY_ARN" '
  walk(
    if type == "string" then
      if . == "${state_key_arn}" then $state
      elif . == "${validator01_key_arn}" then $validator01
      elif . == "${validator02_key_arn}" then $validator02
      elif . == "${validator03_key_arn}" then $validator03
      else .
      end
    else .
    end
  )
' infra/aws/bootstrap/policies/security-remediation-boundary.json \
  >security-remediation-boundary.rendered.json
test "$(wc -c <security-remediation-boundary.rendered.json)" -le 6144
test "$(
  sha256sum security-remediation-boundary.rendered.json | cut -d" " -f1
)" = "$(
  sha256sum boundary-remediation.canonical.json | cut -d" " -f1
)"
```

The resulting plan must show zero key/alias/policy/rotation changes. Security
Bootstrap retains readback, exact state data use through S3, and the one
DynamoDB grant path; it cannot create, repair, disable, schedule deletion,
re-policy, or sign with a key. Each key policy directly grants Security
Bootstrap only `DescribeKey`, `GetKeyPolicy`, `GetKeyRotationStatus`,
`ListGrants`, `ListKeyPolicies`, and `ListResourceTags`. Canonicalize and hash
all four live policies and require equality with the configured policy digest.
Any KMS create/update/delete action or digest mismatch blocks stage.

For the state key and all three signer keys, archive `get-key-policy`,
`list-grants`, and `list-retirable-grants`. Signer grants must be empty.
Unexpected grants must be revoked by the independent remediation role, which
must then return to its disabled state and be read back as absent. State-key
grants require an exact reviewed allowlist bound to the
canonical DynamoDB table service use. The only grant-creation permission is
the state key alias with `kms:GrantIsForAWSResource=true`,
`kms:CallerAccount=595710543956`, and
`kms:ViaService=dynamodb.us-east-1.amazonaws.com`. The state alias must exist
and target the exact state key before DynamoDB reconciliation; Terraform also
orders the table after the alias. Call `list-retirable-grants` only with the
exact reviewed retiring-principal ARN. Any unclassified grant blocks the
migration.

The post-apply signer key policy must permit Security Bootstrap remediation,
permit each validator to sign only its own key, permit quorum verification,
permit Foundation/Observer describe-only evidence, and explicitly deny OIDC
automation key administration, grants, deletion, and signing.

Archive and compare the state bucket's live policy, versioning, public-access
block, ownership controls, and default encryption. The policy must deny
non-TLS access, principals outside the exact Security Bootstrap/remediation/
Foundation/Observer allowlist, unexpected object keys, non-KMS writes, a KMS
key other than the exact state key, non-Security-Bootstrap deletion, and
unexpected list prefixes. The remediation role has control-plane repair only
and is denied object data-plane access. The KMS state-key policy must bind S3
use to `s3.us-east-1.amazonaws.com` and the two exact object encryption
contexts (`bootstrap.tfstate` and `terraform.tfstate`) rather than a bucket-wide
context. S3 bucket keys remain disabled so the per-object context is preserved.

## 3. Move validator IAM ownership without deleting cloud identities

Validator roles, inline signer policies, and instance profiles move from the
runtime state to the Security Bootstrap state. Runtime Terraform now uses data
sources. SSM Core is deliberately detached from signer nodes until the fixed
document/controller design is implemented. This is otherwise a state-only
ownership migration; cloud role/profile deletion or replacement is forbidden.

Pull and hash both remote states first. Inspect all nine retained source addresses
with `terraform state show`. Then, under the AWS freeze and Security Bootstrap
session, remove only those addresses from runtime state and import the same
live resources into the identical bootstrap addresses:

- `aws_iam_role.validator[0..2]`
- `aws_iam_role_policy.validator_signer_boundary[0..2]`
- `aws_iam_instance_profile.validator[0..2]`

After every state operation, compare role IDs, ARNs, trust JSON, policy hashes,
profile membership, and attached policy ARNs to the pre-migration evidence.
Any AWS delete/update event is a hard failure.

Before stage plan, read `GetInstanceProfile`, `GetRole`,
`GetRolePolicy`, `ListRolePolicies`, and `ListAttachedRolePolicies` for each
index. Require profile-N to contain only role-N, the exact EC2-only trust,
the exact index-aligned permissions boundary, exactly one inline signer policy
whose canonical document hash references only signer key N for `kms:Sign`,
and an exact inventory of attached policies. The only tolerated pre-stage
attachment is SSM Core and the stage plan must explicitly detach it. Post-stage
attached policies must be empty. Any other extra policy, cross-index key, or a
second profile role blocks the stage evidence digest.

Before moving permissions-boundary state, run:

```bash
terraform -chdir=infra/aws/bootstrap state list |
  grep -E '^aws_iam_policy\.validator_permissions_boundary($|\\[)'
```

If no result exists, the independent remediation workflow must externally
pre-create, bind, read back, and import the three indexed policies; Security
Bootstrap is explicitly denied boundary changes. If indexed resources already
exist, import/reconcile each index without replacement. If a legacy singular
resource exists, snapshot and remove only its state address. When its live
policy name equals the canonical `Validator01Boundary`, import it as index
zero; otherwise retain it untouched while remediation creates the three new
policies. Bind and verify all three roles before retiring any legacy policy.
No plan containing boundary or validator IAM creation, deletion, replacement,
or boundary mutation may apply.

## 4. Review the future OIDC contract without changing the repository

The exact template is:

```json
{
  "use_default": false,
  "use_immutable_subject": true,
  "include_claim_keys": [
    "repo",
    "context",
    "workflow_ref",
    "runner_environment"
  ]
}
```

`use_immutable_subject=true` is part of the desired PUT contract. The GET
schema is projected to `use_default` and `include_claim_keys`; if GitHub also
returns `use_immutable_subject`, it must be exactly `true`. The authoritative
live effect is proven later by seven JWTs containing the immutable numeric IDs
and accepted by the mapped AWS STS roles.

This section is review material only. Do not create an expected-template file,
PUT the repository template, or request a new-format token yet. The executable
activation procedure appears only after stage apply/readback in section 5.2.

Run `scripts/junca_oidc_claim_attestation.py` in each of the two Foundation,
one AMI Builder, and four Observer workflows. The token itself must never be
stored. From the seven verified evidence files, build this exact aggregate in
this exact array order:

```json
{
  "foundation": [
    "repo:JAIOS-Governance@308604370/junca-social-ecosystem-chain@1310568313:environment:public-testnet:workflow_ref:JAIOS-Governance/junca-social-ecosystem-chain/.github/workflows/junca-validator-foundation-release.yml@refs/heads/main:runner_environment:github-hosted",
    "repo:JAIOS-Governance@308604370/junca-social-ecosystem-chain@1310568313:environment:public-testnet:workflow_ref:JAIOS-Governance/junca-social-ecosystem-chain/.github/workflows/junca-public-testnet-release.yml@refs/heads/main:runner_environment:github-hosted"
  ],
  "ami_builder": [
    "repo:JAIOS-Governance@308604370/junca-social-ecosystem-chain@1310568313:environment:public-testnet:workflow_ref:JAIOS-Governance/junca-social-ecosystem-chain/.github/workflows/junca-validator-ami-build.yml@refs/heads/main:runner_environment:github-hosted"
  ],
  "observer": [
    "repo:JAIOS-Governance@308604370/junca-social-ecosystem-chain@1310568313:environment:public-testnet:workflow_ref:JAIOS-Governance/junca-social-ecosystem-chain/.github/workflows/junca-runtime-release-evidence-collector-v2.yml@refs/heads/main:runner_environment:github-hosted",
    "repo:JAIOS-Governance@308604370/junca-social-ecosystem-chain@1310568313:environment:public-testnet:workflow_ref:JAIOS-Governance/junca-social-ecosystem-chain/.github/workflows/junca-public-testnet-live-soak.yml@refs/heads/main:runner_environment:github-hosted",
    "repo:JAIOS-Governance@308604370/junca-social-ecosystem-chain@1310568313:environment:public-testnet:workflow_ref:JAIOS-Governance/junca-social-ecosystem-chain/.github/workflows/junca-social-ecosystem-chain-aws-binding-readback.yml@refs/heads/main:runner_environment:github-hosted",
    "repo:JAIOS-Governance@308604370/junca-social-ecosystem-chain@1310568313:environment:public-testnet:workflow_ref:JAIOS-Governance/junca-social-ecosystem-chain/.github/workflows/junca-social-ecosystem-chain-aws-readback.yml@refs/heads/main:runner_environment:github-hosted"
  ]
}
```

Validate each evidence file has
`schema_version=junca-github-oidc-claim-attestation/v2`,
`state=EXACT_TOKEN_ACCEPTED_BY_AWS_STS`, `sts_token_accepted=true`,
`token_persisted=false`, `sts_credentials_persisted=false`, the exact claim
keys, exact `sub`, `aud`, issuer, workflow ref, main ref, immutable IDs, and
workflow SHA. A locally decoded or merely JWKS-verified token is insufficient:
the exact token must be accepted by the mapped AWS STS role. Canonical hashes
must use newline-free sorted JSON because Terraform hashes `jsonencode(...)`
without a trailing newline. Finalize consumes the seven redacted v2 projections
directly, checks their artifact hashes, run IDs, exact assumed-role ARNs, and
static contract, then binds the full dynamic evidence list into plan output.

The seven JSEC attestations close only this module's role trust. The current
repository-wide matrix contains 27 AWS credential call sites. Every one must
have an exact future subject, mapped role, owner, and accepted live STS token
before the global freeze can lift. Until that full matrix is complete, global
OIDC cutover remains `BLOCKED`; JSEC's seven successful tokens do not authorize
repository-wide resumption.

## 5. Execute two separately reviewed saved plans

The external remediation prerequisite must first pre-create and bind every
protected role to the exact one-to-one boundary matrix, provision/import both
Security Bootstrap policies, and provision/import the KMS keys and aliases.
Security Bootstrap cannot create a role, alter a permissions boundary, mutate
its own policies, or repair KMS administration. Import all pre-existing
objects into bootstrap state before planning. A create action for any protected
role, boundary, key, or alias is therefore a rejection, not a recovery step.

Initialize the backend with all exact controls. Omitting the lock table or KMS
key, or accepting cached backend settings, is prohibited:

```bash
terraform -chdir=infra/aws/bootstrap init -input=false -reconfigure \
  -backend-config="bucket=$STATE_BUCKET_NAME" \
  -backend-config="key=public-testnet/bootstrap.tfstate" \
  -backend-config="region=$AWS_REGION" \
  -backend-config="dynamodb_table=$LOCK_TABLE_NAME" \
  -backend-config="encrypt=true" \
  -backend-config="kms_key_id=$STATE_KMS_KEY_ARN"
```

### 5.1 Stage: future-only trust, denies, and residue purge

Build `bootstrap-stage-evidence-manifest.json` from the cutover commit, full
27-call inventory/matrix, old template digest, Security Bootstrap Core/State
documents, disabled remediation role, exact role-boundary matrix, exact
seven-role/four-profile protected-prefix inventory, LockID evidence, state
snapshots, exact KMS alias-target map, bucket/KMS policies and grants, and
validator IAM readbacks. The
template has not changed yet, so stage uses all-zero placeholders for the four
phase-specific OIDC desired-payload, GET-projection, provider, and live-token
digests, and the live v2 attestation list must remain empty. Terraform skips
only those four digest comparisons in `stage`; every other gate remains active.

```bash
python scripts/junca_public_testnet_cloud_role_policy.py \
  --policy config/junca_public_testnet_cloud_role_policy.json \
  --workflows-dir .github/workflows
REPO_GLOBAL_OIDC_STAGE_MATRIX_READBACK_SHA256="$(
  jq -cSj .repo_global_oidc_cutover_gate \
    config/junca_public_testnet_cloud_role_policy.json |
    sha256sum |
    cut -d" " -f1
)"

STAGE_EVIDENCE_MANIFEST_SHA256="$(
  jq -cSj . bootstrap-stage-evidence-manifest.json |
    sha256sum |
    cut -d" " -f1
)"
ZERO_SHA256="$(
  printf '%064d' 0
)"

COMMON_VARS=(
  -var="aws_account_id=$AWS_ACCOUNT_ID"
  -var="state_bucket_name=$STATE_BUCKET_NAME"
  -var="github_oidc_thumbprint=$GITHUB_OIDC_THUMBPRINT"
  -var="security_bootstrap_principal_arn=$SECURITY_BOOTSTRAP_PRINCIPAL_ARN"
  -var="security_bootstrap_trusted_admin_principal_arn=$SECURITY_BOOTSTRAP_TRUSTED_ADMIN_PRINCIPAL_ARN"
  -var="security_bootstrap_external_id_sha256=$SECURITY_BOOTSTRAP_EXTERNAL_ID_SHA256"
  -var="security_bootstrap_policy_readback_sha256=$SECURITY_BOOTSTRAP_POLICY_READBACK_SHA256"
  -var="security_bootstrap_core_policy_document_sha256=$SECURITY_BOOTSTRAP_CORE_POLICY_DOCUMENT_SHA256"
  -var="security_bootstrap_state_policy_document_sha256=$SECURITY_BOOTSTRAP_STATE_POLICY_DOCUMENT_SHA256"
  -var="protected_role_boundary_readback_sha256=$PROTECTED_ROLE_BOUNDARY_READBACK_SHA256"
  -var="protected_iam_prefix_inventory_readback_sha256=$PROTECTED_IAM_PREFIX_INVENTORY_READBACK_SHA256"
  -var="external_boundary_policy_readback_sha256=$EXTERNAL_BOUNDARY_POLICY_READBACK_SHA256"
  -var="security_remediation_readback_sha256=$SECURITY_REMEDIATION_READBACK_SHA256"
  -var="state_kms_key_policy_readback_sha256=$STATE_KMS_KEY_POLICY_READBACK_SHA256"
  -var="validator_signer_key_policy_readback_sha256=$VALIDATOR_SIGNER_KEY_POLICY_READBACK_SHA256"
  -var="canonical_kms_alias_target_readback_sha256=$CANONICAL_KMS_ALIAS_TARGET_READBACK_SHA256"
  -var="runtime_state_lock_ids=$RUNTIME_STATE_LOCK_IDS"
  -var="runtime_state_lock_readback_sha256=$RUNTIME_STATE_LOCK_READBACK_SHA256"
)

terraform -chdir=infra/aws/bootstrap plan -input=false \
  "${COMMON_VARS[@]}" \
  -var="iam_migration_phase=stage" \
  -var="bootstrap_evidence_manifest_sha256=$STAGE_EVIDENCE_MANIFEST_SHA256" \
  -var="github_oidc_subject_template_sha256=$ZERO_SHA256" \
  -var="github_oidc_subject_template_projection_readback_sha256=$ZERO_SHA256" \
  -var="github_oidc_provider_readback_sha256=$ZERO_SHA256" \
  -var="github_oidc_subject_readback_sha256=$ZERO_SHA256" \
  -var="repo_global_oidc_stage_matrix_readback_sha256=$REPO_GLOBAL_OIDC_STAGE_MATRIX_READBACK_SHA256" \
  -var="repo_global_oidc_activation_readback_sha256=$ZERO_SHA256" \
  -out=iam-stage.tfplan
terraform -chdir=infra/aws/bootstrap show -json iam-stage.tfplan \
  >iam-stage-plan.json
sha256sum iam-stage.tfplan >iam-stage.tfplan.sha256
```

Reject incomplete/deferred/errored plans and any deletion/replacement of roles,
profiles, keys, boundaries, provider, bucket, or table. Stage must atomically:

- replace Foundation's legacy environment-only trust with future exact trust;
- create no legacy trust on AMI Builder or Observer;
- install all explicit IAM/KMS/runtime denies;
- remove every OIDC provider audience except `sts.amazonaws.com` and retain
  only the reviewed thumbprint;
- detach SSM Core from all three validator signer roles;
- enforce every exclusive inline/attached allowlist and purge residue.

Specifically require purge of `PublicTestnetFoundationBootstrap`,
`JAIOSInstitutionalApexCloudFront`, `SitesCustomDomainsDnsWriteRecovery`, and
`PublicTestnetInputReadback`. Reject any effective Foundation permission for
`kms:CreateGrant`, CloudFront, non-JSEC DNS/ACM, `ec2:RunInstances`,
`iam:PassRole`, or `ssm:SendCommand`.

After the section 6 identity/evidence recheck, apply only the stage plan and
complete an exact role/policy/provider/KMS readback before proceeding:

```bash
terraform -chdir=infra/aws/bootstrap apply -input=false iam-stage.tfplan
```

### 5.2 Prepared gate, template activation, and live STS evidence

External owners now stage future exact trust or reviewed retirement for every
remaining baseline call and update the signed preparation evidence. Only after
the prepared validator exits zero may the repository-global template change:

```bash
python scripts/junca_public_testnet_cloud_role_policy.py \
  --policy config/junca_public_testnet_cloud_role_policy.json \
  --workflows-dir .github/workflows \
  --require-repo-global-oidc-cutover-prepared

cat >oidc-template-expected.json <<'JSON'
{
  "use_default": false,
  "use_immutable_subject": true,
  "include_claim_keys": [
    "repo",
    "context",
    "workflow_ref",
    "runner_environment"
  ]
}
JSON
gh api --method PUT \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  "repos/${JSEC_REPOSITORY}/actions/oidc/customization/sub" \
  --input oidc-template-expected.json \
  >oidc-template-put-response.json
gh api \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  "repos/${JSEC_REPOSITORY}/actions/oidc/customization/sub" \
  >oidc-template-readback.json
jq -e --slurpfile expected oidc-template-expected.json \
  '
    {
      use_default,
      include_claim_keys
    } == (
      $expected[0] | {
        use_default,
        include_claim_keys
      }
    ) and
    (
      (has("use_immutable_subject") | not) or
      .use_immutable_subject == true
    )
  ' oidc-template-readback.json
GITHUB_OIDC_SUBJECT_TEMPLATE_SHA256="$(
  jq -cSj . oidc-template-expected.json |
    sha256sum |
    cut -d" " -f1
)"
jq -cS '{
  include_claim_keys,
  use_default
}' oidc-template-readback.json >oidc-template-projection-readback.json
GITHUB_OIDC_SUBJECT_TEMPLATE_PROJECTION_READBACK_SHA256="$(
  jq -cSj . oidc-template-projection-readback.json |
    sha256sum |
    cut -d" " -f1
)"

aws iam get-open-id-connect-provider \
  --open-id-connect-provider-arn \
  arn:aws:iam::595710543956:oidc-provider/token.actions.githubusercontent.com \
  >oidc-provider-readback.raw.json
jq -cS '{
  url: ("https://" + .Url),
  client_id_list: (.ClientIDList | sort),
  thumbprint_list: (.ThumbprintList | sort)
}' oidc-provider-readback.raw.json >oidc-provider-readback.json
jq -e --arg thumbprint "$GITHUB_OIDC_THUMBPRINT" '
  . == {
    url: "https://token.actions.githubusercontent.com",
    client_id_list: ["sts.amazonaws.com"],
    thumbprint_list: [$thumbprint]
  }
' oidc-provider-readback.json
GITHUB_OIDC_PROVIDER_READBACK_SHA256="$(
  jq -cSj . oidc-provider-readback.json |
    sha256sum |
    cut -d" " -f1
)"
```

Run the v2 attestation described in section 4 for the seven JSEC calls and for
every active call in the 27-call baseline. GET does not authoritatively prove
that GitHub applied `use_immutable_subject` when the response omits that field.
The final live proof is therefore all seven freshly issued JWT `sub` claims
containing numeric owner ID `308604370` and repository ID `1310568313`, with
each same JWT accepted by its mapped AWS STS role. A projected GET, locally
decoded JWT, or JWKS-only verification is insufficient. After exact-token AWS
STS acceptance or reviewed retirement is complete, extract each JSEC v2 JSON
artifact and its generated `.sha256` companion without renaming them under
`oidc-attestations/<workflow-filename>/`.

The following local projection checks shape, internal consistency, and local
file digests only. It does **not** prove that the files came from the named
GitHub workflow run or artifact. Do not use its output to authorize finalize.
It remains useful as diagnostic input while an independent verifier is built
to fetch the exact run and artifact through the GitHub API, bind the immutable
artifact ID/run attempt/head SHA/workflow file, and reject unprotected
repository state. This Terraform revision accepts only
`BLOCKED_PENDING_INDEPENDENT_GITHUB_API_READBACK` and deliberately makes every
finalize plan fail before mutation.

```bash
set -euo pipefail
OIDC_ATTESTATION_DIR=oidc-attestations
declare -A JSEC_OIDC_ATTESTATION_ROLE_ARNS=(
  [junca-public-testnet-live-soak.yml]=arn:aws:iam::595710543956:role/JuncaChainPublicTestnetObserver
  [junca-public-testnet-release.yml]=arn:aws:iam::595710543956:role/JuncaChainPublicTestnetDeployment
  [junca-runtime-release-evidence-collector-v2.yml]=arn:aws:iam::595710543956:role/JuncaChainPublicTestnetObserver
  [junca-social-ecosystem-chain-aws-binding-readback.yml]=arn:aws:iam::595710543956:role/JuncaChainPublicTestnetObserver
  [junca-social-ecosystem-chain-aws-readback.yml]=arn:aws:iam::595710543956:role/JuncaChainPublicTestnetObserver
  [junca-validator-ami-build.yml]=arn:aws:iam::595710543956:role/JuncaChainPublicTestnetAmiBuilder
  [junca-validator-foundation-release.yml]=arn:aws:iam::595710543956:role/JuncaChainPublicTestnetDeployment
)
JSEC_OIDC_ATTESTATION_WORKFLOWS=(
  junca-public-testnet-live-soak.yml
  junca-public-testnet-release.yml
  junca-runtime-release-evidence-collector-v2.yml
  junca-social-ecosystem-chain-aws-binding-readback.yml
  junca-social-ecosystem-chain-aws-readback.yml
  junca-validator-ami-build.yml
  junca-validator-foundation-release.yml
)

for workflow_name in "${JSEC_OIDC_ATTESTATION_WORKFLOWS[@]}"
do
  workflow_path=".github/workflows/${workflow_name}"
  workflow_evidence_dir="${OIDC_ATTESTATION_DIR}/${workflow_name}"
  evidence="${workflow_evidence_dir}/oidc-claim-attestation.json"
  role_arn="${JSEC_OIDC_ATTESTATION_ROLE_ARNS[$workflow_name]}"
  test -f "$evidence"
  test -f "${evidence}.sha256"
  (
    cd "$workflow_evidence_dir"
    sha256sum --check oidc-claim-attestation.json.sha256
  ) >/dev/null

  attestation_sha256="$(sha256sum "$evidence" | cut -d" " -f1)"
  run_id="$(
    jq -er '
      .claims.run_id |
      select(type == "string" and test("^[1-9][0-9]{0,19}$"))
    ' "$evidence"
  )"
  role_name="${role_arn##*/}"
  expected_workflow_ref=\
"JAIOS-Governance/junca-social-ecosystem-chain/${workflow_path}@refs/heads/main"
  expected_sub=\
"repo:JAIOS-Governance@308604370/junca-social-ecosystem-chain@1310568313:"\
"environment:public-testnet:workflow_ref:${expected_workflow_ref}:"\
"runner_environment:github-hosted"
  expected_sts_arn=\
"arn:aws:sts::${AWS_ACCOUNT_ID}:assumed-role/${role_name}/"\
"jsec-oidc-attest-${run_id}"

  jq -e \
    --arg expected_sts_arn "$expected_sts_arn" \
    --arg expected_sub "$expected_sub" \
    --arg expected_workflow_ref "$expected_workflow_ref" \
    --arg run_id "$run_id" '
    .schema_version == "junca-github-oidc-claim-attestation/v2" and
    .state == "EXACT_TOKEN_ACCEPTED_BY_AWS_STS" and
    .subject_claim_keys == [
      "repo",
      "context",
      "workflow_ref",
      "runner_environment"
    ] and
    .claims.iss == "https://token.actions.githubusercontent.com" and
    .claims.aud == "sts.amazonaws.com" and
    .claims.sub == $expected_sub and
    .claims.repository ==
      "JAIOS-Governance/junca-social-ecosystem-chain" and
    .claims.repository_owner_id == "308604370" and
    .claims.repository_id == "1310568313" and
    .claims.environment == "public-testnet" and
    .claims.ref == "refs/heads/main" and
    .claims.ref_type == "branch" and
    .claims.repository_visibility == "public" and
    .claims.runner_environment == "github-hosted" and
    .claims.run_id == $run_id and
    .claims.workflow_ref == $expected_workflow_ref and
    (.claims.workflow_sha | type) == "string" and
    (.claims.workflow_sha | test("^[0-9a-f]{40}$")) and
    (.claims.event_name == "workflow_dispatch" or
      .claims.event_name == "workflow_run") and
    (.claims | has("job_workflow_ref") | not) and
    (.claims.iat | type) == "number" and
    (.claims.nbf | type) == "number" and
    (.claims.exp | type) == "number" and
    .claims.exp > .claims.iat and
    .claims.exp > .claims.nbf and
    .sts_assumed_role_arn == $expected_sts_arn and
    .sts_token_accepted == true and
    .token_persisted == false and
    .sts_credentials_persisted == false and
    .mainnet_changed == false and
    .assets_moved == false and
    .bridge_activated == false
  ' "$evidence" >/dev/null

  jq -cS \
    --arg attestation_sha256 "$attestation_sha256" \
    --arg role_arn "$role_arn" \
    --arg workflow_path "$workflow_path" '{
      assets_moved,
      attestation_sha256: $attestation_sha256,
      audience: .claims.aud,
      bridge_activated,
      event_name: .claims.event_name,
      expires_at: .claims.exp,
      issued_at: .claims.iat,
      issuer: .claims.iss,
      mainnet_changed,
      not_before: .claims.nbf,
      repository: .claims.repository,
      repository_id: .claims.repository_id,
      repository_owner_id: .claims.repository_owner_id,
      role_arn: $role_arn,
      run_id: .claims.run_id,
      schema_version,
      state,
      sts_assumed_role_arn,
      sts_credentials_persisted,
      sts_token_accepted,
      subject_claim_keys,
      sub: .claims.sub,
      token_persisted,
      workflow_path: $workflow_path,
      workflow_ref: .claims.workflow_ref,
      workflow_sha: .claims.workflow_sha
    }' "$evidence"
done |
  jq -csS 'sort_by(.workflow_path)' \
    >oidc-live-sts-attestation-readback.json

jq -e '
  length == 7 and
  ([.[].workflow_path] | unique | length) == 7 and
  ([.[].run_id] | unique | length) == 7 and
  ([.[].attestation_sha256] | unique | length) == 7
' oidc-live-sts-attestation-readback.json

jq -nS \
  --slurpfile evidence oidc-live-sts-attestation-readback.json '
  def sub_for($path):
    first($evidence[0][] | select(.workflow_path == $path) | .sub);
  {
    foundation: [
      sub_for(
        ".github/workflows/junca-validator-foundation-release.yml"
      ),
      sub_for(".github/workflows/junca-public-testnet-release.yml")
    ],
    ami_builder: [
      sub_for(".github/workflows/junca-validator-ami-build.yml")
    ],
    observer: [
      sub_for(
        ".github/workflows/" +
        "junca-runtime-release-evidence-collector-v2.yml"
      ),
      sub_for(".github/workflows/junca-public-testnet-live-soak.yml"),
      sub_for(
        ".github/workflows/" +
        "junca-social-ecosystem-chain-aws-binding-readback.yml"
      ),
      sub_for(
        ".github/workflows/" +
        "junca-social-ecosystem-chain-aws-readback.yml"
      )
    ]
  }
' >oidc-subject-readback.json

jq -cS 'map({
  assets_moved,
  audience,
  bridge_activated,
  issuer,
  mainnet_changed,
  repository,
  repository_id,
  repository_owner_id,
  role_arn,
  schema_version,
  state,
  sts_credentials_persisted,
  sts_token_accepted,
  subject_claim_keys,
  sub,
  token_persisted,
  workflow_path,
  workflow_ref
})' oidc-live-sts-attestation-readback.json \
  >oidc-live-sts-attestation-static-projection.json
jq -nS \
  --slurpfile attestations \
    oidc-live-sts-attestation-static-projection.json \
  --slurpfile subjects oidc-subject-readback.json '{
    attestations: $attestations[0],
    subjects: $subjects[0]
  }' >oidc-live-sts-readback-contract.json
GITHUB_OIDC_SUBJECT_READBACK_SHA256="$(
  jq -cSj . oidc-live-sts-readback-contract.json |
    sha256sum |
    cut -d" " -f1
)"
jq -nS \
  --slurpfile attestations oidc-live-sts-attestation-readback.json '{
    github_oidc_live_sts_attestation_readback: $attestations[0]
  }' >oidc-live-sts-finalize.tfvars.json
sha256sum \
  oidc-live-sts-attestation-readback.json \
  oidc-live-sts-readback-contract.json \
  oidc-live-sts-finalize.tfvars.json \
  >oidc-live-sts-evidence.sha256
```

### 5.3 Finalize: hard-blocked pending origin verification

Build `bootstrap-finalize-evidence-manifest.json` containing everything from
stage plus the strict template readback, all seven v2 artifact digests, the
dynamic STS readback list, the static seven-token contract, all 27 matrix
attestations, and post-stage exclusive-policy/KMS/validator readbacks. Archive
that material as diagnostic evidence only.

Do not create `iam-finalize.tfplan`. In this revision,
`github_oidc_attestation_origin_verification_state` is validation-pinned to
`BLOCKED_PENDING_INDEPENDENT_GITHUB_API_READBACK`, while the finalize
precondition requires
`VERIFIED_BY_INDEPENDENT_GITHUB_API_ARTIFACT_READBACK`. The two values are
deliberately impossible to reconcile. A finalize plan must fail with the
dedicated artifact-origin error even when all seven locally supplied objects
and digests are internally consistent.

Enabling finalize is a future reviewed code change. It requires tests for a
new independent verifier that retrieves the exact GitHub artifact IDs and
archives through the API, binds each to its run attempt/head SHA/workflow
definition, verifies repository/branch/environment protections and reviewer
approval, and then re-reads the resulting immutable record. Do not replace
that requirement with another caller-supplied boolean, object, digest, or
shell-generated projection.

## 6. Reverify immediately before the stage saved-plan apply

Do not rely on the identity that created a plan. Immediately before stage—and
again for any future, separately reviewed finalize implementation:

1. Re-run STS caller/session-issuer and session-tag checks.
2. Re-read both Security Bootstrap documents and exact attachment lists.
3. Re-read the disabled remediation role, exact role-boundary matrix, and
   exact seven-role/four-profile inventory with one-to-one profile membership.
4. Re-read the exact four-alias KMS target map and recompute every evidence
   digest plus the phase-specific manifest digest.
5. Verify `iam_migration_phase` and
   `bootstrap_evidence_manifest_sha256` in plan JSON.
6. Verify the saved-plan SHA-256 equals the independently reviewed value.
7. Verify the repository AWS/OIDC freeze is still active.

Only the exact stage plan from section 5.1 may be applied by this revision.
There is no valid finalize plan or finalize apply command. Finalize remains
blocked after stage, template mutation, local projection, and STS matrix until
the independent GitHub API artifact-origin verifier and fresh approval are
implemented, reviewed, and merged.

## 7. Post-apply readback

Read all four automation/workload roles, three validator roles, policy
attachments, inline policies, boundaries, profiles, OIDC trust, KMS policies,
and grants. Exclusive allowlists must match exactly; no extra policy may
remain. Simulate and require explicit denial for:

- Foundation `kms:CreateGrant`, `kms:Sign`, `ec2:RunInstances`,
  `iam:PassRole`, `ssm:SendCommand`, CloudFront, and non-JSEC DNS/ACM;
- AMI Builder Terraform state, Route 53, validator IAM, and signer access;
- Observer every write action;
- validator-N signing with either other validator key;
- Image Builder worker `ssm:GetParameter` and `ssm:GetParameters`.

For every protected role, repeat `GetRole`, `GetRolePolicy`,
`ListRolePolicies`, `ListAttachedRolePolicies`, and profile membership
readback. Require the exact one-to-one boundary matrix, canonical trust,
canonical inline document hashes, exact attachment allowlists, and zero extras.
Recompute the boundary/readback digest and compare it with the saved plan.

Enumerate every live account principal that can call `ssm:SendCommand`,
including legacy/admin paths, SCPs, permission sets, resource policies, and
cross-account assumptions. While signer nodes have no SSM Core attachment,
require negative authorization and live API tests for raw
`AWS-RunShellScript` and all non-canonical documents. Do not reattach SSM until
the six fixed documents, exact controller, account-wide raw-shell denial, and
negative tests are approved together.

Route 53 write is limited to `rpc`, `explorer`, `scan`, `health`, and each
endpoint's ACM validation CNAME. ACM requests are limited to those four names,
DNS validation, and `us-east-1`.

Repeat negative simulations and non-mutating API canaries with an explicit
second-region endpoint. Require denial for every EC2, ELB, ACM, WAF,
Image Builder, KMS, DynamoDB, logs, alarm, and SNS mutation outside
`us-east-1`. A resource ARN scoped to `us-east-1` is not accepted as a
substitute for this live cross-region test.

Read the live default policy documents for
`EC2InstanceProfileForImageBuilder` and `AmazonSSMManagedInstanceCore`.
Record version and canonical digest. The worker permissions boundary must cap
them to pinned v12-equivalent Image Builder actions plus parameter-free SSM
core and exact build inputs. Run and accept a canary Image Builder build before
resuming AMI production.

Keep the repository-wide OIDC freeze until every role in the cutover matrix
passes its real-token assume-role test and every legacy subject is removed.
Keep validator rollout blocked until fixed SSM documents and the immutable
launch contract are separately approved and implemented.

Re-run Access Analyzer validation for all customer-managed/inline policies and
the four KMS policies. Simulate Security Bootstrap and remediation separately:
Security Bootstrap must be denied role creation, permissions-boundary changes,
self-policy versioning, KMS administration/signing, and application mutation;
remediation must be disabled after use and denied KMS signing, state object
data plane, and application mutation.

The permanent boundary is:

- `mainnet_changed = false`
- `assets_moved = false`
- `bridge_activated = false`
