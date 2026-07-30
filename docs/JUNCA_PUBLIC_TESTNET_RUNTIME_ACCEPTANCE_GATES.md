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

If `/etc/junca/runtime.env` is absent on an otherwise exact stopped baseline,
the prefix length must still be zero. Only then may the workflow stop the
service and atomically reconstruct that file from Terraform-canonical values.
It cannot copy operator input or another host's file. The reconstructed file
must have the exact calculated SHA-256, owner `root:junca`, and mode `0640`
before the service is restarted. A symlink, an existing but contradictory
environment, an AMI/runtime/genesis mismatch, or any resumed mixed prefix
rejects reconstruction. Recovery must emit exact before/after service, repair
source/hash, and health evidence, preserve all four safety boundaries as false,
and then pass the unchanged strict live-prefix readback. Missing durable state,
corrupt SQLite, ambiguous provenance, or failed local health remains
fail-closed and prevents Terraform mutation.

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
