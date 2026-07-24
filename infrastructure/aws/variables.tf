variable "deployment_enabled" {
  description = "Fail-closed switch. Keep false until every canonical binding and approval is read back."
  type        = bool
  default     = false
}

variable "aws_account_id" {
  description = "Canonical AWS account ID obtained by independent readback; never infer it."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must be an independently verified 12-digit account ID."
  }
}

variable "aws_region" {
  description = "Canonical AWS region obtained by independent readback; never infer it."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]$", var.aws_region))
    error_message = "aws_region must be an independently verified AWS region."
  }
}

variable "vpc_id" {
  description = "Verified VPC ID in the canonical account."
  type        = string
  nullable    = false
}

variable "private_subnet_ids" {
  description = "Exactly three private subnet IDs in three distinct Availability Zones."
  type        = list(string)
  nullable    = false
  validation {
    condition     = length(var.private_subnet_ids) == 3 && length(toset(var.private_subnet_ids)) == 3
    error_message = "private_subnet_ids must contain exactly three distinct subnets."
  }
}

variable "public_subnet_ids" {
  description = "At least two public subnet IDs for the public ALB."
  type        = list(string)
  nullable    = false
  validation {
    condition     = length(var.public_subnet_ids) >= 2 && length(toset(var.public_subnet_ids)) == length(var.public_subnet_ids)
    error_message = "public_subnet_ids must contain at least two distinct subnets."
  }
}

variable "route53_zone_id" {
  description = "Verified Route53 public hosted zone delegated by the external registrar."
  type        = string
  nullable    = false
}

variable "root_domain" {
  description = "External-registrar domain delegated to Route53."
  type        = string
  nullable    = false
  validation {
    condition     = var.root_domain == "jaios-governance.org"
    error_message = "The approved external-registrar boundary is jaios-governance.org."
  }
}

variable "validator_ami_id" {
  description = "Verified immutable validator AMI ID."
  type        = string
  nullable    = false
}

variable "validator_instance_type" {
  description = "Capacity-reviewed validator instance type."
  type        = string
  nullable    = false
}

variable "validator_signer_kms_key_arns" {
  description = "Three KMS/HSM external-signer resource ARNs. Resource references only; no key material."
  type        = list(string)
  nullable    = false
  sensitive   = false
  validation {
    condition = (
      length(var.validator_signer_kms_key_arns) == 3 &&
      length(toset(var.validator_signer_kms_key_arns)) == 3 &&
      alltrue([for arn in var.validator_signer_kms_key_arns : can(regex("^arn:aws(-[a-z]+)?:kms:", arn))])
    )
    error_message = "Provide exactly three distinct KMS key ARNs."
  }
}

variable "rpc_gateway_image" {
  description = "Immutable read-only RPC gateway image by digest."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.rpc_gateway_image))
    error_message = "rpc_gateway_image must be pinned by sha256 digest."
  }
}

variable "explorer_image" {
  description = "Immutable finalized-index explorer image by digest."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.explorer_image))
    error_message = "explorer_image must be pinned by sha256 digest."
  }
}

variable "genesis_sha256" {
  description = "Verified genesis SHA-256."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.genesis_sha256))
    error_message = "genesis_sha256 must be 64 lowercase hexadecimal characters."
  }
}

variable "binary_sha256" {
  description = "Verified validator binary SHA-256."
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.binary_sha256))
    error_message = "binary_sha256 must be 64 lowercase hexadecimal characters."
  }
}
