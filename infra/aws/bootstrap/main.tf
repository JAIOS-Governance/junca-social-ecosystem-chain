terraform {
  required_version = ">= 1.7.0"

  # Created with -backend=false, then migrated immediately after the guarded
  # bootstrap apply so the local bootstrap state is never the durable source.
  backend "s3" {}

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 5.100.0"
    }
  }
}

provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.aws_account_id]

  default_tags {
    tags = {
      Project     = "JUNCA Social Ecosystem Chain"
      Governance  = "JAIOS Institutional Governance"
      Network     = "Public Testnet"
      MonetaryUse = "None"
      ManagedBy   = "TerraformBootstrap"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_iam_session_context" "current" {
  arn = data.aws_caller_identity.current.arn
}

data "aws_iam_role" "security_bootstrap" {
  name = element(
    reverse(split("/", var.security_bootstrap_principal_arn)),
    0
  )
}

resource "terraform_data" "account_gate" {
  lifecycle {
    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.aws_account_id
      error_message = "Authenticated AWS account does not match the approved account binding."
    }
    precondition {
      condition = (
        data.aws_iam_session_context.current.issuer_arn ==
        var.security_bootstrap_principal_arn
      )
      error_message = "Bootstrap changes require the exact non-OIDC Security Bootstrap role session."
    }
    precondition {
      condition = (
        length(try(local.security_bootstrap_trust.Statement, [])) == 1 &&
        try(
          local.security_bootstrap_trust.Statement[0].Effect,
          ""
        ) == "Allow" &&
        try(
          local.security_bootstrap_trust.Statement[0].Principal,
          {}
          ) == {
          AWS = var.security_bootstrap_trusted_admin_principal_arn
        } &&
        try(
          local.security_bootstrap_trust.Statement[0].Action,
          []
          ) == [
          "sts:AssumeRole",
          "sts:TagSession",
        ] &&
        sort(keys(try(
          local.security_bootstrap_trust.Statement[0].Condition,
          {}
          ))) == sort([
          "Bool",
          "ForAllValues:StringEquals",
          "StringEquals",
        ]) &&
        try(
          local.security_bootstrap_trust.Statement[0].Condition.Bool[
            "aws:MultiFactorAuthPresent"
          ],
          ""
        ) == "true" &&
        try(
          local.security_bootstrap_trust.Statement[0].Condition.StringEquals[
            "aws:RequestTag/JuncaChangeBoundary"
          ],
          ""
        ) == "SecurityBootstrap" &&
        sha256(try(
          local.security_bootstrap_trust.Statement[0].Condition.StringEquals[
            "sts:ExternalId"
          ],
          ""
        )) == var.security_bootstrap_external_id_sha256 &&
        try(
          local.security_bootstrap_trust.Statement[0].Condition[
            "ForAllValues:StringEquals"
          ]["aws:TagKeys"],
          []
        ) == ["JuncaChangeBoundary"] &&
        data.aws_iam_role.security_bootstrap.max_session_duration <= 3600 &&
        try(
          data.aws_iam_role.security_bootstrap.tags["RoleBoundary"],
          ""
        ) == "SecurityBootstrap"
      )
      error_message = "Security Bootstrap trust must be the exact MFA, ExternalId, session-tagged, non-OIDC human-admin contract."
    }
    precondition {
      condition = (
        var.security_bootstrap_policy_readback_sha256 ==
        sha256(local.security_bootstrap_policy_allowlist_json)
      )
      error_message = "Security Bootstrap attached/inline policy allowlist readback is missing or mismatched."
    }
    precondition {
      condition = (
        var.security_bootstrap_core_policy_document_sha256 ==
        sha256(local.security_bootstrap_core_policy_document_json) &&
        var.security_bootstrap_state_policy_document_sha256 ==
        sha256(local.security_bootstrap_state_policy_document_json)
      )
      error_message = "The live Security Bootstrap Core/State default policy versions do not match both committed least-privilege documents."
    }
    precondition {
      condition = (
        var.security_bootstrap_principal_arn !=
        local.foundation_role_arn &&
        var.security_bootstrap_principal_arn !=
        local.ami_builder_controller_role_arn &&
        var.security_bootstrap_principal_arn !=
        local.observer_role_arn &&
        var.security_bootstrap_principal_arn !=
        local.image_builder_instance_role_arn
      )
      error_message = "Security Bootstrap must be separate from every OIDC or workload role."
    }
    precondition {
      condition = (
        alltrue([
          for role_name, boundary_arn in local.protected_role_boundary_contract :
          try(
            data.aws_iam_role.protected_preexisting[role_name].permissions_boundary,
            ""
          ) == boundary_arn
        ]) &&
        var.protected_role_boundary_readback_sha256 ==
        sha256(local.protected_role_boundary_contract_json)
      )
      error_message = "Every protected role must pre-exist with its exact one-to-one permissions boundary and matching signed live-readback digest."
    }
    precondition {
      condition = (
        var.protected_iam_prefix_inventory_readback_sha256 ==
        sha256(local.protected_iam_prefix_inventory_contract_json)
      )
      error_message = "The live protected prefix inventory must contain exactly seven roles, four profiles, and exact one-to-one profile membership, with no residual or cross-bound identity."
    }
    precondition {
      condition = alltrue([
        for boundary_name, policy_json in local.boundary_policy_document_json :
        var.external_boundary_policy_readback_sha256[boundary_name] ==
        sha256(policy_json)
      ])
      error_message = "All eight protected boundary default-version documents must match the exact configured canonical digests with no missing or extra name."
    }
    precondition {
      condition = (
        length(local.external_boundary_policy_document_json.remediation) <= 6144
      )
      error_message = "The rendered Security Remediation permissions boundary exceeds the 6,144-character AWS managed-policy limit."
    }
    precondition {
      condition = (
        data.aws_iam_role.security_remediation.arn ==
        local.security_remediation_role_arn &&
        try(
          data.aws_iam_role.security_remediation.permissions_boundary,
          ""
        ) == local.security_remediation_boundary_arn &&
        try(
          data.aws_iam_role.security_remediation.tags["RemediationMode"],
          ""
        ) == "Disabled" &&
        data.aws_iam_role.security_remediation.max_session_duration <= 3600 &&
        length(try(local.security_remediation_trust.Statement, [])) > 0 &&
        alltrue([
          for statement in try(local.security_remediation_trust.Statement, []) :
          try(statement.Effect, "") == "Deny"
        ]) &&
        !strcontains(
          jsonencode(local.security_remediation_trust),
          "token.actions.githubusercontent.com"
        ) &&
        var.security_remediation_readback_sha256 ==
        sha256(local.security_remediation_contract_json)
      )
      error_message = "The independent remediation role must exist, be non-OIDC, boundary-capped, and returned to its explicitly disabled state before planning."
    }
    precondition {
      condition = (
        var.state_kms_key_policy_readback_sha256 ==
        sha256(aws_kms_key.terraform_state.policy) &&
        alltrue([
          for index, digest in var.validator_signer_key_policy_readback_sha256 :
          digest == sha256(aws_kms_key.validator_signer[index].policy)
        ])
      )
      error_message = "All four externally provisioned KMS key-policy live readbacks must match the exact configured policies before planning."
    }
    precondition {
      condition = (
        var.canonical_kms_alias_target_readback_sha256 ==
        sha256(local.canonical_kms_alias_target_contract_json)
      )
      error_message = "All four canonical KMS aliases must resolve to the exact imported live KeyIds/KeyArns before any remediation policy can be accepted."
    }
    precondition {
      condition = (
        local.iam_migration_is_stage ||
        var.github_oidc_attestation_origin_verification_state ==
        "VERIFIED_BY_INDEPENDENT_GITHUB_API_ARTIFACT_READBACK"
      )
      error_message = "Finalize is disabled in this revision: locally supplied attestation objects/digests do not prove GitHub artifact origin. Implement, review, and test an independent GitHub API artifact/run verifier before enabling finalize."
    }
    precondition {
      condition = (
        local.iam_migration_is_stage ||
        (
          var.github_oidc_subject_template_sha256 ==
          sha256(local.github_oidc_subject_template_json)
        )
      )
      error_message = "Finalize requires the exact desired GitHub OIDC PUT contract, including use_immutable_subject=true."
    }
    precondition {
      condition = (
        local.iam_migration_is_stage ||
        (
          var.github_oidc_subject_template_projection_readback_sha256 ==
          sha256(local.github_oidc_subject_template_projection_json)
        )
      )
      error_message = "Finalize requires the live GitHub OIDC GET projection to match exact use_default/include_claim_keys; immutable numeric IDs are separately proven by seven STS-accepted JWTs."
    }
    precondition {
      condition = (
        local.iam_migration_is_stage ||
        (
          var.github_oidc_provider_readback_sha256 ==
          sha256(local.github_oidc_provider_contract_json)
        )
      )
      error_message = "Finalize requires the live GitHub OIDC provider to have the exact URL, only sts.amazonaws.com audience, and only the reviewed thumbprint."
    }
    precondition {
      condition = (
        (
          local.iam_migration_is_stage &&
          length(var.github_oidc_live_sts_attestation_readback) == 0
        ) ||
        (
          local.iam_migration_is_finalize &&
          length(var.github_oidc_live_sts_attestation_readback) == 7 &&
          [
            for evidence in var.github_oidc_live_sts_attestation_readback :
            evidence.workflow_path
            ] == sort(keys(
              local.github_oidc_workflow_attestation_binding_contract
          )) &&
          length(distinct([
            for evidence in var.github_oidc_live_sts_attestation_readback :
            evidence.attestation_sha256
          ])) == 7 &&
          length(distinct([
            for evidence in var.github_oidc_live_sts_attestation_readback :
            evidence.run_id
          ])) == 7 &&
          alltrue([
            for evidence in var.github_oidc_live_sts_attestation_readback :
            evidence.expires_at > evidence.issued_at &&
            evidence.expires_at > evidence.not_before &&
            evidence.workflow_sha !=
            "0000000000000000000000000000000000000000" &&
            contains(
              ["workflow_dispatch", "workflow_run"],
              evidence.event_name
            ) &&
            evidence.sts_assumed_role_arn == (
              "arn:${data.aws_partition.current.partition}:sts::" +
              "${var.aws_account_id}:assumed-role/" +
              "${element(reverse(split("/", evidence.role_arn)), 0)}/" +
              "jsec-oidc-attest-${evidence.run_id}"
            )
          ]) &&
          local.github_oidc_live_sts_attestation_readback_static_json ==
          local.github_oidc_subject_readback_json &&
          var.github_oidc_subject_readback_sha256 ==
          sha256(local.github_oidc_subject_readback_json)
        )
      )
      error_message = "Stage requires an empty live-attestation input; finalize requires the exact seven-artifact v2 projection with immutable numeric-ID JWT claims, same-token mapped AWS STS acceptance, non-persistence, and exact subject aggregate."
    }
    precondition {
      condition = (
        try(
          local.repo_global_oidc_cutover_gate.baseline_credential_call_count,
          0
        ) == 27 &&
        (
          (
            local.iam_migration_is_stage &&
            var.repo_global_oidc_stage_matrix_readback_sha256 ==
            sha256(local.repo_global_oidc_cutover_gate_json)
          ) ||
          (
            local.iam_migration_is_finalize &&
            try(local.repo_global_oidc_cutover_gate.preparation_state, "") ==
            try(local.repo_global_oidc_cutover_gate.prepared_state, "NEVER") &&
            try(local.repo_global_oidc_cutover_gate.activation_state, "") ==
            try(local.repo_global_oidc_cutover_gate.ready_state, "NEVER") &&
            try(
              local.repo_global_oidc_cutover_gate.blocked_pending_migration_call_count,
              -1
            ) == 0 &&
            try(
              local.repo_global_oidc_cutover_gate.canonical_call_count,
              -1
              ) + try(
              local.repo_global_oidc_cutover_gate.migrated_exact_call_count,
              -1
              ) + try(
              local.repo_global_oidc_cutover_gate.retired_call_count,
              -1
            ) == 27 &&
            try(
              local.repo_global_oidc_cutover_gate.active_credential_call_count,
              -1
              ) + try(
              local.repo_global_oidc_cutover_gate.retired_call_count,
              -1
            ) == 27 &&
            length(try(
              local.repo_global_oidc_cutover_gate.active_credential_calls,
              []
              )) == try(
              local.repo_global_oidc_cutover_gate.active_credential_call_count,
              -1
            ) &&
            length(try(
              local.repo_global_oidc_cutover_gate.retired_credential_calls,
              []
              )) == try(
              local.repo_global_oidc_cutover_gate.retired_call_count,
              -1
            ) &&
            try(
              local.repo_global_oidc_cutover_gate.external_preparation_evidence.state,
              ""
              ) == try(
              local.repo_global_oidc_cutover_gate.external_preparation_evidence.accepted_state,
              "NEVER"
            ) &&
            try(
              local.repo_global_oidc_cutover_gate.external_preparation_evidence.covered_baseline_call_count,
              0
            ) == 27 &&
            try(
              local.repo_global_oidc_cutover_gate.external_activation_evidence.state,
              ""
              ) == try(
              local.repo_global_oidc_cutover_gate.external_activation_evidence.accepted_state,
              "NEVER"
            ) &&
            try(
              local.repo_global_oidc_cutover_gate.external_activation_evidence.covered_baseline_call_count,
              0
            ) == 27 &&
            alltrue([
              for digest in [
                try(local.repo_global_oidc_cutover_gate.external_preparation_evidence.matrix_sha256, ""),
                try(local.repo_global_oidc_cutover_gate.external_preparation_evidence.trust_readback_sha256, ""),
                try(local.repo_global_oidc_cutover_gate.external_activation_evidence.matrix_sha256, ""),
                try(local.repo_global_oidc_cutover_gate.external_activation_evidence.sts_readback_sha256, ""),
              ] :
              can(regex("^[0-9a-f]{64}$", digest)) &&
              digest != "0000000000000000000000000000000000000000000000000000000000000000"
            ]) &&
            var.repo_global_oidc_activation_readback_sha256 ==
            sha256(local.repo_global_oidc_cutover_gate_json)
          )
        )
      )
      error_message = "Stage requires the exact 27-call baseline matrix digest; finalize additionally requires prepared trust and accepted live STS/retirement evidence for all baseline calls."
    }
    precondition {
      condition = toset(var.runtime_state_lock_ids) == toset([
        "${var.state_bucket_name}/public-testnet/terraform.tfstate",
        "${var.state_bucket_name}/public-testnet/terraform.tfstate-md5",
      ])
      error_message = "Only the exact runtime Terraform lock and checksum LockIDs may be delegated to Foundation."
    }
    precondition {
      condition = (
        var.runtime_state_lock_readback_sha256 ==
        sha256(local.runtime_state_lock_contract_json)
      )
      error_message = "External runtime LockID readback is missing or does not match the exact sorted runtime lock contract."
    }
  }
}

resource "aws_kms_key" "terraform_state" {
  description              = "JUNCA Social Ecosystem Chain public testnet Terraform state"
  key_usage                = "ENCRYPT_DECRYPT"
  customer_master_key_spec = "SYMMETRIC_DEFAULT"
  deletion_window_in_days  = 30
  enable_key_rotation      = true
  multi_region             = false
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "IndependentRemediationStateKeyAdministration"
        Effect    = "Allow"
        Principal = { AWS = local.security_remediation_role_arn }
        Action    = local.kms_key_administration_actions
        Resource  = "*"
      },
      {
        Sid       = "SecurityBootstrapReadStateKeyEvidence"
        Effect    = "Allow"
        Principal = { AWS = var.security_bootstrap_principal_arn }
        Action    = local.kms_key_readback_actions
        Resource  = "*"
      },
      {
        Sid       = "SecurityBootstrapStateDataOnlyThroughS3"
        Effect    = "Allow"
        Principal = { AWS = var.security_bootstrap_principal_arn }
        Action = [
          "kms:Decrypt",
          "kms:Encrypt",
          "kms:GenerateDataKey",
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:EncryptionContext:aws:s3:arn" = local.security_state_kms_encryption_context_arns
            "kms:ViaService"                   = "s3.${var.aws_region}.amazonaws.com"
          }
        }
      },
      {
        Sid       = "SecurityBootstrapCreateOnlyDynamoDbStateGrant"
        Effect    = "Allow"
        Principal = { AWS = var.security_bootstrap_principal_arn }
        Action    = "kms:CreateGrant"
        Resource  = "*"
        Condition = {
          Bool = {
            "kms:GrantIsForAWSResource" = "true"
          }
          "ForAnyValue:StringEquals" = {
            "kms:ResourceAliases" = "alias/junca-social-ecosystem-chain-testnet-state"
          }
          StringEquals = {
            "kms:CallerAccount" = var.aws_account_id
            "kms:ViaService"    = "dynamodb.${var.aws_region}.amazonaws.com"
          }
        }
      },
      {
        Sid    = "FoundationDescribeStateKey"
        Effect = "Allow"
        Principal = {
          AWS = "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:root"
        }
        Action   = "kms:DescribeKey"
        Resource = "*"
        Condition = {
          ArnEquals = {
            "aws:PrincipalArn" = local.foundation_role_arn
          }
        }
      },
      {
        Sid    = "FoundationUseStateKeyOnlyThroughS3"
        Effect = "Allow"
        Principal = {
          AWS = "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:root"
        }
        Action = [
          "kms:Decrypt",
          "kms:Encrypt",
          "kms:GenerateDataKey",
        ]
        Resource = "*"
        Condition = {
          ArnEquals = {
            "aws:PrincipalArn" = local.foundation_role_arn
          }
          StringEquals = {
            "kms:EncryptionContext:aws:s3:arn" = local.runtime_state_kms_encryption_context_arns
            "kms:ViaService"                   = "s3.${var.aws_region}.amazonaws.com"
          }
        }
      },
      {
        Sid    = "ObserverDescribeStateKey"
        Effect = "Allow"
        Principal = {
          AWS = "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:root"
        }
        Action   = "kms:DescribeKey"
        Resource = "*"
        Condition = {
          ArnEquals = {
            "aws:PrincipalArn" = local.observer_role_arn
          }
        }
      },
      {
        Sid    = "ObserverDecryptStateOnlyThroughS3"
        Effect = "Allow"
        Principal = {
          AWS = "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:root"
        }
        Action   = "kms:Decrypt"
        Resource = "*"
        Condition = {
          ArnEquals = {
            "aws:PrincipalArn" = local.observer_role_arn
          }
          StringEquals = {
            "kms:EncryptionContext:aws:s3:arn" = local.runtime_state_kms_encryption_context_arns
            "kms:ViaService"                   = "s3.${var.aws_region}.amazonaws.com"
          }
        }
      },
      {
        Sid    = "DenyOidcStateKeyAdministration"
        Effect = "Deny"
        Principal = {
          AWS = "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:root"
        }
        Action = [
          "kms:CreateGrant",
          "kms:DisableKey",
          "kms:EnableKey",
          "kms:PutKeyPolicy",
          "kms:RetireGrant",
          "kms:RevokeGrant",
          "kms:ScheduleKeyDeletion",
        ]
        Resource = "*"
        Condition = {
          ArnEquals = {
            "aws:PrincipalArn" = [
              local.foundation_role_arn,
              local.ami_builder_controller_role_arn,
              local.observer_role_arn,
            ]
          }
        }
      },
    ]
  })

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Purpose = "TerraformState"
  }
}

resource "aws_kms_alias" "terraform_state" {
  name          = "alias/junca-social-ecosystem-chain-testnet-state"
  target_key_id = aws_kms_key.terraform_state.key_id
}

resource "aws_kms_key" "validator_signer" {
  count = 3

  description              = "JUNCA Social Ecosystem Chain public testnet validator ${count.index + 1} signer"
  key_usage                = "SIGN_VERIFY"
  customer_master_key_spec = "ECC_SECG_P256K1"
  deletion_window_in_days  = 30
  multi_region             = false
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "IndependentRemediationSignerAdministration"
        Effect    = "Allow"
        Principal = { AWS = local.security_remediation_role_arn }
        Action    = local.kms_key_administration_actions
        Resource  = "*"
      },
      {
        Sid       = "SecurityBootstrapReadSignerEvidence"
        Effect    = "Allow"
        Principal = { AWS = var.security_bootstrap_principal_arn }
        Action    = local.kms_key_readback_actions
        Resource  = "*"
      },
      {
        Sid       = "DenySecurityBootstrapSignerDataPlaneAndGrantCreation"
        Effect    = "Deny"
        Principal = { AWS = var.security_bootstrap_principal_arn }
        Action = [
          "kms:CreateGrant",
          "kms:Decrypt",
          "kms:Encrypt",
          "kms:GenerateDataKey",
          "kms:GenerateDataKeyWithoutPlaintext",
          "kms:GenerateMac",
          "kms:ReEncryptFrom",
          "kms:ReEncryptTo",
          "kms:Sign",
        ]
        Resource = "*"
      },
      {
        Sid    = "AutomationEvidenceDescribeSignerOnly"
        Effect = "Allow"
        Principal = {
          AWS = "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:root"
        }
        Action   = "kms:DescribeKey"
        Resource = "*"
        Condition = {
          ArnEquals = {
            "aws:PrincipalArn" = [
              local.foundation_role_arn,
              local.observer_role_arn,
            ]
          }
        }
      },
      {
        Sid    = "ValidatorQuorumVerify"
        Effect = "Allow"
        Principal = {
          AWS = "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:root"
        }
        Action = [
          "kms:DescribeKey",
          "kms:GetPublicKey",
          "kms:Verify",
        ]
        Resource = "*"
        Condition = {
          ArnEquals = {
            "aws:PrincipalArn" = local.validator_role_arns
          }
        }
      },
      {
        Sid    = "AssignedValidatorSignOnly"
        Effect = "Allow"
        Principal = {
          AWS = "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:root"
        }
        Action   = "kms:Sign"
        Resource = "*"
        Condition = {
          ArnEquals = {
            "aws:PrincipalArn" = local.validator_role_arns[count.index]
          }
        }
      },
      {
        Sid    = "DenyAutomationSignerEscalation"
        Effect = "Deny"
        Principal = {
          AWS = "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:root"
        }
        Action = [
          "kms:CreateGrant",
          "kms:DisableKey",
          "kms:EnableKey",
          "kms:PutKeyPolicy",
          "kms:ScheduleKeyDeletion",
          "kms:Sign",
        ]
        Resource = "*"
        Condition = {
          ArnEquals = {
            "aws:PrincipalArn" = local.protected_automation_role_arns
          }
        }
      },
      {
        Sid    = "DenyOtherValidatorSigning"
        Effect = "Deny"
        Principal = {
          AWS = "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:root"
        }
        Action   = "kms:Sign"
        Resource = "*"
        Condition = {
          ArnEquals = {
            "aws:PrincipalArn" = [
              for index, role_arn in local.validator_role_arns :
              role_arn if index != count.index
            ]
          }
        }
      },
    ]
  })

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Purpose   = "ValidatorSigner"
    Validator = format("%02d", count.index + 1)
  }
}

resource "aws_kms_alias" "validator_signer" {
  count = 3

  name          = format("alias/junca-social-ecosystem-chain-testnet-validator-%02d", count.index + 1)
  target_key_id = aws_kms_key.validator_signer[count.index].key_id
}

resource "aws_s3_bucket" "terraform_state" {
  bucket = var.state_bucket_name

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.terraform_state.arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = false
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket                  = aws_s3_bucket.terraform_state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_policy" "terraform_state_tls" {
  bucket = aws_s3_bucket.terraform_state.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.terraform_state.arn,
          "${aws_s3_bucket.terraform_state.arn}/*"
        ]
        Condition = {
          Bool = { "aws:SecureTransport" = "false" }
        }
      },
      {
        Sid       = "DenyUnapprovedStatePrincipal"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.terraform_state.arn,
          "${aws_s3_bucket.terraform_state.arn}/*"
        ]
        Condition = {
          ArnNotEquals = {
            "aws:PrincipalArn" = local.state_bucket_principal_allowlist
          }
        }
      },
      {
        Sid       = "DenyUnexpectedStateObjectKey"
        Effect    = "Deny"
        Principal = "*"
        Action = [
          "s3:DeleteObject",
          "s3:DeleteObjectVersion",
          "s3:GetObject",
          "s3:GetObjectVersion",
          "s3:PutObject",
        ]
        NotResource = [
          "${aws_s3_bucket.terraform_state.arn}/public-testnet/bootstrap.tfstate",
          "${aws_s3_bucket.terraform_state.arn}/public-testnet/terraform.tfstate",
        ]
      },
      {
        Sid       = "DenyStateDataPlaneForRemediationRole"
        Effect    = "Deny"
        Principal = "*"
        Action = [
          "s3:DeleteObject",
          "s3:DeleteObjectVersion",
          "s3:GetObject",
          "s3:GetObjectVersion",
          "s3:PutObject",
        ]
        Resource = "${aws_s3_bucket.terraform_state.arn}/*"
        Condition = {
          ArnEquals = {
            "aws:PrincipalArn" = local.security_remediation_role_arn
          }
        }
      },
      {
        Sid       = "DenyUnapprovedStateWrites"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.terraform_state.arn}/*"
        Condition = {
          ArnNotEquals = {
            "aws:PrincipalArn" = [
              var.security_bootstrap_principal_arn,
              local.foundation_role_arn,
            ]
          }
        }
      },
      {
        Sid       = "DenyBootstrapStateReadOutsideSecurityBootstrap"
        Effect    = "Deny"
        Principal = "*"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion",
        ]
        Resource = "${aws_s3_bucket.terraform_state.arn}/public-testnet/bootstrap.tfstate"
        Condition = {
          ArnNotEquals = {
            "aws:PrincipalArn" = var.security_bootstrap_principal_arn
          }
        }
      },
      {
        Sid       = "DenyBootstrapStateMutationOutsideSecurityBootstrap"
        Effect    = "Deny"
        Principal = "*"
        Action = [
          "s3:DeleteObject",
          "s3:DeleteObjectVersion",
          "s3:PutObject",
        ]
        Resource = "${aws_s3_bucket.terraform_state.arn}/public-testnet/bootstrap.tfstate"
        Condition = {
          ArnNotEquals = {
            "aws:PrincipalArn" = var.security_bootstrap_principal_arn
          }
        }
      },
      {
        Sid       = "DenyStateDeletionOutsideSecurityBootstrap"
        Effect    = "Deny"
        Principal = "*"
        Action = [
          "s3:DeleteObject",
          "s3:DeleteObjectVersion",
        ]
        Resource = "${aws_s3_bucket.terraform_state.arn}/*"
        Condition = {
          ArnNotEquals = {
            "aws:PrincipalArn" = var.security_bootstrap_principal_arn
          }
        }
      },
      {
        Sid       = "DenyStateControlPlaneMutationOutsideRemediationRoles"
        Effect    = "Deny"
        Principal = "*"
        Action = [
          "s3:DeleteBucketPolicy",
          "s3:PutBucketPolicy",
          "s3:PutBucketVersioning",
          "s3:PutEncryptionConfiguration",
        ]
        Resource = aws_s3_bucket.terraform_state.arn
        Condition = {
          ArnNotEquals = {
            "aws:PrincipalArn" = [
              var.security_bootstrap_principal_arn,
              local.security_remediation_role_arn,
            ]
          }
        }
      },
      {
        Sid       = "DenyStateWriteWithoutKms"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.terraform_state.arn}/*"
        Condition = {
          StringNotEquals = {
            "s3:x-amz-server-side-encryption" = "aws:kms"
          }
        }
      },
      {
        Sid       = "DenyStateWriteWithoutExactKmsKey"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.terraform_state.arn}/*"
        Condition = {
          StringNotEquals = {
            "s3:x-amz-server-side-encryption-aws-kms-key-id" = aws_kms_key.terraform_state.arn
          }
        }
      },
      {
        Sid       = "DenyUnexpectedStateListPrefix"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:ListBucket"
        Resource  = aws_s3_bucket.terraform_state.arn
        Condition = {
          StringNotEquals = {
            "s3:prefix" = [
              "public-testnet/bootstrap.tfstate",
              "public-testnet/terraform.tfstate",
            ]
          }
        }
      },
    ]
  })
}

resource "aws_dynamodb_table" "terraform_lock" {
  name         = var.lock_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.terraform_state.arn
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [aws_kms_alias.terraform_state]
}
