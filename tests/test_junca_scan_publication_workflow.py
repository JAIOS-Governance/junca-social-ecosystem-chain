from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "junca-scan-publication.yml"


class JuncaScanPublicationWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_surface_transfer_is_run_scoped_and_verified_on_all_nodes(self) -> None:
        for required in (
            'remote_tmp="/tmp/junca-explorer-surface-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"',
            "run_ssm surface-install",
            "run_ssm surface-integrity",
            "explorer_page_digest=",
            "public_gateway_digest=",
            "chain_logo_digest=",
            "explorer_icon_digest=",
            "assets/junca-chain-logo-gold-on-navy.png",
            "assets/junca-explorer-icon-gold-on-navy.png",
        ):
            self.assertIn(required, self.workflow)

    def test_only_exact_inactive_validator_dependency_is_calmly_classified(self) -> None:
        for required in (
            'gateway-dependency-readback',
            ".ResponseCode == 42",
            'contains("JUNCA_GATEWAY_DEPENDENCY_VERIFICATION_IN_PROGRESS")',
            "systemctl is-active --quiet junca-validator.service",
            '"VERIFICATION IN PROGRESS"',
        ):
            self.assertIn(required, self.workflow)

    def test_acceptance_requires_redundancy_and_complete_node_accounting(self) -> None:
        for required in (
            "required_ready_nodes: 2",
            ".ready_nodes >= .required_ready_nodes",
            "((.ready_nodes + .verification_in_progress_nodes) == 3)",
            "aws elbv2 describe-target-health",
            'assert_rolling_capacity "$instance"',
            "wait_rolled_node",
            'all(.[]; . != "healthy")',
        ):
            self.assertIn(required, self.workflow)

    def test_public_gateways_are_restarted_one_node_at_a_time(self) -> None:
        self.assertIn('run_ssm_instance "$instance" restart', self.workflow)
        self.assertIn('for instance in "${instances[@]}"; do', self.workflow)
        self.assertIn('--instance-ids "$instance"', self.workflow)
        self.assertNotIn('run_ssm restart ', self.workflow)
        self.assertNotIn("systemctl restart junca-validator.service", self.workflow)
        self.assertIn(
            "systemctl restart junca-public-explorer.service junca-public-rpc.service",
            self.workflow,
        )

    def test_production_evidence_keeps_node_publication_state(self) -> None:
        for required in (
            "--slurpfile nodes artifacts/explorer-node-publication.json",
            "node_publication: $nodes[0]",
            'else "VERIFICATION IN PROGRESS"',
            "mainnet_changed: false",
            "assets_moved: false",
            "bridge_activated: false",
        ):
            self.assertIn(required, self.workflow)


if __name__ == "__main__":
    unittest.main()
