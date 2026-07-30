# JUNCA Public Testnet Validator Rolling Update

This runbook is limited to the three Public Testnet validators. It does not
authorize Terraform apply, deployment, Mainnet changes, asset movement, or
bridge activation.

Complete and review the bounded implementation before starting the rollout.
Run the formal audit only after the live activation readback succeeds; pre-live
contract tests and fail-closed release gates are development controls, not the
post-activation audit.

The activation readback consumes the current Operational API and Explorer v4
shapes. It must prove, in the same bounded observation window: chain ID
`20260723`, advancing finalized height, authenticated peers exactly `2/2`,
fresh matching finalized timestamps, matching head and certificate hashes, and
exact finality power `3/3`. An HTTP 200 response, a parseable payload, or a
stable height alone is never activation evidence.

1. Record the target runtime version, its exact 40-character lowercase source
   commit, immutable artifact SHA-256, rollback version and rollback artifact
   SHA-256. Pass the recorded runtime commit as the release manifest gate's
   `source_commit`; never substitute a newer documentation-only workflow head.
   Require a passed release manifest gate and a live no-state-rewind rollback
   rehearsal. Record the
   successful gate run ID as the Foundation Release `manifest_gate_run_id`;
   its AMI ID, source commit, runtime artifact SHA-256 and genesis SHA-256 must
   exactly match the selected AMI Build evidence.
   An immutable AMI may be reused only when the AMI Build evidence proves the
   exact same canonical request digest and all bound source/artifact digests.
   The `reused_existing_ami` field must be a boolean and never weakens any
   provenance, manifest, rollout or live-readback gate.
2. Read back the exact three retained EBS volume IDs and completed encrypted
   rollback snapshots. A runtime rollback must reuse each validator's current
   durable volume. Snapshot restoration or any reduction of finalized height
   is prohibited. Record the pre-rollout head hash, height and certificate hash
   as that validator's immutable rollback floor.
3. Disable the automatic-finality loop on all three validators before replacing
   the first node. The Terraform-bound activation epoch must remain in the
   future. Read back all three through SSM and require, for each validator:
   SSM Online, `junca-validator.service` active, `/var/lib/junca` mounted,
   read-only SQLite `PRAGMA quick_check=ok`, exact runtime artifact digest, and
   a `FINALIZED` certificate that binds its durable head. All three heads and
   certificate hashes must match.
4. Update only the validator returned as `next_validator` by
   `evaluate_rolling_compatibility`. Re-read version, health and finalized head
   after every node. A newly booted replacement is immediately returned to the
   disabled state before the gate is evaluated. Never update out of order, and
   never advance unless all three validators pass the complete per-validator
   readback and remain at or above their rollback floors.
5. After all three report the exact target version and pass service, durable
   state, head and certificate checks, require `READY_FOR_SLOT_EPOCH`. Set the
   same future canonical slot epoch on all three while the block interval
   remains zero.
6. Read back the epoch from all three. Only
   `READY_FOR_FINALITY_ENABLE` permits enabling automatic finality.
7. Enable automatic finality consistently on all three against the still-future
   epoch and require `ACCEPTED`. Runtime acceptance is based on consecutive
   automatic canonical slots; the unaudited `junca_broadcastVote` manual RPC is
   prohibited because it has no peer-delivery acknowledgement.

If a Foundation Release stops after a partial replacement, preserve its
`rolling-resume-evidence.json` and checksum artifact. Dispatch the same
Foundation workflow and candidate with `resume_run_id` set to that exact failed,
cancelled or timed-out run. Resume is permitted only when GitHub provenance,
workflow head, AMI Build run, Manifest Gate run, request digest and manifest
decision digest all match. The original 30-second-aligned slot epoch is part of
the checksummed evidence and must be reused unchanged in Terraform/user data.
It must retain between 900 and 7,230 seconds of lead time; missing, altered,
expired, too-near or excessively future epoch evidence rejects the resume. The
live validators must form a strict ordered
target-runtime/target-AMI prefix of length 0, 1, 2 or 3; Terraform replacement
addresses must be the exact remaining suffix. Previously accepted prefix
instances must retain their instance identity and may not regress below their
recorded head/certificate. Live discovery may exceed the recorded prefix by at
most one validator, covering a stop between one targeted apply and its evidence
write. A larger delta is stale evidence. A gap, unknown AMI, checksum failure,
candidate mismatch, changed EBS/snapshot binding or state rewind rejects the
resume. A 3/3 prefix resumes only the separately gated finality activation.

Any mixed finality state, one unhealthy or unmanaged validator,
finalized-head/certificate disagreement, unexpected version, partial epoch
configuration, active fallback, invalid rollback evidence, epoch expiry before
activation, or release-boundary drift stops the rollout. Rollback must keep
automatic finality disabled, use the recorded immutable previous artifact and
reattach the same retained durable volume; finalized state must never be
rewound. Mainnet, asset movement and bridge activation remain out of scope.
