# JUNCA Public Testnet Fixed SSM and Validator Launch Design

Status: **DESIGN ONLY — NOT IMPLEMENTED**

Operational decision:

`BLOCKED_PENDING_ATTESTED_LAUNCH_AND_SSM_CONTRACT`

This document specifies the Security Bootstrap work required to restore the
three JUNCA Public Testnet validators without returning arbitrary root command
or EC2 launch authority to the Foundation role. It is not evidence that the
AWS resources described below exist, that an IAM change has been applied, or
that a validator rollout is authorized.

Until every acceptance item in this document has independent AWS readback,
the Foundation workflow and validator replacement remain **BLOCKED**. Do not
remove the block merely because repository code, a Terraform plan, an SSM
document draft, or an IAM simulation succeeds.

## Constitutional boundary

This design is limited to the three Public Testnet validators.

- Mainnet changed: **false**
- Assets moved: **false**
- Bridge activated: **false**
- Mainnet activation authorized: **false**
- Transaction submission enabled by this design: **false**

The fixed documents must not contain a Mainnet endpoint, bridge operation,
asset transfer, transaction submission, signer export, interactive shell, or
general-purpose package execution path. Any observation that contradicts the
five declarations above is a hard failure and keeps operation **BLOCKED**.

## Existing conflict and scope

The current separation policy deliberately denies the Foundation role:

- `ec2:RunInstances` in
  [`infra/aws/bootstrap/iam-separation.tf`](../../infra/aws/bootstrap/iam-separation.tf)
  around lines 694–698;
- `iam:PassRole` in the same file around lines 1187–1191; and
- `ssm:SendCommand` on all resources in the same file around lines
  1201–1213.

Those line numbers describe the original audited source snapshot. The
canonical Foundation workflow and rollout script have now retired all nine
caller-constructed `commands` calls to the AWS-managed
`AWS-RunShellScript` document. They invoke only the fixed names below, with
an exact numeric version, repository/live content-digest equality, exact-three
fleet discovery, and command/invocation readback. Because accepted live
versions and live AWS evidence do not yet exist, every operational call
remains fail-closed before mutation. An Allow statement cannot override the
current explicit all-resource Deny.

This design replaces those nine call sites with six fixed Command documents
and replaces Foundation-owned validator creation with one fixed Automation
document. It does not grant Foundation `ec2:RunInstances`, `iam:PassRole`,
document mutation, or arbitrary shell access.

## Non-negotiable document rules

All six Command documents must satisfy these rules:

1. Security Bootstrap owns document creation, versioning, default-version
   selection, tags, and deletion. Foundation and Observer cannot mutate them.
2. The command body is stored in the document. No parameter named `commands`,
   `command`, `script`, `path`, `url`, `service`, `unit`, `instanceId`, or an
   equivalent general-purpose input is permitted.
3. String parameters use `interpolationType: ENV_VAR`, an `allowedPattern`,
   and quoted environment-variable references in the fixed shell body.
   Direct `{{ parameter }}` interpolation into shell text is prohibited.
4. The command begins with fail-fast shell settings and uses absolute paths.
   The document must not invoke Python by embedding Python source in Bash, nor
   invoke Bash by constructing a Bash program in Python.
5. Service name, health URL, runtime environment path, durable state path,
   SQLite path, and allowed output fields are constants in the document.
6. A Command document version is immutable after review. Foundation sends an
   exact numeric `DocumentVersion`; `$LATEST` is prohibited. Security
   Bootstrap may change `$DEFAULT` only after a new version and digest are
   independently accepted.
7. Command output is bounded and must not contain environment dumps, AWS
   credentials, signer material, tokens, private keys, or unrestricted logs.
8. Every invocation uses SSM Run Command output readback. A successful API
   submission is not operational success.
9. A timeout, `Cancelled`, `TimedOut`, `Failed`, missing invocation, malformed
   JSON, extra target, missing target, or contradictory safety flag is failure.
10. AWS-managed shell/session documents remain unavailable to Foundation and
    Observer.

## Fixed Command document inventory

The six-document split is the minimum safe set. Read-only inspection must not
share a document with mutation, and high-frequency health polling must not
gain the deeper filesystem and SQLite surface.

| Document | Access class | Fixed command behavior | Replaces |
| --- | --- | --- | --- |
| `JuncaPTFinalityInspect` | Read-only | Verify `/etc/junca/runtime.env`, exact artifact digest, finality-key counts and values, service state, localhost health, and runtime-env digest. A fixed `preflight` branch may accept all three finality keys being absent only for the disabled `false/0/0` state. A fixed `exact` branch requires one occurrence of every key and an exact value match. | Script finality preflight and compensation readback |
| `JuncaPTFinalitySet` | Mutating | Recheck the exact artifact, copy `runtime.env` to a same-directory temporary file, alter only the three finality keys, verify owner/mode and exact key cardinality, atomically replace the file, restart `junca-validator`, poll fixed localhost health, and perform exact readback. The compensation state is the same fixed operation with `false/0/0`. | Script finality mutation and compensation mutation |
| `JuncaPTBootstrapReadiness` | Read-only | Verify cloud-init completion, active validator service, durable mount, read-only SQLite `quick_check`, exact runtime artifact and genesis digests, immutable archive/genesis evidence, localhost health identity, durable finalized certificate consistency, and all Public Testnet safety flags. | Script bootstrap-readiness command |
| `JuncaPTRuntimeObservation` | Read-only | Return bounded JSON for service, mount, SQLite integrity, durable finalized certificate, runtime artifact version, finality environment, health/finality equality, certificate equality, and safety flags. | Script rolling compatibility readback |
| `JuncaPTRestartHealth` | Mutating | Restart only `junca-validator`, perform the fixed 60-attempt localhost health loop with two-second spacing, and on failure return only bounded unit status plus allowlisted timestamp, priority, and unit metadata from at most the final 100 journal entries. Journal messages are never returned. | Workflow volatile-round reset |
| `JuncaPTHealthReadback` | Read-only | Execute only `curl -fsS http://127.0.0.1:8545/health` and return its bounded JSON response. Any initial delay belongs to the caller; it is not a document parameter. | Workflow ordinary and repeated automatic-finality health readbacks |

### Parameter contract

Parameters not listed here are prohibited.

| Document | Parameter | SSM type | `allowedPattern` | Additional fixed-command constraint |
| --- | --- | --- | --- | --- |
| `JuncaPTFinalityInspect` | `ExpectedArtifactSha256` | `String` | `^[0-9a-f]{64}$` | Must equal the sole `NODE_ARTIFACT_SHA256` value |
|  | `Enabled` | `String` | `^(true\|false)$` | Must agree with interval and epoch |
|  | `BlockIntervalSeconds` | `String` | `^(0\|30)$` | `0` when disabled; `30` when enabled |
|  | `SlotEpochSeconds` | `String` | `^(0\|[1-9][0-9]{0,10})$` | `0` when disabled; future and divisible by 30 when enabled |
|  | `Mode` | `String` | `^(preflight\|exact)$` | Selects only the two fixed read-only branches |
|  | `AllowMissingFinalityKeys` | `String` | `^(true\|false)$` | `true` allowed only for `preflight` with disabled `false/0/0` |
| `JuncaPTFinalitySet` | `ExpectedArtifactSha256` | `String` | `^[0-9a-f]{64}$` | Rechecked before any file mutation |
|  | `Enabled` | `String` | `^(true\|false)$` | Must agree with interval and epoch |
|  | `BlockIntervalSeconds` | `String` | `^(0\|30)$` | `0` when disabled; `30` when enabled |
|  | `SlotEpochSeconds` | `String` | `^(0\|[1-9][0-9]{0,10})$` | `0` when disabled; future and divisible by 30 when enabled |
| `JuncaPTBootstrapReadiness` | `ValidatorId` | `String` | `^validator-0[1-3]$` | Must agree with the target's immutable identity tag and health response |
|  | `ExpectedArtifactSha256` | `String` | `^[0-9a-f]{64}$` | Runtime and immutable artifact evidence must match |
|  | `ExpectedGenesisSha256` | `String` | `^[0-9a-f]{64}$` | Genesis file and immutable evidence must match |
| `JuncaPTRuntimeObservation` | `ValidatorId` | `String` | `^validator-0[1-3]$` | Target identity, health identity, and durable evidence must match |
| `JuncaPTRestartHealth` | — | — | — | No parameters |
| `JuncaPTHealthReadback` | — | — | — | No parameters |

SSM `allowedPattern` is only the first validation layer. Numeric and
cross-parameter relationships must also be checked inside the fixed command
before reading or mutating runtime configuration. An integer accepted by the
regular expression but rejected by shell arithmetic, time bounds, or
30-second alignment must fail without mutation.

### Target contract

After the Security Bootstrap migration, every validator instance must have
all of these exact tags:

| Key | Required value |
| --- | --- |
| `Project` | `JUNCA Social Ecosystem Chain` |
| `Network` | `Public Testnet` |
| `Role` | `Validator` |
| `ValidatorId` | one of `validator-01`, `validator-02`, `validator-03` |
| `LaunchContract` | `JuncaValidatorLaunchV1` |
| `MainnetChanged` | `false` |
| `AssetsMoved` | `false` |
| `BridgeActivated` | `false` |

The existing `Validator=01|02|03` and exact `Name` tags may be retained for
compatibility, but the new `ValidatorId` and `LaunchContract` tags are the
authorization boundary. Foundation must be explicitly denied permission to
add, delete, or change `Project`, `Network`, `Role`, `ValidatorId`,
`LaunchContract`, `MainnetChanged`, `AssetsMoved`, and `BridgeActivated`.

Before every invocation, read-only EC2 discovery proves the complete tag
contract and resolves each `ValidatorId` to exactly one running instance. The
caller then sends to that deterministically discovered exact instance ID,
never to a user-provided or un-read-back instance ID and never to a
late-bound tag target. This closes the tag-addition time-of-check/time-of-use
window while IAM still enforces every resource-tag condition. Discovery must
prove:

- the fleet is exactly the set `validator-01`, `validator-02`,
  `validator-03`;
- each identity maps to exactly one running instance;
- no fourth instance has the same project/network/role/launch contract;
- each instance has the exact expected subnet, private IP, instance profile,
  security group, AMI evidence, and safety tags; and
- a per-node operation resolves to one target, while a fleet operation
  resolves to exactly three targets.

The Send Command response, `ListCommands`, and final invocation must each
bind the same command ID, exact instance ID, document name, and numeric
version. `ListCommands.TargetCount` must converge to exactly one. One success
cannot stand in for a missing validator.

## IAM separation

### Security Bootstrap

The non-OIDC Security Bootstrap role is the only principal allowed to:

- create, update, tag, select the default version of, or delete the six exact
  Command document ARNs;
- create and version the three exact validator launch templates;
- create and update the validator replacement Automation document and its
  execution role;
- establish immutable validator boundary tags; and
- update the Foundation and Observer policies described below.

Its permission must name the exact documents and launch resources. It must
not create a reusable general shell document as part of this migration.

### Foundation

Foundation receives `ssm:SendCommand` only for:

- the exact six approved document ARNs; and
- EC2 managed-instance resources carrying every target-contract tag.

IAM scopes the document resource, not the accepted document-version digest.
The invocation contract must therefore send an exact numeric version, while
the workflow and independent readback verify that version and its previously
accepted content digest.

Foundation receives `ssm:StartAutomationExecution` only for the exact
`JuncaPTReplaceValidator` Automation document. The Automation document embeds
its execution role; Foundation does not supply an automation-assume-role
parameter and does not receive `iam:PassRole`.

Foundation may receive the minimum readback actions required for:

- `ssm:GetCommandInvocation`;
- `ssm:ListCommandInvocations` and `ssm:ListCommands`, if the AWS action does
  not support resource-level restriction;
- `ssm:GetAutomationExecution` and the minimum describe action required to
  poll the exact execution;
- `ssm:GetDocument` and `ssm:DescribeDocument` for the approved documents;
  and
- existing EC2, EBS, ELB, and SSM read-only state verification.

Where AWS requires `Resource: "*"`, the statement contains only the read
action. Workflow evidence must still bind command or automation ID, document
name/version/digest, target identity, source run, source commit, and timestamps.

The current all-resource `ssm:SendCommand` Deny must not simply receive a
competing Allow; explicit Deny wins. Its implementation replacement must:

1. deny the AWS-managed `AWS-RunShellScript`,
   `AWS-RunPowerShellScript`, interactive-session, and other general command
   document ARNs;
2. allow only the six exact customer-managed documents and tag-constrained
   validator resources; and
3. preserve a permissions-boundary or equivalent allowlist so a later broad
   identity policy cannot silently add a seventh document.

Do not implement a naive `Deny` with document `NotResource` across
`ssm:SendCommand`: Send Command authorization also evaluates target instance
resources, and an instance ARN is not a document ARN. The final policy must be
validated against both document and target-resource authorization with
positive and negative simulations, then with independent CloudTrail readback.

The explicit Foundation denies on `ec2:RunInstances` and `iam:PassRole` remain.
Foundation must additionally be denied validator `StopInstances`,
`TerminateInstances`, `AttachVolume`, and `DetachVolume` outside the approved
Automation path. The present tag-wide Foundation EC2 mutation policy in
`infra/aws/bootstrap/iam-separation.tf` around lines 561–648 is not sufficient
for that final boundary.

### Observer

Observer may send only:

- `JuncaPTFinalityInspect`;
- `JuncaPTBootstrapReadiness`;
- `JuncaPTRuntimeObservation`; and
- `JuncaPTHealthReadback`.

Observer cannot send `JuncaPTFinalitySet` or `JuncaPTRestartHealth`, start the
replacement Automation, mutate a document, alter target tags, or mutate EC2.

### Validator workload role

The validator instance role retains only the managed-instance channel and its
existing validator-specific runtime permissions. It does not receive command
submission, document mutation, launch, PassRole, or automation-start
permissions.

## SecurityBootstrap-owned AMI replacement

### Automation contract

Security Bootstrap creates one fixed SSM Automation document:

`JuncaPTReplaceValidator`

The document uses schema `0.3`, embeds the exact
`JuncaPTValidatorReplaceAutomationRole` ARN as `assumeRole`, and exposes only:

| Parameter | `allowedPattern` | Purpose |
| --- | --- | --- |
| `ValidatorId` | `^validator-0[1-3]$` | Select one fixed validator contract |
| `AmiId` | `^ami-[0-9a-f]{8,17}$` | Exact immutable candidate |
| `ExpectedArtifactSha256` | `^[0-9a-f]{64}$` | Runtime artifact binding |
| `ExpectedGenesisSha256` | `^[0-9a-f]{64}$` | Genesis binding |
| `ReleaseManifestSha256` | `^[0-9a-f]{64}$` | Accepted release-decision binding |
| `SourceCommit` | `^[0-9a-f]{40}$` | Exact runtime source provenance |
| `SlotEpochSeconds` | `^[1-9][0-9]{0,10}$` | Future, 30-second-aligned rollout epoch |

It does not accept subnet, Availability Zone, private IP, security group,
instance profile, instance type, root disk, metadata options, user-data text,
state volume, target group, KMS key, service name, or shell input.

### Immutable per-validator map

The Automation document or SecurityBootstrap-owned launch-template contract
maps each `ValidatorId` to:

- one exact launch-template ID and reviewed source version;
- one exact private subnet and Availability Zone;
- private IP `10.67.16.10`, `10.67.32.10`, or `10.67.48.10`;
- one exact validator instance profile and signer boundary;
- one exact validator security group;
- instance type `m7i.large`;
- IMDSv2 required and metadata endpoint enabled;
- no public IP;
- one encrypted 200 GiB `gp3` root disk with 6,000 IOPS and
  250 MiB/s throughput;
- one exact retained validator state volume and device contract;
- the exact applicable target groups;
- the exact KMS and user-data contract; and
- all target and constitutional safety tags.

A new launch-template version may differ from the reviewed source version only
in fields that the fixed Automation explicitly sets from the bounded inputs,
principally the accepted AMI and its provenance-bound bootstrap values. The
Automation must compare the resulting canonical launch-template data with an
expected digest before launch. It must not make the new version the account's
general default for unrelated callers.

### Fixed replacement sequence

The Automation performs one validator at a time:

1. Acquire the validator-specific serialization lock. Reject a second active
   replacement or a fleet shape other than exact-three identities.
2. Read the accepted release manifest and AMI evidence. Require the AMI to be
   owned by the expected account, `available`, and tagged with the exact
   source commit, artifact digest, genesis digest, release manifest digest,
   Public Testnet boundary, and three `false` safety tags.
3. Read the old instance, launch-template contract, retained volume, target
   registrations, service health, durable head, finalized certificate,
   artifact version, and rollback floor. Persist a checksummed pre-mutation
   record.
4. Run fixed finality disable/readback. Require all three validators to be in
   the safe `false/0/0` state before disruptive mutation.
5. Deregister only the selected validator from its exact target groups and
   wait for draining. Stop the service through a fixed document, flush state,
   and prove the retained durable volume and finalized certificate are
   consistent.
6. Detach the selected retained state volume and terminate only the exact old
   instance. Re-read the fleet and reject any unexpected instance.
7. Create the constrained launch-template version and launch exactly one
   instance with a deterministic idempotency token. The Automation role, not
   Foundation, performs `RunInstances`.
8. Require the exact AMI, template version, profile, subnet, private IP,
   security group, IMDSv2 settings, root disk, tags, and no public IP. Attach
   only the same retained durable volume.
9. Wait for EC2 and SSM readiness. Invoke the exact numeric version of
   `JuncaPTBootstrapReadiness`, then `JuncaPTRuntimeObservation`. Reject state
   rewind, certificate mismatch, safety-boundary drift, or unexpected
   artifact.
10. Register the instance in only the recorded target groups, wait for exact
    healthy readback, and write checksummed post-mutation evidence.
11. Release the lock only after terminal evidence is durable. Return the old
    and new instance IDs, AMIs, launch-template version, volume ID, head and
    certificate floors, command IDs, and evidence digest.

The Automation never replaces two validators concurrently and never advances
to a second validator. The canonical Foundation controller starts a separate
accepted execution for the next validator only after the existing rolling
compatibility gate accepts the prior execution.

### Automation execution-role boundary

The execution role receives only the exact resource operations required by
the fixed sequence:

- `ec2:RunInstances` through the three exact launch templates and allowed
  AMI/subnet/security-group resources, with region, request-tag, and launch
  template conditions;
- `iam:PassRole` for only the three exact validator instance profiles, with
  `iam:PassedToService=ec2.amazonaws.com`;
- launch-template version creation/readback on the three exact templates;
- stop/terminate/tag operations on exact launch-contract validator instances;
- attach/detach on the three exact retained state volumes;
- register/deregister and health readback on the exact Public Testnet target
  groups;
- invocation of only the required fixed Command documents; and
- the minimum EC2, EBS, ELB, SSM, and CloudTrail readback actions.

The role has no IAM write, OIDC, KMS key administration, signer use, arbitrary
SSM document, session, network-foundation creation, asset, bridge, or Mainnet
permission. Its trust permits only SSM Automation with account and source
constraints. Foundation cannot assume it.

## Existing code correspondence

The following mappings are implementation targets, not claims that the target
documents or Automation currently exist.

| Existing source | Audited lines | Current behavior | Required replacement |
| --- | ---: | --- | --- |
| [`scripts/junca_public_testnet_foundation.sh`](../../scripts/junca_public_testnet_foundation.sh) | former 286–323, 593–621 | Exact fixed invocation implemented | Send exact `JuncaPTFinalityInspect` version with `Mode=preflight` |
| same | former 325–405, 634–670 | Exact fixed invocation implemented | Send exact `JuncaPTFinalitySet` version |
| same | former 325–405, 684–710 | Exact fixed invocation implemented | Send exact `JuncaPTFinalitySet` version with bounded disabled values |
| same | former 407–430, 715–733 | Exact fixed invocation implemented | Send exact `JuncaPTFinalityInspect` version with `Mode=exact` |
| same | former 788–885 | Exact fixed invocation implemented | Send exact `JuncaPTBootstrapReadiness` version |
| same | former 887–1058 | Exact fixed invocation implemented | Send exact `JuncaPTRuntimeObservation` version |
| [`junca-validator-foundation-release.yml`](../../.github/workflows/junca-validator-foundation-release.yml) | former 808–845 | Exact fixed invocation implemented | Send exact `JuncaPTRestartHealth` version |
| same | former 847–925 | Exact fixed invocation implemented | Caller delay, then exact `JuncaPTHealthReadback` version |
| same | former 926–1037 | Exact fixed invocation implemented | Repeated exact `JuncaPTHealthReadback` version |
| [`infra/aws/public-testnet/main.tf`](../../infra/aws/public-testnet/main.tf) | 467–560 | Foundation Terraform owns three `aws_instance.validator` resources | Move validator compute ownership to SecurityBootstrap launch templates and Automation; Foundation retains readback |
| Foundation script | 2851–2944 | Exact AMI/private IP/type/profile/subnet/SG/tag/user-data/IMDS/root-disk/TG/state-volume plan gate | Preserve as Automation preconditions plus independent post-execution readback |
| Foundation script | 2950–2957 | Targeted Terraform apply causes validator `RunInstances` | Start the exact replacement Automation and wait for terminal accepted evidence |
| Foundation script | 2959–3157 | Post-apply instance, volume, SSM, and bootstrap checks | Retain as independent verification of Automation output |
| Foundation script | 3194–3205 | Target-group health wait | Retain as independent verification |

The existing `wait_for_ssm_command` and
`wait_for_ssm_command_result` behavior around script lines 163–283 can remain
as polling structure, but invocation evidence must additionally validate the
fixed document name, exact version, target tag binding, and output schema.

Foundation Terraform cannot continue to own `aws_instance.validator` after
Automation takes ownership. Otherwise a later plan will treat the
Automation-created instance as drift and attempt another replacement. The
state transition is a Security Bootstrap migration: remove only validator
compute ownership after exact live/state evidence, preserve retained EBS and
other intended Foundation resources, and replace compute resources with
read-only data/readback contracts. No state command in this document is
presented as ready to run.

## Migration order

Every phase ends with independent readback. Failure stops the migration; later
phases do not begin.

1. **Freeze and snapshot.** Freeze Foundation rollout and all validator
   mutation. Record repository commit, both Terraform states, current role
   policies, three instances, profiles, volumes, snapshots, target groups,
   finality state, health, heads, and certificates. State remains **BLOCKED**.
2. **Create boundary tags.** Through the approved non-OIDC Security Bootstrap
   session, place and read back the immutable target and safety tags on the
   exact three existing validators. Add denies preventing Foundation from
   changing them. State remains **BLOCKED**.
3. **Create fixed Command documents.** Create the six documents, archive their
   canonical content and SHA-256 digests, select accepted default versions,
   and perform schema/static review. No Foundation permission is added yet.
   State remains **BLOCKED**.
4. **Create launch contract.** Create the three exact launch templates,
   Automation execution role, fixed Automation document, serialization lock,
   and evidence destination. Read back canonical launch data and policy
   digests. State remains **BLOCKED**.
5. **Apply least privilege.** Replace the current all-resource Send Command
   Deny with the tested fixed-document allowlist and precise general-shell
   denies. Add Observer read-only separation, Automation-start permission,
   and validator mutation denies. Keep Foundation `RunInstances` and
   `PassRole` denied. State remains **BLOCKED**.
6. **Negative authorization acceptance.** Prove every prohibited document,
   target, tag, parameter, mutation, PassRole, launch, and Observer write is
   denied. Prove only the intended fixed calls are allowed. State remains
   **BLOCKED**.
7. **Read-only runtime acceptance.** Execute only the fixed read-only
   documents against the exact three existing validators. Verify document
   version, target cardinality, output schema, runtime identity, durable
   certificate, and all safety flags through independent readback. State
   remains **BLOCKED**.
8. **Compute ownership migration.** Under freeze, move validator compute
   ownership from Foundation Terraform to the SecurityBootstrap launch
   contract without deleting or changing a live instance. A plan containing
   an unapproved replacement or destroy is rejected. State remains
   **BLOCKED**.
9. **Replacement rehearsal.** With explicit Public Testnet authorization,
   rehearse the Automation on exactly one validator using an accepted
   immutable AMI and the same retained state volume. Complete rollback-path,
   CloudTrail, SSM, target-health, and independent rolling-compatibility
   evidence. State remains **BLOCKED** until reviewed.
10. **Contract activation.** Only after all acceptance evidence is complete
    may the repository's blocked mutation contract be changed to the exact
    accepted state. Subsequent replacements remain serial, evidence-bound,
    and independently gated.

## Fail-closed acceptance matrix

All rows are mandatory.

| Area | Positive acceptance | Mandatory negative acceptance |
| --- | --- | --- |
| Document integrity | Exact six names, accepted numeric versions, canonical content digests, SecurityBootstrap owner tags | `$LATEST`, unknown version, seventh customer document, or changed default digest is rejected |
| Parameter safety | Every listed valid parameter reaches only its fixed branch | Shell metacharacters, newline, extra key, overlong integer, invalid Boolean, nonaligned/past epoch, or cross-parameter mismatch is rejected before mutation |
| Target cardinality | Exact-three tag discovery resolves each identity to one instance, then the command is pinned to that discovered instance with target count one | Caller-supplied or un-read-back instance ID, tag-target TOCTOU, duplicate identity, missing validator, fourth validator, wrong project/network/launch tag, or safety tag not `false` is rejected |
| Foundation IAM | Exact approved document invocation, caller-pinned accepted numeric version, and exact Automation start succeed | `AWS-RunShellScript`, PowerShell/session, document mutation, direct `RunInstances`, direct `PassRole`, direct validator terminate/detach, arbitrary Automation role, and unapproved target are denied |
| Observer IAM | Four read-only documents succeed | finality set, restart, Automation start, EC2 mutation, tag mutation, and document mutation are denied |
| Runtime inspection | Exact artifact/genesis, service, mount, SQLite, health, certificate, and safety flags pass | Missing/duplicate env key, malformed JSON, unhealthy service, state rewind, certificate mismatch, fallback active, or any non-false constitutional flag fails |
| Replacement | One accepted validator is replaced with exact AMI/template/profile/network/storage settings and same retained volume | Two concurrent replacements, second instance for one identity, public IP, wrong AMI/profile/subnet/IP/SG/disk/metadata/tag/volume/TG, or fleet outside the temporary exact-two/exact-three transition fails |
| Evidence | CloudTrail, SSM invocation, Automation execution, EC2/EBS/ELB readbacks and checksummed before/after record agree | Missing event, unexpected principal/action/resource, digest mismatch, incomplete output, or evidence written only by the mutating principal is rejected |
| Safety | `MainnetChanged=false`, `AssetsMoved=false`, `BridgeActivated=false`, no transaction submission | Any Mainnet, asset, bridge, public admin/debug/mining/personal/txpool, signer export, or transaction path is rejected |

No warning-only result is accepted. Any unclassified result is **BLOCKED**.

## Rollback and recovery

Rollback means returning the selected Public Testnet validator to the recorded
previous immutable AMI while preserving its current retained durable volume
and finalized-state floor. It does not mean restoring an older chain-state
snapshot, lowering finalized height, activating a fallback signer, changing
Mainnet, moving assets, or activating a bridge.

Before disruptive mutation, the Automation must record:

- previous instance ID, AMI, launch-template version, profile, subnet, private
  IP, security group, root settings, tags, and target registrations;
- retained state volume and attachment identity;
- previous runtime artifact and genesis digests;
- durable head height/hash and finalized certificate hash;
- rollback floor and completed rollback snapshot evidence;
- all three validators' disabled finality state; and
- the canonical evidence digest.

If failure occurs before old-instance termination, leave or return the old
instance to the recorded drained/disabled state and do not launch a
replacement.

If failure occurs after termination, the same fixed Automation recovery branch
may launch exactly one instance from the recorded previous immutable AMI,
using the same launch contract and retained state volume. It must pass the
same bootstrap, durable-state, certificate, safety, and target-health checks.
It must not restore an older snapshot or accept a head below the recorded
floor.

If automatic recovery cannot prove the previous contract, it stops with:

`BLOCKED_MANUAL_SECURITY_BOOTSTRAP_RECOVERY`

The affected validator remains deregistered, finality remains disabled on the
fleet, evidence is preserved, and no later validator is touched. Recovery
requires a fresh non-OIDC Security Bootstrap authorization and independent
readback; Foundation must not bypass the block with direct EC2 or shell access.

## Completion decision

This design is complete only when the six fixed Command documents, exact
target boundary, IAM separation, three launch-template contracts, replacement
Automation, ownership migration, negative tests, one-node rehearsal,
rollback-path evidence, and independent runtime readbacks all exist and agree
in the bound AWS account and region.

Until then:

- validator remote mutation: **BLOCKED**
- validator AMI replacement: **BLOCKED**
- Foundation direct EC2 launch: **DENIED**
- Foundation direct role pass: **DENIED**
- arbitrary SSM root command: **DENIED**
- Mainnet changed: **false**
- Assets moved: **false**
- Bridge activated: **false**
