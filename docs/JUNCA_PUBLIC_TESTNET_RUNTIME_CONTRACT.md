# JUNCA Social Ecosystem Chain — Public Testnet Runtime Contract

Governance: JAIOS Institutional Governance  
Network: Public Testnet / No Monetary Value

The immutable validator AMI must provide all of the following before
`deployment_enabled=true` is permitted:

- `/usr/local/bin/junca-chain-node`, executable and matching `binary_sha256`
- `/etc/junca/genesis.json`, matching `genesis_sha256`
- `/etc/junca/validator.toml`, non-secret runtime configuration
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

Immutable boundaries:

- Mainnet Changed=false
- Assets Moved=false
- Bridge Activated=false
- Bridge Route=PAUSED
- Deployment Performed=false until a separately authorized apply
