# Security Policy

## Reporting

Do not disclose vulnerabilities, credentials, validator keys or exploitable
network details in public issues. Use the private security-reporting channel
configured by JAIOS Institutional Governance. Until that channel is verified,
do not publish sensitive details and mark the report for the Security Reviewer.

## Secret handling

- Private keys and seed phrases are prohibited from source, artifacts, logs and
  infrastructure state.
- Validator configuration stores only external KMS/HSM resource references.
- Signer existence and permissions are verified without reading secret values.
- Public RPC is read-only and separated from validator RPC.

## Release safety

Public Testnet release remains blocked if governance identity, signer
resources, quorum, chain/genesis identity, TLS/DNS, unsafe RPC rejection,
monitoring, acceptance or rollback evidence is missing.

Security policy changes are protected changes under `GOVERNANCE.md`.
