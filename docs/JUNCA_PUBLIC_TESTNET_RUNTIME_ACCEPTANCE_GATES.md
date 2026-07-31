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
If the exact persistence helper or mount unit on an admitted stopped legacy
validator is absent or stale, Foundation may replace only those two root-owned
regular single-link files using same-directory temporary files, file and
directory fsync, atomic rename, daemon reload, and exact post-write readback.
Symlinks, hardlinks, non-root ownership, unexpected target entries, device
ambiguity, unapproved filesystems, or any post-write mismatch remain
fail-closed. The recovery evidence records the last completed mount-repair
stage and the admitted target entry names so a failed precondition is
diagnosable without repeating a blind rollout.
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

An active validator with an unreadable runtime configuration may enter the
same bounded repair only after read-only evidence proves the retained volume,
SQLite integrity, immutable runtime and genesis, plus a healthy loopback
response carrying its exact expected validator ID. Recovery then stops only
that service once, proves it inactive, applies the narrow repair, restarts it,
and records the pre-repair health and controlled-stop evidence. If acceptance
still fails, containment may start that same service exactly once and require
the exact healthy validator ID within 30 bounded polls. Containment never
converts failed repair evidence into acceptance; it only restores the prior
healthy service posture while the rollout remains blocked.

Post-repair acceptance is bound to the same validator identity. Every healthy
loopback response observed after restart must carry the exact expected
`validator_id`; a missing or different identity remains blocked even when the
status string is `healthy`. Recovery evidence schema v6 records that readback
as `health_validator_id`, and the controller rejects evidence whose recorded
identity differs from the validator being advanced in the serial rollout.

Schema v6 also binds each recovery result to a canonical request digest over
the exact validator, instance, AMI, runtime archive, canonical `runtime.env`,
genesis, retained volume, source commit, dispatch sequence, current workflow
run ID and attempt, immutable release-request digest, manifest-decision digest,
candidate head, and the exact runtime-environment repair authorization. The
controller adds the exact SSM Command ID from the invocation it read and
validates every value before serial advancement. Evidence from another
validator, candidate, volume, instance, run, attempt, release decision, repair
mode, or earlier SSM dispatch cannot satisfy the current request.

Both repaired and pre-existing `runtime.env` files must be single-link regular
files owned by `root:junca` with mode `0640`. Recovery pins the admitted
device/inode and digest before restart, then revalidates identity, ownership,
mode, link count, and digest after the validator reports healthy. Any
replacement or hard-link race blocks activation; a changed path is never
deleted by rollback. Recovery evidence records the exact admitted identity,
owner, mode, and link count rather than reducing those properties to an
unverifiable success claim.

Before a stopped validator is restarted, recovery must also prove the service
user can traverse `/etc/junca` and read both `genesis.json` and
`validator.toml`. The canonical contract is `root:junca`/`0750` for the
directory and `root:junca`/`0640`/single-link for both files. A bounded
metadata-only repair is allowed only for exact root-owned regular inputs and
an exact genesis digest. For a pre-existing `validator.toml`, admission pins
the single-link file's device/inode, SHA-256, and size before the controlled
stop; recovery may normalize only group and mode to `root:junca`/`0640`, then
must prove the pinned identity, digest, and size are unchanged and read the
file back as `junca`. Symlinks, hard links, non-root ownership, content or
identity drift, and post-repair unreadability block the rollout before
Terraform apply.

For a stopped legacy validator whose immutable predecessor AMI did not contain
`validator.toml`, recovery may create only the canonical empty compatibility
file. The destination must be absent (including no dangling symlink); recovery
writes a same-directory single-link temporary inode, syncs it, links it without
overwrite, removes the temporary name, and then requires exact zero length,
`root:junca`/`0640`/single-link metadata and service-user readability. Existing
content is never replaced or truncated. Existing group or mode may be
normalized only through the pinned metadata-only path above; other
non-canonical shape is never overwritten.

If that same predecessor lacks the `junca` service account and group, recovery
may create only the fixed system identity UID/GID `992` after the controlled
single-validator stop is proven. It must use `/var/lib/junca` and
`/sbin/nologin`, must not create a home directory, and must read back both the
name and numeric identity. A conflicting name, UID, or GID fails closed before
configuration ownership is changed; existing identities are never rewritten.
Device/inode and digest comparison is lexical. Recovery must not parse a
colon-bearing inode identity or hexadecimal SHA-256 as shell arithmetic; the
exact-existing and new-empty branches are evaluated independently and any
identity, digest, or size drift blocks restart.

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
