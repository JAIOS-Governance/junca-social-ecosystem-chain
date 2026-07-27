from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from jaios.social_ecosystem_chain.validator_node import (
    AuthenticatedVote,
    AwsKmsSecp256k1Adapter,
    BoundedFinalityLoop,
    PublicTestnetConsensus,
    ValidatorNodeError,
    build_genesis,
    canonical_json,
    initialize_state,
    load_genesis,
)
from jaios.social_ecosystem_chain.finality import FinalityVote
import hashlib
import threading
import time


class ValidatorNodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.genesis = build_genesis(
            chain_id=20260723,
            validators=["validator-3", "validator-1", "validator-2"],
        )

    def test_genesis_is_deterministic_and_zero_allocation(self) -> None:
        reordered = build_genesis(
            chain_id=20260723,
            validators=["validator-2", "validator-3", "validator-1"],
        )
        self.assertEqual(canonical_json(self.genesis), canonical_json(reordered))
        self.assertEqual(self.genesis["allocations"], {})
        self.assertFalse(self.genesis["mainnet"])
        self.assertFalse(self.genesis["monetary_value"])
        self.assertFalse(self.genesis["assets_moved"])
        self.assertFalse(self.genesis["bridge_activated"])

    def test_genesis_tampering_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory, "genesis.json")
            path.write_bytes(canonical_json(self.genesis))
            self.assertEqual(load_genesis(path), self.genesis)
            tampered = dict(self.genesis)
            tampered["mainnet"] = True
            path.write_text(json.dumps(tampered))
            with self.assertRaisesRegex(ValidatorNodeError, "genesis_hash"):
                load_genesis(path)

    def test_manual_vote_keeps_legacy_peer_authentication_contract(self) -> None:
        packet = AuthenticatedVote(
            chain_id=20260723,
            height=1,
            round=0,
            block_hash="0x" + ("1" * 64),
            validator_id="validator-1",
            signature=b"consensus",
            peer_signature=b"peer",
        )
        expected = (
            b"JUNCA_AUTHENTICATED_PEER_VOTE_V1\x00"
            + json.dumps(
                {
                    "block_hash": packet.block_hash,
                    "chain_id": packet.chain_id,
                    "height": packet.height,
                    "round": packet.round,
                    "signature": packet.signature.hex(),
                    "validator_id": packet.validator_id,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        self.assertEqual(packet.peer_signing_payload, expected)
        self.assertNotIn(b"block_timestamp", packet.peer_signing_payload)

    def test_runtime_binds_identity_and_read_only_rpc(self) -> None:
        with TemporaryDirectory() as directory:
            state = initialize_state(
                self.genesis,
                directory,
                "validator-1",
                "arn:aws:kms:us-east-1:595710543956:key/example",
            )
            self.addCleanup(state.store.close)
            self.assertEqual(state.rpc("eth_chainId", []), hex(20260723))
            self.assertEqual(state.rpc("eth_blockNumber", []), "0x0")
            self.assertEqual(state.rpc("net_peerCount", []), "0x0")
            self.assertEqual(
                state.rpc("eth_getBlockByNumber", ["latest", False])["hash"],
                self.genesis["genesis_hash"],
            )
            health = state.rpc("junca_health", [])
            self.assertEqual(health["status"], "healthy")
            self.assertFalse(health["private_key_material_accepted"])
            self.assertFalse(health["automatic_finality_enabled"])
            self.assertEqual(health["block_interval_seconds"], 0)
            self.assertEqual(health["slot_epoch_seconds"], 0)
            self.assertIsNone(health["head_timestamp"])
            self.assertFalse(health["automatic_finality_loop_running"])
            self.assertEqual(
                health["automatic_finality"],
                {
                    "enabled": False,
                    "loop_running": False,
                    "block_interval_seconds": 0,
                    "slot_epoch_seconds": 0,
                    "last_attempted_slot": None,
                    "last_successful_slot": None,
                    "last_attempted_height": None,
                    "last_successful_height": None,
                },
            )
            self.assertNotIn("arn:aws:kms:", str(health))
            with self.assertRaisesRegex(ValidatorNodeError, "allowlisted"):
                state.rpc("eth_sendRawTransaction", ["0x00"])

    def test_non_genesis_validator_and_local_key_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValidatorNodeError, "validator set"):
                initialize_state(
                    self.genesis, directory, "validator-9", "kms://valid"
                )
            with self.assertRaisesRegex(ValidatorNodeError, "KMS/HSM"):
                initialize_state(
                    self.genesis, directory, "validator-1", "file:///secret"
                )

    def test_exactly_three_validators_required(self) -> None:
        with self.assertRaisesRegex(ValidatorNodeError, "exactly 3"):
            build_genesis(chain_id=20260723, validators=["validator-1"])

    def test_kms_adapter_converts_fixed_width_and_fails_closed(self) -> None:
        class FakeKms:
            def sign(self, **kwargs):
                self.sign_args = kwargs
                return {"Signature": bytes.fromhex("3006020101020102")}

            def verify(self, **kwargs):
                self.verify_args = kwargs
                return {"SignatureValid": True}

        fake = FakeKms()
        adapter = AwsKmsSecp256k1Adapter(fake)
        arn = "arn:aws:kms:us-east-1:595710543956:key/example"
        signature = adapter.sign(arn, b"vote")
        self.assertEqual(len(signature), 64)
        self.assertEqual(fake.sign_args["MessageType"], "DIGEST")
        self.assertEqual(fake.sign_args["SigningAlgorithm"], "ECDSA_SHA_256")
        self.assertTrue(adapter.verify(arn, b"vote", signature))
        self.assertEqual(fake.verify_args["Signature"], bytes.fromhex("3006020101020102"))
        self.assertFalse(adapter.verify(arn, b"vote", b"short"))


class PublicTestnetConsensusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.genesis = build_genesis(
            chain_id=20260723,
            validators=["validator-1", "validator-2", "validator-3"],
        )
        self.node = initialize_state(
            self.genesis,
            self.directory.name,
            "validator-1",
            "arn:aws:kms:us-east-1:595710543956:key/local",
        )
        self.addCleanup(self.node.store.close)
        self.resources = {
            item: f"arn:aws:kms:us-east-1:595710543956:key/{item}"
            for item in self.genesis["validator_ids"]
        }
        self.consensus_sign_calls: list[tuple[str, bytes]] = []
        self.consensus = PublicTestnetConsensus(
            store=self.node.store,
            data_dir=self.directory.name,
            signer_resources=self.resources,
            consensus_verifier=self.verify_consensus,
            peer_verifier=self.verify_peer,
            consensus_signer=self.sign_consensus,
        )
        self.addCleanup(self.consensus.close)

    @staticmethod
    def signature(context: str, payload: bytes) -> bytes:
        left = hashlib.sha256(context.encode() + b"\x00" + payload).digest()
        right = hashlib.sha256(payload + b"\x00" + context.encode()).digest()
        return left + right

    def verify_consensus(
        self, validator_id: str, resource: str, payload: bytes, signature: bytes
    ) -> bool:
        return (
            resource == self.resources[validator_id]
            and signature == self.signature(resource, payload)
        )

    def sign_consensus(self, resource: str, payload: bytes) -> bytes:
        self.consensus_sign_calls.append((resource, payload))
        return self.signature(resource, payload)

    def verify_peer(
        self, validator_id: str, payload: bytes, signature: bytes
    ) -> bool:
        return signature == self.signature("peer:" + validator_id, payload)

    def packet(
        self, validator_id: str, proposal, *, corrupt_peer: bool = False
    ) -> AuthenticatedVote:
        unsigned = FinalityVote(
            chain_id=20260723,
            height=proposal.height,
            round=0,
            block_hash=proposal.block_hash,
            validator_id=validator_id,
            signature=b"",
        )
        consensus_signature = self.signature(
            self.resources[validator_id], unsigned.signing_payload
        )
        packet = AuthenticatedVote(
            chain_id=unsigned.chain_id,
            height=unsigned.height,
            round=unsigned.round,
            block_hash=unsigned.block_hash,
            validator_id=validator_id,
            signature=consensus_signature,
            peer_signature=b"pending",
            block_timestamp=proposal.block_timestamp,
        )
        peer_signature = self.signature(
            "peer:" + validator_id, packet.peer_signing_payload
        )
        return AuthenticatedVote(
            **{
                **packet.__dict__,
                "peer_signature": b"invalid" if corrupt_peer else peer_signature,
            }
        )

    def test_three_authenticated_kms_bound_votes_finalize_real_blocks(self) -> None:
        self.node.consensus = self.consensus
        first = self.consensus.propose()
        self.assertIsNone(self.consensus.submit(self.packet("validator-1", first)))
        self.assertIsNone(self.consensus.submit(self.packet("validator-2", first)))
        self.assertEqual(self.node.store.head_height, 0)
        finalized = self.consensus.submit(self.packet("validator-3", first))
        self.assertIsNotNone(finalized)
        self.assertEqual(self.node.store.head_height, 1)

        second = self.consensus.propose()
        for validator_id in ("validator-1", "validator-2"):
            self.assertIsNone(
                self.consensus.submit(self.packet(validator_id, second))
            )
        finalized = self.consensus.submit(self.packet("validator-3", second))
        self.assertIsNotNone(finalized)
        self.assertEqual(self.node.store.head_height, 2)
        evidence = self.consensus.evidence()
        self.assertEqual(evidence["head_height"], 2)
        self.assertIsNotNone(evidence["last_certificate_hash"])
        self.assertEqual(
            evidence["last_certificate"]["certificate_hash"],
            evidence["last_certificate_hash"],
        )
        self.assertEqual(
            evidence["last_certificate"]["validator_ids"],
            ["validator-1", "validator-2", "validator-3"],
        )
        self.assertNotIn("arn:aws:kms:", str(evidence))
        self.assertEqual(
            self.node.rpc("junca_health", [])["consensus"]["head_height"], 2
        )

    def test_missing_quorum_never_advances_height(self) -> None:
        proposal = self.consensus.propose()
        for validator_id in ("validator-1", "validator-2"):
            self.assertIsNone(
                self.consensus.submit(self.packet(validator_id, proposal))
            )
        self.assertEqual(self.node.store.head_height, 0)
        self.assertEqual(
            self.consensus.evidence()["authenticated_vote_count"], 2
        )

    def test_finality_certificate_is_recovered_after_consensus_restart(self) -> None:
        proposal = self.consensus.propose()
        finalized = None
        for validator_id in ("validator-1", "validator-2", "validator-3"):
            finalized = self.consensus.submit(self.packet(validator_id, proposal))
        self.assertIsNotNone(finalized)
        expected = self.consensus.evidence()["last_certificate"]

        restarted = PublicTestnetConsensus(
            store=self.node.store,
            data_dir=self.directory.name,
            signer_resources=self.resources,
            consensus_verifier=self.verify_consensus,
            peer_verifier=self.verify_peer,
        )
        self.addCleanup(restarted.close)
        evidence = restarted.evidence()
        self.assertEqual(evidence["head_height"], 1)
        self.assertEqual(evidence["last_certificate"], expected)
        self.assertEqual(
            evidence["last_certificate_hash"],
            expected["certificate_hash"],
        )

    def test_tampered_persisted_certificate_fails_closed_on_restart(self) -> None:
        proposal = self.consensus.propose()
        for validator_id in ("validator-1", "validator-2", "validator-3"):
            self.consensus.submit(self.packet(validator_id, proposal))
        row = self.node.store.connection.execute(
            "SELECT certificate_json FROM finality_certificates WHERE height=1"
        ).fetchone()
        tampered = json.loads(row["certificate_json"])
        tampered["certificate_hash"] = "0x" + ("f" * 64)
        self.node.store.connection.execute(
            "UPDATE finality_certificates SET certificate_json=? WHERE height=1",
            (json.dumps(tampered, sort_keys=True, separators=(",", ":")),),
        )
        with self.assertRaisesRegex(ValueError, "certificate hash mismatch"):
            PublicTestnetConsensus(
                store=self.node.store,
                data_dir=self.directory.name,
                signer_resources=self.resources,
                consensus_verifier=self.verify_consensus,
                peer_verifier=self.verify_peer,
            )

    def test_broadcast_consensus_vote_uses_persistent_signing_journal(self) -> None:
        class PeerKms:
            def sign(inner_self, resource: str, payload: bytes) -> bytes:
                return self.signature(resource, payload)

        class Transport:
            def __init__(inner_self) -> None:
                inner_self.packets: list[AuthenticatedVote] = []

            def broadcast(inner_self, packet: AuthenticatedVote) -> None:
                inner_self.packets.append(packet)

        transport = Transport()
        self.node.consensus = self.consensus
        self.node.kms = PeerKms()
        self.node.peer_transport = transport

        first = self.node.rpc("junca_broadcastVote", [])
        second = self.node.rpc("junca_broadcastVote", [])

        self.assertEqual(first, second)
        self.assertEqual(len(self.consensus_sign_calls), 1)
        self.assertEqual(len(transport.packets), 2)
        self.assertEqual(
            transport.packets[0].signature,
            transport.packets[1].signature,
        )
        self.assertIsNotNone(transport.packets[0].block_timestamp)
        self.assertEqual(
            transport.packets[0].block_timestamp,
            transport.packets[1].block_timestamp,
        )
        self.assertEqual(transport.packets[0].block_timestamp % 30, 0)
        self.assertIn(b"block_timestamp", transport.packets[0].peer_signing_payload)
        journal = self.consensus.runtime.evidence()["signing_journal"]
        self.assertEqual(journal["signature_count"], 1)
        self.assertEqual(journal["latest_height"], 1)

    def test_canonical_timestamp_is_bound_persisted_and_read_after_restart(self) -> None:
        self.node.consensus = self.consensus
        proposal = self.consensus.propose(block_timestamp=1_800_000_030)
        for validator_id in ("validator-1", "validator-2", "validator-3"):
            self.consensus.submit(self.packet(validator_id, proposal))
        self.assertEqual(self.node.store.block_timestamp(1), 1_800_000_030)
        self.assertEqual(
            self.node.rpc("eth_getBlockByNumber", ["latest", False])["timestamp"],
            hex(1_800_000_030),
        )
        self.assertEqual(
            self.node.rpc("junca_health", [])["head_timestamp"],
            1_800_000_030,
        )

        restarted = PublicTestnetConsensus(
            store=self.node.store,
            data_dir=self.directory.name,
            signer_resources=self.resources,
            consensus_verifier=self.verify_consensus,
            peer_verifier=self.verify_peer,
        )
        self.addCleanup(restarted.close)
        self.assertEqual(restarted.evidence()["head_height"], 1)
        self.assertEqual(self.node.store.block_timestamp(1), 1_800_000_030)

    def test_peer_auth_and_assigned_kms_binding_fail_closed(self) -> None:
        proposal = self.consensus.propose()
        with self.assertRaisesRegex(ValidatorNodeError, "authentication"):
            self.consensus.submit(
                self.packet("validator-1", proposal, corrupt_peer=True)
            )
        self.assertEqual(self.node.store.head_height, 0)

        valid = self.packet("validator-1", proposal)
        wrong_signature = self.signature(
            self.resources["validator-2"],
            FinalityVote(
                chain_id=valid.chain_id,
                height=valid.height,
                round=valid.round,
                block_hash=valid.block_hash,
                validator_id=valid.validator_id,
                signature=b"",
            ).signing_payload,
        )
        forged = AuthenticatedVote(
            **{**valid.__dict__, "signature": wrong_signature, "peer_signature": b"x"}
        )
        forged = AuthenticatedVote(
            **{
                **forged.__dict__,
                "peer_signature": self.signature(
                    "peer:validator-1", forged.peer_signing_payload
                ),
            }
        )
        with self.assertRaisesRegex(ValueError, "verification"):
            self.consensus.submit(forged)
        self.assertEqual(self.node.store.head_height, 0)


class BoundedFinalityLoopTests(unittest.TestCase):
    class Store:
        def __init__(self) -> None:
            self.head_height = 0
            self.head_timestamp: int | None = None

        def head(self):
            return type("Head", (), {"height": self.head_height})()

        def block_timestamp(self, height):
            self.asserted_height = height
            return self.head_timestamp

    class State:
        def __init__(self) -> None:
            self.store = BoundedFinalityLoopTests.Store()
            self.timestamps: list[int | None] = []
            self.consensus_lock = threading.RLock()
            self.automatic_finality_loop_running = False
            self.automatic_finality_last_attempted_slot = None
            self.automatic_finality_last_successful_slot = None
            self.automatic_finality_last_attempted_height = None
            self.automatic_finality_last_successful_height = None
            self.consensus = None

        def broadcast_vote(self, *, block_timestamp=None):
            self.timestamps.append(block_timestamp)
            return {"status": "BROADCAST", "height": self.store.head_height + 1}

    def test_lagging_node_advances_at_most_one_height_per_real_slot(self) -> None:
        state = self.State()
        loop = BoundedFinalityLoop(
            state, interval_seconds=30, epoch_seconds=1_800_000_000
        )
        self.assertFalse(loop.run_once(1_800_000_029))
        self.assertTrue(loop.run_once(1_800_000_090))
        self.assertFalse(loop.run_once(1_800_000_099))
        self.assertEqual(state.timestamps, [1_800_000_090])
        self.assertEqual(state.automatic_finality_last_attempted_slot, 3)
        self.assertEqual(state.automatic_finality_last_successful_slot, 3)
        self.assertEqual(state.automatic_finality_last_attempted_height, 1)
        self.assertEqual(state.automatic_finality_last_successful_height, 1)

        state.store.head_height = 1
        state.store.head_timestamp = 1_800_000_090
        self.assertFalse(loop.run_once(1_800_000_119))
        self.assertTrue(loop.run_once(1_800_000_120))
        self.assertEqual(state.timestamps[-1], 1_800_000_120)

    def test_peer_finalized_head_suppresses_second_height_in_same_slot(self) -> None:
        state = self.State()
        state.store.head_height = 7
        state.store.head_timestamp = 1_800_000_090
        loop = BoundedFinalityLoop(
            state, interval_seconds=30, epoch_seconds=1_800_000_000
        )
        self.assertFalse(loop.run_once(1_800_000_099))
        self.assertEqual(state.timestamps, [])
        self.assertIsNone(state.automatic_finality_last_attempted_slot)

    def test_failed_broadcast_retries_only_the_same_height_and_slot(self) -> None:
        state = self.State()

        def fail_broadcast(*, block_timestamp=None):
            state.timestamps.append(block_timestamp)
            raise ValidatorNodeError("temporary signer failure")

        state.broadcast_vote = fail_broadcast
        loop = BoundedFinalityLoop(
            state, interval_seconds=30, epoch_seconds=1_800_000_000
        )
        with self.assertRaisesRegex(ValidatorNodeError, "temporary signer"):
            loop.run_once(1_800_000_030)
        with self.assertRaisesRegex(ValidatorNodeError, "temporary signer"):
            loop.run_once(1_800_000_059)
        self.assertEqual(
            state.timestamps,
            [1_800_000_030, 1_800_000_030],
        )
        self.assertEqual(state.automatic_finality_last_attempted_slot, 1)
        self.assertIsNone(state.automatic_finality_last_successful_slot)
        with self.assertRaisesRegex(ValidatorNodeError, "temporary signer"):
            loop.run_once(1_800_000_060)
        self.assertEqual(state.timestamps[-1], 1_800_000_060)

    def test_unfinalized_proposal_is_not_carried_into_a_later_slot(self) -> None:
        state = self.State()
        proposal = type(
            "Proposal",
            (),
            {"block_timestamp": 1_800_000_030},
        )()
        runtime = type(
            "Runtime",
            (),
            {"pending_proposal": proposal},
        )()
        state.consensus = type(
            "Consensus",
            (),
            {"runtime": runtime},
        )()
        loop = BoundedFinalityLoop(
            state, interval_seconds=30, epoch_seconds=1_800_000_000
        )
        self.assertFalse(loop.run_once(1_800_000_060))
        self.assertEqual(state.timestamps, [])

    def test_loop_stops_cleanly(self) -> None:
        state = self.State()
        loop = BoundedFinalityLoop(
            state,
            interval_seconds=5,
            epoch_seconds=1,
            clock=lambda: 31,
        )
        loop.start()
        self.assertTrue(state.automatic_finality_loop_running)
        time.sleep(0.02)
        loop.stop()
        self.assertFalse(state.automatic_finality_loop_running)
        count = len(state.timestamps)
        time.sleep(0.02)
        self.assertEqual(len(state.timestamps), count)

if __name__ == "__main__":
    unittest.main()
