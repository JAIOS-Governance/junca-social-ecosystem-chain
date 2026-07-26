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

variable "certificate_arn" {
  description = "ACM certificate ARN covering rpc, explorer and health subdomains."
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

variable "node_artifact_sha256" {
  description = "Expected SHA-256 digest of the audited node artifact."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.node_artifact_sha256))
    error_message = "node_artifact_sha256 must be a lowercase SHA-256 digest."
  }
}

variable "enable_public_services" {
  description = "Enable RPC, Explorer, public ALB and DNS only after validator quorum acceptance."
  type        = bool
  default     = false
}

variable "validator_instance_type" {
  type    = string
  default = "m7i.large"
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

variable "alert_topic_arn" {
  description = "Existing SNS topic ARN for institutional operations alerts."
  type        = string
}
