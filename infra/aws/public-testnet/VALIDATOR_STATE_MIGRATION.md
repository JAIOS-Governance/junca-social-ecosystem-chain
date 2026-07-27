# Validator durable-state migration

This document defines the fail-closed boundary for moving Public Testnet
validator state from the instance root volume to an independent EBS volume.
Terraform remains the infrastructure source of truth.

## Phase 1: provision and attach only

Set `enable_validator_state_volumes = true`, review the Terraform plan, and
apply only after confirming that it creates exactly three encrypted gp3 EBS
volumes and three attachments. It must not replace an EC2 instance, modify a
KMS signer, recreate bootstrap resources, or change public endpoints.

The default remains `false`, so adopting this source does not modify the
currently running validators.

Do not format or mount any device during this phase. Read back the volume IDs,
availability zones, encryption state, attachments, instance IDs, and current
finalized certificate. Record the output as release evidence.

## Phase 2: migrate one validator at a time

Migration tooling is intentionally not automated by this Terraform module.
For each validator, independently:

1. Confirm the other two validators are healthy and retain quorum.
2. Stop only that validator and verify the process has exited.
3. Snapshot its current root EBS volume.
4. Resolve the attached EBS volume by its exact AWS volume ID. Never assume
   that `/dev/sdf` is the Linux NVMe device name.
5. If and only if the new volume is empty, create the approved filesystem.
6. Mount it at a temporary path and copy `/var/lib/junca` while preserving
   ownership, modes, extended attributes, and fsync durability.
7. Compare the state manifest and finalized certificate before switching the
   mount.
8. Add an exact-volume systemd mount dependency ahead of
   `junca-validator.service`; fail closed if the volume is absent.
9. Start the validator, confirm peer catch-up, signer journal continuity, and
   finalized certificate continuity.
10. Capture acceptance evidence before proceeding to the next validator.

Rollback restores the root-volume state path while the validator is stopped.
The new EBS volume and all snapshots are retained for investigation.

## Prohibited

- Parallel migration of two or more validators.
- Formatting a device identified only by a transient Linux device name.
- Forced detach, volume deletion, or `terraform state rm`.
- Copying Testnet state into Candidate Mainnet or Mainnet.
- Mainnet, asset, or bridge activation as part of this migration.
