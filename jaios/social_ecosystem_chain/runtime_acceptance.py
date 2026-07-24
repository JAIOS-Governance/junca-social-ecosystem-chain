"""Fail-closed runtime acceptance for the JUNCA Social Ecosystem Chain Public Testnet."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit


class RuntimeAcceptanceError(ValueError):
    """Raised when runtime evidence is malformed or unsafe."""


REQUIRED_GOVERNANCE = "JAIOS Institutional Governance"
REQUIRED_NOTICE = "Public Testnet / No Monetary Value"
UNSAFE_RPC_METHODS = frozenset({
    "admin_addPeer", "admin_nodeInfo", "debug_traceBlockByNumber",
    "miner_start", "personal_listAccounts", "personal_unlockAccount",
})


@dataclass(frozen=True)
class RuntimeAcceptance:
    state: str
    gates: Mapping[str, bool]
    reasons: tuple[str, ...]
    evidence_digest: str

    @property
    def accepted(self) -> bool:
        return self.state == "ACCEPTED"

    def as_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "junca-runtime-acceptance/v1",
            "network": "JUNCA Social Ecosystem Chain Public Testnet",
            "governance": REQUIRED_GOVERNANCE,
            "notice": REQUIRED_NOTICE,
            "state": self.state,
            "gates": dict(self.gates),
            "reasons": list(self.reasons),
            "evidence_digest": self.evidence_digest,
        }


def evaluate_runtime_acceptance(
    policy: Mapping[str, Any],
    observations: Mapping[str, Any],
) -> RuntimeAcceptance:
    chain_id = _positive_int(policy.get("chain_id"), "policy.chain_id")
    validators = _addresses(policy.get("validator_addresses"), "policy.validator_addresses")
    if len(validators) != 3:
        raise RuntimeAcceptanceError("exactly three validator addresses are required")
    if len(set(validators)) != 3:
        raise RuntimeAcceptanceError("validator addresses must be unique")
    if policy.get("governance") != REQUIRED_GOVERNANCE:
        raise RuntimeAcceptanceError("institutional governance label is required")
    if policy.get("notice") != REQUIRED_NOTICE:
        raise RuntimeAcceptanceError("testnet no-value notice is required")

    samples = observations.get("head_samples")
    if not isinstance(samples, Sequence) or isinstance(samples, (str, bytes)) or len(samples) < 2:
        raise RuntimeAcceptanceError("at least two head samples are required")
    first = _head_sample(samples[0], "head_samples[0]")
    last = _head_sample(samples[-1], f"head_samples[{len(samples)-1}]")
    observed_signers = _addresses(
        observations.get("validator_signers"), "observations.validator_signers"
    )
    rpc = _mapping(observations.get("rpc"), "observations.rpc")
    explorer = _mapping(observations.get("explorer"), "observations.explorer")
    public = _mapping(observations.get("public_metadata"), "observations.public_metadata")
    rejected = set(_text_list(rpc.get("rejected_methods"), "rpc.rejected_methods"))

    gates = {
        "chain_identity": _positive_int(observations.get("chain_id"), "observations.chain_id") == chain_id,
        "head_advancing": last["number"] > first["number"] and last["timestamp"] > first["timestamp"],
        "three_validator_quorum": set(observed_signers) == set(validators),
        "peer_connectivity": _nonnegative_int(observations.get("peer_count"), "observations.peer_count") >= 2,
        "rpc_https": _public_https(rpc.get("url"), "rpc.url"),
        "unsafe_rpc_rejected": UNSAFE_RPC_METHODS.issubset(rejected),
        "explorer_head_parity": (
            _public_https(explorer.get("url"), "explorer.url")
            and _nonnegative_int(explorer.get("head"), "explorer.head") == last["number"]
        ),
        "institutional_governance": public.get("governance") == REQUIRED_GOVERNANCE,
        "no_value_notice": public.get("notice") == REQUIRED_NOTICE,
    }
    reasons = tuple(name for name, passed in gates.items() if not passed)
    canonical = {
        "policy": {
            "chain_id": chain_id,
            "validator_addresses": sorted(validators),
            "governance": REQUIRED_GOVERNANCE,
            "notice": REQUIRED_NOTICE,
        },
        "observations": observations,
        "gates": gates,
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return RuntimeAcceptance(
        state="ACCEPTED" if not reasons else "BLOCKED",
        gates=gates,
        reasons=reasons,
        evidence_digest=digest,
    )


def load_and_evaluate(policy_path: str | Path, observations_path: str | Path) -> RuntimeAcceptance:
    return evaluate_runtime_acceptance(_load_json(policy_path), _load_json(observations_path))


def _load_json(path: str | Path) -> Mapping[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeAcceptanceError(f"unable to load JSON evidence: {path}") from exc
    return _mapping(value, str(path))


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeAcceptanceError(f"{field} must be an object")
    return value


def _head_sample(value: Any, field: str) -> dict[str, int]:
    sample = _mapping(value, field)
    return {
        "number": _nonnegative_int(sample.get("number"), f"{field}.number"),
        "timestamp": _positive_int(sample.get("timestamp"), f"{field}.timestamp"),
    }


def _addresses(value: Any, field: str) -> tuple[str, ...]:
    items = _text_list(value, field)
    normalized = []
    for item in items:
        candidate = item.lower()
        if len(candidate) != 42 or not candidate.startswith("0x"):
            raise RuntimeAcceptanceError(f"{field} contains an invalid address")
        try:
            int(candidate[2:], 16)
        except ValueError as exc:
            raise RuntimeAcceptanceError(f"{field} contains an invalid address") from exc
        if candidate == "0x" + "0" * 40:
            raise RuntimeAcceptanceError(f"{field} contains the zero address")
        normalized.append(candidate)
    return tuple(normalized)


def _text_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise RuntimeAcceptanceError(f"{field} must be a non-empty list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise RuntimeAcceptanceError(f"{field} must contain non-empty text")
    return tuple(item.strip() for item in value)


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RuntimeAcceptanceError(f"{field} must be a positive integer")
    return value


def _nonnegative_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeAcceptanceError(f"{field} must be a non-negative integer")
    return value


def _public_https(value: Any, field: str) -> bool:
    if not isinstance(value, str):
        raise RuntimeAcceptanceError(f"{field} must be text")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return False
    return parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
