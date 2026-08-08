"""Fail-closed Terraform plan evaluation for Mainnet candidate infrastructure.

The guard reads Terraform JSON plan structure and rejects managed-resource
deletions, replacements, unknown actions and incomplete plan metadata.  It never
runs Terraform and cannot authorize apply or Mainnet activation.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "junca-mainnet-terraform-plan-guard/v1"
PLAN_DOMAIN = b"JUNCA_MAINNET_TERRAFORM_PLAN_GUARD_V1\x00"
_ALLOWED_ACTIONS = frozenset({("no-op",), ("read",), ("create",), ("update",)})


class TerraformPlanGuardError(ValueError):
    """Raised when a Terraform plan cannot be safely evaluated."""


@dataclass(frozen=True)
class PlanViolation:
    address: str
    actions: tuple[str, ...]
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "actions": list(self.actions),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class TerraformPlanGuardResult:
    terraform_version: str
    format_version: str
    resource_change_count: int
    reviewed_actions: tuple[tuple[str, tuple[str, ...]], ...]
    violations: tuple[PlanViolation, ...]
    plan_digest: str

    @property
    def approved(self) -> bool:
        return not self.violations

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "terraform_version": self.terraform_version,
            "format_version": self.format_version,
            "resource_change_count": self.resource_change_count,
            "reviewed_actions": [
                {"address": address, "actions": list(actions)}
                for address, actions in self.reviewed_actions
            ],
            "violations": [item.as_dict() for item in self.violations],
            "plan_digest": self.plan_digest,
            "approved": self.approved,
            "apply_authorized": False,
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }


def evaluate_terraform_plan(plan: Mapping[str, Any]) -> TerraformPlanGuardResult:
    if not isinstance(plan, Mapping):
        raise TerraformPlanGuardError("Terraform plan must be a mapping")
    terraform_version = _text(plan.get("terraform_version"), "terraform_version")
    format_version = _text(plan.get("format_version"), "format_version")
    changes = plan.get("resource_changes")
    if not isinstance(changes, list):
        raise TerraformPlanGuardError("resource_changes must be a list")

    reviewed: list[tuple[str, tuple[str, ...]]] = []
    violations: list[PlanViolation] = []
    seen: set[str] = set()

    for index, raw in enumerate(changes):
        if not isinstance(raw, Mapping):
            raise TerraformPlanGuardError(
                f"resource_changes[{index}] must be a mapping"
            )
        address = _text(raw.get("address"), f"resource_changes[{index}].address")
        if address in seen:
            raise TerraformPlanGuardError("resource change addresses must be unique")
        seen.add(address)

        mode = raw.get("mode", "managed")
        if mode not in {"managed", "data"}:
            raise TerraformPlanGuardError("resource change mode is invalid")
        change = raw.get("change")
        if not isinstance(change, Mapping):
            raise TerraformPlanGuardError("resource change payload is missing")
        actions_raw = change.get("actions")
        if (
            not isinstance(actions_raw, list)
            or not actions_raw
            or any(not isinstance(item, str) or not item for item in actions_raw)
        ):
            raise TerraformPlanGuardError("resource change actions are invalid")
        actions = tuple(actions_raw)
        reviewed.append((address, actions))

        if mode == "data":
            if actions not in {("read",), ("no-op",)}:
                violations.append(
                    PlanViolation(
                        address=address,
                        actions=actions,
                        reason="data source contains a non-read action",
                    )
                )
            continue

        if "delete" in actions:
            violations.append(
                PlanViolation(
                    address=address,
                    actions=actions,
                    reason=(
                        "managed resource replacement is prohibited"
                        if "create" in actions
                        else "managed resource deletion is prohibited"
                    ),
                )
            )
        elif actions not in _ALLOWED_ACTIONS:
            violations.append(
                PlanViolation(
                    address=address,
                    actions=actions,
                    reason="managed resource action is not allowlisted",
                )
            )

    canonical = {
        "terraform_version": terraform_version,
        "format_version": format_version,
        "resource_changes": [
            {"address": address, "actions": list(actions)}
            for address, actions in sorted(reviewed)
        ],
    }
    digest = "0x" + hashlib.sha256(
        PLAN_DOMAIN
        + json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return TerraformPlanGuardResult(
        terraform_version=terraform_version,
        format_version=format_version,
        resource_change_count=len(reviewed),
        reviewed_actions=tuple(sorted(reviewed)),
        violations=tuple(sorted(violations, key=lambda item: item.address)),
        plan_digest=digest,
    )


def require_safe_terraform_plan(plan: Mapping[str, Any]) -> TerraformPlanGuardResult:
    result = evaluate_terraform_plan(plan)
    if not result.approved:
        details = ", ".join(
            f"{item.address}: {item.reason}" for item in result.violations
        )
        raise TerraformPlanGuardError(f"Terraform plan is not safe: {details}")
    return result


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise TerraformPlanGuardError(f"{field} must be non-empty text")
    return value.strip()
