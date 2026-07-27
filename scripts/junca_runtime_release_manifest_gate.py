#!/usr/bin/env python3
"""Fail-closed promotion gate for a JUNCA immutable validator runtime."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


ACCOUNT_ID = "595710543956"
REGION = "us-east-1"
VALIDATOR_IDS = ("validator-01", "validator-02", "validator-03")
BOUNDARY_FIELDS = ("mainnet_changed", "assets_moved", "bridge_activated")
SHA256 = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
AMI = re.compile(r"ami-[0-9a-f]{8,17}")
INSTANCE = re.compile(r"i-[0-9a-f]{8,17}")
VOLUME = re.compile(r"vol-[0-9a-f]{8,17}")
SNAPSHOT = re.compile(r"snap-[0-9a-f]{8,17}")
HASH = re.compile(r"0x[0-9a-f]{64}")


def read_object(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to read JSON evidence: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"evidence must be a JSON object: {path}")
    return value


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _boundary(source: Mapping[str, Any], name: str, failures: list[str]) -> None:
    boundary = source.get("release_boundary")
    if not isinstance(boundary, Mapping):
        failures.append(f"{name}.release_boundary:missing")
        return
    for field in BOUNDARY_FIELDS:
        if boundary.get(field) is not False:
            failures.append(f"{name}.release_boundary.{field}:not_false")


def _candidate_binding(source: Mapping[str, Any]) -> tuple[Any, Any, Any, Any]:
    return (
        source.get("source_commit"),
        source.get("node_artifact_sha256"),
        source.get("genesis_sha256"),
        source.get("ami_id"),
    )


def _private_ssm_baseline(
    explorer: Mapping[str, Any], failures: list[str]
) -> None:
    readback = explorer.get("readback")
    if not isinstance(readback, Mapping):
        failures.append("private_ssm.readback:missing")
        return
    if (
        readback.get("mode") != "private_ssm"
        or readback.get("scope")
        != "Public Testnet Pre-rollout Baseline / Private SSM Read-only"
        or readback.get("validator_count") != 3
    ):
        failures.append("private_ssm.readback:invalid")
    validators = readback.get("validators")
    if not isinstance(validators, list):
        failures.append("private_ssm.validators:missing")
    else:
        identities = [
            item.get("validator_id")
            for item in validators
            if isinstance(item, Mapping)
        ]
        instance_ids = [
            item.get("instance_id")
            for item in validators
            if isinstance(item, Mapping)
        ]
        signer_digests = [
            item.get("signer_resource_digest")
            for item in validators
            if isinstance(item, Mapping)
        ]
        if (
            len(validators) != 3
            or identities != list(VALIDATOR_IDS)
            or len(set(instance_ids)) != 3
            or any(
                INSTANCE.fullmatch(str(instance_id)) is None
                for instance_id in instance_ids
            )
            or len(set(signer_digests)) != 3
            or any(
                SHA256.fullmatch(str(signer_digest)) is None
                for signer_digest in signer_digests
            )
        ):
            failures.append("private_ssm.validators:not_exact_three")
    finalized = readback.get("finalized_head")
    if not isinstance(finalized, Mapping):
        failures.append("private_ssm.finalized_head:missing")
    elif (
        not isinstance(finalized.get("height"), int)
        or isinstance(finalized.get("height"), bool)
        or finalized.get("height", 0) < 1
        or HASH.fullmatch(str(finalized.get("hash"))) is None
        or HASH.fullmatch(str(finalized.get("certificate_hash"))) is None
    ):
        failures.append("private_ssm.finalized_head:invalid")
    quorum = readback.get("quorum")
    if not isinstance(quorum, Mapping):
        failures.append("private_ssm.quorum:missing")
    elif (
        quorum.get("signed_power") != 3
        or quorum.get("total_power") != 3
        or quorum.get("validator_ids") != list(VALIDATOR_IDS)
    ):
        failures.append("private_ssm.quorum:not_exact_three")


def _public_endpoint_outage(
    outage: Mapping[str, Any], failures: list[str]
) -> None:
    if (
        outage.get("schema_version")
        != "junca-public-endpoint-outage/v1"
        or outage.get("status") != "PUBLIC_ENDPOINTS_UNAVAILABLE"
        or outage.get("public_services_enabled") is not True
        or outage.get("public_endpoint_acceptance") is not False
    ):
        failures.append("public_outage.status:invalid")
    endpoint_test = outage.get("endpoint_test")
    exit_code = outage.get("endpoint_test_exit_code")
    if (
        not isinstance(outage.get("observed_at"), str)
        or not outage.get("observed_at")
        or not isinstance(exit_code, int)
        or isinstance(exit_code, bool)
        or not 1 <= exit_code <= 255
        or not isinstance(endpoint_test, Mapping)
        or endpoint_test.get("status") != "FAIL"
        or not isinstance(endpoint_test.get("error"), str)
        or not endpoint_test.get("error")
    ):
        failures.append("public_outage.endpoint_test:invalid")
    observations = outage.get("observations")
    expected = (
        (
            "health",
            "GET",
            "https://health.jaios-governance.org/health",
        ),
        (
            "explorer",
            "GET",
            "https://explorer.jaios-governance.org/explorer.json",
        ),
        ("rpc", "POST", "https://rpc.jaios-governance.org/"),
    )
    if (
        not isinstance(observations, list)
        or len(observations) != 3
        or any(not isinstance(item, Mapping) for item in observations)
    ):
        failures.append("public_outage.observations:not_exact_three")
    else:
        failed = 0
        for item, (name, method, url) in zip(
            observations, expected, strict=True
        ):
            curl_exit = item.get("curl_exit_code")
            http_status = item.get("http_status")
            body_sha256 = item.get("body_sha256")
            body_base64 = item.get("body_base64")
            if (
                item.get("name") != name
                or item.get("method") != method
                or item.get("url") != url
                or not isinstance(curl_exit, int)
                or isinstance(curl_exit, bool)
                or not 0 <= curl_exit <= 255
                or not isinstance(http_status, int)
                or isinstance(http_status, bool)
                or not 0 <= http_status <= 599
                or SHA256.fullmatch(str(body_sha256)) is None
                or not isinstance(body_base64, str)
                or not isinstance(item.get("stderr"), str)
            ):
                failures.append(f"public_outage.{name}:invalid")
                continue
            try:
                body = base64.b64decode(body_base64, validate=True)
            except (ValueError, binascii.Error):
                failures.append(f"public_outage.{name}:body_base64_invalid")
                continue
            if (
                len(body) > 65536
                or hashlib.sha256(body).hexdigest() != body_sha256
            ):
                failures.append(f"public_outage.{name}:body_digest_mismatch")
                continue
            if curl_exit != 0 or http_status != 200:
                failed += 1
        if failed < 1:
            failures.append("public_outage:no_failed_observation")
    for field in BOUNDARY_FIELDS:
        if outage.get(field) is not False:
            failures.append(f"public_outage.{field}:not_false")


def evaluate(
    manifest: Mapping[str, Any],
    explorer: Mapping[str, Any],
    ebs: Mapping[str, Any],
    *,
    explorer_evidence_sha256: str,
    ebs_evidence_sha256: str,
    expected_source_commit: str,
    expected_artifact_sha256: str,
    expected_genesis_sha256: str,
) -> dict[str, Any]:
    failures: list[str] = []
    expected = (
        expected_source_commit,
        expected_artifact_sha256,
        expected_genesis_sha256,
        manifest.get("ami_id"),
    )
    request_sha256 = manifest.get("request_sha256")
    migration_evidence_sha256 = manifest.get("migration_evidence_sha256")
    baseline_mode = manifest.get("baseline_mode")
    public_services_enabled = manifest.get("public_services_enabled")
    public_endpoint_acceptance = manifest.get(
        "public_endpoint_acceptance"
    )
    public_endpoint_outage = manifest.get("public_endpoint_outage")
    if not SHA256.fullmatch(str(request_sha256)):
        failures.append("manifest.request_sha256:invalid")
    if explorer.get("request_sha256") != request_sha256:
        failures.append("explorer.request_sha256:mismatch")
    if ebs.get("request_sha256") != request_sha256:
        failures.append("ebs.request_sha256:mismatch")
    if not SHA256.fullmatch(str(migration_evidence_sha256)):
        failures.append("manifest.migration_evidence_sha256:invalid")
    if ebs.get("migration_evidence_sha256") != migration_evidence_sha256:
        failures.append("ebs.migration_evidence_sha256:mismatch")

    if (
        manifest.get("schema_version")
        != "junca-runtime-pre-rollout-baseline/v1"
    ):
        failures.append("manifest.schema_version:mismatch")
    if manifest.get("state") != "PRE_ROLLOUT_BASELINE_VERIFIED":
        failures.append("manifest.state:not_baseline_verified")
    if manifest.get("network") != "Public Testnet":
        failures.append("manifest.network:mismatch")
    if manifest.get("notice") != "Public Testnet / No Monetary Value":
        failures.append("manifest.notice:mismatch")
    if not COMMIT.fullmatch(str(expected_source_commit)):
        failures.append("expected.source_commit:invalid")
    if not SHA256.fullmatch(str(expected_artifact_sha256)):
        failures.append("expected.node_artifact_sha256:invalid")
    if not SHA256.fullmatch(str(expected_genesis_sha256)):
        failures.append("expected.genesis_sha256:invalid")
    if _candidate_binding(manifest) != expected:
        failures.append("manifest.candidate_binding:stale_or_mismatched")
    if not AMI.fullmatch(str(manifest.get("ami_id", ""))):
        failures.append("manifest.ami_id:invalid")

    provenance = manifest.get("ami_provenance")
    if not isinstance(provenance, Mapping):
        failures.append("manifest.ami_provenance:missing")
    else:
        required_tags = {
            "State": "available",
            "OwnerId": ACCOUNT_ID,
            "Region": REGION,
            "SourceCommit": expected_source_commit,
            "NodeArtifactSHA256": expected_artifact_sha256,
            "GenesisSHA256": expected_genesis_sha256,
            "RequestDigest": request_sha256,
            "MainnetChanged": "false",
            "AssetsMoved": "false",
            "BridgeActivated": "false",
        }
        for field, value in required_tags.items():
            if provenance.get(field) != value:
                failures.append(f"manifest.ami_provenance.{field}:mismatch")

    signers = manifest.get("signer_bindings")
    signer_prefix = f"arn:aws:kms:{REGION}:{ACCOUNT_ID}:key/"
    if not isinstance(signers, list):
        failures.append("manifest.signer_bindings:missing")
    else:
        identities = tuple(
            sorted(
                item.get("validator_id", "")
                for item in signers
                if isinstance(item, Mapping)
            )
        )
        arns = [
            item.get("resource_arn")
            for item in signers
            if isinstance(item, Mapping)
        ]
        if (
            len(signers) != 3
            or identities != VALIDATOR_IDS
            or len(set(arns)) != 3
            or any(
                not isinstance(arn, str) or not arn.startswith(signer_prefix)
                for arn in arns
            )
        ):
            failures.append("manifest.signer_bindings:not_exact_three")

    previous = manifest.get("previous_runtime")
    if not isinstance(previous, Mapping):
        failures.append("manifest.previous_runtime:missing")
    else:
        previous_binding = _candidate_binding(previous)
        if previous_binding == expected:
            failures.append("manifest.previous_runtime:equals_candidate")
        if not all(previous_binding):
            failures.append("manifest.previous_runtime:incomplete")

    if manifest.get("explorer_baseline_sha256") != explorer_evidence_sha256:
        failures.append("manifest.explorer_baseline_sha256:mismatch")
    if manifest.get("ebs_baseline_sha256") != ebs_evidence_sha256:
        failures.append("manifest.ebs_baseline_sha256:mismatch")

    if baseline_mode not in ("public_endpoints", "private_ssm"):
        failures.append("manifest.baseline_mode:invalid")
    if explorer.get("baseline_mode") != baseline_mode:
        failures.append("explorer.baseline_mode:mismatch")
    if explorer.get("public_services_enabled") is not public_services_enabled:
        failures.append("explorer.public_services_enabled:mismatch")
    if (
        explorer.get("public_endpoint_acceptance")
        is not public_endpoint_acceptance
    ):
        failures.append("explorer.public_endpoint_acceptance:mismatch")
    if explorer.get("public_endpoint_outage") != public_endpoint_outage:
        failures.append("explorer.public_endpoint_outage:mismatch")
    expected_explorer_schema = (
        "junca-public-explorer-pre-rollout-baseline/v1"
        if baseline_mode == "public_endpoints"
        else "junca-private-ssm-pre-rollout-baseline/v1"
    )
    if explorer.get("schema_version") != expected_explorer_schema:
        failures.append("explorer.schema_version:not_pre_rollout_baseline")
    if (
        explorer.get("candidate_accepted") is not False
        or explorer.get("status") != "BASELINE_VERIFIED"
    ):
        failures.append("explorer.baseline:not_verified")
    if explorer.get("finalized_only") is not True:
        failures.append("explorer.finalized_only:not_true")
    if explorer.get("read_only") is not True:
        failures.append("explorer.read_only:not_true")
    if baseline_mode == "public_endpoints":
        if (
            public_services_enabled is not True
            or public_endpoint_acceptance is not True
            or public_endpoint_outage is not None
        ):
            failures.append("public_endpoints.acceptance_binding:invalid")
        if explorer.get("unsafe_rpc_rejection") is not True:
            failures.append("explorer.unsafe_rpc_rejection:not_true")
    elif baseline_mode == "private_ssm":
        if public_endpoint_acceptance is not False:
            failures.append("private_ssm.public_endpoint_acceptance:not_false")
        if public_services_enabled is True:
            if isinstance(public_endpoint_outage, Mapping):
                _public_endpoint_outage(public_endpoint_outage, failures)
            else:
                failures.append("private_ssm.public_outage:missing")
        elif public_services_enabled is False:
            if public_endpoint_outage is not None:
                failures.append("private_ssm.public_outage:unexpected")
        else:
            failures.append("private_ssm.public_services_enabled:invalid")
        if (
            explorer.get("unsafe_rpc_rejection")
            != "NOT_APPLICABLE_PRIVATE_SSM"
        ):
            failures.append("private_ssm.unsafe_rpc_rejection:invalid")
        _private_ssm_baseline(explorer, failures)
    if _candidate_binding(explorer) != expected:
        failures.append("explorer.candidate_binding:mismatch")
    observed_explorer = explorer.get("observed_runtime")
    if (
        not isinstance(observed_explorer, Mapping)
        or not all(_candidate_binding(observed_explorer))
        or _candidate_binding(observed_explorer) == expected
    ):
        failures.append("explorer.observed_runtime:not_distinct_baseline")

    if (
        ebs.get("schema_version")
        != "junca-validator-ebs-pre-rollout-baseline/v1"
    ):
        failures.append("ebs.schema_version:mismatch")
    if (
        ebs.get("candidate_accepted") is not False
        or ebs.get("state") != "BASELINE_VERIFIED"
    ):
        failures.append("ebs.state:not_baseline_verified")
    if ebs.get("migration_complete") is not True:
        failures.append("ebs.migration_complete:not_true")
    if ebs.get("data_loss") is not False:
        failures.append("ebs.data_loss:not_false")
    if _candidate_binding(ebs) != expected:
        failures.append("ebs.candidate_binding:mismatch")
    observed_ebs = ebs.get("observed_runtime")
    if (
        not isinstance(observed_ebs, Mapping)
        or not all(_candidate_binding(observed_ebs))
        or _candidate_binding(observed_ebs) == expected
    ):
        failures.append("ebs.observed_runtime:not_distinct_baseline")
    volumes = ebs.get("validator_volumes")
    if not isinstance(volumes, list):
        failures.append("ebs.validator_volumes:missing")
    else:
        volume_ids: list[Any] = []
        identities: list[Any] = []
        snapshots: list[Any] = []
        for item in volumes:
            if not isinstance(item, Mapping):
                continue
            identities.append(item.get("validator_id"))
            volume_ids.append(item.get("volume_id"))
            snapshots.append(item.get("rollback_snapshot_id"))
            if (
                item.get("encrypted") is not True
                or item.get("volume_type") != "gp3"
                or item.get("mount_path") != "/var/lib/junca"
                or item.get("filesystem_verified") is not True
                or item.get("state_store_integrity") is not True
                or item.get("finality_certificate_recovered") is not True
            ):
                failures.append("ebs.validator_volumes:acceptance_incomplete")
        if (
            len(volumes) != 3
            or tuple(sorted(identities)) != VALIDATOR_IDS
            or len(set(volume_ids)) != 3
            or any(not VOLUME.fullmatch(str(value)) for value in volume_ids)
            or len(set(snapshots)) != 3
            or any(not SNAPSHOT.fullmatch(str(value)) for value in snapshots)
        ):
            failures.append("ebs.validator_volumes:not_exact_three")

    for name, source in (
        ("manifest", manifest),
        ("explorer", explorer),
        ("ebs", ebs),
    ):
        _boundary(source, name, failures)

    failures = sorted(set(failures))
    return {
        "schema_version": "junca-runtime-release-manifest-decision/v1",
        "decision": "PROMOTION_GATE_PASS" if not failures else "PROMOTION_GATE_REJECTED",
        "accepted": not failures,
        "phase": "PREDEPLOYMENT_READINESS",
        "baseline_mode": baseline_mode,
        "public_services_enabled": public_services_enabled,
        "public_endpoint_acceptance": public_endpoint_acceptance,
        "public_endpoint_outage_status": (
            public_endpoint_outage.get("status")
            if isinstance(public_endpoint_outage, Mapping)
            else None
        ),
        "candidate": {
            "source_commit": expected_source_commit,
            "node_artifact_sha256": expected_artifact_sha256,
            "genesis_sha256": expected_genesis_sha256,
            "ami_id": manifest.get("ami_id"),
            "request_sha256": request_sha256,
            "migration_evidence_sha256": migration_evidence_sha256,
        },
        "failure_count": len(failures),
        "failures": failures,
        "release_boundary": {
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--explorer-acceptance", required=True)
    parser.add_argument("--ebs-migration", required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--expected-artifact-sha256", required=True)
    parser.add_argument("--expected-genesis-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    decision = evaluate(
        read_object(args.manifest),
        read_object(args.explorer_acceptance),
        read_object(args.ebs_migration),
        explorer_evidence_sha256=file_sha256(args.explorer_acceptance),
        ebs_evidence_sha256=file_sha256(args.ebs_migration),
        expected_source_commit=args.expected_source_commit,
        expected_artifact_sha256=args.expected_artifact_sha256,
        expected_genesis_sha256=args.expected_genesis_sha256,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"decision": decision["decision"], "output": str(output)}))
    return 0 if decision["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
