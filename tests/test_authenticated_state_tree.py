from __future__ import annotations

import unittest

from jaios.social_ecosystem_chain.authenticated_state_tree import (
    AuthenticatedStateTreeError,
    SparseMerkleStateTree,
    StateProof,
    state_key_hash,
    verify_state_proof,
)


class AuthenticatedStateTreeTests(unittest.TestCase):
    def test_root_is_deterministic_and_order_independent(self) -> None:
        first = SparseMerkleStateTree(
            {
                "identity:profiles/alice": b"Alice",
                "permissions:roles/alice": b"member",
            }
        )
        second = SparseMerkleStateTree(
            {
                "permissions:roles/alice": b"member",
                "identity:profiles/alice": b"Alice",
            }
        )
        self.assertEqual(first.root_hash, second.root_hash)

    def test_key_domain_separates_namespaces(self) -> None:
        self.assertNotEqual(
            state_key_hash("identity", "alice"),
            state_key_hash("permissions", "alice"),
        )

    def test_inclusion_proof_verifies(self) -> None:
        tree = SparseMerkleStateTree({"identity:profiles/alice": b"Alice"})
        proof = tree.prove("identity", "profiles/alice")
        self.assertTrue(proof.exists)
        self.assertTrue(verify_state_proof(tree.root_hash, proof))

    def test_non_inclusion_proof_verifies(self) -> None:
        tree = SparseMerkleStateTree({"identity:profiles/alice": b"Alice"})
        proof = tree.prove("identity", "profiles/bob")
        self.assertFalse(proof.exists)
        self.assertTrue(verify_state_proof(tree.root_hash, proof))

    def test_tampered_value_or_sibling_fails(self) -> None:
        tree = SparseMerkleStateTree({"identity:profiles/alice": b"Alice"})
        proof = tree.prove("identity", "profiles/alice")
        tampered_value = StateProof(
            key_hash=proof.key_hash,
            value_hash="0x" + ("44" * 32),
            siblings=proof.siblings,
        )
        siblings = list(proof.siblings)
        siblings[17] = "0x" + ("55" * 32)
        tampered_sibling = StateProof(
            key_hash=proof.key_hash,
            value_hash=proof.value_hash,
            siblings=tuple(siblings),
        )
        self.assertFalse(verify_state_proof(tree.root_hash, tampered_value))
        self.assertFalse(verify_state_proof(tree.root_hash, tampered_sibling))

    def test_update_and_delete_change_root_and_proofs(self) -> None:
        tree = SparseMerkleStateTree()
        empty_root = tree.root_hash
        tree.set("identity", "profiles/alice", b"Alice")
        first_root = tree.root_hash
        tree.set("identity", "profiles/alice", b"Alice-v2")
        second_root = tree.root_hash
        self.assertNotEqual(empty_root, first_root)
        self.assertNotEqual(first_root, second_root)
        self.assertTrue(tree.delete("identity", "profiles/alice"))
        self.assertEqual(tree.root_hash, empty_root)
        self.assertTrue(
            verify_state_proof(
                tree.root_hash,
                tree.prove("identity", "profiles/alice"),
            )
        )

    def test_batch_is_atomic_and_rejects_duplicate_keys(self) -> None:
        tree = SparseMerkleStateTree({"identity:profiles/alice": b"Alice"})
        original = tree.root_hash
        with self.assertRaisesRegex(AuthenticatedStateTreeError, "duplicate"):
            tree.apply_batch(
                (
                    ("identity", "profiles/alice", b"A"),
                    ("identity", "profiles/alice", b"B"),
                )
            )
        self.assertEqual(tree.root_hash, original)

    def test_batch_result_is_order_independent_for_distinct_keys(self) -> None:
        first = SparseMerkleStateTree()
        second = SparseMerkleStateTree()
        first.apply_batch(
            (
                ("identity", "profiles/alice", b"Alice"),
                ("identity", "profiles/bob", b"Bob"),
            )
        )
        second.apply_batch(
            (
                ("identity", "profiles/bob", b"Bob"),
                ("identity", "profiles/alice", b"Alice"),
            )
        )
        self.assertEqual(first.root_hash, second.root_hash)

    def test_proof_from_old_root_does_not_verify_after_update(self) -> None:
        tree = SparseMerkleStateTree({"identity:profiles/alice": b"Alice"})
        old_proof = tree.prove("identity", "profiles/alice")
        tree.set("identity", "profiles/alice", b"Alice-v2")
        self.assertFalse(verify_state_proof(tree.root_hash, old_proof))

    def test_safety_evidence_preserves_activation_boundary(self) -> None:
        evidence = SparseMerkleStateTree().as_evidence()
        self.assertEqual(evidence["depth"], 256)
        self.assertEqual(
            evidence["activation_status"],
            "MAINNET_CANDIDATE_NOT_ACTIVATED",
        )
        self.assertFalse(evidence["mainnet_changed"])
        self.assertFalse(evidence["assets_moved"])
        self.assertFalse(evidence["bridge_activated"])


if __name__ == "__main__":
    unittest.main()
