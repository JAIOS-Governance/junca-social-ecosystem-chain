import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class ValidatorStateVolumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        module = ROOT / "infra/aws/public-testnet"
        cls.volume = (module / "validator-state-volume.tf").read_text(
            encoding="utf-8"
        )
        cls.variables = (module / "variables.tf").read_text(encoding="utf-8")
        cls.outputs = (module / "outputs.tf").read_text(encoding="utf-8")
        cls.runbook = (module / "VALIDATOR_STATE_MIGRATION.md").read_text(
            encoding="utf-8"
        )

    def test_volume_provisioning_is_opt_in_and_three_way(self) -> None:
        self.assertIn('variable "enable_validator_state_volumes"', self.variables)
        variable = self.variables.split(
            'variable "enable_validator_state_volumes"', 1
        )[1].split("}", 1)[0]
        self.assertIn("default     = false", variable)
        self.assertIn(
            "count = var.enable_validator_state_volumes ? 3 : 0", self.volume
        )

    def test_volumes_are_encrypted_retained_and_az_bound(self) -> None:
        for required in (
            'resource "aws_ebs_volume" "validator_state"',
            "availability_zone = aws_subnet.private[count.index].availability_zone",
            "encrypted         = true",
            'type              = "gp3"',
            "prevent_destroy = true",
            'StatePath         = "/var/lib/junca"',
            'MigrationRequired = "true"',
            "var.validator_state_volume_iops / 4",
        ):
            self.assertIn(required, self.volume)

    def test_attachment_is_safe_but_replaceable_for_immutable_rollout(self) -> None:
        attachment = self.volume.split(
            'resource "aws_volume_attachment" "validator_state"', 1
        )[1]
        self.assertIn('device_name  = "/dev/sdf"', attachment)
        self.assertIn("force_detach = false", attachment)
        self.assertIn("stop_instance_before_detaching = true", attachment)
        self.assertNotIn("prevent_destroy = true", attachment)
        volume = self.volume.split(
            'resource "aws_ebs_volume" "validator_state"', 1
        )[1].split(
            'resource "aws_volume_attachment" "validator_state"', 1
        )[0]
        self.assertIn("prevent_destroy = true", volume)

    def test_snapshot_restore_is_exact_and_fail_closed(self) -> None:
        self.assertIn('variable "validator_state_snapshot_ids"', self.variables)
        self.assertIn(
            "length(var.validator_state_snapshot_ids) == 3", self.variables
        )
        self.assertIn(
            "length(toset(var.validator_state_snapshot_ids)) == 3", self.variables
        )
        self.assertIn(
            'can(regex("^snap-[0-9a-f]{8,17}$", snapshot_id))', self.variables
        )

    def test_output_exposes_migration_readback_without_secrets(self) -> None:
        self.assertIn('output "validator_state_volume_readback"', self.outputs)
        for required in (
            "volume_id",
            "availability_zone",
            "encrypted",
            "attachment_device",
            "migration_required",
        ):
            self.assertIn(required, self.outputs)

    def test_runbook_requires_serial_quorum_safe_migration(self) -> None:
        for required in (
            "one validator at a time",
            "other two validators are healthy",
            "exact AWS volume ID",
            "finalized certificate continuity",
            "Parallel migration of two or more validators",
            "Copying Testnet state into Candidate Mainnet or Mainnet",
        ):
            self.assertIn(required, self.runbook)


if __name__ == "__main__":
    unittest.main()
