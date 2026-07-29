#!/usr/bin/env python3
"""Validate one repository-authorized validator release request."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "junca-validator-ami-build-request/v2"
DEPENDENCY_LOCK_SCHEMA_VERSION = "junca-validator-ami-dependency-lock/v1"
APPROVAL_PHRASE = "PUBLIC_TESTNET_IMMUTABLE_AMI_BUILD"
FOUNDATION_RESUME_SCHEMA_VERSION = (
    "junca-validator-foundation-resume-request/v1"
)
FOUNDATION_RESUME_APPROVAL_PHRASE = "PUBLIC_TESTNET_ROLLOUT"
FOUNDATION_RESUME_MODE = "foundation-resume-only"
FOUNDATION_WORKFLOW = (
    ".github/workflows/junca-validator-foundation-release.yml"
)
NETWORK = "Public Testnet"
ENVIRONMENT = "public-testnet"
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
AMI_ID = re.compile(r"^ami-[0-9a-f]{8,17}$")
AWS_ACCOUNT_ID = re.compile(r"^[0-9]{12}$")
AL2023_RELEASEVER = re.compile(r"^2023\.[0-9]+\.[0-9]{8}$")
AL2023_AMI_NAME = re.compile(
    r"^al2023-ami-2023\.[0-9]+\.[0-9]{8}\.[0-9]+-kernel-"
    r"[0-9]+\.[0-9]+-x86_64$"
)
RPM_NEVRA = re.compile(
    r"^[a-z0-9][a-z0-9+_.-]*-[0-9]+:"
    r"[A-Za-z0-9][A-Za-z0-9+_.~^%-]*-"
    r"[A-Za-z0-9][A-Za-z0-9+_.~^%-]*\.[a-z0-9_]+$"
)
RUN_ID = re.compile(r"^[1-9][0-9]*$")
NONCE = re.compile(r"^[a-z0-9][a-z0-9-]{15,127}$")
EXPECTED_BOUNDARIES = {
    "terraform_state_changed": False,
    "mainnet_changed": False,
    "assets_moved": False,
    "bridge_activated": False,
}
EXPECTED_FOUNDATION_RESUME_BOUNDARIES = {
    "rebuild_ami": False,
    "rebuild_manifest": False,
    "mainnet_changed": False,
    "assets_moved": False,
    "bridge_activated": False,
}
OUTPUT_FIELDS = (
    "request_type",
    "source_run_id",
    "source_commit",
    "node_artifact_name",
    "genesis_artifact_name",
    "node_sha256",
    "genesis_sha256",
    "parent_ami_id",
    "parent_ami_owner_id",
    "parent_ami_name",
    "component_source_sha256",
    "dependency_lock_sha256",
    "supply_chain_policy_sha256",
    "dnf_releasever",
    "python3_boto3_nevra",
    "python3_botocore_nevra",
    "request_sha256",
    "migration_run_id",
    "migration_evidence_sha256",
    "ami_run_id",
    "manifest_gate_run_id",
    "resume_run_id",
    "target_workflow",
    "one_shot_nonce",
)
RUNTIME_REQUEST_FIELDS = {
    "schema_version",
    "state",
    "network",
    "environment",
    "approval_phrase",
    "source_run_id",
    "source_commit",
    "node_artifact_name",
    "genesis_artifact_name",
    "node_sha256",
    "genesis_sha256",
    "parent_ami_id",
    "parent_ami_owner_id",
    "parent_ami_name",
    "component_source_sha256",
    "dependency_lock_sha256",
    "supply_chain_policy_sha256",
    "dnf_releasever",
    "python3_boto3_nevra",
    "python3_botocore_nevra",
    "boundaries",
    "request_sha256",
}
MIGRATION_BINDING_FIELDS = {
    "migration_run_id",
    "migration_evidence_sha256",
}
FOUNDATION_RESUME_REQUEST_FIELDS = {
    "schema_version",
    "state",
    "network",
    "environment",
    "mode",
    "approval_phrase",
    "ami_run_id",
    "manifest_gate_run_id",
    "resume_run_id",
    "target_workflow",
    "one_shot_nonce",
    "boundaries",
    "request_sha256",
}


class RequestValidationError(ValueError):
    """Raised when a request does not satisfy the fail-closed contract."""


def canonical_request_sha256(request: Mapping[str, Any]) -> str:
    # The runtime artifact identity is intentionally independent of the
    # completed durable-state migration.  This preserves the already approved
    # immutable AMI request digest while a later signed request binds the exact
    # migration run and evidence into the release phase.
    excluded = {"request_sha256"}
    if request.get("schema_version") == SCHEMA_VERSION:
        excluded |= MIGRATION_BINDING_FIELDS
    payload = {key: value for key, value in request.items() if key not in excluded}
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_dependency_lock(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact install closure selected by the release candidate."""

    return {
        "schema_version": DEPENDENCY_LOCK_SCHEMA_VERSION,
        "distribution": "amazon-linux-2023",
        "architecture": "x86_64",
        "dnf_releasever": request.get("dnf_releasever"),
        "packages": [
            {
                "name": "python3-boto3",
                "nevra": request.get("python3_boto3_nevra"),
            },
            {
                "name": "python3-botocore",
                "nevra": request.get("python3_botocore_nevra"),
            },
        ],
        "install_weak_dependencies": False,
    }


def canonical_dependency_lock_sha256(request: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        canonical_dependency_lock(request),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_request(
    request: Mapping[str, Any],
    *,
    require_migration_binding: bool = False,
) -> dict[str, str]:
    if request.get("schema_version") == FOUNDATION_RESUME_SCHEMA_VERSION:
        return _validate_foundation_resume_request(request)

    fields = set(request)
    if fields not in (
        RUNTIME_REQUEST_FIELDS,
        RUNTIME_REQUEST_FIELDS | MIGRATION_BINDING_FIELDS,
    ):
        raise RequestValidationError("request fields do not match the v2 contract")
    has_migration_binding = MIGRATION_BINDING_FIELDS <= fields
    if require_migration_binding and not has_migration_binding:
        raise RequestValidationError("completed migration binding is required")
    if request["schema_version"] != SCHEMA_VERSION:
        raise RequestValidationError("schema_version mismatch")
    if request["state"] != "AUTHORIZED":
        raise RequestValidationError("request is not authorized")
    if request["network"] != NETWORK:
        raise RequestValidationError("network mismatch")
    if request["environment"] != ENVIRONMENT:
        raise RequestValidationError("environment mismatch")
    if request["approval_phrase"] != APPROVAL_PHRASE:
        raise RequestValidationError("approval phrase mismatch")
    if request["boundaries"] != EXPECTED_BOUNDARIES:
        raise RequestValidationError("release boundary mismatch")

    source_run_id = str(request["source_run_id"])
    source_commit = str(request["source_commit"])
    node_sha256 = str(request["node_sha256"])
    genesis_sha256 = str(request["genesis_sha256"])
    parent_ami_id = str(request["parent_ami_id"])
    parent_ami_owner_id = str(request["parent_ami_owner_id"])
    parent_ami_name = str(request["parent_ami_name"])
    component_source_sha256 = str(request["component_source_sha256"])
    dependency_lock_sha256 = str(request["dependency_lock_sha256"])
    supply_chain_policy_sha256 = str(request["supply_chain_policy_sha256"])
    dnf_releasever = str(request["dnf_releasever"])
    python3_boto3_nevra = str(request["python3_boto3_nevra"])
    python3_botocore_nevra = str(request["python3_botocore_nevra"])
    if not RUN_ID.fullmatch(source_run_id):
        raise RequestValidationError("source_run_id must be a positive integer")
    if not HEX_40.fullmatch(source_commit):
        raise RequestValidationError("source_commit must be lowercase SHA-1")
    if not HEX_64.fullmatch(node_sha256):
        raise RequestValidationError("node_sha256 must be lowercase SHA-256")
    if not HEX_64.fullmatch(genesis_sha256):
        raise RequestValidationError("genesis_sha256 must be lowercase SHA-256")
    if not AMI_ID.fullmatch(parent_ami_id):
        raise RequestValidationError("parent_ami_id must be an exact AMI ID")
    if not AWS_ACCOUNT_ID.fullmatch(parent_ami_owner_id):
        raise RequestValidationError(
            "parent_ami_owner_id must be a 12-digit AWS account ID"
        )
    if parent_ami_owner_id != "137112412989":
        raise RequestValidationError("parent AMI owner is not Amazon Linux")
    if not AL2023_AMI_NAME.fullmatch(parent_ami_name):
        raise RequestValidationError("parent_ami_name must be an exact AL2023 AMI name")
    if not AL2023_RELEASEVER.fullmatch(dnf_releasever):
        raise RequestValidationError("dnf_releasever must be an exact AL2023 release")
    if not parent_ami_name.startswith(f"al2023-ami-{dnf_releasever}."):
        raise RequestValidationError(
            "parent AMI name is not bound to dnf_releasever"
        )
    for name, value in (
        ("component_source_sha256", component_source_sha256),
        ("dependency_lock_sha256", dependency_lock_sha256),
        ("supply_chain_policy_sha256", supply_chain_policy_sha256),
    ):
        if not HEX_64.fullmatch(value):
            raise RequestValidationError(f"{name} must be lowercase SHA-256")
    for name, package, value in (
        ("python3_boto3_nevra", "python3-boto3", python3_boto3_nevra),
        (
            "python3_botocore_nevra",
            "python3-botocore",
            python3_botocore_nevra,
        ),
    ):
        if not RPM_NEVRA.fullmatch(value) or not value.startswith(f"{package}-"):
            raise RequestValidationError(f"{name} must be an exact package NEVRA")
    if dependency_lock_sha256 != canonical_dependency_lock_sha256(request):
        raise RequestValidationError("dependency_lock_sha256 mismatch")
    if has_migration_binding:
        migration_run_id = str(request["migration_run_id"])
        migration_evidence_sha256 = str(request["migration_evidence_sha256"])
        if not RUN_ID.fullmatch(migration_run_id):
            raise RequestValidationError(
                "migration_run_id must be a positive integer"
            )
        if not HEX_64.fullmatch(migration_evidence_sha256):
            raise RequestValidationError(
                "migration_evidence_sha256 must be lowercase SHA-256"
            )

    expected_node_artifact = f"junca-validator-runtime-{source_run_id}"
    expected_genesis_artifact = f"junca-validator-genesis-{source_run_id}"
    if request["node_artifact_name"] != expected_node_artifact:
        raise RequestValidationError("node artifact is not bound to source_run_id")
    if request["genesis_artifact_name"] != expected_genesis_artifact:
        raise RequestValidationError("genesis artifact is not bound to source_run_id")

    expected_digest = canonical_request_sha256(request)
    if request["request_sha256"] != expected_digest:
        raise RequestValidationError("request_sha256 mismatch")

    outputs = {field: str(request.get(field, "")) for field in OUTPUT_FIELDS}
    outputs["request_type"] = "ami-build"
    return outputs


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RequestValidationError(f"{label} must be an object")
    return value


def _require_exact_provenance_tags(
    value: Any,
    request: Mapping[str, Any],
    *,
    label: str,
) -> None:
    tags = _require_mapping(value, f"{label}.tags")
    expected = {
        "Network": NETWORK,
        "Governance": "JAIOS Institutional Governance",
        "RequestSchema": SCHEMA_VERSION,
        "SourceCommit": request["source_commit"],
        "NodeArtifactSHA256": request["node_sha256"],
        "GenesisSHA256": request["genesis_sha256"],
        "RequestDigest": request["request_sha256"],
        "ParentAMIId": request["parent_ami_id"],
        "ParentAMIOwnerId": request["parent_ami_owner_id"],
        "ParentAMIName": request["parent_ami_name"],
        "ComponentSourceSHA256": request["component_source_sha256"],
        "DependencyLockSHA256": request["dependency_lock_sha256"],
        "SupplyChainPolicySHA256": request["supply_chain_policy_sha256"],
        "DnfReleasever": request["dnf_releasever"],
        "Boto3NEVRA": request["python3_boto3_nevra"],
        "BotocoreNEVRA": request["python3_botocore_nevra"],
    }
    for key, expected_value in expected.items():
        if tags.get(key) != expected_value:
            raise RequestValidationError(f"{label}.tags.{key} mismatch")


def validate_image_builder_lineage(
    *,
    image_readback: Mapping[str, Any],
    recipe_readback: Mapping[str, Any],
    component_readback: Mapping[str, Any],
    component_source: bytes,
    request: Mapping[str, Any],
    image_builder_arn: str,
    ami_id: str,
    aws_account_id: str,
    aws_region: str,
) -> dict[str, str]:
    """Validate immutable Image Builder lineage for a fresh or reused AMI."""

    validate_request(request)
    if not AWS_ACCOUNT_ID.fullmatch(aws_account_id):
        raise RequestValidationError("AWS account ID is invalid")
    if aws_region != "us-east-1":
        raise RequestValidationError("Image Builder region mismatch")
    if not AMI_ID.fullmatch(ami_id):
        raise RequestValidationError("lineage AMI ID is invalid")

    image_arn_pattern = re.compile(
        rf"^arn:aws:imagebuilder:{re.escape(aws_region)}:"
        rf"{re.escape(aws_account_id)}:image/"
        r"(junca-validator-([1-9][0-9]*)-([1-9][0-9]*))/"
        r"1\.0\.0/([1-9][0-9]*)$"
    )
    image_arn_match = image_arn_pattern.fullmatch(image_builder_arn)
    if image_arn_match is None:
        raise RequestValidationError("Image Builder ARN is not exact")
    lineage_name = image_arn_match.group(1)
    lineage_suffix = (
        f"{image_arn_match.group(2)}-{image_arn_match.group(3)}"
    )
    image_build_number = image_arn_match.group(4)

    image = _require_mapping(
        image_readback.get("image"),
        "image readback.image",
    )
    if image.get("arn") != image_builder_arn:
        raise RequestValidationError("Image Builder image ARN mismatch")
    if image.get("name") != lineage_name:
        raise RequestValidationError("Image Builder image name mismatch")
    if image.get("version") != f"1.0.0/{image_build_number}":
        raise RequestValidationError("Image Builder image version mismatch")
    if image.get("platform") != "Linux":
        raise RequestValidationError("Image Builder image platform mismatch")
    image_state = _require_mapping(
        image.get("state"),
        "image readback.image.state",
    )
    if image_state.get("status") != "AVAILABLE":
        raise RequestValidationError("Image Builder image is not available")
    image_recipe = _require_mapping(
        image.get("imageRecipe"),
        "image readback.image.imageRecipe",
    )
    expected_recipe_arn = (
        f"arn:aws:imagebuilder:{aws_region}:{aws_account_id}:"
        f"image-recipe/{lineage_name}/1.0.0"
    )
    if image_recipe.get("arn") != expected_recipe_arn:
        raise RequestValidationError("Image Builder recipe ARN mismatch")
    output_resources = _require_mapping(
        image.get("outputResources"),
        "image readback.image.outputResources",
    )
    output_amis = output_resources.get("amis")
    if not isinstance(output_amis, list) or len(output_amis) != 1:
        raise RequestValidationError("Image Builder output AMI is not unique")
    output_ami = _require_mapping(
        output_amis[0],
        "image readback.image.outputResources.amis[0]",
    )
    if (
        output_ami.get("image") != ami_id
        or output_ami.get("region") != aws_region
        or output_ami.get("accountId") != aws_account_id
        or _require_mapping(
            output_ami.get("state"),
            "image readback.image.outputResources.amis[0].state",
        ).get("status")
        != "AVAILABLE"
    ):
        raise RequestValidationError("Image Builder output AMI mismatch")
    _require_exact_provenance_tags(
        image.get("tags"),
        request,
        label="image readback.image",
    )

    recipe = _require_mapping(
        recipe_readback.get("imageRecipe"),
        "recipe readback.imageRecipe",
    )
    if recipe.get("arn") != expected_recipe_arn:
        raise RequestValidationError("recipe readback ARN mismatch")
    if recipe.get("name") != lineage_name:
        raise RequestValidationError("recipe readback name mismatch")
    if recipe.get("version") != "1.0.0":
        raise RequestValidationError("recipe readback version mismatch")
    if recipe.get("owner") != aws_account_id:
        raise RequestValidationError("recipe readback owner mismatch")
    if recipe.get("type") != "AMI" or recipe.get("platform") != "Linux":
        raise RequestValidationError("recipe readback platform mismatch")
    if recipe.get("parentImage") != request["parent_ami_id"]:
        raise RequestValidationError("recipe parent AMI mismatch")
    _require_exact_provenance_tags(
        recipe.get("tags"),
        request,
        label="recipe readback.imageRecipe",
    )

    components = recipe.get("components")
    if not isinstance(components, list) or len(components) != 1:
        raise RequestValidationError("recipe component is not unique")
    recipe_component = _require_mapping(
        components[0],
        "recipe readback.imageRecipe.components[0]",
    )
    component_arn = str(recipe_component.get("componentArn", ""))
    component_arn_pattern = re.compile(
        rf"^arn:aws:imagebuilder:{re.escape(aws_region)}:"
        rf"{re.escape(aws_account_id)}:component/"
        rf"{re.escape(lineage_name)}/1\.0\.0/[1-9][0-9]*$"
    )
    if component_arn_pattern.fullmatch(component_arn) is None:
        raise RequestValidationError("recipe component ARN mismatch")

    parameters = recipe_component.get("parameters")
    if not isinstance(parameters, list) or len(parameters) != 10:
        raise RequestValidationError("recipe parameters are not exact")
    parameter_map: dict[str, Any] = {}
    for index, parameter_value in enumerate(parameters):
        parameter = _require_mapping(
            parameter_value,
            f"recipe parameter {index}",
        )
        if set(parameter) != {"name", "value"}:
            raise RequestValidationError("recipe parameter fields are not exact")
        name = parameter.get("name")
        if not isinstance(name, str) or name in parameter_map:
            raise RequestValidationError("recipe parameter names are not unique")
        parameter_map[name] = parameter.get("value")
    expected_parameters = {
        "ArtifactBucket": [
            "junca-validator-ami-build-"
            f"{aws_account_id}-{lineage_suffix}"
        ],
        "NodeSHA256": [request["node_sha256"]],
        "GenesisSHA256": [request["genesis_sha256"]],
        "ParentAMIId": [request["parent_ami_id"]],
        "DnfReleasever": [request["dnf_releasever"]],
        "Boto3Nevra": [request["python3_boto3_nevra"]],
        "BotocoreNevra": [request["python3_botocore_nevra"]],
        "ComponentSourceSHA256": [request["component_source_sha256"]],
        "DependencyLockSHA256": [request["dependency_lock_sha256"]],
        "SupplyChainPolicySHA256": [
            request["supply_chain_policy_sha256"]
        ],
    }
    if parameter_map != expected_parameters:
        raise RequestValidationError("recipe parameter closure mismatch")

    component = _require_mapping(
        component_readback.get("component"),
        "component readback.component",
    )
    if component.get("arn") != component_arn:
        raise RequestValidationError("component readback ARN mismatch")
    if component.get("name") != lineage_name:
        raise RequestValidationError("component readback name mismatch")
    if component.get("version") != "1.0.0":
        raise RequestValidationError("component readback version mismatch")
    if component.get("owner") != aws_account_id:
        raise RequestValidationError("component readback owner mismatch")
    if component.get("platform") != "Linux":
        raise RequestValidationError("component readback platform mismatch")
    component_data = component.get("data")
    if not isinstance(component_data, str):
        raise RequestValidationError("component data is missing")
    if component_data.encode("utf-8") != component_source:
        raise RequestValidationError("component source readback mismatch")
    if hashlib.sha256(component_source).hexdigest() != request[
        "component_source_sha256"
    ]:
        raise RequestValidationError("component source digest mismatch")
    _require_exact_provenance_tags(
        component.get("tags"),
        request,
        label="component readback.component",
    )
    return {
        "image_builder_arn": image_builder_arn,
        "image_recipe_arn": expected_recipe_arn,
        "component_arn": component_arn,
    }


def _validate_foundation_resume_request(
    request: Mapping[str, Any],
) -> dict[str, str]:
    if set(request) != FOUNDATION_RESUME_REQUEST_FIELDS:
        raise RequestValidationError(
            "request fields do not match the foundation resume v1 contract"
        )
    if request["state"] != "AUTHORIZED":
        raise RequestValidationError("request is not authorized")
    if request["network"] != NETWORK:
        raise RequestValidationError("network mismatch")
    if request["environment"] != ENVIRONMENT:
        raise RequestValidationError("environment mismatch")
    if request["mode"] != FOUNDATION_RESUME_MODE:
        raise RequestValidationError("foundation resume mode mismatch")
    if request["approval_phrase"] != FOUNDATION_RESUME_APPROVAL_PHRASE:
        raise RequestValidationError("approval phrase mismatch")
    if request["target_workflow"] != FOUNDATION_WORKFLOW:
        raise RequestValidationError("target workflow mismatch")
    if request["boundaries"] != EXPECTED_FOUNDATION_RESUME_BOUNDARIES:
        raise RequestValidationError("release boundary mismatch")

    for field in ("ami_run_id", "manifest_gate_run_id", "resume_run_id"):
        if not RUN_ID.fullmatch(str(request[field])):
            raise RequestValidationError(f"{field} must be a positive integer")
    if not NONCE.fullmatch(str(request["one_shot_nonce"])):
        raise RequestValidationError("one_shot_nonce format is invalid")

    expected_digest = canonical_request_sha256(request)
    if request["request_sha256"] != expected_digest:
        raise RequestValidationError("request_sha256 mismatch")

    outputs = {field: str(request.get(field, "")) for field in OUTPUT_FIELDS}
    outputs["request_type"] = "foundation-resume"
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument(
        "--seal-missing-digest",
        action="store_true",
        help="Set an empty request_sha256 before validating a manual request.",
    )
    parser.add_argument(
        "--require-migration-binding",
        action="store_true",
        help="Require an exact completed migration run and evidence digest.",
    )
    parser.add_argument("--lineage-image-readback", type=Path)
    parser.add_argument("--lineage-recipe-readback", type=Path)
    parser.add_argument("--lineage-component-readback", type=Path)
    parser.add_argument("--lineage-component-source", type=Path)
    parser.add_argument("--lineage-image-builder-arn")
    parser.add_argument("--lineage-ami-id")
    parser.add_argument("--lineage-aws-account-id")
    parser.add_argument("--lineage-aws-region")
    args = parser.parse_args()

    raw = json.loads(args.request.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RequestValidationError("request must be a JSON object")
    if args.seal_missing_digest:
        if raw.get("request_sha256") not in ("", None):
            raise RequestValidationError("manual request digest must start empty")
        if raw.get("schema_version") == SCHEMA_VERSION:
            if raw.get("dependency_lock_sha256") in ("", None):
                raw["dependency_lock_sha256"] = (
                    canonical_dependency_lock_sha256(raw)
                )
        raw["request_sha256"] = canonical_request_sha256(raw)
    outputs = validate_request(
        raw,
        require_migration_binding=args.require_migration_binding,
    )
    lineage_arguments = (
        args.lineage_image_readback,
        args.lineage_recipe_readback,
        args.lineage_component_readback,
        args.lineage_component_source,
        args.lineage_image_builder_arn,
        args.lineage_ami_id,
        args.lineage_aws_account_id,
        args.lineage_aws_region,
    )
    if any(value is not None for value in lineage_arguments):
        if not all(value is not None for value in lineage_arguments):
            raise RequestValidationError(
                "all Image Builder lineage arguments are required"
            )
        image_readback = json.loads(
            args.lineage_image_readback.read_text(encoding="utf-8")
        )
        recipe_readback = json.loads(
            args.lineage_recipe_readback.read_text(encoding="utf-8")
        )
        component_readback = json.loads(
            args.lineage_component_readback.read_text(encoding="utf-8")
        )
        for label, value in (
            ("image readback", image_readback),
            ("recipe readback", recipe_readback),
            ("component readback", component_readback),
        ):
            if not isinstance(value, dict):
                raise RequestValidationError(f"{label} must be an object")
        validate_image_builder_lineage(
            image_readback=image_readback,
            recipe_readback=recipe_readback,
            component_readback=component_readback,
            component_source=args.lineage_component_source.read_bytes(),
            request=raw,
            image_builder_arn=args.lineage_image_builder_arn,
            ami_id=args.lineage_ami_id,
            aws_account_id=args.lineage_aws_account_id,
            aws_region=args.lineage_aws_region,
        )
    rendered = "".join(f"{key}={outputs[key]}\n" for key in OUTPUT_FIELDS)
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write(rendered)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
