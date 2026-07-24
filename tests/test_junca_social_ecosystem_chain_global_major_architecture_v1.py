import copy
import json
from pathlib import Path
import unittest

from jaios.social_ecosystem_chain.global_major_architecture import (
    GlobalArchitectureError,
    evaluate_capacity_report,
    evaluate_global_architecture,
    load_evidence_bundle,
)


CONFIG = Path("config")


def load(name):
    return json.loads((CONFIG / name).read_text(encoding="utf-8"))


def bundle():
    return {
        "architecture": load(
            "junca_social_ecosystem_chain_global_major_architecture_v1.json"
        ),
        "capabilities": load(
            "junca_social_ecosystem_chain_capability_registry_v1.json"
        ),
        "selection_matrix": load(
            "junca_social_ecosystem_chain_selection_matrix_v1.json"
        ),
        "roadmap": load("junca_social_ecosystem_chain_roadmap_gates_v1.json"),
        "benchmark_plan": load(
            "junca_social_ecosystem_chain_benchmark_plan_v1.json"
        ),
        "security_plan": load(
            "junca_social_ecosystem_chain_security_plan_v1.json"
        ),
    }


class GlobalArchitectureTests(unittest.TestCase):
    def test_complete_architecture_contract_is_verified_and_deterministic(self):
        first = load_evidence_bundle(CONFIG)
        second = evaluate_global_architecture(**bundle())
        self.assertEqual(first.state, "VERIFIED")
        self.assertEqual(first.blockers, ())
        self.assertEqual(first.evidence_digest, second.evidence_digest)
        self.assertTrue(all(first.controls.values()))
        self.assertFalse(first.as_dict()["mainnet_changed"])
        self.assertFalse(first.as_dict()["assets_moved"])
        self.assertFalse(first.as_dict()["bridge_activated"])

    def test_unverified_runtime_capability_cannot_be_claimed(self):
        data = bundle()
        execution = next(
            item
            for item in data["capabilities"]["capabilities"]
            if item["id"] == "execution"
        )
        execution["claim_allowed"] = True
        result = evaluate_global_architecture(**data)
        self.assertEqual(result.state, "BLOCKED")
        self.assertIn("capability_registry", result.blockers)

    def test_performance_targets_and_results_are_not_invented(self):
        data = bundle()
        metric = data["architecture"]["scalability_metrics"][0]
        metric["target"] = 1000
        result = evaluate_global_architecture(**data)
        self.assertEqual(result.state, "BLOCKED")
        self.assertIn("scalability_measurement", result.blockers)

    def test_competitor_verified_cell_requires_official_primary_evidence(self):
        data = bundle()
        cell = data["selection_matrix"]["chains"][1]["dimensions"][0]
        cell["status"] = "VERIFIED"
        cell["value"] = "example"
        cell["evidence"] = {
            "source_type": "secondary",
            "url": "https://example.invalid",
            "retrieved_at": "2026-07-24T00:00:00Z",
            "content_digest": "a" * 64,
        }
        result = evaluate_global_architecture(**data)
        self.assertEqual(result.state, "BLOCKED")
        self.assertIn("selection_matrix", result.blockers)

    def test_supremacy_claim_is_rejected(self):
        data = bundle()
        data["architecture"]["positioning"] = "世界一"
        with self.assertRaises(GlobalArchitectureError):
            evaluate_global_architecture(**data)

    def test_secret_material_field_is_rejected(self):
        data = bundle()
        data["security_plan"]["private_key"] = "forbidden"
        with self.assertRaises(GlobalArchitectureError):
            evaluate_global_architecture(**data)

    def test_mainnet_assets_and_bridge_boundaries_are_immutable(self):
        for boundary in ("mainnet_changed", "assets_moved", "bridge_activated"):
            data = bundle()
            data["roadmap"][boundary] = True
            with self.assertRaises(GlobalArchitectureError):
                evaluate_global_architecture(**data)

    def test_interoperability_routes_remain_paused(self):
        data = bundle()
        route = next(
            item
            for item in data["architecture"]["interoperability"]
            if item["id"] == "bsc-testnet"
        )
        route["status"] = "ACTIVE"
        result = evaluate_global_architecture(**data)
        self.assertEqual(result.state, "BLOCKED")
        self.assertIn("interoperability_boundary", result.blockers)

    def test_roadmap_cannot_skip_public_testnet(self):
        data = bundle()
        data["roadmap"]["stages"][1]["status"] = "COMPLETE"
        result = evaluate_global_architecture(**data)
        self.assertEqual(result.state, "BLOCKED")
        self.assertIn("roadmap_gates", result.blockers)


class CapacityReportTests(unittest.TestCase):
    def test_empty_measurements_are_blocked(self):
        plan = bundle()["benchmark_plan"]
        report = {
            "metrics": [
                {
                    "id": metric,
                    "status": "UNVERIFIED",
                    "verified_result": None,
                    "evidence": None,
                }
                for metric in (
                    "throughput",
                    "finality",
                    "latency",
                    "state_growth",
                    "availability",
                )
            ]
        }
        result = evaluate_capacity_report(plan, report)
        self.assertEqual(result["state"], "BLOCKED")
        self.assertFalse(any(result["metrics"].values()))

    def test_measured_results_require_declared_targets(self):
        plan = copy.deepcopy(bundle()["benchmark_plan"])
        report_metrics = []
        for metric in plan["metrics"]:
            metric["target"] = {"operator": ">=", "value": 1, "unit": metric["unit"]}
            report_metrics.append(
                {
                    "id": metric["id"],
                    "status": "VERIFIED",
                    "verified_result": {
                        "value": 1,
                        "unit": metric["unit"],
                    },
                    "evidence": {
                        "source_type": "official-primary",
                        "url": "https://example.invalid/controlled-evidence",
                        "retrieved_at": "2026-07-24T00:00:00Z",
                        "content_digest": "b" * 64,
                    },
                }
            )
        result = evaluate_capacity_report(plan, {"metrics": report_metrics})
        self.assertEqual(result["state"], "VERIFIED")
        self.assertTrue(all(result["metrics"].values()))


if __name__ == "__main__":
    unittest.main()

