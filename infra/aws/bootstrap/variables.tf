variable "aws_account_id" {
  description = "Exact 12-digit AWS account ID from authenticated readback."
  type        = string

  validation {
    condition     = var.aws_account_id == "595710543956"
    error_message = "aws_account_id must be the canonical Public Testnet account 595710543956."
  }
}

variable "aws_region" {
  description = "Canonical AWS region for the public testnet."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = var.aws_region == "us-east-1"
    error_message = "aws_region must remain the canonical Public Testnet region us-east-1."
  }
}

variable "iam_migration_phase" {
  description = "IAM/OIDC migration phase. This revision permits stage only; finalize remains a recognized value solely so Terraform can return the dedicated independent-origin-verification blocker."
  type        = string

  validation {
    condition     = contains(["stage", "finalize"], var.iam_migration_phase)
    error_message = "iam_migration_phase must be exactly stage or finalize."
  }
}

variable "github_oidc_attestation_origin_verification_state" {
  description = "Fail-closed origin-verification state for the seven GitHub OIDC/STS artifacts. This revision has no GitHub API/artifact-origin verifier, so only the blocked state is accepted and every finalize plan is rejected."
  type        = string
  default     = "BLOCKED_PENDING_INDEPENDENT_GITHUB_API_READBACK"

  validation {
    condition = (
      var.github_oidc_attestation_origin_verification_state ==
      "BLOCKED_PENDING_INDEPENDENT_GITHUB_API_READBACK"
    )
    error_message = "This revision cannot accept an asserted OIDC attestation origin state; implement and review an independent GitHub API/artifact-origin verifier first."
  }
}

variable "security_bootstrap_principal_arn" {
  description = "Canonical pre-existing non-OIDC Security Bootstrap role ARN."
  type        = string
  default     = "arn:aws:iam::595710543956:role/JuncaChainSecurityBootstrap"

  validation {
    condition = (
      var.security_bootstrap_principal_arn ==
      "arn:aws:iam::595710543956:role/JuncaChainSecurityBootstrap"
    )
    error_message = "security_bootstrap_principal_arn must be the canonical JuncaChainSecurityBootstrap role."
  }
}

variable "security_bootstrap_trusted_admin_principal_arn" {
  description = "Exact same-account hardware-MFA IAM user ARN trusted by Security Bootstrap."
  type        = string

  validation {
    condition = can(regex(
      "^arn:aws:iam::595710543956:user/[A-Za-z0-9+=,.@_/-]{1,512}$",
      var.security_bootstrap_trusted_admin_principal_arn
    ))
    error_message = "security_bootstrap_trusted_admin_principal_arn must be one exact same-account IAM user ARN; role chaining is not part of this MFA contract."
  }
}

variable "security_bootstrap_external_id_sha256" {
  description = "SHA-256 of the exact ExternalId required by the live Security Bootstrap trust."
  type        = string

  validation {
    condition = can(regex(
      "^[0-9a-f]{64}$",
      var.security_bootstrap_external_id_sha256
    ))
    error_message = "security_bootstrap_external_id_sha256 must be an exact lowercase SHA-256 digest."
  }
}

variable "security_bootstrap_policy_readback_sha256" {
  description = "SHA-256 of newline-free canonical JSON proving the exact attached/inline Security Bootstrap policy-name allowlist."
  type        = string

  validation {
    condition = can(regex(
      "^[0-9a-f]{64}$",
      var.security_bootstrap_policy_readback_sha256
    ))
    error_message = "security_bootstrap_policy_readback_sha256 must be an exact lowercase SHA-256 digest."
  }
}

variable "security_bootstrap_core_policy_document_sha256" {
  description = "SHA-256 of the newline-free canonical JSON for the live default version of JuncaChainSecurityBootstrapCore."
  type        = string

  validation {
    condition = can(regex(
      "^[0-9a-f]{64}$",
      var.security_bootstrap_core_policy_document_sha256
    ))
    error_message = "security_bootstrap_core_policy_document_sha256 must be an exact lowercase SHA-256 digest."
  }
}

variable "security_bootstrap_state_policy_document_sha256" {
  description = "SHA-256 of the newline-free canonical JSON for the live default version of JuncaChainSecurityBootstrapState."
  type        = string

  validation {
    condition = can(regex(
      "^[0-9a-f]{64}$",
      var.security_bootstrap_state_policy_document_sha256
    ))
    error_message = "security_bootstrap_state_policy_document_sha256 must be an exact lowercase SHA-256 digest."
  }
}

variable "bootstrap_evidence_manifest_sha256" {
  description = "SHA-256 of the immutable pre-plan evidence manifest; the apply wrapper must match it to the saved plan variable."
  type        = string

  validation {
    condition = can(regex(
      "^[0-9a-f]{64}$",
      var.bootstrap_evidence_manifest_sha256
    ))
    error_message = "bootstrap_evidence_manifest_sha256 must be an exact lowercase SHA-256 digest."
  }
}

variable "github_oidc_subject_template_sha256" {
  description = "SHA-256 of the exact desired repository OIDC PUT payload with immutable repo, context, workflow_ref, runner_environment, use_default false, and use_immutable_subject true."
  type        = string

  validation {
    condition = can(regex(
      "^[0-9a-f]{64}$",
      var.github_oidc_subject_template_sha256
    ))
    error_message = "github_oidc_subject_template_sha256 must be an exact lowercase SHA-256 digest."
  }
}

variable "github_oidc_subject_template_projection_readback_sha256" {
  description = "SHA-256 of the live GET projection containing exact use_default/include_claim_keys; use_immutable_subject must be true when returned and is ultimately proven by seven numeric-ID JWTs accepted by STS."
  type        = string

  validation {
    condition = can(regex(
      "^[0-9a-f]{64}$",
      var.github_oidc_subject_template_projection_readback_sha256
    ))
    error_message = "github_oidc_subject_template_projection_readback_sha256 must be an exact lowercase SHA-256 digest."
  }
}

variable "github_oidc_provider_readback_sha256" {
  description = "SHA-256 of the exact live GitHub OIDC provider URL, single STS audience, and single verified thumbprint."
  type        = string

  validation {
    condition = can(regex(
      "^[0-9a-f]{64}$",
      var.github_oidc_provider_readback_sha256
    ))
    error_message = "github_oidc_provider_readback_sha256 must be an exact lowercase SHA-256 digest."
  }
}

variable "github_oidc_subject_readback_sha256" {
  description = "SHA-256 of newline-free canonical JSON containing the exact subject aggregate plus seven normalized v2 evidence projections that bind immutable numeric-ID JWT claims to same-token mapped AWS STS acceptance and credential/token non-persistence."
  type        = string

  validation {
    condition = can(regex(
      "^[0-9a-f]{64}$",
      var.github_oidc_subject_readback_sha256
    ))
    error_message = "github_oidc_subject_readback_sha256 must be an exact lowercase SHA-256 digest."
  }
}

variable "github_oidc_live_sts_attestation_readback" {
  description = "Untrusted typed projection of seven redacted v2 attestation files. Shape/digest checks are diagnostic only and cannot authorize finalize without an independently implemented GitHub API/artifact-origin verifier."
  type = list(object({
    assets_moved              = bool
    attestation_sha256        = string
    audience                  = string
    bridge_activated          = bool
    event_name                = string
    expires_at                = number
    issued_at                 = number
    issuer                    = string
    mainnet_changed           = bool
    not_before                = number
    repository                = string
    repository_id             = string
    repository_owner_id       = string
    role_arn                  = string
    run_id                    = string
    schema_version            = string
    state                     = string
    sts_assumed_role_arn      = string
    sts_credentials_persisted = bool
    sts_token_accepted        = bool
    subject_claim_keys        = list(string)
    sub                       = string
    token_persisted           = bool
    workflow_path             = string
    workflow_ref              = string
    workflow_sha              = string
  }))
  default = []

  validation {
    condition = (
      length(var.github_oidc_live_sts_attestation_readback) == 0 ||
      (
        length(var.github_oidc_live_sts_attestation_readback) == 7 &&
        alltrue([
          for evidence in var.github_oidc_live_sts_attestation_readback :
          can(regex("^[0-9a-f]{64}$", evidence.attestation_sha256)) &&
          evidence.attestation_sha256 !=
          "0000000000000000000000000000000000000000000000000000000000000000" &&
          can(regex("^[0-9a-f]{40}$", evidence.workflow_sha)) &&
          can(regex("^[1-9][0-9]{0,19}$", evidence.run_id))
        ])
      )
    )
    error_message = "github_oidc_live_sts_attestation_readback must be empty for stage or contain exactly seven well-formed, non-zero v2 evidence entries for finalize."
  }
}

variable "repo_global_oidc_stage_matrix_readback_sha256" {
  description = "SHA-256 binding the exact baseline repository credential-call matrix used for stage; preparation may still be blocked."
  type        = string

  validation {
    condition = can(regex(
      "^[0-9a-f]{64}$",
      var.repo_global_oidc_stage_matrix_readback_sha256
    ))
    error_message = "repo_global_oidc_stage_matrix_readback_sha256 must be an exact lowercase SHA-256 digest."
  }
}

variable "repo_global_oidc_activation_readback_sha256" {
  description = "SHA-256 binding the exact repository-global activation gate after every baseline call is STS-attested or retired."
  type        = string

  validation {
    condition = can(regex(
      "^[0-9a-f]{64}$",
      var.repo_global_oidc_activation_readback_sha256
    ))
    error_message = "repo_global_oidc_activation_readback_sha256 must be an exact lowercase SHA-256 digest."
  }
}

variable "runtime_state_lock_ids" {
  description = "Exact runtime LockID and checksum LockID read from DynamoDB/CloudTrail by Security Bootstrap before planning."
  type        = list(string)

  validation {
    condition = (
      length(var.runtime_state_lock_ids) == 2 &&
      alltrue([
        for lock_id in var.runtime_state_lock_ids :
        can(regex("^[A-Za-z0-9._/-]{1,1024}$", lock_id))
      ])
    )
    error_message = "runtime_state_lock_ids must contain exactly two concrete DynamoDB keys."
  }
}

variable "runtime_state_lock_readback_sha256" {
  description = "SHA-256 of the newline-free sorted runtime_state_lock_ids JSON obtained from an external DynamoDB/CloudTrail readback."
  type        = string

  validation {
    condition = can(regex(
      "^[0-9a-f]{64}$",
      var.runtime_state_lock_readback_sha256
    ))
    error_message = "runtime_state_lock_readback_sha256 must be an exact lowercase SHA-256 digest."
  }
}

variable "protected_role_boundary_readback_sha256" {
  description = "SHA-256 of the newline-free canonical exact role-to-permissions-boundary live readback."
  type        = string

  validation {
    condition = can(regex(
      "^[0-9a-f]{64}$",
      var.protected_role_boundary_readback_sha256
    ))
    error_message = "protected_role_boundary_readback_sha256 must be an exact lowercase SHA-256 digest."
  }
}

variable "protected_iam_prefix_inventory_readback_sha256" {
  description = "SHA-256 of the exact live role/profile name inventory and one-to-one profile membership under both protected name prefixes; equality proves no residual or cross-bound identity."
  type        = string

  validation {
    condition = can(regex(
      "^[0-9a-f]{64}$",
      var.protected_iam_prefix_inventory_readback_sha256
    ))
    error_message = "protected_iam_prefix_inventory_readback_sha256 must be an exact lowercase SHA-256 digest."
  }
}

variable "security_remediation_readback_sha256" {
  description = "SHA-256 of the exact disabled non-OIDC remediation-role live-readback contract."
  type        = string

  validation {
    condition = can(regex(
      "^[0-9a-f]{64}$",
      var.security_remediation_readback_sha256
    ))
    error_message = "security_remediation_readback_sha256 must be an exact lowercase SHA-256 digest."
  }
}

variable "state_kms_key_policy_readback_sha256" {
  description = "SHA-256 of the exact live state-key default policy read back after external provisioning/import."
  type        = string

  validation {
    condition = can(regex(
      "^[0-9a-f]{64}$",
      var.state_kms_key_policy_readback_sha256
    ))
    error_message = "state_kms_key_policy_readback_sha256 must be an exact lowercase SHA-256 digest."
  }
}

variable "validator_signer_key_policy_readback_sha256" {
  description = "Index-aligned SHA-256 digests of the three exact live signer-key policies."
  type        = list(string)

  validation {
    condition = (
      length(var.validator_signer_key_policy_readback_sha256) == 3 &&
      alltrue([
        for digest in var.validator_signer_key_policy_readback_sha256 :
        can(regex("^[0-9a-f]{64}$", digest))
      ])
    )
    error_message = "validator_signer_key_policy_readback_sha256 must contain exactly three lowercase SHA-256 digests."
  }
}

variable "canonical_kms_alias_target_readback_sha256" {
  description = "SHA-256 of the exact four-name live KMS alias-to-KeyId/KeyArn map; it binds remediation mutations to the already resolved canonical keys."
  type        = string

  validation {
    condition = can(regex(
      "^[0-9a-f]{64}$",
      var.canonical_kms_alias_target_readback_sha256
    ))
    error_message = "canonical_kms_alias_target_readback_sha256 must be an exact lowercase SHA-256 digest."
  }
}

variable "external_boundary_policy_readback_sha256" {
  description = "Exact eight-name canonical live default-version document digests for every protected permissions boundary."
  type = object({
    foundation           = string
    ami_builder          = string
    observer             = string
    remediation          = string
    image_builder_worker = string
    validator01          = string
    validator02          = string
    validator03          = string
  })

  validation {
    condition = alltrue([
      for digest in values(var.external_boundary_policy_readback_sha256) :
      can(regex("^[0-9a-f]{64}$", digest))
    ])
    error_message = "Every external boundary policy readback must be a lowercase SHA-256 digest."
  }
}

variable "domain_name" {
  description = "Canonical Public Testnet DNS suffix used to scope Route 53 mutation."
  type        = string
  default     = "jaios-governance.org"

  validation {
    condition     = var.domain_name == "jaios-governance.org"
    error_message = "domain_name must remain jaios-governance.org."
  }
}

variable "route53_zone_id" {
  description = "Canonical hosted zone ID to which Foundation DNS mutation is restricted."
  type        = string
  default     = "Z0336017285464TX0NT1G"

  validation {
    condition     = var.route53_zone_id == "Z0336017285464TX0NT1G"
    error_message = "route53_zone_id must remain the canonical Public Testnet hosted zone."
  }
}

variable "state_bucket_name" {
  description = "Canonical dedicated Terraform state bucket name."
  type        = string
  default     = "junca-social-ecosystem-chain-tfstate-595710543956-us-east-1"

  validation {
    condition = (
      var.state_bucket_name ==
      "junca-social-ecosystem-chain-tfstate-595710543956-us-east-1"
    )
    error_message = "state_bucket_name must remain the canonical Public Testnet Terraform state bucket."
  }
}

variable "lock_table_name" {
  description = "Dedicated Terraform state locking table."
  type        = string
  default     = "junca-social-ecosystem-chain-testnet-lock"

  validation {
    condition = (
      var.lock_table_name ==
      "junca-social-ecosystem-chain-testnet-lock"
    )
    error_message = "lock_table_name must remain the canonical Public Testnet state-lock table."
  }
}

variable "github_oidc_thumbprint" {
  description = "Verified SHA-1 thumbprint for token.actions.githubusercontent.com."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.github_oidc_thumbprint))
    error_message = "github_oidc_thumbprint must be a verified lowercase SHA-1 thumbprint."
  }
}
