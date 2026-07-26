"""Fail-closed validator predeployment acceptance.

This controller joins immutable runtime, AWS foundation, and quorum bootstrap
evidence into one machine-readable manifest.  It does not deploy infrastructure
and cannot promote pending or synthetic values into live AWS claims.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

CHAIN = "JUNCA Social Ecosystem Chain"
GOVERNANCE = "JAIOS Institutional Governance"
NOTICE = "Public Testnet / No Monetary Value"
ACCOUNT = "595710543956"
REGION = "us-east-1"
VALIDATORS = ("validator-01", "validator-02", "validator-03")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_AMI = re.compile(r"^ami-[0-9a-f]{8,17}$")
_KMS_PREFIX = f"arn:aws:kms:{REGION}:{ACCOUNT}:key/"


def evaluate_predeployment(
    artifact: Mapping[str, Any],
    foundation: Mapping[str, Any],
    bootstrap: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a deterministic manifest and explicit missing/invalid fields."""
    failures: list[str] = []

    _identity(artifact, "artifact", failures)
    _identity(foundation, "foundation", failures)
    _identity(bootstrap, "bootstrap", failures)
    _boundaries(artifact, "artifact", failures)
    _boundaries(foundation, "foundation", failures)
    _boundaries(bootstrap, "bootstrap", failures)

    if artifact.get("state") != "READY_FOR_AWS_AMI_READBACK":
        failures.append("artifact.state:not_ready_for_ami_readback")
    ami_id = artifact.get("ami_id")
    if not isinstance(ami_id, str) or not _AMI.fullmatch(ami_id):
        failures.append("artifact.ami_id:missing_or_invalid")
    binary_sha = _digest(artifact, "node_artifact_sha256", "artifact", failures)
    genesis_sha = _digest(artifact, "genesis_sha256", "artifact", failures)
    if artifact.get("ami_readback_verified") is not True:
        failures.append("artifact.ami_readback_verified:not_true")
    if artifact.get("live_runtime_verified") is not False:
        failures.append("artifact.live_runtime_verified:must_be_false_predeploy")

    if foundation.get("status") != "AWS_FOUNDATION_READBACK_VERIFIED":
        failures.append("foundation.status:not_verified")
    if foundation.get("aws_account_id") != ACCOUNT:
        failures.append("foundation.aws_account_id:mismatch")
    if foundation.get("aws_region") != REGION:
        failures.append("foundation.aws_region:mismatch")
    zones = _texts(foundation.get("availability_zones"))
    if len(zones) != 3 or len(set(zones)) != 3 or any(not z.startswith(REGION) for z in zones):
        failures.append("foundation.availability_zones:not_three_distinct")
    subnets = _texts(foundation.get("private_subnet_ids"))
    if len(subnets) != 3 or len(set(subnets)) != 3 or any(not s.startswith("subnet-") for s in subnets):
        failures.append("foundation.private_subnet_ids:not_three_distinct")
    signers = _texts(foundation.get("validator_signer_kms_key_arns"))
    if len(signers) != 3 or len(set(signers)) != 3 or any(not s.startswith(_KMS_PREFIX) for s in signers):
        failures.append("foundation.validator_signers:not_three_canonical")
    if foundation.get("kms_key_usage") != "SIGN_VERIFY":
        failures.append("foundation.kms_key_usage:not_sign_verify")

    validators = _texts(bootstrap.get("validator_ids"))
    if validators != VALIDATORS:
        failures.append("bootstrap.validator_ids:not_canonical_order")
    if bootstrap.get("validator_count") != 3:
        failures.append("bootstrap.validator_count:not_three")
    if bootstrap.get("quorum_threshold") != 2:
        failures.append("bootstrap.quorum_threshold:not_two_of_three")
    if bootstrap.get("chain_id") in (None, "", 0):
        failures.append("bootstrap.chain_id:missing")
    if bootstrap.get("genesis_sha256") != genesis_sha:
        failures.append("bootstrap.genesis_sha256:mismatch")
    if bootstrap.get("node_artifact_sha256") != binary_sha:
        failures.append("bootstrap.node_artifact_sha256:mismatch")
    bootnodes = _texts(bootstrap.get("bootnode_endpoints"))
    if len(bootnodes) != 3 or len(set(bootnodes)) != 3:
        failures.append("bootstrap.bootnode_endpoints:not_three_distinct")
    elif any("PENDING" in item.upper() or "placeholder" in item.lower() for item in bootnodes):
        failures.append("bootstrap.bootnode_endpoints:contains_placeholder")

    commits = {artifact.get("source_commit"), foundation.get("source_commit"), bootstrap.get("source_commit")}
    if len(commits) != 1 or any(not isinstance(v, str) or not _COMMIT.fullmatch(v) for v in commits):
        failures.append("source_commit:missing_or_mismatch")

    if signers:
        signer_digests = [hashlib.sha256(value.encode()).hexdigest() for value in signers]
        if artifact.get("signer_resource_digests") != signer_digests:
            failures.append("artifact.signer_resource_digests:mismatch")

    failures = sorted(set(failures))
    accepted = not failures
    manifest: dict[str, Any] = {
        "schema_version": "junca-validator-predeployment-manifest/v1",
        "official_chain_name": CHAIN,
        "governance": GOVERNANCE,
        "network_label": NOTICE,
        "decision": "PREDEPLOYMENT_ACCEPTED" if accepted else "PREDEPLOYMENT_REJECTED",
        "accepted": accepted,
        "aws": {
            "account_id": ACCOUNT,
            "region": REGION,
            "availability_zones": list(zones),
            "private_subnet_ids": list(subnets),
        },
        "runtime": {
            "ami_id": ami_id,
            "node_artifact_sha256": binary_sha,
            "genesis_sha256": genesis_sha,
        },
        "validators": {
            "ids": list(validators),
            "signer_kms_key_arns": list(signers),
            "bootnode_endpoints": list(bootnodes),
            "count": bootstrap.get("validator_count"),
            "quorum_threshold": bootstrap.get("quorum_threshold"),
        },
        "source_commit": next(iter(commits)) if len(commits) == 1 else None,
        "failure_count": len(failures),
        "failures": failures,
        "live_runtime_verified": False,
        "release_boundary": {
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
            "bridge_route": "PAUSED",
        },
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return manifest


def _identity(value: Mapping[str, Any], name: str, failures: list[str]) -> None:
    expected = {
        "official_chain_name": CHAIN,
        "governance": GOVERNANCE,
        "network_label": NOTICE,
    }
    aliases = {"official_chain_name": "chain_name", "network_label": "notice"}
    for field, wanted in expected.items():
        actual = value.get(field, value.get(aliases.get(field, "")))
        if actual != wanted:
            failures.append(f"{name}.{field}:mismatch")


def _boundaries(value: Mapping[str, Any], name: str, failures: list[str]) -> None:
    boundary = value.get("release_boundary", value)
    for field in ("mainnet_changed", "assets_moved", "bridge_activated"):
        if boundary.get(field) is not False:
            failures.append(f"{name}.{field}:not_false")
    route = boundary.get("bridge_route", "PAUSED")
    if route != "PAUSED":
        failures.append(f"{name}.bridge_route:not_paused")


def _digest(value: Mapping[str, Any], field: str, name: str, failures: list[str]) -> str | None:
    item = value.get(field)
    if not isinstance(item, str) or not _SHA256.fullmatch(item):
        failures.append(f"{name}.{field}:missing_or_invalid")
        return None
    return item


def _texts(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    if any(not isinstance(item, str) or not item.strip() for item in value):
        return ()
    return tuple(item.strip() for item in value)
