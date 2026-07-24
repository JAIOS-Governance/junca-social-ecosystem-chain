import json
import unittest
from pathlib import Path

from jaios.social_ecosystem_chain.bridge_protocol import (
    BridgeMessage,
    BridgeProtocol,
    BridgeProtocolError,
    BridgeState,
    RelayerAttestation,
)


ROOT = Path(__file__).resolve().parents[1]


def load_scenario(name):
    return json.loads((ROOT / f"config/{name}").read_text())


class BridgeProtocolTests(unittest.TestCase):
    def make(self, name="junca_social_ecosystem_chain_bsc_bridge.simulation.json"):
        scenario = load_scenario(name)
        protocol = BridgeProtocol(**scenario["policy"])
        message = BridgeMessage(**scenario["message"])
        return scenario, protocol, message

    def attest(self, scenario, protocol, message):
        for item in scenario["attestations"]:
            protocol.attest(RelayerAttestation(**item, message_digest=message.digest))

    def test_bsc_forward_flow(self):
        scenario, protocol, message = self.make()
        record = protocol.observe(message)
        protocol.apply_confirmations(message.digest, scenario["confirmations"])
        self.attest(scenario, protocol, message)
        self.assertEqual(record.state, BridgeState.ATTESTED)
        with self.assertRaises(BridgeProtocolError):
            protocol.prepare_execution(message.digest)
        protocol.set_paused(False)
        protocol.prepare_execution(message.digest)
        protocol.mark_executed(message.digest, scenario["execution_transaction"])
        self.assertEqual(record.state, BridgeState.EXECUTED)

    def test_tron_reverse_flow(self):
        scenario, protocol, message = self.make("junca_social_ecosystem_chain_tron_bridge.simulation.json")
        record = protocol.observe(message)
        protocol.apply_confirmations(message.digest, 20)
        self.attest(scenario, protocol, message)
        protocol.set_paused(False)
        protocol.prepare_execution(message.digest)
        protocol.mark_executed(message.digest, scenario["execution_transaction"])
        self.assertEqual(record.state, BridgeState.EXECUTED)

    def test_rejects_message_transaction_and_nonce_replay(self):
        _, protocol, message = self.make()
        protocol.observe(message)
        with self.assertRaises(BridgeProtocolError):
            protocol.observe(message)
        duplicate_nonce = BridgeMessage(
            **{**message.canonical_payload(), "source_transaction": "f" * 64, "recipient": "different"}
        )
        with self.assertRaises(BridgeProtocolError):
            protocol.observe(duplicate_nonce)

    def test_rejects_unverified_and_duplicate_relayer(self):
        scenario, protocol, message = self.make()
        protocol.observe(message)
        item = scenario["attestations"][0]
        with self.assertRaises(BridgeProtocolError):
            protocol.attest(RelayerAttestation(**{**item, "cryptographic_verification": False}, message_digest=message.digest))
        protocol.attest(RelayerAttestation(**item, message_digest=message.digest))
        with self.assertRaises(BridgeProtocolError):
            protocol.attest(RelayerAttestation(**item, message_digest=message.digest))

    def test_requires_finality_and_threshold(self):
        scenario, protocol, message = self.make()
        record = protocol.observe(message)
        protocol.apply_confirmations(message.digest, 19)
        self.attest(scenario, protocol, message)
        self.assertEqual(record.state, BridgeState.FINALITY_PENDING)
        with self.assertRaises(BridgeProtocolError):
            protocol.prepare_execution(message.digest)

    def test_rate_limits(self):
        scenario, protocol, message = self.make()
        protocol.per_transaction_limit = 99
        protocol.observe(message)
        protocol.apply_confirmations(message.digest, 20)
        self.attest(scenario, protocol, message)
        protocol.set_paused(False)
        with self.assertRaises(BridgeProtocolError):
            protocol.prepare_execution(message.digest)

    def test_rejects_wrong_governance_or_notice(self):
        _, protocol, message = self.make()
        for field, value in (("governance", "CEO"), ("notice", "production")):
            payload = message.canonical_payload()
            payload[field] = value
            with self.assertRaises(BridgeProtocolError):
                protocol.observe(BridgeMessage(**payload))

    def test_message_digest_is_domain_separated_and_stable(self):
        _, _, message = self.make()
        self.assertEqual(message.digest, message.digest)
        changed = BridgeMessage(**{**message.canonical_payload(), "nonce": 2})
        self.assertNotEqual(message.digest, changed.digest)


if __name__ == "__main__":
    unittest.main()
