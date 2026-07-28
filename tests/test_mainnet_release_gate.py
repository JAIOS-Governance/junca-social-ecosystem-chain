from __future__ import annotations

import unittest

from jaios.social_ecosystem_chain.mainnet_release_gate import (
    GateStatus,
    MainnetReleaseCandidateGate,
    MainnetReleaseGateError,
    REQUIRED_GATES,
    ReleaseArtifactBinding,
)


HASHES = ["0x" + (f"{index:02x}" * 32) for index in range(1, 32)]


class MainnetReleaseGateTests(unittest.TestCase):
    def _binding(self) -> ReleaseArtifactBinding:
        return ReleaseArtifactBinding(
            source_sha=HASHES[0],
            artifact_digest=HASHES[1],
            genesis_digest=HASHES[2],
            configuration_digest=HASHES[3],
            sbom_digest=HASHES[4],
            infrastructure_plan_digest=HASHES[5],
        )

    def test_gate_starts_fail_closed(self) -> None:
        gate = MainnetReleaseCandidateGate(self._binding())

        self.assertFalse(gate.release_candidate_ready)
        self.assertEqual(gate.pending_gates, REQUIRED_GATES)
        self.assertFalse(gate.as_evidence()["activation_authorized"])

    def test_ceo_approval_is_blocked_until_all_gates_pass(self) -> None:
        gate = MainnetReleaseCandidateGate(self._binding())
        gate.record("protocol", GateStatus.PASS, HASHES[6])

        with self.assertRaisesRegex(MainnetReleaseGateError, "all Mainnet"):
            gate.record_ceo_final_approval(True)

    def test_all_passed_gates_and_ceo_approval_create_candidate_readiness(self) -> None:
        gate = MainnetReleaseCandidateGate(self._binding())
        for index, name in enumerate(REQUIRED_GATES, start=6):
            gate.record(name, GateStatus.PASS, HASHES[index])

        gate.record_ceo_final_approval(True)

        self.assertTrue(gate.release_candidate_ready)
        self.assertFalse(gate.as_evidence()["activation_authorized"])
        self.assertFalse(gate.as_evidence()["mainnet_changed"])

    def test_failed_gate_cannot_be_silently_rewritten(self) -> None:
        gate = MainnetReleaseCandidateGate(self._binding())
        gate.record("security-cryptography", GateStatus.FAIL, HASHES[6])

        with self.assertRaisesRegex(MainnetReleaseGateError, "new candidate"):
            gate.record("security-cryptography", GateStatus.PASS, HASHES[7])

    def test_passed_gate_cannot_be_downgraded_on_same_binding(self) -> None:
        gate = MainnetReleaseCandidateGate(self._binding())
        gate.record("protocol", GateStatus.PASS, HASHES[6])

        with self.assertRaisesRegex(MainnetReleaseGateError, "new candidate"):
            gate.record("protocol", GateStatus.FAIL, HASHES[7])


if __name__ == "__main__":
    unittest.main()
