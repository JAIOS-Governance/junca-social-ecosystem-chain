variable "aws_account_id" {
  description = "Exact AWS account ID read back from the authenticated deployment identity."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must be an exact 12-digit AWS account ID."
  }
}

variable "aws_region" {
  description = "AWS region dedicated to the public testnet."
  type        = string
  default     = "us-east-1"
}

variable "availability_zones" {
  description = "Exactly three distinct availability zones for validator failure-domain separation."
  type        = list(string)

  validation {
    condition     = length(var.availability_zones) == 3 && length(toset(var.availability_zones)) == 3
    error_message = "Exactly three distinct availability zones are required."
  }
}

variable "domain_name" {
  description = "Verified root DNS name controlled for JUNCA Social Ecosystem Chain."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$", var.domain_name))
    error_message = "domain_name must be a valid lower-case DNS name."
  }
}

variable "route53_zone_id" {
  description = "Verified Route 53 public hosted-zone ID."
  type        = string
}

variable "deployment_principal_arn" {
  description = "OIDC deployment role ARN approved for this repository."
  type        = string
}

variable "validator_signer_arns" {
  description = "Three distinct existing KMS/HSM signer resource ARNs; key material is never placed in Terraform state."
  type        = list(string)
  sensitive   = false

  validation {
    condition     = length(var.validator_signer_arns) == 3 && length(toset(var.validator_signer_arns)) == 3 && alltrue([for arn in var.validator_signer_arns : can(regex("^arn:aws:(kms|cloudhsm):", arn))])
    error_message = "Three distinct KMS or CloudHSM resource ARNs are required."
  }
}

variable "node_ami_id" {
  description = "Approved immutable AMI containing the audited node runtime."
  type        = string

  validation {
    condition     = can(regex("^ami-[0-9a-f]{8,17}$", var.node_ami_id))
    error_message = "node_ami_id must be an exact approved AMI ID."
  }
}

variable "source_commit" {
  description = "Exact 40-character source commit embedded in the approved immutable node AMI."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.source_commit))
    error_message = "source_commit must be an exact lowercase 40-character Git commit SHA."
  }
}

variable "node_artifact_sha256" {
  description = "Expected SHA-256 digest of the audited node artifact."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.node_artifact_sha256))
    error_message = "node_artifact_sha256 must be a lowercase SHA-256 digest."
  }
}

variable "enable_public_services" {
  description = "Enable RPC, Explorer, public ALB and DNS only after validator quorum and runtime acceptance."
  type        = bool
  default     = false
}

variable "quorum_acceptance_sha256" {
  description = "SHA-256 digest of the three-validator quorum acceptance evidence. Required only when public services are enabled."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.quorum_acceptance_sha256 == null || can(regex("^[0-9a-f]{64}$", var.quorum_acceptance_sha256))
    error_message = "quorum_acceptance_sha256 must be null or a lowercase SHA-256 digest."
  }
}

variable "runtime_acceptance_sha256" {
  description = "SHA-256 digest of the runtime acceptance evidence. Required only when public services are enabled."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.runtime_acceptance_sha256 == null || can(regex("^[0-9a-f]{64}$", var.runtime_acceptance_sha256))
    error_message = "runtime_acceptance_sha256 must be null or a lowercase SHA-256 digest."
  }
}

variable "validator_instance_type" {
  type    = string
  default = "m7i.large"
}

variable "automatic_finality_enabled" {
  description = "Enable the bounded automatic finality loop on all three Public Testnet validators."
  type        = bool
  default     = false
}

variable "validator_block_interval_seconds" {
  description = "Canonical Public Testnet finality interval shared by all validators."
  type        = number
  default     = 30

  validation {
    condition     = var.validator_block_interval_seconds == 30
    error_message = "Public Testnet automatic finality requires the canonical 30-second interval."
  }
}

variable "validator_slot_epoch_seconds" {
  description = "Shared Unix epoch for the canonical 30-second validator slots. Zero is allowed only while automatic finality is disabled."
  type        = number
  default     = 0

  validation {
    condition = (
      var.validator_slot_epoch_seconds >= 0 &&
      floor(var.validator_slot_epoch_seconds) == var.validator_slot_epoch_seconds &&
      var.validator_slot_epoch_seconds % 30 == 0
    )
    error_message = "validator_slot_epoch_seconds must be a non-negative Unix timestamp on a 30-second boundary."
  }
}

variable "enable_validator_state_volumes" {
  description = "Require the already-provisioned retained EBS volumes to be mounted at /var/lib/junca by the validator runtime."
  type        = bool
  default     = false
}

variable "provision_validator_state_volumes" {
  description = "Provision and attach retained EBS volumes without changing the validator runtime mount until the one-at-a-time migration gate passes."
  type        = bool
  default     = false
}

variable "validator_state_migration_accepted" {
  description = "Record that all three retained validator volumes passed serial migration, state integrity, finality continuity, and rollback acceptance."
  type        = bool
  default     = false
}

variable "validator_state_rollback_snapshot_ids" {
  description = "Exact root-volume rollback snapshots captured during accepted serial migration; distinct from volume restore source snapshots."
  type        = list(string)
  default     = null
  nullable    = true

  validation {
    condition = var.validator_state_rollback_snapshot_ids == null ? true : (
      length(var.validator_state_rollback_snapshot_ids) == 3 &&
      length(toset(var.validator_state_rollback_snapshot_ids)) == 3 &&
      alltrue([
        for snapshot_id in var.validator_state_rollback_snapshot_ids :
        can(regex("^snap-[0-9a-f]{8,17}$", snapshot_id))
      ])
    )
    error_message = "validator_state_rollback_snapshot_ids must be null or three distinct exact EBS snapshot IDs."
  }
}

variable "validator_state_volume_size_gib" {
  description = "Size of each validator durable-state gp3 volume in GiB."
  type        = number
  default     = 200

  validation {
    condition     = var.validator_state_volume_size_gib >= 100
    error_message = "Validator durable-state volumes must be at least 100 GiB."
  }
}

variable "validator_state_volume_iops" {
  description = "Provisioned IOPS for each validator durable-state gp3 volume."
  type        = number
  default     = 6000

  validation {
    condition     = var.validator_state_volume_iops >= 3000 && var.validator_state_volume_iops <= 16000
    error_message = "validator_state_volume_iops must be within the gp3 range 3000..16000."
  }
}

variable "validator_state_volume_throughput_mibps" {
  description = "Provisioned throughput in MiB/s for each validator durable-state gp3 volume."
  type        = number
  default     = 250

  validation {
    condition     = var.validator_state_volume_throughput_mibps >= 125 && var.validator_state_volume_throughput_mibps <= 1000
    error_message = "validator_state_volume_throughput_mibps must be within the gp3 range 125..1000."
  }
}

variable "validator_state_snapshot_ids" {
  description = "Optional exact-three EBS snapshot IDs used to restore validator state. Null creates empty volumes; empty or guessed IDs are rejected."
  type        = list(string)
  default     = null
  nullable    = true

  validation {
    condition = var.validator_state_snapshot_ids == null ? true : (
      length(var.validator_state_snapshot_ids) == 3 &&
      length(toset(var.validator_state_snapshot_ids)) == 3 &&
      alltrue([
        for snapshot_id in var.validator_state_snapshot_ids :
        can(regex("^snap-[0-9a-f]{8,17}$", snapshot_id))
      ])
    )
    error_message = "validator_state_snapshot_ids must be null or three distinct exact EBS snapshot IDs."
  }
}

variable "rpc_instance_type" {
  type    = string
  default = "m7i.large"
}

variable "explorer_instance_type" {
  type    = string
  default = "m7i.large"
}

variable "chain_id" {
  type    = number
  default = 20260723
}

variable "genesis_sha256" {
  description = "Approved genesis SHA-256 used by runtime acceptance."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.genesis_sha256))
    error_message = "genesis_sha256 must be a lowercase SHA-256 digest."
  }
}
