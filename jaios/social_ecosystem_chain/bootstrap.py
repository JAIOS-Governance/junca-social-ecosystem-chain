"""Fail-closed build and private-testnet bootstrap contracts."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping


class ChainBootstrapError(RuntimeError):
    """Raised when build or network bootstrap controls are unsafe."""


@dataclass(frozen=True)
class LegacyBuildContract:
    repository: str
    commit: str
    tag: str
    go_directive: str
    builder_image: str
    runtime_image: str
    build_command: tuple[str, ...]
    output_path: str
    build_status: str

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "junca-legacy-build-contract/v1",
            "repository": self.repository,
            "commit": self.commit,
            "tag": self.tag,
            "go_directive": self.go_directive,
            "builder_image": self.builder_image,
            "runtime_image": self.runtime_image,
            "build_command": list(self.build_command),
            "output_path": self.output_path,
            "contract_status": "valid",
            "binary_build_status": self.build_status,
        }


@dataclass(frozen=True)
class SovereignTestnetBootstrap:
    network_name: str
    release_stage: str
    chain_id: int
    chain_id_status: str
    registration_status: str
    consensus_engine: str
    validator_count: int
    validator_quorum: int
    bootnode_count: int
    rpc_node_count: int
    failure_domains: int

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "junca-sovereign-testnet-bootstrap/v1",
            "network_name": self.network_name,
            "release_stage": self.release_stage,
            "chain_id": self.chain_id,
            "chain_id_status": self.chain_id_status,
            "registration_status": self.registration_status,
            "consensus_engine": self.consensus_engine,
            "validator_count": self.validator_count,
            "validator_quorum": self.validator_quorum,
            "bootnode_count": self.bootnode_count,
            "rpc_node_count": self.rpc_node_count,
            "failure_domains": self.failure_domains,
            "configuration_status": "valid-private-bootstrap",
            "deployment_status": "pending-new-infrastructure-and-keys",
        }


def load_build_contract(path: str | Path) -> LegacyBuildContract:
    raw = _load_object(path)
    _require(raw, "schema_version", "junca-legacy-build-contract/v1")
    source = _mapping(raw.get("source"), "source")
    repository = _text(source.get("repository"), "source.repository")
    commit = _text(source.get("commit"), "source.commit")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ChainBootstrapError("source.commit must be a lowercase 40-character SHA")
    tag = _text(source.get("tag"), "source.tag")
    _require(source, "go_module", "github.com/juncachain/juncachain")
    _require(source, "go_directive", "1.17")

    build = _mapping(raw.get("build"), "build")
    command = _string_list(build.get("command"), "build.command")
    if command != (
        "go",
        "run",
        "build/ci.go",
        "install",
        "-static",
        "./cmd/junca",
    ):
        raise ChainBootstrapError("build.command does not match the audited Docker build")
    _require(build, "output_path", "build/bin/junca")
    _require(build, "status", "pending-toolchain")

    container = _mapping(raw.get("container"), "container")
    _require(container, "builder_image", "golang:1.18-alpine")
    _require(container, "runtime_image", "alpine:latest")
    _require(container, "image_digest_status", "mutable-tags-unpinned")
    gates = _mapping(raw.get("release_gates"), "release_gates")
    for field in (
        "pin_builder_image_digest",
        "pin_runtime_image_digest",
        "produce_binary_sha256",
        "produce_container_digest",
        "produce_sbom",
    ):
        if gates.get(field) is not True:
            raise ChainBootstrapError(f"release_gates.{field} must be true")
    if gates.get("public_release_allowed") is not False:
        raise ChainBootstrapError("public_release_allowed must remain false before gates pass")

    return LegacyBuildContract(
        repository=repository,
        commit=commit,
        tag=tag,
        go_directive="1.17",
        builder_image="golang:1.18-alpine",
        runtime_image="alpine:latest",
        build_command=command,
        output_path="build/bin/junca",
        build_status="pending-toolchain",
    )


def load_testnet_bootstrap(path: str | Path) -> SovereignTestnetBootstrap:
    raw = _load_object(path)
    _require(raw, "schema_version", "junca-sovereign-testnet-bootstrap/v1")
    _require(raw, "release_stage", "private-bootstrap")
    network_name = _text(raw.get("network_name"), "network_name")

    chain = _mapping(raw.get("chain_identity"), "chain_identity")
    chain_id = _positive_integer(chain.get("chain_id"), "chain_identity.chain_id")
    _require(chain, "status", "private-candidate")
    _require(chain, "registry", "ethereum-lists/chains")
    _require(chain, "registration_status", "pending")
    if chain.get("public_use_allowed") is not False:
        raise ChainBootstrapError(
            "public_use_allowed must be false until chain ID registration is verified"
        )

    consensus = _mapping(raw.get("consensus"), "consensus")
    _require(consensus, "engine", "posv")
    period = _positive_integer(consensus.get("period_seconds"), "consensus.period_seconds")
    epoch = _positive_integer(consensus.get("epoch_blocks"), "consensus.epoch_blocks")
    if period != 2 or epoch != 900:
        raise ChainBootstrapError("PoSV period/epoch must remain 2/900 for bootstrap")

    topology = _mapping(raw.get("topology"), "topology")
    validators = _positive_integer(topology.get("validators"), "topology.validators")
    quorum = _positive_integer(topology.get("validator_quorum"), "topology.validator_quorum")
    bootnodes = _positive_integer(topology.get("bootnodes"), "topology.bootnodes")
    rpc_nodes = _positive_integer(topology.get("rpc_nodes"), "topology.rpc_nodes")
    failure_domains = _positive_integer(
        topology.get("failure_domains"),
        "topology.failure_domains",
    )
    if validators < 5 or quorum < 4 or quorum > validators:
        raise ChainBootstrapError("topology requires at least 5 validators and quorum 4")
    if quorum * 100 <= validators * 75:
        raise ChainBootstrapError("validator quorum must be greater than 75 percent")
    if bootnodes < 3 or rpc_nodes < 2 or failure_domains < 3:
        raise ChainBootstrapError("topology lacks required failure isolation")

    custody = _mapping(raw.get("custody"), "custody")
    _require(custody, "validator_key_source", "new-at-deployment")
    _require(custody, "bootnode_key_source", "new-at-deployment")
    if custody.get("legacy_key_reuse") is not False:
        raise ChainBootstrapError("legacy_key_reuse must be false")
    if custody.get("secrets_in_repository") is not False:
        raise ChainBootstrapError("secrets_in_repository must be false")

    genesis = _mapping(raw.get("genesis"), "genesis")
    _require(genesis, "strategy", "new-genesis")
    if genesis.get("legacy_state_import") is not False:
        raise ChainBootstrapError("legacy_state_import must be false")
    if genesis.get("legacy_balance_import") is not False:
        raise ChainBootstrapError("legacy_balance_import must be false")
    _require(genesis, "prefund_policy", "jaios-governed-manifest-only")

    gates = _mapping(raw.get("publication_gates"), "publication_gates")
    required_gates = (
        "chain_id_registration_verified",
        "new_keys_attested",
        "genesis_fingerprint_verified",
        "validator_quorum_verified",
        "rpc_boundary_verified",
        "explorer_head_parity_verified",
        "rollback_package_verified",
    )
    for field in required_gates:
        if gates.get(field) is not False:
            raise ChainBootstrapError(
                f"publication_gates.{field} must start false and require evidence"
            )

    return SovereignTestnetBootstrap(
        network_name=network_name,
        release_stage="private-bootstrap",
        chain_id=chain_id,
        chain_id_status="private-candidate",
        registration_status="pending",
        consensus_engine="posv",
        validator_count=validators,
        validator_quorum=quorum,
        bootnode_count=bootnodes,
        rpc_node_count=rpc_nodes,
        failure_domains=failure_domains,
    )


def _load_object(path: str | Path) -> Mapping[str, Any]:
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ChainBootstrapError(f"unable to load configuration: {source}") from exc
    if not isinstance(raw, Mapping):
        raise ChainBootstrapError("configuration must be a JSON object")
    return raw


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ChainBootstrapError(f"{field} must be an object")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 300:
        raise ChainBootstrapError(f"{field} must contain 1-300 characters")
    return value.strip()


def _positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ChainBootstrapError(f"{field} must be a positive integer")
    return value


def _string_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ChainBootstrapError(f"{field} must be a non-empty string list")
    return tuple(value)


def _require(values: Mapping[str, Any], field: str, expected: Any) -> None:
    if values.get(field) != expected:
        raise ChainBootstrapError(f"{field} must be {expected!r}")
