"""Fail-closed JSEC native-token Genesis plan and fixed-date schedule gate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


SCHEMA_VERSION = "jsec-native-token-genesis-plan/v1"
ECONOMICS_DEFINITION_SCHEMA_VERSION = "jsec-native-economics-definition/v1"
GENESIS_CANDIDATE_SCHEMA_VERSION = "jsec-native-genesis-candidate/v1"
OFFICIAL_NAME = "JUNCA Social Ecosystem Chain"
GOVERNANCE = "JAIOS Institutional Governance"
ECONOMICS_AUTHORITY = "JUNCA Holdings Founder / Chairman / CEO"
TARGET_GENESIS_DATE = date(2026, 10, 1)
ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
SYMBOL = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

ECONOMICS_DEFINITION_FIELDS = (
    "name",
    "symbol",
    "decimals",
    "total_supply_base_units",
    "supply_model",
    "post_genesis_issuance",
    "fee_model",
)

ECONOMICS_APPROVAL_FIELDS = (
    "authority",
    "status",
    "decision_record_id",
    "approved_definition_sha256",
    "decision_record_sha256",
    "approved_at",
)

LOCKED_MILESTONES = (
    ("native_economics_constitution", date(2026, 8, 7)),
    ("deterministic_genesis_allocations", date(2026, 8, 21)),
    ("custody_key_ceremony_rehearsal", date(2026, 9, 4)),
    ("independent_security_review", date(2026, 9, 11)),
    ("candidate_genesis_and_recovery", date(2026, 9, 18)),
    ("production_slo_24h_soak_release_evidence", date(2026, 9, 25)),
    ("governance_and_ceo_final_approval", TARGET_GENESIS_DATE),
)

REQUIRED_GATES = (
    "native_economics_locked",
    "deterministic_genesis_allocations",
    "custody_key_ceremony",
    "independent_security_review",
    "disaster_recovery_rehearsal",
    "production_slo_and_24h_soak",
    "governance_release_authorization",
    "ceo_final_approval",
)

MILESTONE_GATES = {
    "native_economics_constitution": ("native_economics_locked",),
    "deterministic_genesis_allocations": (
        "deterministic_genesis_allocations",
    ),
    "custody_key_ceremony_rehearsal": ("custody_key_ceremony",),
    "independent_security_review": ("independent_security_review",),
    "candidate_genesis_and_recovery": ("disaster_recovery_rehearsal",),
    "production_slo_24h_soak_release_evidence": (
        "production_slo_and_24h_soak",
    ),
    "governance_and_ceo_final_approval": (
        "governance_release_authorization",
        "ceo_final_approval",
    ),
}


class NativeTokenGenesisError(ValueError):
    """Raised when native-token Genesis inputs or schedule state are unsafe."""


@dataclass(frozen=True)
class GenesisAllocation:
    address: str
    amount_base_units: int
    category: str


@dataclass(frozen=True)
class GenesisMilestone:
    milestone_id: str
    due_date: date
    status: str
    owner: str


@dataclass(frozen=True)
class NativeTokenGenesisPlan:
    definition: Mapping[str, Any]
    economics_approval: Mapping[str, Any]
    allocations_locked: bool
    allocations: tuple[GenesisAllocation, ...]
    custody: Mapping[str, Any]
    gates: tuple[tuple[str, bool], ...]
    milestones: tuple[GenesisMilestone, ...]
    specification_digest: str

    @property
    def target_date(self) -> date:
        return TARGET_GENESIS_DATE

    @property
    def missing_gates(self) -> tuple[str, ...]:
        return tuple(name for name, passed in self.gates if not passed)

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.definition.get("locked") is not True:
            blockers.append("native-token-definition")
        if self.economics_approval.get("status") != "approved":
            blockers.append("native-economics-approval")
        if not self.allocations_locked:
            blockers.append("genesis-allocations")
        if self.custody.get("locked") is not True:
            blockers.append("institutional-custody")
        blockers.extend(self.missing_gates)
        return tuple(blockers)

    @property
    def ready_for_genesis_ceremony(self) -> bool:
        return not self.blockers

    def overdue_milestones(self, as_of: date) -> tuple[str, ...]:
        _require_date(as_of, "as_of")
        return tuple(
            item.milestone_id
            for item in self.milestones
            if item.status != "completed" and as_of > item.due_date
        )

    def schedule_state(self, as_of: date) -> str:
        _require_date(as_of, "as_of")
        if self.ready_for_genesis_ceremony:
            return "READY_FOR_CEREMONY"
        if as_of > TARGET_GENESIS_DATE:
            return "TARGET_MISSED"
        if self.overdue_milestones(as_of):
            return "AT_RISK"
        return "ON_TRACK"

    def assert_on_track(self, as_of: date) -> None:
        state = self.schedule_state(as_of)
        if state not in {"ON_TRACK", "READY_FOR_CEREMONY"}:
            details = ", ".join(self.overdue_milestones(as_of)) or "target-date"
            raise NativeTokenGenesisError(f"native Genesis schedule {state}: {details}")

    def assert_ready_for_genesis_ceremony(self) -> None:
        if self.blockers:
            raise NativeTokenGenesisError(
                "native Genesis ceremony blocked by: " + ", ".join(self.blockers)
            )

    def economics_decision_packet(self) -> dict[str, Any]:
        definition = {
            key: self.definition[key]
            for key in ECONOMICS_DEFINITION_FIELDS
        }
        missing = [key for key, value in definition.items() if value is None]
        return {
            "schema_version": "jsec-native-economics-decision-packet/v1",
            "official_name": OFFICIAL_NAME,
            "governance": GOVERNANCE,
            "authority_required": ECONOMICS_AUTHORITY,
            "target_genesis_date": TARGET_GENESIS_DATE.isoformat(),
            "status": self.economics_approval["status"],
            "definition": definition,
            "missing_decisions": missing,
            "candidate_definition_sha256": native_economics_definition_digest(
                self.definition
            ),
            "approved_definition_sha256": self.economics_approval[
                "approved_definition_sha256"
            ],
            "decision_record_id": self.economics_approval["decision_record_id"],
            "decision_record_sha256": self.economics_approval[
                "decision_record_sha256"
            ],
            "approved_at": self.economics_approval["approved_at"],
            "constraints": {
                "asset_class": "native-token",
                "issuance_event": "mainnet-genesis",
                "contract_token_dependency": False,
                "contract_address": None,
                "mainnet_changed": False,
                "genesis_applied": False,
                "assets_moved": False,
                "bridge_activated": False,
                "mainnet_activation_authorized": False,
            },
        }

    def genesis_candidate(self) -> dict[str, Any]:
        """Compile an approved plan into a deterministic, non-activated Genesis."""

        self.assert_ready_for_genesis_ceremony()
        allocations = [
            {
                "address": item.address,
                "amount_base_units": item.amount_base_units,
                "category": item.category,
            }
            for item in sorted(self.allocations, key=lambda item: item.address)
        ]
        allocation_commitment = {
            "schema_version": "jsec-native-genesis-allocations/v1",
            "accounts": allocations,
        }
        custody_commitment = {
            "control_model": self.custody["control_model"],
            "threshold": self.custody["threshold"],
            "participants": sorted(self.custody["participants"]),
            "key_ceremony_evidence_sha256": self.custody[
                "key_ceremony_evidence_sha256"
            ],
        }
        return {
            "schema_version": GENESIS_CANDIDATE_SCHEMA_VERSION,
            "official_name": OFFICIAL_NAME,
            "governance": GOVERNANCE,
            "asset_class": "native-token",
            "issuance_event": "mainnet-genesis",
            "target_genesis_date": TARGET_GENESIS_DATE.isoformat(),
            "definition": {
                key: self.definition[key]
                for key in ("locked", *ECONOMICS_DEFINITION_FIELDS)
            },
            "economics_approval": dict(self.economics_approval),
            "allocations": allocations,
            "allocations_sha256": _canonical_sha256(allocation_commitment),
            "custody": custody_commitment,
            "custody_sha256": _canonical_sha256(custody_commitment),
            "source_plan_sha256": self.specification_digest,
            "safety": {
                "mainnet_changed": False,
                "genesis_applied": False,
                "assets_moved": False,
                "bridge_activated": False,
                "mainnet_activation_authorized": False,
            },
        }

    def as_evidence(self, as_of: date) -> dict[str, Any]:
        _require_date(as_of, "as_of")
        next_milestone = next(
            (item for item in self.milestones if item.status != "completed"),
            None,
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "official_name": OFFICIAL_NAME,
            "governance": GOVERNANCE,
            "asset_class": "native-token",
            "issuance_event": "mainnet-genesis",
            "target_genesis_date": TARGET_GENESIS_DATE.isoformat(),
            "target_date_locked": True,
            "as_of": as_of.isoformat(),
            "schedule_state": self.schedule_state(as_of),
            "ready_for_genesis_ceremony": self.ready_for_genesis_ceremony,
            "next_milestone": (
                {
                    "id": next_milestone.milestone_id,
                    "due_date": next_milestone.due_date.isoformat(),
                }
                if next_milestone
                else None
            ),
            "overdue_milestones": list(self.overdue_milestones(as_of)),
            "blockers": list(self.blockers),
            "specification_digest": self.specification_digest,
            "native_economics": {
                "status": self.economics_approval["status"],
                "authority": self.economics_approval["authority"],
                "candidate_definition_sha256": (
                    native_economics_definition_digest(self.definition)
                ),
                "approved_definition_sha256": self.economics_approval[
                    "approved_definition_sha256"
                ],
                "decision_record_sha256": self.economics_approval[
                    "decision_record_sha256"
                ],
            },
            "contract_token_dependency": False,
            "mainnet_changed": False,
            "genesis_applied": False,
            "assets_moved": False,
            "bridge_activated": False,
            "mainnet_activation_authorized": False,
        }


def load_native_token_genesis_plan(path: str | Path) -> NativeTokenGenesisPlan:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NativeTokenGenesisError("unable to load native Genesis plan") from exc
    return evaluate_native_token_genesis_plan(raw)


def evaluate_native_token_genesis_plan(
    raw: Mapping[str, Any],
) -> NativeTokenGenesisPlan:
    if not isinstance(raw, Mapping):
        raise NativeTokenGenesisError("native Genesis plan must be an object")
    rendered = json.dumps(raw, sort_keys=True, separators=(",", ":")).lower()
    for marker in ("private_key", "mnemonic", "seed_phrase", "secret_value"):
        if marker in rendered:
            raise NativeTokenGenesisError(f"secret material marker prohibited: {marker}")

    _require(raw, "schema_version", SCHEMA_VERSION)
    _require(raw, "official_name", OFFICIAL_NAME)
    _require(raw, "governance", GOVERNANCE)
    _require(raw, "asset_class", "native-token")
    _require(raw, "issuance_event", "mainnet-genesis")
    _require(raw, "target_genesis_date", TARGET_GENESIS_DATE.isoformat())
    _require(raw, "target_date_locked", True)
    _require(raw, "contract_token_dependency", False)
    _require(raw, "contract_address", None)

    definition = _definition(_mapping(raw.get("definition"), "definition"))
    economics_approval = _economics_approval(
        _mapping(raw.get("economics_approval"), "economics_approval"),
        definition,
    )
    allocations_section = _mapping(raw.get("allocations"), "allocations")
    allocations_locked = _boolean(
        allocations_section.get("locked"), "allocations.locked"
    )
    allocations = _allocations(allocations_section.get("accounts"))
    _validate_allocation_supply(definition, allocations_locked, allocations)

    custody = _custody(_mapping(raw.get("custody"), "custody"))
    gates_raw = _mapping(raw.get("gates"), "gates")
    if set(gates_raw) != set(REQUIRED_GATES):
        raise NativeTokenGenesisError("native Genesis gate set mismatch")
    gates = tuple(
        (name, _boolean(gates_raw[name], f"gates.{name}"))
        for name in REQUIRED_GATES
    )
    gate_map = dict(gates)
    _validate_gate_dependencies(
        definition,
        economics_approval,
        allocations_locked,
        custody,
        gate_map,
    )

    milestones = _milestones(raw.get("milestones"), gate_map)
    _validate_safety_boundary(_mapping(raw.get("safety"), "safety"))

    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return NativeTokenGenesisPlan(
        definition=definition,
        economics_approval=economics_approval,
        allocations_locked=allocations_locked,
        allocations=allocations,
        custody=custody,
        gates=gates,
        milestones=milestones,
        specification_digest=hashlib.sha256(canonical).hexdigest(),
    )


def native_economics_definition_digest(definition: Mapping[str, Any]) -> str:
    """Bind an economics approval record to the exact normalized definition."""

    normalized = _definition(_mapping(definition, "definition"))
    payload = {
        "schema_version": ECONOMICS_DEFINITION_SCHEMA_VERSION,
        "official_name": OFFICIAL_NAME,
        "definition": {
            key: normalized[key]
            for key in ECONOMICS_DEFINITION_FIELDS
        },
    }
    return _canonical_sha256(payload)


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(canonical).hexdigest()


def _definition(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != {"locked", *ECONOMICS_DEFINITION_FIELDS}:
        raise NativeTokenGenesisError("native-token definition field set mismatch")
    locked = _boolean(value.get("locked"), "definition.locked")
    name = _optional_text(value.get("name"), "definition.name", 64)
    symbol = _optional_text(value.get("symbol"), "definition.symbol", 10)
    if symbol is not None and not SYMBOL.fullmatch(symbol):
        raise NativeTokenGenesisError("definition.symbol must be 2-10 uppercase characters")
    decimals = _optional_integer(value.get("decimals"), "definition.decimals")
    if decimals is not None and not 0 <= decimals <= 18:
        raise NativeTokenGenesisError("definition.decimals must be between 0 and 18")
    total_supply = _optional_integer(
        value.get("total_supply_base_units"),
        "definition.total_supply_base_units",
    )
    if total_supply is not None and total_supply <= 0:
        raise NativeTokenGenesisError("definition.total_supply_base_units must be positive")
    supply_model = value.get("supply_model")
    if supply_model not in {None, "fixed", "capped", "protocol-governed"}:
        raise NativeTokenGenesisError("definition.supply_model is unsupported")
    post_genesis = value.get("post_genesis_issuance")
    if post_genesis not in {None, "disabled", "governance-upgrade-only"}:
        raise NativeTokenGenesisError("definition.post_genesis_issuance is unsupported")
    fee_model = value.get("fee_model")
    if fee_model not in {None, "burn", "validator-reward", "burn-and-reward"}:
        raise NativeTokenGenesisError("definition.fee_model is unsupported")
    normalized = {
        "locked": locked,
        "name": name,
        "symbol": symbol,
        "decimals": decimals,
        "total_supply_base_units": total_supply,
        "supply_model": supply_model,
        "post_genesis_issuance": post_genesis,
        "fee_model": fee_model,
    }
    if locked and any(item is None for key, item in normalized.items() if key != "locked"):
        raise NativeTokenGenesisError("locked native-token definition is incomplete")
    return normalized


def _allocations(value: Any) -> tuple[GenesisAllocation, ...]:
    if not isinstance(value, list):
        raise NativeTokenGenesisError("allocations.accounts must be a list")
    result: list[GenesisAllocation] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        record = _mapping(item, f"allocations.accounts[{index}]")
        address = _address(record.get("address"), f"allocations.accounts[{index}].address")
        if address in seen:
            raise NativeTokenGenesisError("Genesis allocation addresses must be unique")
        amount = _positive_integer(
            record.get("amount_base_units"),
            f"allocations.accounts[{index}].amount_base_units",
        )
        category = _text(
            record.get("category"),
            f"allocations.accounts[{index}].category",
            64,
        )
        seen.add(address)
        result.append(GenesisAllocation(address, amount, category))
    return tuple(result)


def _economics_approval(
    value: Mapping[str, Any],
    definition: Mapping[str, Any],
) -> dict[str, Any]:
    if set(value) != set(ECONOMICS_APPROVAL_FIELDS):
        raise NativeTokenGenesisError("economics approval field set mismatch")
    _require(value, "authority", ECONOMICS_AUTHORITY)
    status = value.get("status")
    if status not in {"approval_required", "approved"}:
        raise NativeTokenGenesisError("economics_approval.status is unsupported")
    decision_record_id = _optional_text(
        value.get("decision_record_id"),
        "economics_approval.decision_record_id",
        200,
    )
    approved_definition_sha256 = _optional_sha256(
        value.get("approved_definition_sha256"),
        "economics_approval.approved_definition_sha256",
    )
    decision_record_sha256 = _optional_sha256(
        value.get("decision_record_sha256"),
        "economics_approval.decision_record_sha256",
    )
    approved_at = _optional_text(
        value.get("approved_at"),
        "economics_approval.approved_at",
        40,
    )
    approval_values = (
        decision_record_id,
        approved_definition_sha256,
        decision_record_sha256,
        approved_at,
    )
    if status == "approval_required" and any(item is not None for item in approval_values):
        raise NativeTokenGenesisError(
            "unapproved economics must not contain approval evidence"
        )
    if status == "approved":
        if definition.get("locked") is not True:
            raise NativeTokenGenesisError(
                "approved economics requires a locked native-token definition"
            )
        if any(item is None for item in approval_values):
            raise NativeTokenGenesisError("approved economics evidence is incomplete")
        expected = native_economics_definition_digest(definition)
        if approved_definition_sha256 != expected:
            raise NativeTokenGenesisError(
                "approved economics definition digest does not match"
            )
    elif definition.get("locked") is True:
        raise NativeTokenGenesisError(
            "locked native-token definition requires approved economics"
        )
    return {
        "authority": ECONOMICS_AUTHORITY,
        "status": status,
        "decision_record_id": decision_record_id,
        "approved_definition_sha256": approved_definition_sha256,
        "decision_record_sha256": decision_record_sha256,
        "approved_at": approved_at,
    }


def _validate_allocation_supply(
    definition: Mapping[str, Any],
    allocations_locked: bool,
    allocations: tuple[GenesisAllocation, ...],
) -> None:
    if allocations and definition.get("total_supply_base_units") is None:
        raise NativeTokenGenesisError("allocations require a declared total supply")
    if allocations_locked:
        if definition.get("locked") is not True or not allocations:
            raise NativeTokenGenesisError(
                "locked Genesis allocations require a locked definition and accounts"
            )
        allocated = sum(item.amount_base_units for item in allocations)
        if allocated != definition["total_supply_base_units"]:
            raise NativeTokenGenesisError(
                "Genesis allocation total must equal native total supply"
            )


def _custody(value: Mapping[str, Any]) -> dict[str, Any]:
    _require(value, "control_model", "institutional-multisig")
    locked = _boolean(value.get("locked"), "custody.locked")
    threshold = _optional_integer(value.get("threshold"), "custody.threshold")
    participants_raw = value.get("participants")
    if not isinstance(participants_raw, list):
        raise NativeTokenGenesisError("custody.participants must be a list")
    participants = tuple(
        _address(item, f"custody.participants[{index}]")
        for index, item in enumerate(participants_raw)
    )
    if len(set(participants)) != len(participants):
        raise NativeTokenGenesisError("custody participants must be unique")
    evidence_digest = value.get("key_ceremony_evidence_sha256")
    if evidence_digest is not None and (
        not isinstance(evidence_digest, str) or not SHA256.fullmatch(evidence_digest)
    ):
        raise NativeTokenGenesisError(
            "custody.key_ceremony_evidence_sha256 must be a SHA-256 digest"
        )
    if locked:
        if len(participants) < 3:
            raise NativeTokenGenesisError("locked custody requires at least 3 participants")
        if threshold is None or not 2 <= threshold <= len(participants):
            raise NativeTokenGenesisError("custody threshold is outside participant bounds")
        if evidence_digest is None:
            raise NativeTokenGenesisError("locked custody requires key ceremony evidence")
    return {
        "locked": locked,
        "control_model": "institutional-multisig",
        "threshold": threshold,
        "participants": participants,
        "key_ceremony_evidence_sha256": evidence_digest,
    }


def _validate_gate_dependencies(
    definition: Mapping[str, Any],
    economics_approval: Mapping[str, Any],
    allocations_locked: bool,
    custody: Mapping[str, Any],
    gates: Mapping[str, bool],
) -> None:
    economics_locked = (
        definition.get("locked") is True
        and economics_approval.get("status") == "approved"
    )
    if gates["native_economics_locked"] != economics_locked:
        raise NativeTokenGenesisError(
            "native_economics_locked does not match approved definition evidence"
        )
    if gates["deterministic_genesis_allocations"] and not allocations_locked:
        raise NativeTokenGenesisError(
            "deterministic_genesis_allocations lacks allocation evidence"
        )
    if gates["custody_key_ceremony"] and custody.get("locked") is not True:
        raise NativeTokenGenesisError("custody_key_ceremony lacks custody evidence")


def _milestones(
    value: Any,
    gates: Mapping[str, bool],
) -> tuple[GenesisMilestone, ...]:
    if not isinstance(value, list) or len(value) != len(LOCKED_MILESTONES):
        raise NativeTokenGenesisError("fixed native Genesis milestone set mismatch")
    result: list[GenesisMilestone] = []
    for index, ((expected_id, expected_date), item) in enumerate(
        zip(LOCKED_MILESTONES, value, strict=True)
    ):
        record = _mapping(item, f"milestones[{index}]")
        _require(record, "id", expected_id)
        _require(record, "due_date", expected_date.isoformat())
        status = record.get("status")
        if status not in {"not_started", "in_progress", "completed"}:
            raise NativeTokenGenesisError(f"milestones[{index}].status is unsupported")
        owner = _text(record.get("owner"), f"milestones[{index}].owner", 100)
        required = MILESTONE_GATES[expected_id]
        if status == "completed" and not all(gates[name] for name in required):
            raise NativeTokenGenesisError(
                f"completed milestone {expected_id} lacks gate evidence"
            )
        result.append(GenesisMilestone(expected_id, expected_date, status, owner))
    return tuple(result)


def _validate_safety_boundary(value: Mapping[str, Any]) -> None:
    for field in (
        "mainnet_changed",
        "genesis_applied",
        "assets_moved",
        "bridge_activated",
        "mainnet_activation_authorized",
    ):
        _require(value, field, False)


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise NativeTokenGenesisError(f"{field} must be an object")
    return value


def _require(mapping: Mapping[str, Any], field: str, expected: Any) -> None:
    if mapping.get(field) != expected:
        raise NativeTokenGenesisError(f"{field} must be {expected!r}")


def _text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise NativeTokenGenesisError(f"{field} must contain 1-{maximum} characters")
    return value.strip()


def _optional_text(value: Any, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    return _text(value, field, maximum)


def _optional_sha256(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise NativeTokenGenesisError(f"{field} must be a SHA-256 digest")
    return value


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise NativeTokenGenesisError(f"{field} must be boolean")
    return value


def _optional_integer(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise NativeTokenGenesisError(f"{field} must be an integer")
    return value


def _positive_integer(value: Any, field: str) -> int:
    result = _optional_integer(value, field)
    if result is None or result <= 0:
        raise NativeTokenGenesisError(f"{field} must be a positive integer")
    return result


def _address(value: Any, field: str) -> str:
    if not isinstance(value, str) or not ADDRESS.fullmatch(value):
        raise NativeTokenGenesisError(f"{field} must be a 20-byte address")
    normalized = value.lower()
    if normalized == "0x" + ("0" * 40):
        raise NativeTokenGenesisError(f"{field} must not be the zero address")
    return normalized


def _require_date(value: Any, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, date):
        raise NativeTokenGenesisError(f"{field} must be a date")
