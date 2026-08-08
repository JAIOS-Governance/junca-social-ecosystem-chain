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

## Block header V2 activation safety

Receipt-committing V2 block headers are a coordinated consensus upgrade, not a
per-validator deployment toggle. Keep
`--block-header-v2-activation-height` absent while the three validators run
different runtime versions. After all three validators run the exact same
reviewed source and runtime artifact, choose one shared future finalized height
with enough lead time to complete readback, bind that exact positive integer
through the separately reviewed immutable service configuration on all three
validators, and verify each Health response reports the same stored activation
height before it is reached. A missing, past, unequal, changed or non-integer
height blocks activation. Never reinterpret an existing finalized V1 block as
V2. A restored pruned checkpoint begins local V2 integrity checks at its next
height while preserving the trusted checkpoint block hash.

At the activation height, require all three proposals and votes to use header
version `2`; the header commits the versioned transition root, ordered
transaction hashes, sender and recipient binding, gas price, base-fee burn,
validator tip, aggregate execution values and state root. Any validator still
reporting header version `1` is a consensus-safety stop condition. Rollback may
return to the prior runtime only before the activation height. After a V2 block
is finalized, use forward repair with the same activation record; never roll
back the header rule or rewrite finalized state.

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
   A stale predecessor `runtime.env` may be canonically replaced only after
   the same controlled stop. Require a root-owned, single-link regular file,
   mode `0600`/`0640`/`0644`, at most 8192 bytes, and exactly the 18 allowlisted
   assignments with no foreign keys. Pin inode, SHA-256, size, owner, and mode;
   create and verify a same-directory hard-link rollback copy; then atomically
   install the exact canonical file. If restart acceptance fails, restore the
   pinned original inode before containment restart. Never repair symlinks,
   foreign assignments, identity/digest drift, or a rollback-path collision.
   A stopped legacy validator may also lack the empty compatibility
   `/etc/junca/validator.toml` supplied by the current immutable AMI. Admit that
   case only when the destination is wholly absent, create a zero-length
   `root:junca` `0640` single-link inode with the same no-overwrite hard-link
   pattern, sync the file and directory, and prove service-user readability.
   Never replace or truncate an existing validator configuration. For an
   existing root-owned, single-link regular file, pin device/inode, SHA-256,
   and byte size before the controlled stop. Group and mode may then be
   normalized to `root:junca` `0640`; contents and inode must remain exact.
   A legacy predecessor may also lack the `junca` service principal. Only
   after the exact healthy validator has been stopped may recovery create the
   fixed system identity `junca` UID/GID `992`, home `/var/lib/junca`, shell
   `/sbin/nologin`, without creating a home directory. Existing names or
   numeric IDs must match that contract exactly; any conflicting passwd or
   group record blocks repair. A partially completed exact group creation is
   resumable, while no non-canonical identity is edited or deleted.
   A retained database may still be inaccessible after an immutable-instance
   replacement when its prior file ownership does not match the fixed `junca`
   UID/GID. Only while that exact validator is stopped, and only after the
   retained volume identity, mount contract and read-only SQLite integrity have
   passed, admission may normalize `/var/lib/junca` plus the exact allowlist
   `state.sqlite`, `state.sqlite-wal`, and `state.sqlite-shm`. Require a real
   directory, real single-link regular files on the mounted filesystem,
   root/JUNCA ownership and non-writable legacy modes; pin device, inode and
   size before mutation. Set only the directory to `junca:junca` `0750` and
   present allowlisted files to `junca:junca` `0600`, fsync each path, prove
   every pinned identity and size unchanged, and run `PRAGMA quick_check` as
   the service user through a read/write-opened, query-only connection. Never
   infer that canonical runtime configuration makes legacy state ownership
   safe. During live-prefix readback, an exact active and healthy validator
   with mismatched state access must enter the same identity-bound controlled
   stop before this allowlisted repair; a degraded service, wrong validator ID,
   unverified system identity, or failed stop remains blocked. Never
   recurse, touch another entry, copy, truncate, format, detach, replace, or
   repair the database. A symlink, hard link, special file, cross-filesystem
   entry, foreign owner, broad mode or failed service-user readback blocks the
   rollout before restart.
   Every shape and metadata predicate must return immediately on failure,
   including when the admission helper is evaluated inside a shell
   conditional. This keeps a wholly absent path on the explicit create-empty
   route instead of misclassifying it as a pre-existing file with empty
   readback values.
   The same condition-safe rule applies to every controlled-stop predicate:
   a failed health, identity, durable-state, binary, or genesis check must
   return before `systemctl stop` is reachable. Legacy private metadata may be
   normalized from runtime-directory modes `0700`, `0710`, `0750`, or `0755`
   and digest-pinned genesis modes `0600`, `0640`, or `0644`; group- or
   world-writable modes remain outside admission.
   Re-read identity, digest, size, ownership, mode, and link count before
   restart and after the validator reports healthy. A path replacement,
   content drift, size drift, permission drift, or hard-link race blocks
   activation even when the health endpoint is healthy.
   Evaluate inode identities and SHA-256 strings only with lexical shell tests;
   never route colon-bearing device/inode identities or hexadecimal digests
   through arithmetic evaluation. Both the pinned-existing and canonical-empty
   branches must be independently executable and fail closed on drift.
   Parse all 18 canonical runtime assignments and require every key exactly
   once with its exact expected value. Reject duplicates even when whitespace
   hides the second assignment; never rely on `grep` finding one good line when
   systemd may consume a later contradictory line. Reject unknown assignments
   and non-canonical syntax rather than allowing an unreviewed runtime toggle.
   Never repair a symlink, overwrite an existing contradictory file, or accept
   an operator-supplied value. During a mixed/resumed prefix with automatic
   finality configured, a canonical-key-only `runtime.env` may carry the
   previously accepted slot epoch while Terraform is already bound to the
   renewed shared epoch. Reconcile only that pinned file through the same
   exact-identity, one-validator controlled-stop path; atomically replace it
   with the rendered canonical environment and require strict post-restart
   validator-ID, health, owner, mode, inode, digest, and persistence readback.
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
   After each Terraform replacement, do not proceed directly from SSM Online
   to finality quiesce. First require the exact candidate AMI and retained EBS
   attachment, then run the bounded canonical service recovery against only
   the newly created instance. It must reconstruct an absent `runtime.env`,
   prove its SHA-256/owner/mode/inode and service-user readability, restart the
   validator, and read back the exact healthy validator ID. A failed recovery
   is a serial circuit breaker: keep later validators untouched and do not
   mutate finality or mark the replacement accepted.
   If that replacement has already committed in Terraform and makes the
   ordinary public baseline unavailable solely because its mutable
   `runtime.env` is absent, use the main-push-only Validator 01 Runtime
   Recovery V2 incident workflow. It admits only the exact running instance,
   AMI, retained EBS attachment, Terraform signer set and disabled-finality
   state, then calls the same bounded helper once. It cannot run Terraform
   apply, replace an instance or detach a volume. After success, return to the
   unchanged baseline and manifest gates; incident repair is not rollout
   acceptance.
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
one-shot resume request may bind the exact phrase
`RENEW_EXPIRED_QUIESCED_EPOCH` and a preserved prefix count from `1` through
`3`; the orchestrator forwards that pair unchanged. `NONE` is valid only with
prefix `0`, and partial or contradictory pairs fail before workflow dispatch.
After the live-prefix gate, Foundation reuses an already quiesced readback only
when all three validators independently report `false/0/0` through both
`runtime.env` and Health, the promoted prefix is bound to the exact candidate,
and every safety boundary is false. Otherwise it performs the existing
fail-closed quiesce mutation; an ambiguous or failed readback never advances to
the next validator.
The live validators must form a strict ordered
target-runtime/target-AMI prefix of length 0, 1, 2 or 3; Terraform replacement
addresses must be the exact remaining suffix. Previously accepted prefix
instances must retain their instance identity and may not regress below their
recorded head/certificate. Live discovery may exceed the recorded prefix by at
most one validator, covering a stop between one targeted apply and its evidence
write. After that exact one-node delta passes retained-volume, rollback,
candidate AMI/runtime, health, finalized-head and finality-provenance readback,
the workflow promotes the observed contiguous prefix to its run-local evidence
floor before quiescing finality or planning the next validator. The original
checksummed resume artifact is preserved separately and is never rewritten.
A larger delta is stale evidence. A gap, unknown AMI, checksum failure,
candidate mismatch, changed EBS/snapshot binding or state rewind rejects the
resume. A 3/3 prefix resumes only the separately gated finality activation.
The long rollout epoch is a replacement safety boundary, not the live start
time. After all three exact-runtime validators pass SSM, service, retained
volume and finalized-certificate readback, Foundation binds a separate
`junca-finality-activation/v1` artifact to the exact runtime and ordered
instances. It then re-anchors all three nodes to one future 30-second boundary
with a bounded three-minute lead, disables finality before the coordinated
write, and only then enables it. The pre-slot readback permits an authenticated
vote count from zero through three because no vote is due before the bound
slot; the following gate still requires two fresh consecutive heights with
matching timestamps and exact current 3/3 certificates. A stale epoch,
unbound instance, partial write, boundary drift or failed readback compensates
to disabled `false/0/0` and stops.
The replacement safety epoch and live activation epoch are distinct contracts.
The former retains 900 to 7,230 seconds for serial replacement. Only after all
three validators are the exact target runtime may an explicit
`finality_activation_contract` admit the next-slot epoch with 30 to 210 seconds
remaining. Missing, non-boolean, partial-prefix, too-near or too-far activation
evidence remains rejected; the near-term exception cannot authorize a rolling
replacement.
The evidence-bound gate carries both epochs explicitly during that handoff:
`baseline_slot_epoch_seconds` must match the immutable 3/3 rollout baseline,
while `requested_slot_epoch_seconds` must match the newly configured activation
readback. They may differ only under the exact 3/3 activation contract. This
prevents a recovered long-running rollout from reusing an expired baseline
epoch while preserving the prior evidence binding through the coordinated
disable/configure/enable transition.
The cross-head comparison allowlist includes the live-prefix gate, its focused
negative tests, and this acceptance contract because those files implement and
specify the same bounded recovery decision. No unrelated runtime, Mainnet,
asset, bridge, or general infrastructure path is admitted by that exception.

Automatic finality binds every timestamped proposal's consensus round to its
canonical slot timestamp. The round is therefore deterministic across all
three validators and never reuses a retained signing-journal coordinate after
an activation epoch changes. Manual proposals retain their explicit round
contract. A validator restart must also re-enable and restart both read-only
public gateways after the private validator health check, then prove local RPC
and Explorer health before public endpoint acceptance; validator health alone
cannot admit an ALB target.

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

### Superseding a stale finality monitor

An orchestrator waiting on an older Foundation child may be superseded by a
newer signed one-shot request because the orchestrator is only a monitor; it
does not hold the Terraform state lock. Foundation execution remains on the
shared `junca-public-testnet-aws-foundation` concurrency group. The sole v24
exception is bound to AMI run `30682660387`, manifest run `30683678492`, and
completed failed Foundation run `30688476089`. That source run proves all
three exact-runtime validators healthy and the later run proves the obsolete
Foundation child has completed every mutation and is sleeping only in finality
readback. No wildcard, prefix, renewal, alternate run, or alternate artifact
may enter the exception group. The resumed execution must still re-read all
three validators, bind the activation evidence, and prove two consecutive
canonical 3/3 finalized slots before acceptance.
