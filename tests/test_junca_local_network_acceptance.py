from __future__ import annotations

import copy
import hashlib
import json
import unittest

from scripts.dev.local_network_acceptance import (
    VALIDATOR_IDS,
    development_manual_mode_ready,
    manual_finality_converged,
)


def health(validator_id: str, *, finalized: bool) -> dict[str, object]:
    height = 1 if finalized else 0
    head_hash = "0x" + ("1" * 64 if finalized else "0" * 64)
    vote_hashes = ["0x" + str(index) * 64 for index in range(2, 5)]
    certificate_body = {
        "block_hash": head_hash,
        "chain_id": 20260723,
        "height": height,
        "round": 0,
        "signed_power": 3,
        "total_power": 3,
        "validator_ids": list(VALIDATOR_IDS),
        "vote_hashes": vote_hashes,
    }
    certificate_hash = "0x" + hashlib.sha256(
        b"JUNCA_FINALITY_CERTIFICATE_V1\x00"
        + json.dumps(
            certificate_body,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    certificate = (
        {
            **certificate_body,
            "certificate_hash": certificate_hash,
            "finality_status": "FINALIZED",
        }
        if finalized
        else None
    )
    return {
        "status": "unhealthy",
        "network": "Public Testnet / No Monetary Value",
        "chain_id": 20260723,
        "validator_id": validator_id,
        "head_height": height,
        "head_hash": head_hash,
        "head_timestamp": 1_800_000_000 if finalized else None,
        "genesis_hash": "0x" + "0" * 64,
        "peer_count": 2 if finalized else 0,
        "health_gates": {
            "authenticated_peer_quorum": finalized,
            "current_three_of_three_certificate": finalized,
            "fresh_finalized_head": finalized,
            "automatic_finality": False,
        },
        "automatic_finality_enabled": False,
        "block_interval_seconds": 0,
        "slot_epoch_seconds": 0,
        "automatic_finality_loop_running": False,
        "automatic_finality": {
            "enabled": False,
            "loop_running": False,
            "block_interval_seconds": 0,
            "slot_epoch_seconds": 0,
        },
        "private_key_material_accepted": False,
        "consensus": {
            "schema_version": "junca-public-testnet-consensus-runtime/v1",
            "chain_id": 20260723,
            "head_height": height,
            "required_vote_count": 3,
            "quorum_rule": "strictly-greater-than-two-thirds",
            "private_key_material_accepted": False,
            "last_certificate_hash": (
                certificate_hash if finalized else None
            ),
            "last_certificate": certificate,
        },
        "sync_recovery": {
            "schema_version": "junca-validator-sync-recovery/v1",
            "recovery_action": "CLEAN",
            "chain_id": 20260723,
            "genesis_hash": "0x" + "0" * 64,
        },
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }


class LocalNetworkAcceptanceTests(unittest.TestCase):
    def snapshot(self, *, finalized: bool) -> dict[str, dict[str, object]]:
        return {
            validator_id: health(validator_id, finalized=finalized)
            for validator_id in VALIDATOR_IDS
        }

    def test_manual_bootstrap_is_reachable_but_never_production_healthy(self) -> None:
        value = self.snapshot(finalized=False)

        self.assertTrue(development_manual_mode_ready(value))
        self.assertFalse(manual_finality_converged(value, 1))

    def test_exact_three_validator_manual_finality_converges(self) -> None:
        value = self.snapshot(finalized=True)

        self.assertTrue(development_manual_mode_ready(value))
        self.assertTrue(manual_finality_converged(value, 1))

    def test_production_healthy_claim_is_rejected_in_manual_mode(self) -> None:
        value = self.snapshot(finalized=True)
        value["validator-01"]["status"] = "healthy"

        self.assertFalse(development_manual_mode_ready(value))
        self.assertFalse(manual_finality_converged(value, 1))

    def test_automatic_finality_claim_is_rejected_in_manual_mode(self) -> None:
        value = self.snapshot(finalized=True)
        value["validator-02"]["automatic_finality_enabled"] = True

        self.assertFalse(development_manual_mode_ready(value))
        self.assertFalse(manual_finality_converged(value, 1))

    def test_non_exact_certificate_is_rejected(self) -> None:
        value = self.snapshot(finalized=True)
        mutated = copy.deepcopy(value)
        certificate = mutated["validator-03"]["consensus"]["last_certificate"]
        certificate["validator_ids"] = [
            "validator-01",
            "validator-02",
            "validator-02",
        ]

        self.assertFalse(manual_finality_converged(mutated, 1))


if __name__ == "__main__":
    unittest.main()
