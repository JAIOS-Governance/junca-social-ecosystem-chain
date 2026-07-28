"""Deterministic non-production signer for isolated local network simulation.

This adapter exists only to exercise validator networking, finality and recovery in
an isolated development environment. It is not cryptographic key management and
must never be used for Public Testnet, Mainnet Candidate or Mainnet operation.
"""

from __future__ import annotations

import hashlib
import hmac
import os

from .validator_node import ValidatorNodeError

DEVELOPMENT_MODE_ENV = "JUNCA_LOCAL_DEVELOPMENT"
DEVELOPMENT_KMS_PREFIX = "arn:aws:kms:local:000000000000:key/"
DEVELOPMENT_VALIDATORS = ("validator-01", "validator-02", "validator-03")
_SIGNATURE_DOMAIN = b"JUNCA_LOCAL_DEVELOPMENT_SIGNATURE_V1\x00"


def development_resource(validator_id: str) -> str:
    if validator_id not in DEVELOPMENT_VALIDATORS:
        raise ValidatorNodeError("local development validator is not allowlisted")
    return DEVELOPMENT_KMS_PREFIX + validator_id


class DeterministicDevelopmentKmsAdapter:
    """KMS-compatible deterministic adapter with an explicit development gate."""

    def __init__(self, client: object | None = None) -> None:
        if client is not None:
            raise ValidatorNodeError("local development signer does not accept a client")
        if os.getenv(DEVELOPMENT_MODE_ENV) != "1":
            raise ValidatorNodeError("local development signer is disabled")

    @staticmethod
    def _resource(resource: str) -> str:
        if resource not in {
            development_resource(validator_id)
            for validator_id in DEVELOPMENT_VALIDATORS
        }:
            raise ValidatorNodeError("local development signer resource is invalid")
        return resource

    def sign(self, resource: str, payload: bytes) -> bytes:
        resource = self._resource(resource)
        if not isinstance(payload, bytes) or not payload:
            raise ValidatorNodeError("local development signing payload is invalid")
        return hashlib.sha512(
            _SIGNATURE_DOMAIN + resource.encode("utf-8") + b"\x00" + payload
        ).digest()

    def verify(self, resource: str, payload: bytes, signature: bytes) -> bool:
        try:
            expected = self.sign(resource, payload)
        except ValidatorNodeError:
            return False
        return isinstance(signature, bytes) and hmac.compare_digest(expected, signature)

    def evidence(self) -> dict[str, object]:
        return {
            "schema_version": "junca-local-development-signer/v1",
            "mode": "isolated-local-development-only",
            "deterministic": True,
            "cryptographic_key_management": False,
            "private_key_material_accepted": False,
            "mainnet_changed": False,
            "assets_moved": False,
            "bridge_activated": False,
        }
