#
# Validator durable state volumes
#
# This is deliberately opt-in. Enabling it provisions and attaches one retained
# EBS volume per validator, but it does not format, copy, or mount the volume.
# The running validator state must be migrated under an explicit maintenance
# procedure after snapshot/readback evidence has been captured.
#

resource "aws_ebs_volume" "validator_state" {
  count = var.provision_validator_state_volumes ? 3 : 0

  availability_zone = aws_subnet.private[count.index].availability_zone
  encrypted         = true
  type              = "gp3"
  size              = var.validator_state_volume_size_gib
  iops              = var.validator_state_volume_iops
  throughput        = var.validator_state_volume_throughput_mibps
  snapshot_id = (
    var.validator_state_snapshot_ids == null
    ? null
    : var.validator_state_snapshot_ids[count.index]
  )

  lifecycle {
    prevent_destroy = true

    precondition {
      condition = (
        var.validator_state_volume_throughput_mibps <=
        var.validator_state_volume_iops / 4
      )
      error_message = "gp3 throughput must not exceed one quarter of provisioned IOPS."
    }

    precondition {
      condition = (
        !var.validator_state_migration_accepted ||
        (
          var.provision_validator_state_volumes &&
          var.validator_state_rollback_snapshot_ids != null &&
          length(var.validator_state_rollback_snapshot_ids) == 3
        )
      )
      error_message = "Accepted validator state requires three provisioned volumes and three exact rollback snapshots."
    }
  }

  tags = merge(
    {
      Name              = format("${local.name}-validator-%02d-state", count.index + 1)
      Validator         = format("%02d", count.index + 1)
      FailureDomain     = var.availability_zones[count.index]
      StatePath         = "/var/lib/junca"
      MigrationRequired = var.validator_state_migration_accepted ? "false" : "true"
      PublicTestnetOnly = "true"
    },
    var.validator_state_migration_accepted ? {
      JuncaMigrationState               = "VERIFIED_PASS"
      JuncaFilesystemVerified           = "true"
      JuncaStateStoreIntegrity          = "true"
      JuncaFinalityCertificateRecovered = "true"
      JuncaRollbackSnapshotId = (
        var.validator_state_rollback_snapshot_ids[count.index]
      )
    } : {}
  )
}

resource "aws_volume_attachment" "validator_state" {
  count = var.provision_validator_state_volumes ? 3 : 0

  device_name  = "/dev/sdf"
  volume_id    = aws_ebs_volume.validator_state[count.index].id
  instance_id  = aws_instance.validator[count.index].id
  force_detach = false

  # A detach must never be forced from a running validator.
  stop_instance_before_detaching = true

  # The retained EBS volume is protected above. The attachment itself must be
  # replaceable when an immutable validator instance is rotated, otherwise
  # Terraform cannot move the preserved volume to the replacement instance.
}
