# Isolated Three-Validator Development Network

## Status

Development simulation only. This environment does not represent Public Testnet,
Mainnet Candidate or Mainnet production operation.

## Purpose

The local network exercises the canonical JUNCA validator runtime across three
independent containers with deterministic zero-allocation genesis, authenticated
vote transport, strict three-of-three finality, persistent state and restart
acceptance.

## Start

```bash
make local-network-up
make local-network-status  # use the direct script status command until this alias is added
```

Current validator health endpoints:

- `http://127.0.0.1:18545/health`
- `http://127.0.0.1:18546/health`
- `http://127.0.0.1:18547/health`

## Full acceptance

```bash
make local-network-test
```

The acceptance procedure verifies:

1. all three validators reach the same finalized head;
2. stopping validator-03 prevents two-validator false finality;
3. restarting validator-03 restores quorum and advances finality;
4. every health response preserves the Mainnet, asset and bridge safety boundary;
5. evidence is written to `artifacts/local-network/acceptance.json`.

## State management

```bash
make local-network-down   # preserve development state
make local-network-reset  # remove all local validator and genesis volumes
```

## Signer boundary

The network uses `DeterministicDevelopmentKmsAdapter`, which exposes the same
`sign` and `verify` interface as the production AWS KMS adapter but contains no
private key material. Signatures are deterministic simulation values and have no
cryptographic or production authority.

The adapter is available only when:

```text
JUNCA_LOCAL_DEVELOPMENT=1
```

It accepts only these non-production resource identifiers:

```text
arn:aws:kms:local:000000000000:key/validator-01
arn:aws:kms:local:000000000000:key/validator-02
arn:aws:kms:local:000000000000:key/validator-03
```

## Prohibited use

- Public Testnet deployment
- Mainnet Candidate release evidence
- Mainnet operation
- transaction or asset custody
- bridge activation
- production-state import
- production KMS/HSM substitution

## Fixed safety state

```text
Mainnet Changed: false
Assets Moved: false
Bridge Activated: false
```
