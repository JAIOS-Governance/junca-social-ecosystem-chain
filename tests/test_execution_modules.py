from __future__ import annotations

import unittest

from jaios.social_ecosystem_chain.execution_modules import (
    ApplicationCall,
    ExecutionModuleError,
    ModuleDescriptor,
    ModuleRegistry,
    validate_application_call,
)


HASH_A = "0x" + ("11" * 32)
HASH_B = "0x" + ("22" * 32)
CALLER = "0x" + ("33" * 20)


class ExecutionModuleTests(unittest.TestCase):
    def _descriptor(self, module_id: str = "identity") -> ModuleDescriptor:
        return ModuleDescriptor(
            module_id=module_id,
            version="1.0.0",
            capabilities=("query", "write"),
            implementation_digest=HASH_A,
        )

    def _call(self, **overrides) -> ApplicationCall:
        values = {
            "chain_id": 20260723,
            "protocol_version": "1.0.0",
            "module_id": "identity",
            "capability": "write",
            "action": "register",
            "caller": CALLER,
            "nonce": 0,
            "gas_limit": 100_000,
            "payload_hash": HASH_B,
        }
        values.update(overrides)
        return ApplicationCall(**values)

    def test_registry_hash_is_deterministic_and_order_independent(self) -> None:
        first = ModuleRegistry((self._descriptor("identity"), self._descriptor("permission")))
        second = ModuleRegistry((self._descriptor("permission"), self._descriptor("identity")))

        self.assertEqual(first.registry_hash, second.registry_hash)

    def test_duplicate_module_is_rejected(self) -> None:
        registry = ModuleRegistry((self._descriptor(),))

        with self.assertRaisesRegex(ExecutionModuleError, "already registered"):
            registry.register(self._descriptor())

    def test_call_hash_commits_to_nonce_and_payload(self) -> None:
        base = self._call()

        self.assertNotEqual(base.call_hash, self._call(nonce=1).call_hash)
        self.assertNotEqual(base.call_hash, self._call(payload_hash=HASH_A).call_hash)

    def test_capability_negotiation_fails_closed(self) -> None:
        registry = ModuleRegistry((self._descriptor(),))

        self.assertEqual(
            validate_application_call(self._call(), registry=registry).module_id,
            "identity",
        )
        with self.assertRaisesRegex(ExecutionModuleError, "does not provide"):
            validate_application_call(
                self._call(capability="admin"),
                registry=registry,
            )

    def test_registry_evidence_preserves_activation_boundary(self) -> None:
        evidence = ModuleRegistry((self._descriptor(),)).as_evidence()

        self.assertEqual(evidence["activation_status"], "CANDIDATE_NOT_ACTIVATED")
        self.assertFalse(evidence["dynamic_code_loading"])
        self.assertFalse(evidence["mainnet_changed"])
        self.assertFalse(evidence["assets_moved"])
        self.assertFalse(evidence["bridge_activated"])


if __name__ == "__main__":
    unittest.main()
