"""Deterministic key-distinct relayer signature quorum aggregation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Iterable

from .signing_boundary import SigningRequest, SigningResult


class SignatureQuorumError(ValueError):
    pass


@dataclass(frozen=True)
class SignatureQuorum:
    request_digest: str
    threshold: int
    key_resources: tuple[str, ...]
    signatures: tuple[str, ...]
    aggregate_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "request_digest": self.request_digest,
            "threshold": self.threshold,
            "key_resources": list(self.key_resources),
            "signatures": list(self.signatures),
            "aggregate_digest": self.aggregate_digest,
        }


def aggregate_signature_quorum(
    request: SigningRequest,
    results: Iterable[SigningResult],
    *,
    threshold: int,
) -> SignatureQuorum:
    if threshold < 2:
        raise SignatureQuorumError("threshold must be at least two")
    items = list(results)
    if len(items) < threshold:
        raise SignatureQuorumError("insufficient signatures")
    request_digest = request.request_digest
    by_key: dict[str, SigningResult] = {}
    for item in items:
        if item.request_digest != request_digest:
            raise SignatureQuorumError("signing request mismatch")
        if item.cryptographic_verification is not True:
            raise SignatureQuorumError("unverified signature")
        if not item.key_resource.startswith(("kms://", "hsm://")):
            raise SignatureQuorumError("invalid key resource")
        if item.key_resource in by_key:
            raise SignatureQuorumError("duplicate signing key")
        if not re.fullmatch(r"[0-9a-f]{128}|[0-9a-f]{130}", item.signature):
            raise SignatureQuorumError("invalid signature encoding")
        by_key[item.key_resource] = item
    ordered = sorted(by_key.items())
    if len(ordered) < threshold:
        raise SignatureQuorumError("insufficient distinct keys")
    selected = ordered[:threshold]
    canonical = json.dumps(
        {
            "request_digest": request_digest,
            "threshold": threshold,
            "signatures": [
                {"key_resource": key, "signature": value.signature}
                for key, value in selected
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return SignatureQuorum(
        request_digest=request_digest,
        threshold=threshold,
        key_resources=tuple(key for key, _ in selected),
        signatures=tuple(value.signature for _, value in selected),
        aggregate_digest=hashlib.sha256(
            b"JUNCA_SIGNATURE_QUORUM_V1\x00" + canonical
        ).hexdigest(),
    )
