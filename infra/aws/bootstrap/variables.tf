variable "aws_account_id" {
  description = "Exact 12-digit AWS account ID from authenticated readback."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must be an exact 12-digit AWS account ID."
  }
}

variable "aws_region" {
  description = "Canonical AWS region for the public testnet."
  type        = string
  default     = "ap-northeast-1"
}

variable "state_bucket_name" {
  description = "Globally unique dedicated Terraform state bucket name."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.state_bucket_name))
    error_message = "state_bucket_name must be a valid S3 bucket name."
  }
}

variable "lock_table_name" {
  description = "Dedicated Terraform state locking table."
  type        = string
  default     = "junca-social-ecosystem-chain-testnet-lock"
}

variable "github_oidc_thumbprint" {
  description = "Verified SHA-1 thumbprint for token.actions.githubusercontent.com."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.github_oidc_thumbprint))
    error_message = "github_oidc_thumbprint must be a verified lowercase SHA-1 thumbprint."
  }
}
