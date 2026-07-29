# JUNCA Public Testnet Validator Rolling Update

This runbook is limited to the three Public Testnet validators. It does not
authorize Terraform apply, deployment, Mainnet changes, asset movement, or
bridge activation.

## Fresh immutable-candidate handoff

Do not run these commands until the protected `public-testnet` GitHub
environment and the non-OIDC AWS bootstrap boundary have both been read back
by an independent reviewer. Obtain the parent AMI ID, owner, immutable name,
repository release and both package NEVRAs from the approved supply-chain
record. Values named `latest`, blank values and values inferred from the
repository policy file are prohibited.

Dispatch the controller only from the exact successful runtime-artifact commit
on `main`:

```bash
JSEC_REPOSITORY=JAIOS-Governance/junca-social-ecosystem-chain
SOURCE_RUN_ID=REPLACE_WITH_SUCCESSFUL_RUNTIME_ARTIFACT_RUN_ID
SOURCE_COMMIT=REPLACE_WITH_EXACT_40_CHARACTER_MAIN_COMMIT
PARENT_AMI_ID=REPLACE_WITH_APPROVED_PARENT_AMI_ID
PARENT_AMI_OWNER_ID=REPLACE_WITH_APPROVED_12_DIGIT_OWNER_ID
PARENT_AMI_NAME=REPLACE_WITH_APPROVED_IMMUTABLE_PARENT_AMI_NAME
DNF_RELEASEVER=REPLACE_WITH_APPROVED_EXACT_RELEASEVER
PYTHON3_BOTO3_NEVRA=REPLACE_WITH_APPROVED_EXACT_NEVRA
PYTHON3_BOTOCORE_NEVRA=REPLACE_WITH_APPROVED_EXACT_NEVRA

[[ "$SOURCE_RUN_ID" =~ ^[1-9][0-9]*$ ]]
[[ "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]]
[[ "$PARENT_AMI_ID" =~ ^ami-[0-9a-f]{8,17}$ ]]
[[ "$PARENT_AMI_OWNER_ID" =~ ^[0-9]{12}$ ]]
[[ "$PARENT_AMI_NAME" != REPLACE_WITH_* ]]
[[ "$DNF_RELEASEVER" != REPLACE_WITH_* ]]
[[ "$PYTHON3_BOTO3_NEVRA" != REPLACE_WITH_* ]]
[[ "$PYTHON3_BOTOCORE_NEVRA" != REPLACE_WITH_* ]]

gh workflow run junca-hardened-immutable-candidate-release-v2.yml \
  --repo "$JSEC_REPOSITORY" \
  --ref main \
  -f source_run_id="$SOURCE_RUN_ID" \
  -f source_commit="$SOURCE_COMMIT" \
  -f parent_ami_id="$PARENT_AMI_ID" \
  -f parent_ami_owner_id="$PARENT_AMI_OWNER_ID" \
  -f parent_ami_name="$PARENT_AMI_NAME" \
  -f dnf_releasever="$DNF_RELEASEVER" \
  -f python3_boto3_nevra="$PYTHON3_BOTO3_NEVRA" \
  -f python3_botocore_nevra="$PYTHON3_BOTOCORE_NEVRA" \
  -f approval_phrase=PUBLIC_TESTNET_IMMUTABLE_CANDIDATE
```

Record the resulting controller run ID as `PARENT_RUN_ID`. After it completes
successfully, download and verify the exact checksummed handoff. The
controller's `manifest_run_id` maps unchanged to the Foundation input
`manifest_gate_run_id`; never select a manifest run by name or recency.

```bash
PARENT_RUN_ID=REPLACE_WITH_SUCCESSFUL_CONTROLLER_RUN_ID
[[ "$PARENT_RUN_ID" =~ ^[1-9][0-9]*$ ]]
EVIDENCE_DIR="$(mktemp -d)"
gh run download "$PARENT_RUN_ID" \
  --repo "$JSEC_REPOSITORY" \
  --name "junca-hardened-immutable-release-v2-${PARENT_RUN_ID}" \
  --dir "$EVIDENCE_DIR"
(
  cd "$EVIDENCE_DIR/release-v2"
  sha256sum --check SHA256SUMS
)
RELEASE_CHAIN="$EVIDENCE_DIR/release-v2/release-chain.json"
jq -e \
  --arg source_commit "$SOURCE_COMMIT" '
    .schema_version == "junca-hardened-immutable-candidate/v3" and
    .state == "PUBLIC_TESTNET_CANDIDATE_READY_FOR_SERIAL_ROLLOUT" and
    .source_commit == $source_commit and
    .candidate_ref == ("release-candidate/" + $source_commit) and
    .serial_rollout_dispatched == false and
    .continuity_dispatched == false and
    .transaction_submission_enabled == false and
    .mainnet_changed == false and
    .assets_moved == false and
    .bridge_activated == false and
    .mainnet_activation_authorized == false
  ' "$RELEASE_CHAIN"

CANDIDATE_REF="$(jq -er .candidate_ref "$RELEASE_CHAIN")"
AMI_RUN_ID="$(jq -er .ami_run_id "$RELEASE_CHAIN")"
MANIFEST_GATE_RUN_ID="$(jq -er .manifest_run_id "$RELEASE_CHAIN")"
```

The controller intentionally does not dispatch a rollout. After a separate
recorded rollout authorization, start a fresh Foundation run with the exact
handoff IDs:

```bash
gh workflow run junca-validator-foundation-release.yml \
  --repo "$JSEC_REPOSITORY" \
  --ref "$CANDIDATE_REF" \
  -f ami_run_id="$AMI_RUN_ID" \
  -f manifest_gate_run_id="$MANIFEST_GATE_RUN_ID" \
  -f resume_run_id=0 \
  -f renew_expired_epoch=NONE \
  -f renewal_preserve_prefix_count=0 \
  -f authorize_rollout=PUBLIC_TESTNET_ROLLOUT
```

1. Record the target runtime version, its exact 40-character lowercase source
   commit, immutable artifact SHA-256, rollback version and rollback artifact
   SHA-256. Pass the recorded runtime commit as the release manifest gate's
   `source_commit`; never substitute a newer documentation-only workflow head.
   Require a passed release manifest gate and a live no-state-rewind rollback
   rehearsal. Record the
   successful gate run ID as the Foundation Release `manifest_gate_run_id`;
   its AMI ID, source commit, runtime artifact SHA-256 and genesis SHA-256 must
   exactly match the selected AMI Build evidence.
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
