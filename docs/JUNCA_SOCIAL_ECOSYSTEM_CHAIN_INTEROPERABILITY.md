# JUNCA Social Ecosystem Chain — Testnet Interoperability

**Public Testnet / Protocol Validation Environment**

Governance: **JAIOS Institutional Governance**

## Scope

The partner interoperability architecture covers Ethereum / ERC, BSC Testnet
and TRON Shasta. The current control plane prepares audited routes from JUNCA
Public Testnet to BSC Testnet and TRON Shasta. The Ethereum target-network
binding, Chain ID, RPC and contracts remain **Planned / Pending Verification**.
It validates configuration and emits deterministic evidence. It does **not**
deploy contracts, operate relayers, or move assets.

Supported mappings:

| Asset | JUNCA | Ethereum / ERC | BSC Testnet | TRON Shasta |
|---|---|---|---|---|
| Fungible token | ERC-20 | ERC-20 — Planned / Pending Verification | BEP-20 | TRC-20 |
| NFT | ERC-721 | ERC-721 — Planned / Pending Verification | ERC-721 (BSC-compatible) | TRC-721 |

## Safety model

Every new route starts paused and fails closed. Activation requires all of:

- deployed source and destination contracts;
- independent security review;
- three or more distinct relayers with a threshold of at least two;
- verified relayer keys and multisig custody;
- finality, per-transaction and daily limits;
- replay protection and role separation;
- an approved incident runbook.

The included `.pending.json` files deliberately contain non-production
placeholder contract addresses and false attestations. Therefore their expected
state is `BLOCKED`.

## Validate

```bash
python scripts/junca_social_ecosystem_chain_interoperability.py \
  --specification config/junca_social_ecosystem_chain_bsc_interoperability.pending.json \
  --expect-state BLOCKED

python scripts/junca_social_ecosystem_chain_interoperability.py \
  --specification config/junca_social_ecosystem_chain_tron_interoperability.pending.json \
  --expect-state BLOCKED
```

## Bridge protocol reference engine

`bridge_protocol.py` implements the testable state sequence:

`OBSERVED → FINALITY_PENDING → ATTESTED → EXECUTION_READY → EXECUTED`

The reference engine supports JUNCA-to-BSC and TRON-to-JUNCA directions and
enforces domain-separated message digests, source-transaction and nonce replay
protection, confirmation depth, verified relayer attestations, quorum,
pause-before-activation, transaction limits, daily limits and terminal-state
rules.

The simulation CLI emits evidence without connecting a wallet, deploying a
contract or transferring an asset:

```bash
python scripts/junca_social_ecosystem_chain_bridge_simulation.py \
  --scenario config/junca_social_ecosystem_chain_bsc_bridge.simulation.json \
  --output artifacts/junca-social-ecosystem-chain-bsc-bridge-simulation.json

python scripts/junca_social_ecosystem_chain_bridge_simulation.py \
  --scenario config/junca_social_ecosystem_chain_tron_bridge.simulation.json \
  --output artifacts/junca-social-ecosystem-chain-tron-bridge-simulation.json
```

Simulation signatures are non-secret fixtures. A real route must use
chain-appropriate cryptographic verification, KMS/HSM-backed relayer keys and
independently audited bridge contracts before activation.

## Network identity

Ethereum / ERC connectivity is part of the approved partner architecture, but
the target Ethereum network, Chain ID, RPC endpoints and contract bindings are
not yet verified and therefore remain `BLOCKED`.

BSC Testnet is validated as EVM Chain ID `97`. TRON Shasta is identified by the
explicit network identifier `tron-shasta`; this project does not invent an EVM
chain ID for TRON. Only allowlisted HTTPS testnet endpoints are accepted.

## Primary specifications

- BNB Smart Chain JSON-RPC endpoints:
  <https://docs.bnbchain.org/bnb-smart-chain/developers/json_rpc/json-rpc-endpoint/>
- TRON networks:
  <https://developers.tron.network/docs/networks>
- TRON token standards:
  <https://developers.tron.network/docs/token-standards-overview>
- TRC-20 interface:
  <https://developers.tron.network/docs/trc20-protocol-interface>
- TRC-721 interface:
  <https://developers.tron.network/docs/trc-721-protocol-interface>
