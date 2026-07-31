# JUNCA Social Ecosystem Chain Development Environment

Authority: JAIOS Institutional Governance  
Status: Development baseline / no Mainnet activation authority

## Purpose

This environment standardizes protocol, consensus, state, validator, RPC,
release-evidence and infrastructure development for JUNCA Social Ecosystem
Chain. It does not expose signer secrets and does not authorize deployment,
Mainnet activation, asset movement or bridge activation.

## Canonical development layers

### 1. Protocol core — primary

The current executable validator runtime is Python. The primary development
loop is therefore:

1. edit modules under `jaios/social_ecosystem_chain/`;
2. run the complete unit suite;
3. build the deterministic runtime archive;
4. verify the runtime layout and SHA-256 evidence;
5. generate a zero-allocation three-validator genesis;
6. submit changes through a reviewed pull request.

Use `make dev-test` as the canonical local acceptance command.

The transfer-only protocol kernel charges deterministic intrinsic gas for the
transaction envelope before signature admission or block selection: `21,000`
base gas plus `4` for each zero calldata byte and `16` for each non-zero
calldata byte. The same calculation is used by mempool admission, deterministic
candidate capacity, execution fee/burn/tip accounting, and receipts. A declared
gas limit below that amount fails closed; calldata can never consume fixed base
gas while bypassing block capacity. These are Candidate Mainnet correctness
controls only and do not authorize Mainnet activation.

### 2. Runtime and infrastructure — primary

The development container includes Docker, GitHub CLI, AWS CLI and Terraform
for local packaging, CI inspection and infrastructure planning. Production
credentials, validator keys, seed phrases and static long-lived credentials are
prohibited from the repository and development container.

Terraform planning and AWS readback are separate from deployment. Any
production mutation remains subject to the existing release and approval gates.

### 3. Smart-contract laboratory — isolated track

Foundry is the preferred future contract-testing tool for Solidity unit, fuzz,
invariant and deployment-script work. Hardhat is optional for TypeScript-heavy
integration tests and application SDK workflows.

The contract laboratory must remain isolated from protocol consensus and
validator release acceptance. It is added only when canonical EVM contract
sources and acceptance requirements exist; contract tooling must not be treated
as the chain protocol implementation.

### 4. Local network simulation — next implementation track

A deterministic local three-validator simulation must use development-only
signer adapters. It must never accept production KMS/HSM keys or copy production
state. Required acceptance includes quorum, finality, restart recovery, peer
partition, stale-validator recovery, state persistence and read-only RPC tests.

### 5. Observability — next implementation track

Use OpenTelemetry Collector as the vendor-neutral telemetry boundary, Prometheus
for numeric time-series collection and alert rules, and Grafana for local
visualization. Datadog and other paid backends are optional exporters, not
required dependencies.

Required protocol metrics include:

- finalized height and finality lag;
- quorum and validator availability;
- peer count and peer-delivery failures;
- mempool depth and rejected transactions;
- state commit latency and recovery duration;
- RPC request rate, latency and unsafe-method rejection;
- exact source commit, runtime artifact SHA-256 and genesis SHA-256 labels.

## Entry points

```bash
make doctor
make unit
make runtime
make genesis
make dev-test
```

## Development container

Open the repository in GitHub Codespaces or VS Code Dev Containers. The
`.devcontainer/devcontainer.json` configuration provides a consistent Linux,
Python, Docker, AWS CLI, GitHub CLI and Terraform environment.

Codespaces is optional. A local Windows workstation can use Docker Desktop and
VS Code Dev Containers with the same repository configuration.

## Safety boundaries

- Public Testnet only until separate Mainnet acceptance and CEO final approval.
- No private keys, seed phrases or signer secret values.
- No automatic merge, release dispatch or deployment from the developer
  container.
- No production-state import into local simulation.
- Mainnet changed: false.
- Assets moved: false.
- Bridge activated: false.
