# Public Testnet Runtime Acceptance Gates

The release path uses two deliberately different decisions.

The automatic immutable release owner is
`JUNCA Hardened Immutable Candidate Release V2`. The legacy candidate-release
job remains in the repository as historical executable evidence but is
fail-closed and cannot dispatch an AMI build, evidence collector, manifest
gate, or validator rollout. This prevents two release parents from replacing
the same three-validator fleet.

1. `JUNCA Runtime Release Manifest Gate` is a **predeployment readiness**
   decision. Its three inputs use `pre-rollout-baseline/v1` schemas. They prove
   that the candidate AMI is immutable, the existing runtime is a distinct
   rollback baseline, and the three durable EBS volumes and snapshots are
   readable. This gate never claims that the candidate is live.
2. `JUNCA Public Testnet Runtime Acceptance Gate` is the **post-rollout
   acceptance** decision. It runs only after a successful Foundation Release
   and Public Testnet Release, and requires the completed live soak plus the
   end-of-soak Terraform/AWS candidate identity readback.

Pre-rollout endpoint evidence requires the exact
`junca-public-explorer/v4` read-only schema. Its hexadecimal and decimal Chain
ID and peer-count projections must agree before RPC parity is evaluated. An
older Explorer schema or contradictory duplicate projection fails the bounded
sample; it is never treated as transient parity.

Before the immutable serial replacement reads its strict live prefix, it may
recover an existing stopped validator service in place. That bounded recovery
is permitted only after SSM Online, the retained `/var/lib/junca` mount,
read-only SQLite `PRAGMA quick_check=ok`, the current EC2 AMI, immutable runtime
archive digest, genesis digest, exact validator KMS binding, and exact three-peer
contract are proven. An already active validator is not restarted.

If the exact encrypted retained EBS volume remains singly attached to the
Terraform-bound instance but its mount is absent, the same zero-prefix
recovery may re-run the immutable AMI's canonical durable-state mount unit.
Admission binds the Terraform volume ID, AWS attachment, NVMe by-id serial,
resolved block device, approved `ext4`/`xfs` filesystem, empty real mount
target, canonical helper/unit bytes and validator unit mount dependencies.
The device must not already be mounted elsewhere. Acceptance then requires the
exact resolved mount source, `noatime,nosuid,nodev`, enabled active boot
persistence and read-only SQLite integrity before any `runtime.env` repair.
There is no format, filesystem repair, relabel, detach, volume replacement or
snapshot restoration path. A failed prerequisite stops the unhealthy service
and leaves the rollout blocked, preventing its prior unbounded restart loop.

The pre-replacement Terraform readback treats `enabled: false` as an explicit,
valid JSON boolean rather than as a failed shell predicate. Both public-service
and automatic-finality flags are decoded by type and rendered as the literal
`true` or `false`; a missing value, `null`, number, or string such as `"false"`
still fails closed before any AWS mutation. This distinction is required when
the existing rollback baseline correctly has automatic finality disabled.

If `/etc/junca/runtime.env` is absent on an otherwise exact stopped baseline,
the prefix length must still be zero. Only then may the workflow stop the
service and atomically reconstruct that file from Terraform-canonical values.
It cannot copy operator input or another host's file. The reconstructed file
must have the exact calculated SHA-256, owner `root:junca`, and mode `0640`
before the service is restarted. Installation uses an atomic no-overwrite
hard-link from a same-directory temporary file, so a file appearing after
preflight cannot be replaced. The temporary file is synced before linking and
the `/etc/junca` directory is synced after linking; recovery evidence must prove
that persistence boundary and the created device/inode identity before restart.
A symlink, an existing but contradictory
environment, an AMI/runtime/genesis mismatch, or any resumed mixed prefix
rejects reconstruction. Recovery must emit exact before/after service, repair
source/hash, and health evidence, preserve all four safety boundaries as false,
and then pass the unchanged strict live-prefix readback. Missing durable state,
corrupt SQLite, ambiguous provenance, or failed local health remains
fail-closed and prevents Terraform mutation.

If health never becomes accepted after this attempt created the file, rollback
stops the service, removes only a single-link canonical file with the exact
expected digest and the same recorded device/inode identity, and syncs
`/etc/junca`. Failure to prove either install or rollback persistence remains
blocked for operator inspection.

Both repaired and pre-existing `runtime.env` files must be single-link regular
files owned by `root:junca` with mode `0640`. Recovery pins the admitted
device/inode and digest before restart, then revalidates identity, ownership,
mode, link count, and digest after the validator reports healthy. Any
replacement or hard-link race blocks activation; a changed path is never
deleted by rollback. Recovery evidence records the exact admitted identity,
owner, mode, and link count rather than reducing those properties to an
unverifiable success claim.

Before either an existing or reconstructed file is admitted, all 18 canonical
runtime assignments must appear exactly once with exact values. Duplicate,
whitespace-disguised, missing, or contradictory assignments for chain,
validator, genesis, artifact, signer, peer, region, public-RPC, finality, or
bridge controls fail closed before restart. This prevents systemd
`EnvironmentFile` last-assignment behavior from selecting a different value
than the recovery evidence inspected. Non-comment content is restricted to
those 18 assignments; unknown variables and non-canonical assignment syntax
are rejected so an unreviewed environment toggle cannot enter the validator.

The real-time soak is automatically started by a successful
`JUNCA Public Testnet Release`. It uses six sequential four-hour jobs because a
single GitHub-hosted job cannot safely own a 24-hour observation. Every segment
collects 49 read-only observations at five-minute intervals. The aggregate
requires all six segments, at least 86,400 seconds of continuous wall time,
advancing finalized heads and timestamps, exact three-validator finality,
at least two peers, and unchanged Mainnet/assets/bridge boundaries.

The soak shares the `junca-public-testnet-aws-foundation` concurrency group
with deployment workflows. This prevents a rollout from changing the observed
runtime during the soak. At the end, a read-only Terraform output and AWS EC2
readback must prove that all three running instances still use the exact AMI
whose SourceCommit, NodeArtifactSHA256 and GenesisSHA256 match the candidate.

The deterministic 24-hour simulation remains in fast CI. It tests restart,
single-validator loss, signer throttling, replay idempotence and double-signing
rejection without representing elapsed live runtime.
