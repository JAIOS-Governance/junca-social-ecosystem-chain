from __future__ import annotations

import hashlib
import hmac
import json
import unittest

from jaios.social_ecosystem_chain.consensus_sync import build_snapshot_descriptor
from jaios.social_ecosystem_chain.finality import FinalityVote, Validator
from jaios.social_ecosystem_chain.sync_finality import (
    CertifiedFinalityVerifier,
    FinalityProof,
    ValidatorSet,
    ValidatorSetSchedule,
    proof_to_payload,
)
from jaios.social_ecosystem_chain.sync_runtime import (
    SyncRuntimeError,
    ValidatorSyncRuntime,
)
from jaios.social_ecosystem_chain.wire_protocol import (
    AuthenticatedPeerSession,
    Handshake,
    MessageType,
    WireProtocolError,
)


def hx(value: str) -> str:
    return "0x" + hashlib.sha256(value.encode()).hexdigest()


KEYS = {"local": b"local-key", "peer-a": b"peer-key"}


def signer(node_id: str):
    return lambda message: hmac.new(KEYS[node_id], message, hashlib.sha256).digest()


def verifier(node_id: str, message: bytes, signature: bytes) -> bool:
    expected = hmac.new(KEYS[node_id], message, hashlib.sha256).digest()
    return hmac.compare_digest(expected, signature)


def sessions():
    local = Handshake("local", 22012024, hx("genesis"), hx("local-nonce"))
    peer = Handshake("peer-a", 22012024, hx("genesis"), hx("peer-nonce"))
    inbound = AuthenticatedPeerSession(
        local=local,
        remote=peer,
        signer=signer("local"),
        verifier=verifier,
    )
    outbound = AuthenticatedPeerSession(
        local=peer,
        remote=local,
        signer=signer("peer-a"),
        verifier=verifier,
    )
    return inbound, outbound


def status_payload(height: int = 10):
    return {
        "chain_id": 22012024,
        "genesis_hash": hx("genesis"),
        "height": height,
        "block_hash": hx(f"block-{height}"),
        "parent_hash": hx(f"block-{height - 1}"),
        "state_root": hx(f"state-{height}"),
        "signed_power": 7,
        "total_power": 10,
    }


VALIDATOR_SET = ValidatorSet(
    0,
    0,
    (
        Validator("v1", 3),
        Validator("v2", 3),
        Validator("v3", 2),
        Validator("v4", 2),
    ),
)


def finality_proof(height: int) -> FinalityProof:
    block_hash = hx(f"block-{height}")
    votes = tuple(
        FinalityVote(
            chain_id=22012024,
            height=height,
            round=0,
            block_hash=block_hash,
            validator_id=validator,
            signature=f"{validator}:{height}".encode(),
        )
        for validator in ("v1", "v2", "v3")
    )
    body = {
        "block_hash": block_hash,
        "chain_id": 22012024,
        "height": height,
        "round": 0,
        "signed_power": 8,
        "total_power": 10,
        "validator_ids": ["v1", "v2", "v3"],
        "vote_hashes": [item.vote_hash for item in votes],
    }
    certificate_hash = "0x" + hashlib.sha256(
        b"JUNCA_FINALITY_CERTIFICATE_V1\x00"
        + json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return FinalityProof(
        chain_id=22012024,
        height=height,
        round=0,
        block_hash=block_hash,
        validator_set_hash=VALIDATOR_SET.set_hash,
        votes=votes,
        certificate_hash=certificate_hash,
    )


def block(height: int):
    proof = finality_proof(height)
    return {
        "height": height,
        "block_hash": hx(f"block-{height}"),
        "parent_hash": hx(f"block-{height - 1}"),
        "state_root": hx(f"state-{height}"),
        "certificate_hash": proof.certificate_hash,
    }


class SyncRuntimeTests(unittest.TestCase):
    def runtime(self, threshold: int = 2048):
        finality_verifier = CertifiedFinalityVerifier(
            chain_id=22012024,
            schedule=ValidatorSetSchedule(VALIDATOR_SET),
            vote_verifier=lambda item: bool(item.signature),
        )
        runtime = ValidatorSyncRuntime(
            chain_id=22012024,
            genesis_hash=hx("genesis"),
            expected_total_power=10,
            finality_verifier=finality_verifier,
            snapshot_threshold=threshold,
        )
        inbound, outbound = sessions()
        runtime.register(inbound)
        return runtime, outbound

    def authenticate_status(self, runtime, outbound, height: int = 10):
        frame = outbound.send(MessageType.STATUS, status_payload(height))
        return runtime.receive_status("peer-a", frame)

    def test_authenticated_status_updates_finalized_head(self):
        runtime, outbound = self.runtime()
        claim = self.authenticate_status(runtime, outbound)
        self.assertEqual(claim.height, 10)
        self.assertEqual(runtime.fork_choice.head.block_hash, hx("block-10"))

    def test_tampered_status_faults_peer(self):
        runtime, outbound = self.runtime()
        frame = bytearray(outbound.send(MessageType.STATUS, status_payload()))
        frame[-2] ^= 1
        with self.assertRaises(SyncRuntimeError):
            runtime.receive_status("peer-a", bytes(frame))
        self.assertEqual(runtime.fork_choice.discipline("peer-a").faults, 1)

    def test_status_payload_has_exact_schema(self):
        _, outbound = self.runtime()
        payload = status_payload()
        payload["untrusted"] = True
        with self.assertRaisesRegex(WireProtocolError, "STATUS payload fields"):
            outbound.send(MessageType.STATUS, payload)

    def test_fork_choice_rejection_counts_one_fault(self):
        runtime, outbound = self.runtime()
        payload = status_payload()
        payload["chain_id"] = 1
        frame = outbound.send(MessageType.STATUS, payload)
        with self.assertRaisesRegex(SyncRuntimeError, "chain_id mismatch"):
            runtime.receive_status("peer-a", frame)
        self.assertEqual(runtime.fork_choice.discipline("peer-a").faults, 1)

    def test_duplicate_session_rejected(self):
        runtime, _ = self.runtime()
        inbound, _ = sessions()
        with self.assertRaisesRegex(SyncRuntimeError, "already registered"):
            runtime.register(inbound)

    def test_block_range_plan_and_acceptance(self):
        runtime, outbound = self.runtime(threshold=100)
        self.authenticate_status(runtime, outbound)
        plan = runtime.plan(peer_id="peer-a", local_height=8, target_height=10)
        self.assertEqual(plan.mode, "BLOCK_RANGE")
        frame = outbound.send(
            MessageType.BLOCK_RANGE,
            {
                "blocks": [block(9), block(10)],
                "finality_proofs": [
                    proof_to_payload(finality_proof(9)),
                    proof_to_payload(finality_proof(10)),
                ],
            },
        )
        result = runtime.receive_block_range(
            peer_id="peer-a",
            frame=frame,
            local_hash=hx("block-8"),
        )
        self.assertEqual((result.start_height, result.end_height), (9, 10))
        self.assertEqual(result.status, "VERIFIED")

    def test_block_range_rejects_local_anchor_mismatch(self):
        runtime, outbound = self.runtime(threshold=100)
        self.authenticate_status(runtime, outbound)
        runtime.plan(peer_id="peer-a", local_height=8, target_height=10)
        frame = outbound.send(
            MessageType.BLOCK_RANGE,
            {
                "blocks": [block(9), block(10)],
                "finality_proofs": [
                    proof_to_payload(finality_proof(9)),
                    proof_to_payload(finality_proof(10)),
                ],
            },
        )
        with self.assertRaisesRegex(SyncRuntimeError, "anchored"):
            runtime.receive_block_range(
                peer_id="peer-a",
                frame=frame,
                local_hash=hx("wrong"),
            )

    def test_block_range_rejects_terminal_finality_mismatch(self):
        runtime, outbound = self.runtime(threshold=100)
        self.authenticate_status(runtime, outbound)
        runtime.plan(peer_id="peer-a", local_height=9, target_height=10)
        bad = block(10)
        bad["state_root"] = hx("wrong-state")
        frame = outbound.send(
            MessageType.BLOCK_RANGE,
            {
                "blocks": [bad],
                "finality_proofs": [proof_to_payload(finality_proof(10))],
            },
        )
        with self.assertRaisesRegex(SyncRuntimeError, "finality mismatch"):
            runtime.receive_block_range(
                peer_id="peer-a",
                frame=frame,
                local_hash=hx("block-9"),
            )

    def test_snapshot_plan_and_acceptance(self):
        runtime, outbound = self.runtime(threshold=2)
        claim = self.authenticate_status(runtime, outbound)
        runtime.plan(peer_id="peer-a", local_height=1, target_height=10)
        chunks = [b"first", b"second"]
        descriptor = build_snapshot_descriptor(
            chain_id=claim.chain_id,
            height=claim.height,
            block_hash=claim.block_hash,
            state_root=claim.state_root,
            chunks=chunks,
        )
        payload = {
            "chain_id": descriptor.chain_id,
            "height": descriptor.height,
            "block_hash": descriptor.block_hash,
            "state_root": descriptor.state_root,
            "checkpoint_digest": descriptor.checkpoint_digest,
            "chunk_hashes": list(descriptor.chunk_hashes),
        }
        frame = outbound.send(MessageType.SNAPSHOT_MANIFEST, payload)
        result = runtime.receive_snapshot(
            peer_id="peer-a",
            frame=frame,
            chunks=chunks,
        )
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(result.verified_bytes, 11)

    def test_snapshot_chunk_tamper_faults_peer(self):
        runtime, outbound = self.runtime(threshold=2)
        claim = self.authenticate_status(runtime, outbound)
        runtime.plan(peer_id="peer-a", local_height=1, target_height=10)
        chunks = [b"first"]
        descriptor = build_snapshot_descriptor(
            chain_id=claim.chain_id,
            height=claim.height,
            block_hash=claim.block_hash,
            state_root=claim.state_root,
            chunks=chunks,
        )
        payload = {
            "chain_id": descriptor.chain_id,
            "height": descriptor.height,
            "block_hash": descriptor.block_hash,
            "state_root": descriptor.state_root,
            "checkpoint_digest": descriptor.checkpoint_digest,
            "chunk_hashes": list(descriptor.chunk_hashes),
        }
        frame = outbound.send(MessageType.SNAPSHOT_MANIFEST, payload)
        with self.assertRaises(SyncRuntimeError):
            runtime.receive_snapshot(
                peer_id="peer-a",
                frame=frame,
                chunks=[b"tampered"],
            )

    def test_repeated_faults_quarantine_peer(self):
        runtime, outbound = self.runtime()
        for _ in range(3):
            frame = bytearray(outbound.send(MessageType.STATUS, status_payload()))
            frame[-2] ^= 1
            with self.assertRaises(SyncRuntimeError):
                runtime.receive_status("peer-a", bytes(frame))
        self.assertTrue(runtime.fork_choice.discipline("peer-a").quarantined)
        with self.assertRaisesRegex(SyncRuntimeError, "quarantined"):
            runtime.plan(peer_id="peer-a", local_height=1, target_height=10)

    def test_evidence_boundaries(self):
        runtime, _ = self.runtime()
        evidence = runtime.evidence()
        self.assertEqual(evidence["authenticated_session_count"], 1)
        self.assertFalse(evidence["mainnet_changed"])
        self.assertFalse(evidence["assets_moved"])
        self.assertFalse(evidence["bridge_activated"])


if __name__ == "__main__":
    unittest.main()
