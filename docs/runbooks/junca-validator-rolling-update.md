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
   certificate hashes must match. If an existing service is stopped at this
   boundary, the workflow may restart only that service after SSM Online,
   retained-volume mount, SQLite integrity, and the single exact runtime digest
   are verified. It records before/after evidence and immediately returns to
   the same strict readback; it never treats the restart itself as acceptance.
   A failed prerequisite or failed health readback stops before Terraform
   mutation and preserves service diagnostics for the next repair.
   A fresh rollout may encounter an ordered, heterogeneous legacy baseline.
   Before service recovery, bind each current instance separately to its exact
   EC2 AMI ID and the AMI's unique `NodeArtifactSHA256`, `GenesisSHA256`,
   `SourceCommit`, `Network`, and `Governance` tags. Require the exact AWS
   account, region, instance state, private self-owned AMI, architecture,
   virtualization and EBS root-device readback. Never normalize three current
   validators to one historical AMI by assertion. A resumed rollout must use
   the checksummed per-validator instance, AMI and runtime bindings from its
   exact resume evidence; any live or provenance drift stops before mutation.
   If the retained volume is still attached to the exact current instance but
   `/var/lib/junca` is not mounted, the zero-prefix recovery may stop the
   already-unhealthy validator and re-run only the AMI-installed canonical
   `junca-validator-state.service`. Before doing so it must prove the
   Terraform volume ID equals the single encrypted AWS attachment, the NVMe
   by-id serial equals that volume ID, the device is not mounted elsewhere,
   the unmounted target is a real directory, and the filesystem is `ext4` or
   `xfs`. An empty target is accepted. A non-empty target is accepted only
   after the stopped service leaves an exact allowlist of single-link regular
   `state.sqlite`, `state.sqlite-wal`, and `state.sqlite-shm` files, with the
   database passing read-only `PRAGMA quick_check=ok`. The exact diagnostic
   directory `scan-rollbacks` may also be admitted only when its complete
   same-filesystem tree is bounded to 1,000 entries and 1 GiB, contains only
   root/JUNCA-owned directories and single-link regular files, and contains no
   symlink, mount, device, socket, FIFO, or hard link. Before the retained EBS
   is mounted, atomically rename that directory into root-only
   `/var/lib/junca-unmounted-recovery` using a content-manifest SHA-256 name,
   fsync both parent directories, and record the exact destination and digest.
   This preserves the failed-run evidence outside the mount shadow without
   deleting or overwriting it. The retained EBS mount masks any admitted local
   SQLite legacy files, so an unmount remains a non-destructive rollback. Any
   other name, unsafe entry, oversized tree, destination collision, cross-
   filesystem rename, or invalid database blocks recovery. The installed mount
   helper and systemd unit must be exact, single-link root-owned canonical
   files. Persistence repair must also atomically install the exact
   `junca-validator.service.d/validator-state.conf` dependency drop-in before
   `daemon-reload`; its parent must be a real root-owned `0755` directory and
   the drop-in a real single-link root-owned `0640` file with byte-exact
   `Requires`, `After`, `RequiresMountsFor`, and state path conditions.
   Symlinks, non-root ownership, link-count drift, content drift, or a
   same-path collision block recovery. Do not overwrite the vendor validator
   unit or use an interactive systemd editor. Afterward require the exact resolved device as the
   mount source, `noatime,nosuid,nodev`, an active enabled persistence unit,
   and read-only SQLite integrity. Never format, repair, relabel, detach,
   replace, or restore the volume in this recovery. Any mismatch leaves the
   validator stopped as a circuit breaker and blocks runtime reconstruction.
   When the exact failure is a missing `/etc/junca/runtime.env`, reconstruction
   is allowed only before any validator replacement (`updated_count=0`) and only
   after exact current AMI, runtime archive, genesis, retained state,
   `PRAGMA quick_check`, KMS signer binding and peer binding readback. Generate
   the file from those Terraform-canonical values, write it atomically as
   `root:junca` mode `0640`, and require its calculated SHA-256 before restart.
   Use a same-directory temporary file plus an atomic no-overwrite hard-link;
   fsync the temporary file before linking and `/etc/junca` after linking.
   Record the installed device/inode identity. Treat a concurrent destination,
   unresolved multi-link result, or failed persistence sync as a blocked
   recovery, never as a reason to overwrite.
   A stopped legacy validator may also lack the empty compatibility
   `/etc/junca/validator.toml` supplied by the current immutable AMI. Admit that
   case only when the destination is wholly absent, create a zero-length
   `root:junca` `0640` single-link inode with the same no-overwrite hard-link
   pattern, sync the file and directory, and prove service-user readability.
   Never replace or truncate an existing validator configuration. For an
   existing root-owned, single-link regular file, pin device/inode, SHA-256,
   and byte size before the controlled stop. Group and mode may then be
   normalized to `root:junca` `0640`; contents and inode must remain exact.
   Re-read identity, digest, size, ownership, mode, and link count before
   restart and after the validator reports healthy. A path replacement,
   content drift, size drift, permission drift, or hard-link race blocks
   activation even when the health endpoint is healthy.
   Parse all 18 canonical runtime assignments and require every key exactly
   once with its exact expected value. Reject duplicates even when whitespace
   hides the second assignment; never rely on `grep` finding one good line when
   systemd may consume a later contradictory line. Reject unknown assignments
   and non-canonical syntax rather than allowing an unreviewed runtime toggle.
   Never repair a symlink, overwrite an existing contradictory file, accept an
   operator-supplied value, or reconstruct during a mixed/resumed prefix.
   If the reconstructed runtime does not reach an active, healthy state within
   the bounded recovery window, stop the service and remove only the exact
   canonical file created by this attempt. Never delete a linked, changed, or
   otherwise unrecognized file; fsync the directory after removal and block the
   rollout for operator inspection unless durable rollback is proven.
   If the validator was already active and healthy but its configuration access
   contract failed, admit repair only after exact validator-ID, retained-state,
   runtime and genesis readback. Stop only that validator once and prove it
   inactive before mutation. If repair acceptance fails, make at most one
   containment start and require the same healthy validator ID within 30 polls.
   Record containment separately and keep acceptance false; do not retry repair,
   loop service restarts, or touch another validator. For successful repair,
   require the post-restart loopback response to report both `healthy` and the
   exact expected validator ID. Persist that readback as `health_validator_id`
   in service-recovery evidence schema v6; status-only health is not sufficient.
   Require the same evidence to match the canonical recovery request SHA-256,
   exact SSM Command ID and dispatch sequence `1`. The request digest must bind
   validator, instance, AMI, runtime, canonical runtime environment, genesis,
   retained volume, source commit, current workflow run ID and attempt,
   immutable release-request digest, manifest-decision digest, candidate head,
   and the exact runtime-environment repair authorization. Never reuse an
   earlier run, attempt, decision, repair mode, or dispatch result.
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

The parent release must invoke the dispatch helper with an
`artifacts/.../*.json` evidence path. The helper atomically records the exact
child run ID, URL, workflow identity, expected head, status and conclusion
before it returns failure. Its stdout remains the numeric run ID on success
only; failure details go to stderr. Because the parent uploads `artifacts/`
under `if: always()`, a failed Foundation run remains directly diagnosable and
must be inspected before any retry or resume. Missing dispatch evidence is a
release-observability gate failure, not permission to redispatch blindly.

Any mixed finality state, one unhealthy or unmanaged validator,
finalized-head/certificate disagreement, unexpected version, partial epoch
configuration, active fallback, invalid rollback evidence, epoch expiry before
activation, or release-boundary drift stops the rollout. Rollback must keep
automatic finality disabled, use the recorded immutable previous artifact and
reattach the same retained durable volume; finalized state must never be
rewound. Mainnet, asset movement and bridge activation remain out of scope.
