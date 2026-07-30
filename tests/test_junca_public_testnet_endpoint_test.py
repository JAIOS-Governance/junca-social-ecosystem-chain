import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import unittest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "junca_public_testnet_endpoint_test.py"
)
SPEC = importlib.util.spec_from_file_location("junca_endpoint_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
endpoint_test = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = endpoint_test
SPEC.loader.exec_module(endpoint_test)


class PublicTestnetEndpointAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls = []
        self.finalized_timestamp = int(time.time()) - 30
        self.certificate_proof = self.build_certificate_proof()

    @staticmethod
    def build_certificate_proof():
        chain_id = 20260723
        height = 7
        round_number = 0
        block_hash = "0x" + "ab" * 32
        validator_ids = [
            "validator-01",
            "validator-02",
            "validator-03",
        ]
        votes = []
        vote_hashes = []
        for index, validator_id in enumerate(validator_ids, start=1):
            signature = bytes([index]) * 64
            signing_payload = json.dumps(
                {
                    "block_hash": block_hash,
                    "chain_id": chain_id,
                    "height": height,
                    "round": round_number,
                    "validator_id": validator_id,
                    "vote_type": "PRECOMMIT",
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            vote_hashes.append(
                "0x"
                + hashlib.sha256(signing_payload + signature).hexdigest()
            )
            votes.append(
                {
                    "chain_id": chain_id,
                    "height": height,
                    "round": round_number,
                    "block_hash": block_hash,
                    "validator_id": validator_id,
                    "signature": signature.hex(),
                }
            )
        certificate_body = {
            "block_hash": block_hash,
            "chain_id": chain_id,
            "height": height,
            "round": round_number,
            "signed_power": 3,
            "total_power": 3,
            "validator_ids": validator_ids,
            "vote_hashes": vote_hashes,
        }
        certificate_hash = (
            "0x"
            + hashlib.sha256(
                b"JUNCA_FINALITY_CERTIFICATE_V1\x00"
                + json.dumps(
                    certificate_body,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        )
        return {
            "schema_version": (
                "junca-public-finality-certificate-proof/v1"
            ),
            "certificate": {
                "schema_version": "junca-finality-certificate/v1",
                **certificate_body,
                "certificate_hash": certificate_hash,
                "finality_status": "FINALIZED",
                "mainnet_changed": False,
                "assets_moved": False,
                "bridge_activated": False,
            },
            "votes": votes,
        }

    def transport(self, method, url, payload):
        self.calls.append((method, url, payload))
        if url == endpoint_test.HEALTH_URL:
            return endpoint_test.HttpResponse(
                200,
                {
                    "schema_version": "junca-public-gateway-health/v1",
                    "status": "healthy",
                    "read_only": True,
                    "mainnet_changed": False,
                    "assets_moved": False,
                    "bridge_activated": False,
                },
            )
        if url == endpoint_test.EXPLORER_URL:
            return endpoint_test.HttpResponse(
                200,
                {
                    "schema_version": "junca-public-explorer/v5",
                    "status": "ready",
                    "finalized_only": True,
                    "read_only": True,
                    "network": {
                        "chain_id": "0x1352773",
                        "chain_id_decimal": 20260723,
                        "client_version": (
                            "JUNCA-Social-Ecosystem-Chain/public-testnet-python-v1"
                        ),
                        "peer_count": 2,
                        "peer_count_hex": "0x2",
                    },
                    "head": {
                        "height": 7,
                        "hash": "0x" + "ab" * 32,
                        "certificate_hash": self.certificate_proof[
                            "certificate"
                        ]["certificate_hash"],
                        "signed_power": 3,
                        "total_power": 3,
                        "certificate": copy.deepcopy(
                            self.certificate_proof
                        ),
                        "timestamp": hex(self.finalized_timestamp),
                        "state_root": "0x" + "22" * 32,
                        "transaction_count": 0,
                    },
                    "mainnet_changed": False,
                    "assets_moved": False,
                    "bridge_activated": False,
                },
            )
        if payload["method"] in endpoint_test.UNSAFE_RPC_METHODS:
            return endpoint_test.HttpResponse(
                403,
                {
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "error": {"code": -32601, "message": "method not found"},
                },
            )
        safe_results = {
            "eth_chainId": "0x1352773",
            "eth_blockNumber": "0x7",
            "eth_getBlockByNumber": {
                "number": "0x7",
                "hash": "0x" + "ab" * 32,
                "timestamp": hex(self.finalized_timestamp),
                "stateRoot": "0x" + "22" * 32,
                "transactions": [],
            },
            "net_peerCount": "0x2",
            "web3_clientVersion": (
                "JUNCA-Social-Ecosystem-Chain/public-testnet-python-v1"
            ),
        }
        return endpoint_test.HttpResponse(
            200,
            {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": safe_results[payload["method"]],
            },
        )

    def test_complete_contract_passes_without_external_network(self):
        report = endpoint_test.run_acceptance(self.transport)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["checks"]["health"], "PASS")
        self.assertEqual(report["checks"]["explorer"]["finalized_height"], 7)
        self.assertEqual(report["checks"]["explorer"]["peer_count"], 2)
        self.assertEqual(
            report["checks"]["explorer"]["certificate_hash"],
            self.certificate_proof["certificate"]["certificate_hash"],
        )
        self.assertEqual(report["finalized_head"]["height"], 7)
        self.assertEqual(
            report["finalized_head"]["timestamp"],
            hex(self.finalized_timestamp),
        )
        self.assertIn("observed_at", report)
        self.assertEqual(
            report["checks"]["safe_rpc"]["methods"],
            sorted(endpoint_test.SAFE_RPC_METHODS),
        )
        expected_calls = (
            2
            + len(endpoint_test.SAFE_RPC_METHODS)
            + len(endpoint_test.UNSAFE_RPC_METHODS)
        )
        self.assertEqual(len(self.calls), expected_calls)

    def test_boundary_drift_fails_closed_before_rpc_checks(self):
        def drifted_transport(method, url, payload):
            response = self.transport(method, url, payload)
            if url == endpoint_test.HEALTH_URL:
                body = dict(response.body)
                body["assets_moved"] = True
                return endpoint_test.HttpResponse(response.status, body)
            return response

        with self.assertRaisesRegex(
            endpoint_test.AcceptanceError, "assets_moved must be false"
        ):
            endpoint_test.run_acceptance(drifted_transport)
        self.assertEqual(len(self.calls), 1)

    def test_nonfinalized_explorer_fails_closed(self):
        def syncing_transport(method, url, payload):
            response = self.transport(method, url, payload)
            if url == endpoint_test.EXPLORER_URL:
                body = dict(response.body)
                body.update({"status": "syncing", "head": None})
                return endpoint_test.HttpResponse(503, body)
            return response

        with self.assertRaisesRegex(endpoint_test.AcceptanceError, "expected HTTP 200"):
            endpoint_test.run_acceptance(syncing_transport)
        self.assertEqual(len(self.calls), 2)

    def test_zero_or_one_peer_cannot_pass(self):
        for peer_count in (0, 1):
            with self.subTest(peer_count=peer_count):
                def isolated_transport(method, url, payload):
                    response = self.transport(method, url, payload)
                    if url == endpoint_test.EXPLORER_URL:
                        body = dict(response.body)
                        body["network"] = dict(body["network"])
                        body["network"]["peer_count"] = peer_count
                        body["network"]["peer_count_hex"] = hex(peer_count)
                        return endpoint_test.HttpResponse(
                            response.status,
                            body,
                        )
                    return response

                with self.assertRaisesRegex(
                    endpoint_test.AcceptanceError,
                    "exact two-peer quorum",
                ):
                    endpoint_test.run_acceptance(isolated_transport)

    def test_stale_finalized_head_cannot_pass(self):
        self.finalized_timestamp = int(time.time()) - 121
        with self.assertRaisesRegex(
            endpoint_test.AcceptanceError,
            "stale or future-dated",
        ):
            endpoint_test.run_acceptance(self.transport)

    def test_legacy_database_without_certificate_body_fails_closed(self):
        def legacy_transport(method, url, payload):
            response = self.transport(method, url, payload)
            if url == endpoint_test.EXPLORER_URL:
                body = dict(response.body)
                body.update({"status": "syncing", "head": None})
                return endpoint_test.HttpResponse(503, body)
            return response

        with self.assertRaisesRegex(endpoint_test.AcceptanceError, "expected HTTP 200"):
            endpoint_test.run_acceptance(legacy_transport)
        self.assertEqual(len(self.calls), 2)

    def test_explorer_v4_cannot_pass_v5_rollout_gate(self):
        def v1_transport(method, url, payload):
            response = self.transport(method, url, payload)
            if url == endpoint_test.EXPLORER_URL:
                body = dict(response.body)
                body["schema_version"] = "junca-public-explorer/v4"
                return endpoint_test.HttpResponse(response.status, body)
            return response

        with self.assertRaisesRegex(endpoint_test.AcceptanceError, "v5 schema is required"):
            endpoint_test.run_acceptance(v1_transport)

    def test_missing_certificate_body_projection_fails_closed(self):
        def incomplete_transport(method, url, payload):
            response = self.transport(method, url, payload)
            if url == endpoint_test.EXPLORER_URL:
                body = dict(response.body)
                body["head"] = dict(body["head"])
                body["head"]["certificate_hash"] = None
                return endpoint_test.HttpResponse(response.status, body)
            return response

        with self.assertRaisesRegex(
            endpoint_test.AcceptanceError, "finalized certificate is missing"
        ):
            endpoint_test.run_acceptance(incomplete_transport)

    def test_missing_certificate_proof_fails_closed(self):
        def incomplete_transport(method, url, payload):
            response = self.transport(method, url, payload)
            if url == endpoint_test.EXPLORER_URL:
                body = copy.deepcopy(response.body)
                body["head"].pop("certificate")
                return endpoint_test.HttpResponse(response.status, body)
            return response

        with self.assertRaisesRegex(
            endpoint_test.AcceptanceError,
            "certificate proof is missing",
        ):
            endpoint_test.run_acceptance(incomplete_transport)

    def test_certificate_requires_exact_power_and_validator_ids(self):
        mutations = (
            ("signed_power", 2, "exact three-of-three"),
            ("total_power", 4, "exact three-of-three"),
            (
                "validator_ids",
                ["validator-01", "validator-03", "validator-02"],
                "validator identities are not exact",
            ),
            (
                "validator_ids",
                ["validator-01", "validator-01", "validator-03"],
                "validator identities are not exact",
            ),
        )
        for field, value, error in mutations:
            with self.subTest(field=field, value=value):
                def mutated_transport(method, url, payload):
                    response = self.transport(method, url, payload)
                    if url == endpoint_test.EXPLORER_URL:
                        body = copy.deepcopy(response.body)
                        body["head"]["certificate"]["certificate"][
                            field
                        ] = value
                        return endpoint_test.HttpResponse(
                            response.status,
                            body,
                        )
                    return response

                with self.assertRaisesRegex(
                    endpoint_test.AcceptanceError,
                    error,
                ):
                    endpoint_test.run_acceptance(mutated_transport)

    def test_vote_identity_or_signature_tamper_fails_closed(self):
        mutations = (
            ("validator_id", "validator-99", "does not bind"),
            ("height", 8, "does not bind"),
            ("round", 1, "does not bind"),
            ("block_hash", "0x" + "ff" * 32, "does not bind"),
            ("signature", "00" * 63, "signature is invalid"),
            ("signature", "AA" * 64, "signature is invalid"),
        )
        for field, value, error in mutations:
            with self.subTest(field=field, value=value):
                def tampered_transport(method, url, payload):
                    response = self.transport(method, url, payload)
                    if url == endpoint_test.EXPLORER_URL:
                        body = copy.deepcopy(response.body)
                        body["head"]["certificate"]["votes"][0][
                            field
                        ] = value
                        return endpoint_test.HttpResponse(
                            response.status,
                            body,
                        )
                    return response

                with self.assertRaisesRegex(
                    endpoint_test.AcceptanceError,
                    error,
                ):
                    endpoint_test.run_acceptance(tampered_transport)

    def test_vote_hash_and_certificate_hash_are_recalculated(self):
        mutations = (
            ("vote_hash", "0x" + "00" * 32, "vote hashes"),
            ("certificate_hash", "0x" + "00" * 32, "hash reconstruction"),
        )
        for mutation, value, error in mutations:
            with self.subTest(mutation=mutation):
                def tampered_transport(method, url, payload):
                    response = self.transport(method, url, payload)
                    if url == endpoint_test.EXPLORER_URL:
                        body = copy.deepcopy(response.body)
                        certificate = body["head"]["certificate"][
                            "certificate"
                        ]
                        if mutation == "vote_hash":
                            certificate["vote_hashes"][0] = value
                        else:
                            certificate["certificate_hash"] = value
                            body["head"]["certificate_hash"] = value
                        return endpoint_test.HttpResponse(
                            response.status,
                            body,
                        )
                    return response

                with self.assertRaisesRegex(
                    endpoint_test.AcceptanceError,
                    error,
                ):
                    endpoint_test.run_acceptance(tampered_transport)

    def test_gateway_summary_cannot_override_reconstructed_certificate(self):
        mutations = (
            ("signed_power", 2, "exact three-of-three"),
            ("total_power", 4, "exact three-of-three"),
            ("certificate_hash", "0x" + "00" * 32, "hash reconstruction"),
        )
        for field, value, error in mutations:
            with self.subTest(field=field):
                def forged_summary_transport(method, url, payload):
                    response = self.transport(method, url, payload)
                    if url == endpoint_test.EXPLORER_URL:
                        body = copy.deepcopy(response.body)
                        body["head"][field] = value
                        return endpoint_test.HttpResponse(
                            response.status,
                            body,
                        )
                    return response

                with self.assertRaisesRegex(
                    endpoint_test.AcceptanceError,
                    error,
                ):
                    endpoint_test.run_acceptance(
                        forged_summary_transport
                    )

    def test_certificate_boundary_claim_drift_fails_closed(self):
        def drifted_transport(method, url, payload):
            response = self.transport(method, url, payload)
            if url == endpoint_test.EXPLORER_URL:
                body = copy.deepcopy(response.body)
                body["head"]["certificate"]["certificate"][
                    "bridge_activated"
                ] = True
                return endpoint_test.HttpResponse(response.status, body)
            return response

        with self.assertRaisesRegex(
            endpoint_test.AcceptanceError,
            "bridge_activated must be false",
        ):
            endpoint_test.run_acceptance(drifted_transport)

    def test_unsafe_method_must_be_rejected_with_exact_contract(self):
        def permissive_transport(method, url, payload):
            response = self.transport(method, url, payload)
            if (
                url == endpoint_test.RPC_URL
                and payload["method"] == "eth_sendTransaction"
            ):
                return endpoint_test.HttpResponse(
                    200,
                    {"jsonrpc": "2.0", "id": payload["id"], "result": "0xunsafe"},
                )
            return response

        with self.assertRaisesRegex(endpoint_test.AcceptanceError, "expected HTTP 403"):
            endpoint_test.run_acceptance(permissive_transport)

    def test_safe_rpc_envelope_mismatch_fails(self):
        def mismatched_transport(method, url, payload):
            response = self.transport(method, url, payload)
            if (
                url == endpoint_test.RPC_URL
                and payload["method"] == "eth_chainId"
            ):
                return endpoint_test.HttpResponse(
                    200, {"jsonrpc": "2.0", "id": "wrong", "result": "0x1"}
                )
            return response

        with self.assertRaisesRegex(endpoint_test.AcceptanceError, "id mismatch"):
            endpoint_test.run_acceptance(mismatched_transport)


if __name__ == "__main__":
    unittest.main()
