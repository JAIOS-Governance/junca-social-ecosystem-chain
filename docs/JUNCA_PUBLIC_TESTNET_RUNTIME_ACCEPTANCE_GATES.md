# Public Testnet Runtime Acceptance Gates

The release path uses two deliberately different decisions.

1. `JUNCA Runtime Release Manifest Gate` is a **predeployment readiness**
   decision. Its three inputs use `pre-rollout-baseline/v1` schemas. They prove
   that the candidate AMI is immutable, the existing runtime is a distinct
   rollback baseline, and the three durable EBS volumes and snapshots are
   readable. This gate never claims that the candidate is live.
2. `JUNCA Public Testnet Runtime Acceptance Gate` is the **post-rollout
   acceptance** decision. It runs only after a successful Foundation Release
   and Public Testnet Release, and requires the completed live soak plus the
   end-of-soak Terraform/AWS candidate identity readback.

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
