#!/usr/bin/env python3
"""Fail-closed validation for JSEC cloud role and workflow quarantine policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


class CloudRolePolicyError(ValueError):
    """Raised when the cloud role boundary is incomplete or unsafe."""


REPOSITORY = "JAIOS-Governance/junca-social-ecosystem-chain"
ENVIRONMENT = "public-testnet"
SUBJECT_TEMPLATE = (
    "repo:JAIOS-Governance@308604370/"
    "junca-social-ecosystem-chain@1310568313:"
    "environment:{environment}:workflow_ref:"
    "{repository}/.github/workflows/{workflow}@refs/heads/main:"
    "runner_environment:github-hosted"
)
LEGACY_SUBJECT = (
    "repo:JAIOS-Governance@308604370/"
    "junca-social-ecosystem-chain@1310568313:environment:public-testnet"
)
ROLE_WORKFLOWS = {
    "foundation": {
        "junca-public-testnet-release.yml",
        "junca-validator-foundation-release.yml",
    },
    "ami_builder": {"junca-validator-ami-build.yml"},
    "observer": {
        "junca-public-testnet-live-soak.yml",
        "junca-runtime-release-evidence-collector-v2.yml",
        "junca-social-ecosystem-chain-aws-binding-readback.yml",
        "junca-social-ecosystem-chain-aws-readback.yml",
    },
}
ROLE_NAMES = {
    "foundation": "JuncaChainPublicTestnetDeployment",
    "ami_builder": "JuncaChainPublicTestnetAmiBuilder",
    "observer": "JuncaChainPublicTestnetObserver",
    "security_bootstrap": "JuncaChainSecurityBootstrap",
}
ROLE_ARNS = {
    role_key: f"arn:aws:iam::595710543956:role/{role_name}"
    for role_key, role_name in ROLE_NAMES.items()
}
CANONICAL_ROLE_MAPPING = {
    "junca-validator-ami-build.yml": "ami_builder",
    "junca-validator-foundation-release.yml": "foundation",
    "junca-runtime-release-evidence-collector-v2.yml": "observer",
    "junca-public-testnet-release.yml": "foundation",
    "junca-public-testnet-live-soak.yml": "observer",
}
WORKFLOW_ROLE_EXPECTATIONS = {
    **CANONICAL_ROLE_MAPPING,
    "junca-social-ecosystem-chain-aws-binding-readback.yml": "observer",
    "junca-social-ecosystem-chain-aws-readback.yml": "observer",
}
QUARANTINE_WORKFLOWS = {
    "junca-chain-aws-canonical-inventory.yml",
    "junca-emergency-finality-restore.yml",
    "junca-emergency-gateway-diagnostic.yml",
    "junca-emergency-gateway-redundancy.yml",
    "junca-emergency-gateway-service-restore.yml",
    "junca-emergency-manual-quorum-restore.yml",
    "junca-emergency-p2p-diagnostic.yml",
    "junca-emergency-public-runtime-restore.yml",
    "junca-emergency-public-target-failover.yml",
    "junca-emergency-runtime-activate.yml",
    "junca-emergency-runtime-archive-restore.yml",
    "junca-emergency-runtime-final-restore.yml",
    "junca-emergency-runtime-parity.yml",
    "junca-emergency-runtime-unit-restore.yml",
    "junca-emergency-validator-state-finality-restore.yml",
    "junca-emergency-validator01-lsblk-recovery.yml",
    "junca-emergency-validator01-node-diagnostic.yml",
    "junca-emergency-vote-diagnostic.yml",
    "junca-public-testnet-iam-recovery.yml",
    "junca-public-testnet-oidc-trust-recovery.yml",
    "junca-validator-runtime-diagnostic.yml",
    "junca-validator-runtime-recovery.yml",
}
OIDC_TEMPLATE_MUTATOR_WORKFLOWS = {
    "junca-chain-aws-production-recovery.yml",
    "junca-chain-bootstrap-role-recovery.yml",
    "junca-chain-brand-domain-dns.yml",
    "junca-chain-brand-domain-recovery-canonical.yml",
    "junca-chain-domain-final-execution.yml",
    "junca-jaios-dual-domain-final-cutover.yml",
    "junca-point-member-domain-final-recovery-20260726.yml",
    "junca-point-member-domain-iam-recovery-20260726.yml",
}
RAW_OIDC_QUARANTINE_WORKFLOWS = {
    "junca-chain-bootstrap-inline-policy-repair.yml",
    "junca-chain-runtime-self-permission-recovery.yml",
    "junca-point-member-production-recovery.yml",
}
FORBIDDEN_OIDC_TEMPLATE_MUTATION_TOKENS = {
    "actions/oidc/customization/sub",
    "include_claim_keys",
    "use_immutable_subject",
    "use_default",
}
FORBIDDEN_RAW_OIDC_WORKFLOW_TOKENS = {
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
    "ACTIONS_ID_TOKEN_REQUEST_URL",
    "assume-role-with-web-identity",
}
CANONICAL_CREDENTIAL_DISPOSITION = (
    "CANONICAL_EXACT_ROLE_AND_STS_ATTESTATION_REQUIRED"
)
BLOCKED_CREDENTIAL_DISPOSITION = (
    "BLOCK_REPO_GLOBAL_CUTOVER_PENDING_EXACT_ROLE_TRUST_AND_STS_ATTESTATION"
)
MIGRATED_CREDENTIAL_DISPOSITION = (
    "MIGRATED_EXACT_ROLE_AND_STS_ATTESTATION_REQUIRED"
)
RETIRED_CREDENTIAL_DISPOSITION = "RETIRED_WORKFLOW_FILE_REMOVED"
REPO_GLOBAL_OIDC_PREPARATION_STATE = (
    "BLOCKED_PENDING_EXTERNAL_FUTURE_TRUST_READBACK"
)
REPO_GLOBAL_OIDC_PREPARED_STATE = (
    "PREPARED_ALL_CREDENTIAL_CALLS_EXACTLY_TRUSTED_OR_RETIRED"
)
REPO_GLOBAL_OIDC_CUTOVER_STATE = (
    "BLOCKED_PENDING_COMPLETE_REPOSITORY_CREDENTIAL_MATRIX_ATTESTATION"
)
CUTOVER_READY_STATE = "READY_AFTER_ALL_CREDENTIAL_CALLS_EXACTLY_ATTESTED"
PREPARATION_EVIDENCE_ACCEPTED_STATE = (
    "EXACT_FUTURE_TRUST_AND_RETIREMENT_READBACK_VERIFIED"
)
ACTIVATION_EVIDENCE_ACCEPTED_STATE = (
    "EXACT_ACTIVE_TOKENS_ACCEPTED_BY_AWS_STS_OR_RETIRED"
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CloudRolePolicyError(message)


def exact_subject(workflow: str) -> str:
    return SUBJECT_TEMPLATE.format(
        repository=REPOSITORY,
        environment=ENVIRONMENT,
        workflow=workflow,
    )


def load_policy(path: Path) -> dict[str, Any]:
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CloudRolePolicyError(f"cannot load cloud role policy: {exc}") from exc
    _require(isinstance(policy, dict), "cloud role policy must be an object")
    return policy


def _resolve_role_expression(role: str, environment: dict[str, Any]) -> str:
    resolved = role
    for key, value in environment.items():
        resolved = resolved.replace(f"${{{{ env.{key} }}}}", str(value))
    _require(
        "${{" not in resolved and resolved.startswith("arn:aws:iam::"),
        f"role-to-assume is not an exact resolvable IAM ARN: {role}",
    )
    return resolved


def collect_repository_credential_calls(
    workflows_dir: Path,
) -> list[dict[str, Any]]:
    """Return every active configure-aws-credentials call deterministically."""

    calls: list[dict[str, Any]] = []
    for workflow_path in sorted(workflows_dir.glob("*.y*ml")):
        try:
            document = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise CloudRolePolicyError(
                f"{workflow_path.name}: cannot load workflow inventory: {exc}"
            ) from exc
        if document is None:
            continue
        _require(
            isinstance(document, dict),
            f"{workflow_path.name}: workflow inventory document is invalid",
        )
        jobs = document.get("jobs") or {}
        _require(
            isinstance(jobs, dict),
            f"{workflow_path.name}: workflow jobs must be an object",
        )
        for job_name, job in jobs.items():
            _require(
                isinstance(job, dict),
                f"{workflow_path.name}: invalid job {job_name}",
            )
            call_index = 0
            for step in job.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                action = str(step.get("uses", ""))
                if "aws-actions/configure-aws-credentials@" not in action:
                    continue
                calls.append(
                    {
                        "workflow": workflow_path.name,
                        "job": str(job_name),
                        "call_index": call_index,
                        "action": action,
                        "role_to_assume": str(
                            (step.get("with") or {}).get("role-to-assume", "")
                        ),
                    }
                )
                call_index += 1
    return calls


def validate_repository_credential_inventory(
    policy: dict[str, Any],
    workflows_dir: Path,
) -> None:
    """Require an exclusive disposition for every active AWS OIDC call."""

    gate = policy.get("repo_global_oidc_cutover_gate")
    _require(
        isinstance(gate, dict),
        "repository-global OIDC cutover gate must be an object",
    )
    inventory = gate.get("active_credential_calls")
    _require(
        isinstance(inventory, list),
        "active AWS credential inventory must be a list",
    )
    identifiers: set[tuple[str, str, int]] = set()
    expected_calls: list[dict[str, Any]] = []
    canonical_calls: list[dict[str, Any]] = []
    migrated_calls: list[dict[str, Any]] = []
    blocked_calls: list[dict[str, Any]] = []
    for item in inventory:
        _require(isinstance(item, dict), "invalid AWS credential inventory entry")
        workflow = item.get("workflow")
        job = item.get("job")
        call_index = item.get("call_index")
        action = item.get("action")
        role_to_assume = item.get("role_to_assume")
        disposition = item.get("disposition")
        _require(
            isinstance(workflow, str)
            and isinstance(job, str)
            and isinstance(call_index, int)
            and call_index >= 0
            and isinstance(action, str)
            and action.startswith("aws-actions/configure-aws-credentials@")
            and isinstance(role_to_assume, str)
            and role_to_assume,
            "AWS credential inventory entry is incomplete",
        )
        identifier = (workflow, job, call_index)
        _require(
            identifier not in identifiers,
            f"duplicate AWS credential inventory entry: {identifier}",
        )
        identifiers.add(identifier)
        expected_calls.append(
            {
                "workflow": workflow,
                "job": job,
                "call_index": call_index,
                "action": action,
                "role_to_assume": role_to_assume,
            }
        )
        if disposition == CANONICAL_CREDENTIAL_DISPOSITION:
            canonical_calls.append(item)
        elif disposition == MIGRATED_CREDENTIAL_DISPOSITION:
            migrated_calls.append(item)
        elif disposition == BLOCKED_CREDENTIAL_DISPOSITION:
            blocked_calls.append(item)
        else:
            raise CloudRolePolicyError(
                f"{workflow}#{job}[{call_index}]: unknown credential disposition"
            )

    actual_calls = collect_repository_credential_calls(workflows_dir)
    _require(
        expected_calls == actual_calls,
        "active AWS credential call set differs from the exclusive repository "
        "inventory",
    )
    _require(
        gate.get("active_credential_call_count") == len(inventory),
        "active AWS credential call count differs",
    )
    _require(
        gate.get("canonical_call_count") == len(canonical_calls),
        "canonical AWS credential call count differs",
    )
    _require(
        gate.get("blocked_pending_migration_call_count") == len(blocked_calls),
        "blocked AWS credential call count differs",
    )
    _require(
        gate.get("migrated_exact_call_count") == len(migrated_calls),
        "migrated exact AWS credential call count differs",
    )

    retired_calls = gate.get("retired_credential_calls")
    _require(
        isinstance(retired_calls, list),
        "retired AWS credential inventory must be a list",
    )
    for item in retired_calls:
        _require(isinstance(item, dict), "invalid retired credential entry")
        workflow = item.get("workflow")
        job = item.get("job")
        call_index = item.get("call_index")
        identifier = (workflow, job, call_index)
        _require(
            isinstance(workflow, str)
            and isinstance(job, str)
            and isinstance(call_index, int)
            and call_index >= 0
            and item.get("disposition") == RETIRED_CREDENTIAL_DISPOSITION
            and isinstance(item.get("retirement_reason"), str)
            and item["retirement_reason"].strip(),
            "retired AWS credential entry is incomplete",
        )
        _require(
            identifier not in identifiers,
            f"active/retired AWS credential inventory overlap: {identifier}",
        )
        identifiers.add(identifier)
        _require(
            not (workflows_dir / workflow).exists(),
            f"{workflow}: retired credential workflow must be absent",
        )
    _require(
        gate.get("retired_call_count") == len(retired_calls),
        "retired AWS credential call count differs",
    )
    _require(
        gate.get("baseline_credential_call_count")
        == len(inventory) + len(retired_calls)
        == 27
        and len(canonical_calls) == 7,
        "reviewed repository AWS credential matrix cardinality differs",
    )
    canonical_workflows = {
        item["workflow"]
        for item in canonical_calls
    }
    _require(
        canonical_workflows == set(WORKFLOW_ROLE_EXPECTATIONS),
        "canonical AWS credential matrix differs from the reviewed seven",
    )
    _require(
        all(
            item.get("required_evidence_state")
            == "EXACT_TOKEN_ACCEPTED_BY_AWS_STS"
            for item in canonical_calls + migrated_calls
        ),
        "exact-role AWS credential calls require exact-token AWS STS evidence",
    )
    for item in migrated_calls:
        validate_migrated_credential_identity(workflows_dir, item)
    _require(
        all(
            isinstance(item.get("block_reason"), str)
            and item["block_reason"].strip()
            for item in blocked_calls
        ),
        "blocked AWS credential calls require an explicit reason",
    )
    _require(
        gate.get("prepared_state") == REPO_GLOBAL_OIDC_PREPARED_STATE,
        "repository-global OIDC prepared-state contract differs",
    )
    _require(
        gate.get("ready_state") == CUTOVER_READY_STATE,
        "repository-global OIDC ready-state contract differs",
    )
    preparation_evidence = gate.get("external_preparation_evidence")
    activation_evidence = gate.get("external_activation_evidence")
    _require(
        isinstance(preparation_evidence, dict)
        and preparation_evidence.get("accepted_state")
        == PREPARATION_EVIDENCE_ACCEPTED_STATE,
        "repository-global OIDC preparation evidence contract differs",
    )
    _require(
        isinstance(activation_evidence, dict)
        and activation_evidence.get("accepted_state")
        == ACTIVATION_EVIDENCE_ACCEPTED_STATE,
        "repository-global OIDC activation evidence contract differs",
    )

    if blocked_calls:
        _require(
            gate.get("preparation_state")
            == REPO_GLOBAL_OIDC_PREPARATION_STATE,
            "blocked credential calls require a blocked preparation state",
        )
    elif gate.get("preparation_state") == REPO_GLOBAL_OIDC_PREPARED_STATE:
        _require(
            preparation_evidence.get("state")
            == PREPARATION_EVIDENCE_ACCEPTED_STATE
            and _is_sha256(preparation_evidence.get("matrix_sha256"))
            and _is_sha256(preparation_evidence.get("trust_readback_sha256"))
            and preparation_evidence.get("covered_baseline_call_count") == 27,
            "prepared OIDC cutover requires exact future-trust and retirement "
            "readback evidence for the complete baseline matrix",
        )
    else:
        _require(
            gate.get("preparation_state")
            == REPO_GLOBAL_OIDC_PREPARATION_STATE
            and preparation_evidence.get("state")
            == "BLOCKED_PENDING_EXTERNAL_FUTURE_TRUST_READBACK"
            and preparation_evidence.get("matrix_sha256") is None
            and preparation_evidence.get("trust_readback_sha256") is None
            and preparation_evidence.get("covered_baseline_call_count") == 0,
            "retired credential matrix must remain blocked until exact "
            "external future-trust readback evidence is accepted",
        )

    if gate.get("activation_state") == CUTOVER_READY_STATE:
        _require(
            not blocked_calls
            and gate.get("preparation_state") == REPO_GLOBAL_OIDC_PREPARED_STATE
            and activation_evidence.get("state")
            == ACTIVATION_EVIDENCE_ACCEPTED_STATE
            and _is_sha256(activation_evidence.get("matrix_sha256"))
            and _is_sha256(activation_evidence.get("sts_readback_sha256"))
            and activation_evidence.get("covered_baseline_call_count") == 27,
            "ready OIDC cutover requires complete exact-token AWS STS or "
            "retirement evidence",
        )
    else:
        _require(
            gate.get("activation_state") == REPO_GLOBAL_OIDC_CUTOVER_STATE,
            "repository-global OIDC activation state is unknown",
        )


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and set(value).issubset(set("0123456789abcdef"))
    )


def require_repo_global_oidc_cutover_prepared(
    policy: dict[str, Any],
) -> None:
    """Fail until all baseline calls have staged exact trust or are retired."""

    gate = policy.get("repo_global_oidc_cutover_gate") or {}
    blocked = [
        item
        for item in gate.get("active_credential_calls") or []
        if isinstance(item, dict)
        and item.get("disposition") == BLOCKED_CREDENTIAL_DISPOSITION
    ]
    _require(
        gate.get("preparation_state") == gate.get("prepared_state")
        and not blocked,
        "repository-global OIDC template change is blocked until every "
        "credential call has staged exact future trust or is retired",
    )


def require_repo_global_oidc_cutover_ready(policy: dict[str, Any]) -> None:
    """Fail unless every active credential call has completed exact attestation."""

    require_repo_global_oidc_cutover_prepared(policy)
    gate = policy.get("repo_global_oidc_cutover_gate") or {}
    _require(
        gate.get("activation_state") == gate.get("ready_state"),
        "repository-global OIDC finalize is blocked until every active token "
        "is accepted by AWS STS or its workflow is retired",
    )


def validate_migrated_credential_identity(
    workflows_dir: Path,
    item: dict[str, Any],
) -> None:
    """Validate a future non-core workflow before global subject cutover."""

    workflow_path = workflows_dir / item["workflow"]
    try:
        document = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CloudRolePolicyError(
            f"{workflow_path.name}: cannot load migrated workflow: {exc}"
        ) from exc
    _require(
        isinstance(document, dict),
        f"{workflow_path.name}: migrated workflow is invalid",
    )
    jobs = document.get("jobs") or {}
    job = jobs.get(item["job"]) if isinstance(jobs, dict) else None
    _require(
        isinstance(job, dict),
        f"{workflow_path.name}: migrated job is absent",
    )
    credential_steps = [
        (step_index, step)
        for step_index, step in enumerate(job.get("steps") or [])
        if isinstance(step, dict)
        and "aws-actions/configure-aws-credentials@"
        in str(step.get("uses", ""))
    ]
    call_index = item["call_index"]
    _require(
        call_index < len(credential_steps),
        f"{workflow_path.name}: migrated credential call is absent",
    )
    step_index, step = credential_steps[call_index]
    steps = job.get("steps") or []
    _require(
        step_index > 0 and isinstance(steps[step_index - 1], dict),
        f"{workflow_path.name}: migrated credential call lacks immediate "
        "exact-token attestation",
    )
    attestation = steps[step_index - 1]
    attestation_run = str(attestation.get("run", ""))
    _require(
        attestation.get("name") == "Attest exact live GitHub OIDC claims"
        and "python3 scripts/junca_oidc_claim_attestation.py" in attestation_run
        and f'".github/workflows/{workflow_path.name}"' in attestation_run
        and "--role-arn" in attestation_run
        and "--output" in attestation_run,
        f"{workflow_path.name}: migrated exact-token attestation is incomplete",
    )
    environment = job.get("environment")
    _require(
        isinstance(environment, str) and environment,
        f"{workflow_path.name}: migrated job environment must be exact",
    )
    workflow_environment = document.get("env") or {}
    job_environment = {
        **workflow_environment,
        **(job.get("env") or {}),
        **(step.get("env") or {}),
    }
    role_expression = str((step.get("with") or {}).get("role-to-assume", ""))
    resolved_role = _resolve_role_expression(role_expression, job_environment)
    _require(
        item.get("expected_role_arn") == resolved_role,
        f"{workflow_path.name}: migrated exact role ARN differs",
    )
    expected_subject = SUBJECT_TEMPLATE.format(
        repository=REPOSITORY,
        environment=environment,
        workflow=workflow_path.name,
    )
    _require(
        item.get("exact_subject") == expected_subject,
        f"{workflow_path.name}: migrated exact subject differs",
    )
    permissions = document.get("permissions") or {}
    job_permissions = job.get("permissions") or {}
    effective_id_token = (
        job_permissions.get("id-token")
        if isinstance(job_permissions, dict) and "id-token" in job_permissions
        else permissions.get("id-token")
        if isinstance(permissions, dict)
        else None
    )
    _require(
        effective_id_token == "write",
        f"{workflow_path.name}: migrated workflow lacks exact id-token permission",
    )
    text = workflow_path.read_text(encoding="utf-8")
    _require(
        "refs/heads/main" in text,
        f"{workflow_path.name}: migrated workflow lacks a main-ref gate",
    )


def validate_allowed_workflow_identity(
    workflow_path: Path,
    *,
    expected_role_key: str,
) -> None:
    try:
        text = workflow_path.read_text(encoding="utf-8")
        document = yaml.safe_load(text)
    except (OSError, yaml.YAMLError) as exc:
        raise CloudRolePolicyError(
            f"{workflow_path.name}: cannot load allowed workflow: {exc}"
        ) from exc
    _require(isinstance(document, dict), f"{workflow_path.name}: invalid workflow")
    _require(
        "assume-role-with-web-identity" not in text
        and "ACTIONS_ID_TOKEN_REQUEST" not in text,
        f"{workflow_path.name}: raw OIDC acquisition is forbidden",
    )
    workflow_environment = document.get("env") or {}
    _require(
        isinstance(workflow_environment, dict),
        f"{workflow_path.name}: workflow env must be an object",
    )
    acquired_roles: list[str] = []
    for job_name, job in (document.get("jobs") or {}).items():
        _require(isinstance(job, dict), f"{workflow_path.name}: invalid job {job_name}")
        job_environment = {**workflow_environment, **(job.get("env") or {})}
        steps = job.get("steps") or []
        for step_index, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            if "configure-aws-credentials" not in str(step.get("uses", "")):
                continue
            _require(
                step_index > 0 and isinstance(steps[step_index - 1], dict),
                f"{workflow_path.name}#{job_name}: AWS identity is not "
                "immediately preceded by exact-token attestation",
            )
            attestation_step = steps[step_index - 1]
            attestation_run = str(attestation_step.get("run", ""))
            _require(
                attestation_step.get("name")
                == "Attest exact live GitHub OIDC claims"
                and "python3 scripts/junca_oidc_claim_attestation.py"
                in attestation_run
                and "--workflow-path" in attestation_run
                and f'".github/workflows/{workflow_path.name}"'
                in attestation_run
                and "--role-arn" in attestation_run
                and "--output" in attestation_run
                and attestation_step.get("continue-on-error") is not True,
                f"{workflow_path.name}#{job_name}: exact-token attestation "
                "must immediately precede AWS credential acquisition",
            )
            _require(
                job.get("environment") == ENVIRONMENT,
                f"{workflow_path.name}#{job_name}: AWS identity requires "
                f"environment {ENVIRONMENT}",
            )
            step_environment = {**job_environment, **(step.get("env") or {})}
            role = str((step.get("with") or {}).get("role-to-assume", ""))
            acquired_roles.append(_resolve_role_expression(role, step_environment))
    expected_role_arn = ROLE_ARNS[expected_role_key]
    _require(
        acquired_roles == [expected_role_arn],
        f"{workflow_path.name}: acquired roles differ; "
        f"expected {[expected_role_arn]}, got {acquired_roles}",
    )
    if workflow_path.name == "junca-validator-ami-build.yml":
        build_job = (document.get("jobs") or {}).get("build") or {}
        build_steps = build_job.get("steps") or []
        _require(
            len(build_steps) >= 2
            and isinstance(build_steps[0], dict)
            and isinstance(build_steps[1], dict),
            "junca-validator-ami-build.yml: trusted pre-checkout binding is absent",
        )
        precheckout = build_steps[0]
        precheckout_run = str(precheckout.get("run", ""))
        checkout = build_steps[1]
        _require(
            precheckout.get("name") == "Bind trusted main execution before checkout"
            and precheckout.get("shell") == "bash"
            and 'test "$GITHUB_REPOSITORY" = \\\n'
            in precheckout_run
            and '"JAIOS-Governance/junca-social-ecosystem-chain"'
            in precheckout_run
            and 'test "$GITHUB_REF" = "refs/heads/main"'
            in precheckout_run
            and 'test "$GITHUB_REF_TYPE" = "branch"'
            in precheckout_run
            and 'test "$GITHUB_SHA" = "$SOURCE_COMMIT"'
            in precheckout_run
            and "[[ \"$SOURCE_COMMIT\" =~ ^[0-9a-f]{40}$ ]]"
            in precheckout_run
            and str(checkout.get("uses", "")).startswith("actions/checkout@")
            and (checkout.get("with") or {}).get("ref")
            == "${{ inputs.source_commit }}",
            "junca-validator-ami-build.yml: untrusted source can execute "
            "before immutable main binding",
        )
    has_direct_main_ref_gate = "refs/heads/main" in text
    has_api_main_sha_gate = (
        '.head_branch == "main"' in text and ".head_sha ==" in text
    )
    _require(
        has_direct_main_ref_gate or has_api_main_sha_gate,
        f"{workflow_path.name}: exact main ref/SHA enforcement is absent",
    )
    trigger = document.get("on", document.get(True))
    if isinstance(trigger, dict) and "workflow_run" in trigger:
        has_workflow_run_branch_gate = (
            "WORKFLOW_RUN_HEAD_BRANCH" in text
            or '.head_branch == "main"' in text
        )
        has_workflow_run_sha_gate = (
            "WORKFLOW_RUN_HEAD_SHA" in text
            or ".head_sha ==" in text
        )
        _require(
            has_workflow_run_branch_gate and has_workflow_run_sha_gate,
            f"{workflow_path.name}: workflow_run branch/SHA binding is incomplete",
        )


def validate_policy(policy: dict[str, Any], workflows_dir: Path) -> None:
    _require(
        policy.get("schema_version") == "junca-public-testnet-cloud-role-policy/v1",
        "unexpected cloud role policy schema",
    )
    _require(policy.get("repository") == REPOSITORY, "repository boundary differs")
    _require(policy.get("environment") == ENVIRONMENT, "environment boundary differs")
    _require(
        policy.get("oidc_subject_claim_keys")
        == ["repo", "context", "workflow_ref", "runner_environment"],
        "OIDC subject claim keys differ",
    )
    _require(
        policy.get("oidc_use_immutable_subject") is True,
        "immutable GitHub OIDC subject opt-in must be explicit",
    )
    _require(policy.get("subject_template") == SUBJECT_TEMPLATE, "subject template differs")
    _require(
        "job_workflow_ref" not in json.dumps(policy, sort_keys=True),
        "job_workflow_ref is forbidden for direct workflow jobs",
    )
    _require(
        policy.get("external_oidc_readback_state")
        == "BLOCKED_PENDING_EXTERNAL_READBACK",
        "external OIDC/JWT readback must remain explicitly blocked",
    )
    _require(
        policy.get("runtime_recovery_execution_state")
        == "BLOCKED_PENDING_ATTESTED_LAUNCH_AND_SSM_CONTRACT",
        "runtime recovery must remain blocked until fixed SSM/launch attestation",
    )
    _require(
        policy.get("prohibited_legacy_subject") == LEGACY_SUBJECT,
        "legacy subject must be recorded exactly",
    )
    validate_repository_credential_inventory(policy, workflows_dir)
    roles = policy.get("roles")
    _require(
        isinstance(roles, dict)
        and set(roles) == {"foundation", "ami_builder", "observer", "security_bootstrap"},
        "role set differs from the approved boundary",
    )
    allowed_workflows: set[str] = set()
    for role_key, expected_workflows in ROLE_WORKFLOWS.items():
        role = roles[role_key]
        _require(
            role.get("role_name") == ROLE_NAMES[role_key],
            f"{role_key}: role name differs",
        )
        _require(role.get("oidc_enabled") is True, f"{role_key}: OIDC must be enabled")
        actual_workflows = role.get("exact_workflow_allowlist")
        _require(
            isinstance(actual_workflows, list)
            and len(actual_workflows) == len(set(actual_workflows))
            and set(actual_workflows) == expected_workflows,
            f"{role_key}: exact workflow allowlist differs",
        )
        for workflow in expected_workflows:
            _require(
                (workflows_dir / workflow).is_file(),
                f"{role_key}: allowed workflow is absent: {workflow}",
            )
        overlap = allowed_workflows.intersection(expected_workflows)
        _require(not overlap, f"workflow role overlap: {sorted(overlap)}")
        allowed_workflows.update(expected_workflows)
        expected_subjects = {exact_subject(workflow) for workflow in expected_workflows}
        actual_subjects = role.get("exact_subject_allowlist")
        _require(
            isinstance(actual_subjects, list)
            and len(actual_subjects) == len(set(actual_subjects))
            and set(actual_subjects) == expected_subjects,
            f"{role_key}: exact subject allowlist differs",
        )
        _require(
            all(subject != LEGACY_SUBJECT for subject in actual_subjects),
            f"{role_key}: legacy environment-only subject is forbidden",
        )
        _require(
            all(
                subject.startswith(
                    "repo:JAIOS-Governance@308604370/"
                    "junca-social-ecosystem-chain@1310568313:"
                )
                and subject.endswith(
                    ":runner_environment:github-hosted"
                )
                for subject in actual_subjects
            ),
            f"{role_key}: immutable repo or hosted-runner subject differs",
        )
    _require(
        roles["observer"].get("mutation_capable") is False,
        "Observer must be read-only",
    )
    for mutation_role in ("foundation", "ami_builder"):
        _require(
            roles[mutation_role].get("mutation_capable") is True,
            f"{mutation_role}: mutation capability declaration differs",
        )
    _require(
        roles["foundation"].get("blocked_capabilities")
        == [
            "ec2:validator-host-replacement",
            "iam:PassRole:validator-instance-role",
            "ssm:validator-command-execution",
        ],
        "Foundation unsafe runtime capabilities must remain blocked",
    )
    security = roles["security_bootstrap"]
    _require(
        security.get("role_name") == ROLE_NAMES["security_bootstrap"],
        "Security Bootstrap role name differs",
    )
    _require(security.get("oidc_enabled") is False, "Security Bootstrap must be non-OIDC")
    _require(
        security.get("exact_workflow_allowlist") == []
        and security.get("exact_subject_allowlist") == [],
        "Security Bootstrap cannot trust a GitHub workflow",
    )
    _require(
        security.get("trust_boundary") == "NON_OIDC_MFA_ADMIN_SESSION_ONLY",
        "Security Bootstrap trust boundary differs",
    )
    _require(
        security.get("prohibited_principals") == ["token.actions.githubusercontent.com"],
        "GitHub OIDC principal must be prohibited for Security Bootstrap",
    )
    _require(
        policy.get("canonical_release_role_mapping") == CANONICAL_ROLE_MAPPING,
        "canonical release role mapping differs",
    )
    _require(
        allowed_workflows == set(WORKFLOW_ROLE_EXPECTATIONS),
        "OIDC workflow set differs from the seven reviewed workflows",
    )
    for workflow, role_key in WORKFLOW_ROLE_EXPECTATIONS.items():
        validate_allowed_workflow_identity(
            workflows_dir / workflow,
            expected_role_key=role_key,
        )
    _require(
        policy.get("temporary_non_oidc_operations")
        == [
            {
                "workflow": "junca-validator-state-migration.yml",
                "purpose": "One-time durable validator state migration",
                "steady_state_role_allowed": False,
                "oidc_enabled": False,
                "execution_state": (
                    "BLOCKED_UNTIL_DEDICATED_NON_OIDC_AUTHORIZATION"
                ),
            }
        ],
        "temporary state migration must remain non-OIDC and blocked",
    )
    blocked_mutators = policy.get("blocked_oidc_template_mutators")
    _require(
        isinstance(blocked_mutators, list),
        "blocked OIDC template mutators must be a list",
    )
    blocked_names = [
        item.get("workflow")
        for item in blocked_mutators
        if isinstance(item, dict)
    ]
    _require(
        len(blocked_names) == len(set(blocked_names))
        and set(blocked_names) == OIDC_TEMPLATE_MUTATOR_WORKFLOWS,
        "blocked OIDC template mutator set differs",
    )
    for item in blocked_mutators:
        _require(isinstance(item, dict), "invalid blocked OIDC mutator entry")
        workflow = item.get("workflow")
        _require(
            isinstance(workflow, str)
            and isinstance(item.get("original_name"), str)
            and isinstance(item.get("retired_reason"), str)
            and item["retired_reason"].strip()
            and item.get("disposition") == "DELETE_WORKFLOW_FILE",
            "blocked OIDC mutator entry is incomplete",
        )
        _require(
            not (workflows_dir / workflow).exists(),
            f"{workflow}: OIDC template mutator workflow must be absent",
        )
    blocked_raw_oidc = policy.get("blocked_raw_oidc_workflows")
    _require(
        isinstance(blocked_raw_oidc, list),
        "blocked raw OIDC workflows must be a list",
    )
    blocked_raw_names = [
        item.get("workflow")
        for item in blocked_raw_oidc
        if isinstance(item, dict)
    ]
    _require(
        len(blocked_raw_names) == len(set(blocked_raw_names))
        and set(blocked_raw_names) == RAW_OIDC_QUARANTINE_WORKFLOWS,
        "blocked raw OIDC workflow set differs",
    )
    for item in blocked_raw_oidc:
        _require(isinstance(item, dict), "invalid blocked raw OIDC entry")
        workflow = item.get("workflow")
        _require(
            isinstance(workflow, str)
            and isinstance(item.get("original_name"), str)
            and isinstance(item.get("retired_reason"), str)
            and item["retired_reason"].strip()
            and item.get("disposition") == "DELETE_WORKFLOW_FILE",
            "blocked raw OIDC entry is incomplete",
        )
        _require(
            not (workflows_dir / workflow).exists(),
            f"{workflow}: raw OIDC workflow must be absent",
        )
    _require(
        policy.get("quarantine_mode") == "DELETE_WORKFLOW_FILE",
        "quarantine must delete the workflow execution entry point",
    )
    quarantine = policy.get("quarantine")
    _require(isinstance(quarantine, list), "quarantine must be a list")
    quarantine_names = [item.get("workflow") for item in quarantine if isinstance(item, dict)]
    _require(
        len(quarantine_names) == len(set(quarantine_names))
        and set(quarantine_names) == QUARANTINE_WORKFLOWS,
        "quarantine workflow set differs",
    )
    _require(
        not allowed_workflows.intersection(QUARANTINE_WORKFLOWS),
        "an OIDC-allowed workflow is quarantined",
    )
    for item in quarantine:
        _require(isinstance(item, dict), "invalid quarantine entry")
        workflow = item.get("workflow")
        original_name = item.get("original_name")
        retired_reason = item.get("retired_reason")
        _require(
            isinstance(workflow, str)
            and isinstance(original_name, str)
            and isinstance(retired_reason, str)
            and retired_reason.strip(),
            "quarantine entry is incomplete",
        )
        _require(
            not (workflows_dir / workflow).exists(),
            f"{workflow}: quarantined workflow must be absent",
        )
    for workflow_path in sorted(workflows_dir.glob("*.y*ml")):
        workflow_text = workflow_path.read_text(encoding="utf-8")
        forbidden_template_tokens = sorted(
            token
            for token in FORBIDDEN_OIDC_TEMPLATE_MUTATION_TOKENS
            if token in workflow_text
        )
        _require(
            not forbidden_template_tokens,
            f"{workflow_path.name}: repository OIDC template mutation is "
            f"forbidden: {forbidden_template_tokens}",
        )
        forbidden_raw_oidc_tokens = sorted(
            token
            for token in FORBIDDEN_RAW_OIDC_WORKFLOW_TOKENS
            if token in workflow_text
        )
        _require(
            not forbidden_raw_oidc_tokens,
            f"{workflow_path.name}: raw GitHub OIDC or direct web-identity "
            f"STS is forbidden: {forbidden_raw_oidc_tokens}",
        )
        stale_references = sorted(
            workflow
            for workflow in (
                QUARANTINE_WORKFLOWS | OIDC_TEMPLATE_MUTATOR_WORKFLOWS
            )
            if workflow in workflow_text
        )
        _require(
            not stale_references,
            f"{workflow_path.name}: references quarantined workflows: "
            f"{stale_references}",
        )
    _require(
        policy.get("release_boundary")
        == {
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        },
        "release boundary differs",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("config/junca_public_testnet_cloud_role_policy.json"),
    )
    parser.add_argument(
        "--workflows-dir",
        type=Path,
        default=Path(".github/workflows"),
    )
    parser.add_argument(
        "--require-repo-global-oidc-cutover-prepared",
        action="store_true",
        help=(
            "fail until every baseline AWS credential call has staged exact "
            "future trust or is retired"
        ),
    )
    parser.add_argument(
        "--require-repo-global-oidc-cutover-ready",
        action="store_true",
        help=(
            "fail until every active AWS credential call is exactly trusted, "
            "STS-attested, or retired"
        ),
    )
    args = parser.parse_args()
    policy = load_policy(args.policy)
    validate_policy(policy, args.workflows_dir)
    if args.require_repo_global_oidc_cutover_prepared:
        require_repo_global_oidc_cutover_prepared(policy)
    if args.require_repo_global_oidc_cutover_ready:
        require_repo_global_oidc_cutover_ready(policy)
    print("JSEC cloud role policy and quarantine: VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
