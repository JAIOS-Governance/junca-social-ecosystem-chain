"""Keyless relayer signing request and provider boundary."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Callable, Mapping


class SigningBoundaryError(ValueError):
    pass


@dataclass(frozen=True)
class SigningRequest:
    message_digest: str
    route_digest: str
    network: str
    purpose: str
    key_resource: str
    governance: str = "JAIOS Institutional Governance"
    notice: str = "Public Testnet / No Monetary Value"

    @property
    def request_digest(self) -> str:
        payload = json.dumps(self.__dict__, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(b"JUNCA_SIGNING_REQUEST_V1\x00" + payload).hexdigest()


@dataclass(frozen=True)
class SigningResult:
    request_digest: str
    key_resource: str
    signature: str
    cryptographic_verification: bool


Signer = Callable[[str, bytes], bytes]


class ExternalSignerBoundary:
    """Delegates digest signing without accepting or returning private key material."""

    def __init__(self, signer: Signer, allowed_key_prefix: str) -> None:
        if not allowed_key_prefix.startswith(("kms://", "hsm://")):
            raise SigningBoundaryError("key prefix must identify KMS or HSM")
        self.signer = signer
        self.allowed_key_prefix = allowed_key_prefix

    def sign(self, request: SigningRequest) -> SigningResult:
        self._validate(request)
        signature = self.signer(request.key_resource, bytes.fromhex(request.message_digest))
        if not isinstance(signature, bytes) or len(signature) not in {64, 65}:
            raise SigningBoundaryError("provider returned invalid signature")
        return SigningResult(
            request_digest=request.request_digest,
            key_resource=request.key_resource,
            signature=signature.hex(),
            cryptographic_verification=True,
        )

    def _validate(self, request: SigningRequest) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", request.message_digest):
            raise SigningBoundaryError("invalid message digest")
        if not re.fullmatch(r"[0-9a-f]{64}", request.route_digest):
            raise SigningBoundaryError("invalid route digest")
        if request.network not in {"junca-public-testnet", "bsc-testnet", "tron-shasta"}:
            raise SigningBoundaryError("unsupported network")
        if request.purpose != "bridge-relayer-attestation":
            raise SigningBoundaryError("invalid signing purpose")
        if not request.key_resource.startswith(self.allowed_key_prefix):
            raise SigningBoundaryError("key resource is not allowlisted")
        if request.governance != "JAIOS Institutional Governance":
            raise SigningBoundaryError("invalid governance display")
        if request.notice != "Public Testnet / No Monetary Value":
            raise SigningBoundaryError("testnet notice is required")
