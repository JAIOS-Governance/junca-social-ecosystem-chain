# JUNCA Social Ecosystem Chain — Public Testnet Runtime Contract

Governance: JAIOS Institutional Governance  
Network: Public Testnet / No Monetary Value

The immutable validator AMI must provide all of the following before
`deployment_enabled=true` is permitted:

- `/usr/local/bin/junca-chain-node`, executable and matching `binary_sha256`
- `/etc/junca`, owned by `root:junca` with mode `0750`
- `/etc/junca/genesis.json`, matching `genesis_sha256`, owned by
  `root:junca` with mode `0640`, and readable by the `junca` service user
- `/etc/junca/validator.toml`, an explicitly created empty compatibility file,
  owned by `root:junca` with mode `0640`, and readable by the `junca` service
  user. The current node accepts `--config` for command-line compatibility but
  does not consume file content; the AMI must not inherit this path from a
  prior host or recovery action
- local `junca` user and group
- `/var/lib/junca`, owned by `junca:junca`
- AWS KMS signing support through the EC2 instance role

Instance bootstrap verifies the binary and genesis digests before writing or
starting `junca-validator.service`. The validator JSON-RPC boundary remains
loopback-only. The service receives only the external KMS resource ARN; private
key material is prohibited from user data, Terraform state, and evidence.

Any missing file, digest mismatch, service-start failure, or inactive service
causes bootstrap to fail closed. Terraform remains disabled until the AMI,
three independent KMS signers, three private failure domains, state backend,
RPC and explorer image digests, and rollback target have canonical readback.

The live-prefix recovery may repair only this narrow contract on an inactive
validator. It requires a real root-owned directory, a real single-link
root-owned genesis, an exact genesis digest, and pre-repair modes limited to
`0750`/`0755` and `0640`/`0644`. An existing validator configuration must be a
root-owned single-link regular file within those modes. A legacy predecessor
with no validator configuration may receive only the canonical zero-length
compatibility file through a synced same-directory, no-overwrite hard-link
install. After applying `root:junca` ownership and canonical modes, recovery
syncs both files and the directory and proves zero-length compatibility config
and readability as the `junca` service user. Symlinks, hard links, existing
non-empty content during creation, non-root ownership, unexpected modes,
digest mismatch or destination races fail closed. An active service is
repairable only through the serial controlled-active path: exact retained-state,
runtime, genesis, healthy loopback and validator-ID readback must precede one
service stop; inactivity must be proven before mutation. A failed repair may
perform one containment start for that same validator, but containment evidence
is never accepted as successful repair or rollout evidence. After repair, the
healthy loopback response must again carry the exact validator ID. Evidence
schema v4 records this as `health_validator_id`; a missing or different ID
blocks serial advancement even when the reported status is `healthy`.

Immutable boundaries:

- Mainnet Changed=false
- Assets Moved=false
- Bridge Activated=false
- Bridge Route=PAUSED
- Deployment Performed=false until a separately authorized apply
