output "aws_account_id" {
  value = data.aws_caller_identity.current.account_id
}

output "aws_region" {
  value = var.aws_region
}

output "state_bucket" {
  value = aws_s3_bucket.terraform_state.id
}

output "state_kms_key_arn" {
  value = aws_kms_key.terraform_state.arn
}

output "lock_table" {
  value = aws_dynamodb_table.terraform_lock.name
}

output "deployment_principal_arn" {
  description = "Compatibility alias for the narrowed Foundation role ARN."
  value = aws_iam_role.deployment.arn
}

output "foundation_principal_arn" {
  value = aws_iam_role.deployment.arn
}

output "ami_builder_principal_arn" {
  value = aws_iam_role.ami_builder_controller.arn
}

output "observer_principal_arn" {
  value = aws_iam_role.observer.arn
}

output "security_bootstrap_principal_arn" {
  value = var.security_bootstrap_principal_arn
}

output "security_bootstrap_policy_allowlist_contract" {
  value = {
    policies = local.security_bootstrap_policy_allowlist_contract
    sha256   = sha256(local.security_bootstrap_policy_allowlist_json)
    document_sha256 = {
      core  = sha256(local.security_bootstrap_core_policy_document_json)
      state = sha256(local.security_bootstrap_state_policy_document_json)
    }
  }
}

output "iam_migration_phase" {
  value = {
    phase = var.iam_migration_phase
    legacy_subject_accepted = false
    stage_enforces_exclusive_policy_purge = true
    finalize_requires_live_sts_readback = true
  }
}

output "bootstrap_evidence_manifest_sha256" {
  value = var.bootstrap_evidence_manifest_sha256
}

output "github_oidc_subject_template_contract" {
  value = {
    include_claim_keys   = local.github_oidc_subject_template_contract.include_claim_keys
    use_default          = local.github_oidc_subject_template_contract.use_default
    use_immutable_subject = local.github_oidc_subject_template_contract.use_immutable_subject
    desired_sha256       = sha256(local.github_oidc_subject_template_json)
    get_projection       = local.github_oidc_subject_template_projection_contract
    get_projection_sha256 = sha256(local.github_oidc_subject_template_projection_json)
  }
}

output "github_oidc_provider_contract" {
  value = {
    provider = local.github_oidc_provider_contract
    sha256   = sha256(local.github_oidc_provider_contract_json)
  }
}

output "github_oidc_subject_readback_contract" {
  value = {
    subjects      = local.github_oidc_subject_readback_contract
    attestations  = local.github_oidc_live_sts_attestation_contract.attestations
    sha256        = sha256(local.github_oidc_subject_readback_json)
    artifact_sha256 = {
      for evidence in var.github_oidc_live_sts_attestation_readback :
      evidence.workflow_path => evidence.attestation_sha256
    }
    live_bundle_sha256 = sha256(jsonencode(
      var.github_oidc_live_sts_attestation_readback
    ))
    live_evidence = "Seven v2 artifacts bind numeric-ID JWT claims to same-token mapped AWS STS acceptance"
  }
}

output "repo_global_oidc_cutover_contract" {
  value = {
    gate   = local.repo_global_oidc_cutover_gate
    sha256 = sha256(local.repo_global_oidc_cutover_gate_json)
  }
}

output "runtime_state_lock_contract" {
  value = {
    lock_ids = local.runtime_state_lock_contract
    sha256   = sha256(local.runtime_state_lock_contract_json)
  }
}

output "protected_role_boundary_contract" {
  value = {
    role_to_boundary = local.protected_role_boundary_contract
    sha256           = sha256(local.protected_role_boundary_contract_json)
    external_policy_document_sha256 = {
      for name, policy_json in local.boundary_policy_document_json :
      name => sha256(policy_json)
    }
    owner            = "ExternalTwoPersonRemediation"
  }
}

output "protected_iam_prefix_inventory_contract" {
  value = {
    inventory = local.protected_iam_prefix_inventory_contract
    sha256    = sha256(local.protected_iam_prefix_inventory_contract_json)
  }
}

output "security_remediation_contract" {
  value = {
    contract = local.security_remediation_contract
    sha256   = sha256(local.security_remediation_contract_json)
    current_state_required = "Disabled"
  }
}

output "validator_signer_arns" {
  description = "Three isolated asymmetric validator signer ARNs."
  value       = aws_kms_key.validator_signer[*].arn
}

output "kms_key_policy_contract" {
  value = {
    state_sha256 = sha256(aws_kms_key.terraform_state.policy)
    signer_sha256 = [
      for key in aws_kms_key.validator_signer :
      sha256(key.policy)
    ]
    administration_owner = local.security_remediation_role_arn
  }
}

output "canonical_kms_alias_target_contract" {
  value = {
    aliases = local.canonical_kms_alias_target_contract
    sha256  = sha256(local.canonical_kms_alias_target_contract_json)
  }
}

output "validator_permissions_boundary_arns" {
  description = "Index-aligned one-to-one permissions boundaries for validator-01 through validator-03."
  value       = aws_iam_policy.validator_permissions_boundary[*].arn
}

output "validator_workload_identity_contract" {
  value = {
    role_arns             = aws_iam_role.validator[*].arn
    instance_profile_arns = aws_iam_instance_profile.validator[*].arn
    owner                 = "SecurityBootstrap"
  }
}

output "foundation_mutation_contract" {
  description = "Explicit fail-closed operations pending fixed SSM documents and an immutable launch-template contract."
  value = {
    ec2_run_instances = false
    iam_pass_role      = false
    ssm_send_command   = false
    validator_ssm_agent = false
    rollout_state      = "BLOCKED_PENDING_ATTESTED_LAUNCH_AND_SSM_CONTRACT"
  }
}

output "validator_image_builder_profile" {
  value = {
    name     = aws_iam_instance_profile.validator_image_builder.name
    arn      = aws_iam_instance_profile.validator_image_builder.arn
    role_arn = aws_iam_role.validator_image_builder.arn
  }
}

output "backend_configuration" {
  value = {
    bucket         = aws_s3_bucket.terraform_state.id
    key            = "public-testnet/terraform.tfstate"
    region         = var.aws_region
    dynamodb_table = aws_dynamodb_table.terraform_lock.name
    encrypt        = true
    kms_key_id     = aws_kms_key.terraform_state.arn
    role_arn       = aws_iam_role.deployment.arn
    read_role_arn  = aws_iam_role.observer.arn
  }
}
