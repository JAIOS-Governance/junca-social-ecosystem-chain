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

The live-prefix recovery may repair only this narrow metadata contract on an
inactive validator. It requires a real root-owned directory, real single-link
root-owned genesis and validator configuration files, an exact genesis digest,
and pre-repair modes limited to `0750`/`0755` and `0640`/`0644`. It changes no
file content. After applying `root:junca` ownership and the canonical modes, it
syncs both files and the directory, then proves readability as the `junca`
service user. Symlinks, hard links, non-root ownership, unexpected modes,
digest mismatch, or an active service fail closed before metadata mutation.

Immutable boundaries:

- Mainnet Changed=false
- Assets Moved=false
- Bridge Activated=false
- Bridge Route=PAUSED
- Deployment Performed=false until a separately authorized apply
