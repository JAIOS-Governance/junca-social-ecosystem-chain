locals {
  public_testnet_project = "JUNCA Social Ecosystem Chain"
  public_testnet_network = "Public Testnet"
  public_testnet_domain  = var.domain_name
  state_bucket_arn = (
    "arn:${data.aws_partition.current.partition}:s3:::${var.state_bucket_name}"
  )
  security_state_kms_encryption_context_arns = [
    "${local.state_bucket_arn}/public-testnet/bootstrap.tfstate",
    "${local.state_bucket_arn}/public-testnet/terraform.tfstate",
  ]
  runtime_state_kms_encryption_context_arns = [
    "${local.state_bucket_arn}/public-testnet/terraform.tfstate",
  ]
  iam_migration_is_stage    = var.iam_migration_phase == "stage"
  iam_migration_is_finalize = var.iam_migration_phase == "finalize"
  security_bootstrap_trust = jsondecode(
    data.aws_iam_role.security_bootstrap.assume_role_policy
  )
  security_remediation_trust = jsondecode(
    data.aws_iam_role.security_remediation.assume_role_policy
  )
  security_bootstrap_policy_allowlist_contract = {
    attached_policy_arns = [
      "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:policy/JuncaChainSecurityBootstrapCore",
      "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:policy/JuncaChainSecurityBootstrapState",
    ]
    inline_policy_names = []
  }
  security_bootstrap_policy_allowlist_json = jsonencode(
    local.security_bootstrap_policy_allowlist_contract
  )
  security_bootstrap_core_policy_document_json = jsonencode(jsondecode(file(
    "${path.module}/policies/security-bootstrap-core.json"
  )))
  security_bootstrap_state_policy_document_json = jsonencode(jsondecode(file(
    "${path.module}/policies/security-bootstrap-state.json"
  )))

  # GitHub's immutable repository format keeps owner/repository numeric IDs
  # inside the mandatory repo segment. runner_environment is part of the IAM
  # trust boundary, rather than merely an in-workflow claim check.
  # workflow_ref is present for direct jobs.
  # job_workflow_ref is intentionally absent because GitHub emits it only for
  # jobs using a reusable workflow.
  github_oidc_subject_template_contract = {
    include_claim_keys = [
      "repo",
      "context",
      "workflow_ref",
      "runner_environment",
    ]
    use_default           = false
    use_immutable_subject = true
  }
  github_oidc_subject_template_json = jsonencode(
    local.github_oidc_subject_template_contract
  )
  github_oidc_subject_template_projection_contract = {
    include_claim_keys = (
      local.github_oidc_subject_template_contract.include_claim_keys
    )
    use_default = local.github_oidc_subject_template_contract.use_default
  }
  github_oidc_subject_template_projection_json = jsonencode(
    local.github_oidc_subject_template_projection_contract
  )
  github_oidc_provider_contract = {
    url             = "https://token.actions.githubusercontent.com"
    client_id_list  = ["sts.amazonaws.com"]
    thumbprint_list = [var.github_oidc_thumbprint]
  }
  github_oidc_provider_contract_json = jsonencode(
    local.github_oidc_provider_contract
  )
  github_oidc_subject_prefix = (
    "repo:JAIOS-Governance@308604370/" +
    "junca-social-ecosystem-chain@1310568313:" +
    "environment:public-testnet:workflow_ref:" +
    "JAIOS-Governance/junca-social-ecosystem-chain/.github/workflows/"
  )
  github_oidc_subject_suffix = ":runner_environment:github-hosted"

  # Every value is an exact StringEquals subject. Wildcard workflow identities
  # and branch/tag subjects are deliberately absent.
  foundation_oidc_subjects = [
    "${local.github_oidc_subject_prefix}junca-validator-foundation-release.yml@refs/heads/main${local.github_oidc_subject_suffix}",
    "${local.github_oidc_subject_prefix}junca-public-testnet-release.yml@refs/heads/main${local.github_oidc_subject_suffix}",
  ]
  ami_builder_oidc_subjects = [
    "${local.github_oidc_subject_prefix}junca-validator-ami-build.yml@refs/heads/main${local.github_oidc_subject_suffix}",
  ]
  observer_oidc_subjects = [
    "${local.github_oidc_subject_prefix}junca-runtime-release-evidence-collector-v2.yml@refs/heads/main${local.github_oidc_subject_suffix}",
    "${local.github_oidc_subject_prefix}junca-public-testnet-live-soak.yml@refs/heads/main${local.github_oidc_subject_suffix}",
    "${local.github_oidc_subject_prefix}junca-social-ecosystem-chain-aws-binding-readback.yml@refs/heads/main${local.github_oidc_subject_suffix}",
    "${local.github_oidc_subject_prefix}junca-social-ecosystem-chain-aws-readback.yml@refs/heads/main${local.github_oidc_subject_suffix}",
  ]
  github_oidc_subject_readback_contract = {
    foundation  = local.foundation_oidc_subjects
    ami_builder = local.ami_builder_oidc_subjects
    observer    = local.observer_oidc_subjects
  }
  github_oidc_workflow_attestation_binding_contract = {
    ".github/workflows/junca-public-testnet-live-soak.yml" = {
      role_arn = local.observer_role_arn
      sub      = local.observer_oidc_subjects[1]
    }
    ".github/workflows/junca-public-testnet-release.yml" = {
      role_arn = local.foundation_role_arn
      sub      = local.foundation_oidc_subjects[1]
    }
    ".github/workflows/junca-runtime-release-evidence-collector-v2.yml" = {
      role_arn = local.observer_role_arn
      sub      = local.observer_oidc_subjects[0]
    }
    ".github/workflows/junca-social-ecosystem-chain-aws-binding-readback.yml" = {
      role_arn = local.observer_role_arn
      sub      = local.observer_oidc_subjects[2]
    }
    ".github/workflows/junca-social-ecosystem-chain-aws-readback.yml" = {
      role_arn = local.observer_role_arn
      sub      = local.observer_oidc_subjects[3]
    }
    ".github/workflows/junca-validator-ami-build.yml" = {
      role_arn = local.ami_builder_controller_role_arn
      sub      = local.ami_builder_oidc_subjects[0]
    }
    ".github/workflows/junca-validator-foundation-release.yml" = {
      role_arn = local.foundation_role_arn
      sub      = local.foundation_oidc_subjects[0]
    }
  }
  github_oidc_live_sts_attestation_contract = {
    attestations = [
      for workflow_path in sort(keys(
        local.github_oidc_workflow_attestation_binding_contract
      )) : {
        assets_moved              = false
        audience                  = "sts.amazonaws.com"
        bridge_activated          = false
        issuer                    = "https://token.actions.githubusercontent.com"
        mainnet_changed           = false
        repository                = "JAIOS-Governance/junca-social-ecosystem-chain"
        repository_id             = "1310568313"
        repository_owner_id       = "308604370"
        role_arn                  = local.github_oidc_workflow_attestation_binding_contract[workflow_path].role_arn
        schema_version            = "junca-github-oidc-claim-attestation/v2"
        state                     = "EXACT_TOKEN_ACCEPTED_BY_AWS_STS"
        sts_credentials_persisted = false
        sts_token_accepted        = true
        subject_claim_keys        = local.github_oidc_subject_template_contract.include_claim_keys
        sub                       = local.github_oidc_workflow_attestation_binding_contract[workflow_path].sub
        token_persisted           = false
        workflow_path             = workflow_path
        workflow_ref              = "JAIOS-Governance/junca-social-ecosystem-chain/${workflow_path}@refs/heads/main"
      }
    ]
    subjects = local.github_oidc_subject_readback_contract
  }
  github_oidc_live_sts_attestation_readback_static_projection = [
    for evidence in var.github_oidc_live_sts_attestation_readback : {
      assets_moved              = evidence.assets_moved
      audience                  = evidence.audience
      bridge_activated          = evidence.bridge_activated
      issuer                    = evidence.issuer
      mainnet_changed           = evidence.mainnet_changed
      repository                = evidence.repository
      repository_id             = evidence.repository_id
      repository_owner_id       = evidence.repository_owner_id
      role_arn                  = evidence.role_arn
      schema_version            = evidence.schema_version
      state                     = evidence.state
      sts_credentials_persisted = evidence.sts_credentials_persisted
      sts_token_accepted        = evidence.sts_token_accepted
      subject_claim_keys        = evidence.subject_claim_keys
      sub                       = evidence.sub
      token_persisted           = evidence.token_persisted
      workflow_path             = evidence.workflow_path
      workflow_ref              = evidence.workflow_ref
    }
  ]
  github_oidc_live_sts_attestation_readback_static_json = jsonencode({
    attestations = local.github_oidc_live_sts_attestation_readback_static_projection
    subjects     = local.github_oidc_subject_readback_contract
  })
  github_oidc_subject_readback_json = jsonencode(
    local.github_oidc_live_sts_attestation_contract
  )
  repo_global_oidc_cutover_gate = jsondecode(file(
    "${path.module}/../../../config/junca_public_testnet_cloud_role_policy.json"
  )).repo_global_oidc_cutover_gate
  repo_global_oidc_cutover_gate_json = jsonencode(
    local.repo_global_oidc_cutover_gate
  )
  runtime_state_lock_contract = sort(var.runtime_state_lock_ids)
  runtime_state_lock_contract_json = jsonencode(
    local.runtime_state_lock_contract
  )

  foundation_role_arn = "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:role/JuncaChainPublicTestnetDeployment"
  ami_builder_controller_role_arn = (
    "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:" +
    "role/JuncaChainPublicTestnetAmiBuilder"
  )
  observer_role_arn = (
    "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:" +
    "role/JuncaChainPublicTestnetObserver"
  )
  image_builder_instance_role_arn = (
    "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:" +
    "role/JuncaChainPublicTestnetImageBuilder"
  )
  security_remediation_role_arn = (
    "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:" +
    "role/JuncaChainSecurityBootstrapRemediation"
  )
  security_remediation_boundary_arn = (
    "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:" +
    "policy/JuncaChainSecurityBootstrapRemediationBoundary"
  )
  security_remediation_contract = {
    role_arn                 = local.security_remediation_role_arn
    permissions_boundary_arn = local.security_remediation_boundary_arn
    normal_state             = "Disabled"
    oidc_allowed             = false
    requested_session_max    = 900
  }
  security_remediation_contract_json = jsonencode(
    local.security_remediation_contract
  )
  canonical_kms_key_arns = {
    state       = aws_kms_key.terraform_state.arn
    validator01 = aws_kms_key.validator_signer[0].arn
    validator02 = aws_kms_key.validator_signer[1].arn
    validator03 = aws_kms_key.validator_signer[2].arn
  }
  canonical_kms_alias_target_contract = {
    "alias/junca-social-ecosystem-chain-testnet-state" = {
      key_id  = aws_kms_key.terraform_state.key_id
      key_arn = aws_kms_key.terraform_state.arn
    }
    "alias/junca-social-ecosystem-chain-testnet-validator-01" = {
      key_id  = aws_kms_key.validator_signer[0].key_id
      key_arn = aws_kms_key.validator_signer[0].arn
    }
    "alias/junca-social-ecosystem-chain-testnet-validator-02" = {
      key_id  = aws_kms_key.validator_signer[1].key_id
      key_arn = aws_kms_key.validator_signer[1].arn
    }
    "alias/junca-social-ecosystem-chain-testnet-validator-03" = {
      key_id  = aws_kms_key.validator_signer[2].key_id
      key_arn = aws_kms_key.validator_signer[2].arn
    }
  }
  canonical_kms_alias_target_contract_json = jsonencode(
    local.canonical_kms_alias_target_contract
  )
  external_boundary_policy_document_json = {
    foundation = jsonencode(jsondecode(file(
      "${path.module}/policies/foundation-boundary.json"
    )))
    ami_builder = jsonencode(jsondecode(file(
      "${path.module}/policies/ami-builder-boundary.json"
    )))
    observer = jsonencode(jsondecode(file(
      "${path.module}/policies/observer-boundary.json"
    )))
    remediation = jsonencode(jsondecode(templatefile(
      "${path.module}/policies/security-remediation-boundary.json",
      {
        state_key_arn       = local.canonical_kms_key_arns.state
        validator01_key_arn = local.canonical_kms_key_arns.validator01
        validator02_key_arn = local.canonical_kms_key_arns.validator02
        validator03_key_arn = local.canonical_kms_key_arns.validator03
      }
    )))
  }
  boundary_policy_document_json = merge(
    local.external_boundary_policy_document_json,
    {
      image_builder_worker = aws_iam_policy.validator_image_builder_boundary.policy
      validator01          = aws_iam_policy.validator_permissions_boundary[0].policy
      validator02          = aws_iam_policy.validator_permissions_boundary[1].policy
      validator03          = aws_iam_policy.validator_permissions_boundary[2].policy
    }
  )
  state_bucket_principal_allowlist = [
    var.security_bootstrap_principal_arn,
    local.security_remediation_role_arn,
    local.foundation_role_arn,
    local.observer_role_arn,
  ]
  protected_automation_role_arns = [
    local.foundation_role_arn,
    local.ami_builder_controller_role_arn,
    local.observer_role_arn,
    local.image_builder_instance_role_arn,
  ]

  validator_role_names = [
    for index in range(3) :
    "junca-social-ecosystem-chain-testnet-validator-${index + 1}"
  ]
  validator_role_arns = [
    for name in local.validator_role_names :
    "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:role/${name}"
  ]
  validator_instance_profile_arns = [
    for name in local.validator_role_names :
    "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:instance-profile/${name}"
  ]
  validator_permissions_boundary_arns = [
    for index in range(3) :
    (
      "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:" +
      "policy/JuncaChainPublicTestnetValidator${format("%02d", index + 1)}Boundary"
    )
  ]
  protected_role_boundary_contract = merge(
    {
      JuncaChainPublicTestnetDeployment = (
        "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:" +
        "policy/JuncaChainPublicTestnetFoundationBoundary"
      )
      JuncaChainPublicTestnetAmiBuilder = (
        "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:" +
        "policy/JuncaChainPublicTestnetAmiBuilderBoundary"
      )
      JuncaChainPublicTestnetObserver = (
        "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:" +
        "policy/JuncaChainPublicTestnetObserverBoundary"
      )
      JuncaChainPublicTestnetImageBuilder = (
        "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:" +
        "policy/JuncaChainPublicTestnetImageBuilderBoundary"
      )
    },
    {
      for index, name in local.validator_role_names :
      name => local.validator_permissions_boundary_arns[index]
    }
  )
  protected_role_boundary_contract_json = jsonencode(
    local.protected_role_boundary_contract
  )
  protected_iam_prefix_inventory_contract = {
    role_names = sort(concat(
      [
        "JuncaChainPublicTestnetDeployment",
        "JuncaChainPublicTestnetAmiBuilder",
        "JuncaChainPublicTestnetObserver",
        "JuncaChainPublicTestnetImageBuilder",
      ],
      local.validator_role_names
    ))
    instance_profile_names = sort(concat(
      ["JuncaChainPublicTestnetImageBuilder"],
      local.validator_role_names
    ))
    instance_profile_roles = merge(
      {
        JuncaChainPublicTestnetImageBuilder = [
          "JuncaChainPublicTestnetImageBuilder",
        ]
      },
      {
        for name in local.validator_role_names :
        name => [name]
      }
    )
  }
  protected_iam_prefix_inventory_contract_json = jsonencode(
    local.protected_iam_prefix_inventory_contract
  )
  protected_managed_policy_arns = concat(
    [
      "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:policy/JuncaChainPublicTestnetFoundationEc2Create",
      "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:policy/JuncaChainPublicTestnetFoundationEc2Mutation",
      "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:policy/JuncaChainPublicTestnetFoundationEdge",
      "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:policy/JuncaChainPublicTestnetFoundationObservability",
      "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:policy/JuncaChainPublicTestnetValidatorReadOnly",
      "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:policy/JuncaChainPublicTestnetImageBuilderBoundary",
      "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:policy/JuncaChainPublicTestnetFoundationBoundary",
      "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:policy/JuncaChainPublicTestnetAmiBuilderBoundary",
      "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:policy/JuncaChainPublicTestnetObserverBoundary",
      "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:policy/JuncaChainSecurityBootstrapCore",
      "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:policy/JuncaChainSecurityBootstrapState",
    ],
    local.validator_permissions_boundary_arns
  )

  public_testnet_ec2_resource_arns = [
    "arn:${data.aws_partition.current.partition}:ec2:${var.aws_region}:${var.aws_account_id}:instance/*",
    "arn:${data.aws_partition.current.partition}:ec2:${var.aws_region}:${var.aws_account_id}:volume/*",
    "arn:${data.aws_partition.current.partition}:ec2:${var.aws_region}:${var.aws_account_id}:snapshot/*",
    "arn:${data.aws_partition.current.partition}:ec2:${var.aws_region}:${var.aws_account_id}:vpc/*",
    "arn:${data.aws_partition.current.partition}:ec2:${var.aws_region}:${var.aws_account_id}:subnet/*",
    "arn:${data.aws_partition.current.partition}:ec2:${var.aws_region}:${var.aws_account_id}:security-group/*",
    "arn:${data.aws_partition.current.partition}:ec2:${var.aws_region}:${var.aws_account_id}:internet-gateway/*",
    "arn:${data.aws_partition.current.partition}:ec2:${var.aws_region}:${var.aws_account_id}:route-table/*",
    "arn:${data.aws_partition.current.partition}:ec2:${var.aws_region}:${var.aws_account_id}:network-interface/*",
    "arn:${data.aws_partition.current.partition}:ec2:${var.aws_region}:${var.aws_account_id}:vpc-endpoint/*",
  ]
  public_testnet_elb_resource_arns = [
    "arn:${data.aws_partition.current.partition}:elasticloadbalancing:${var.aws_region}:${var.aws_account_id}:loadbalancer/app/junca-testnet-public/*",
    "arn:${data.aws_partition.current.partition}:elasticloadbalancing:${var.aws_region}:${var.aws_account_id}:targetgroup/junca-testnet-*/*",
    "arn:${data.aws_partition.current.partition}:elasticloadbalancing:${var.aws_region}:${var.aws_account_id}:listener/app/junca-testnet-public/*/*",
    "arn:${data.aws_partition.current.partition}:elasticloadbalancing:${var.aws_region}:${var.aws_account_id}:listener-rule/app/junca-testnet-public/*/*/*",
  ]
  public_testnet_waf_resource_arns = [
    "arn:${data.aws_partition.current.partition}:wafv2:${var.aws_region}:${var.aws_account_id}:regional/webacl/junca-testnet-public/*",
  ]
  public_testnet_acm_resource_arn = (
    "arn:${data.aws_partition.current.partition}:acm:${var.aws_region}:" +
    "${var.aws_account_id}:certificate/*"
  )
  public_testnet_log_resource_arns = [
    "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${var.aws_account_id}:log-group:/junca/social-ecosystem-chain/public-testnet/validator",
    "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${var.aws_account_id}:log-group:/junca/social-ecosystem-chain/public-testnet/validator:*",
  ]
  public_testnet_alarm_resource_arn = (
    "arn:${data.aws_partition.current.partition}:cloudwatch:${var.aws_region}:" +
    "${var.aws_account_id}:alarm:junca-social-ecosystem-chain-testnet-validator-*-status"
  )
  public_testnet_sns_resource_arn = (
    "arn:${data.aws_partition.current.partition}:sns:${var.aws_region}:" +
    "${var.aws_account_id}:junca-social-ecosystem-chain-testnet-validator-alerts"
  )
  route53_hosted_zone_arn = (
    "arn:${data.aws_partition.current.partition}:route53:::hostedzone/" +
    var.route53_zone_id
  )
  public_testnet_dns_record_names = [
    "rpc.${local.public_testnet_domain}",
    "explorer.${local.public_testnet_domain}",
    "scan.${local.public_testnet_domain}",
    "health.${local.public_testnet_domain}",
    "_*.rpc.${local.public_testnet_domain}",
    "_*.explorer.${local.public_testnet_domain}",
    "_*.scan.${local.public_testnet_domain}",
    "_*.health.${local.public_testnet_domain}",
  ]
  public_testnet_certificate_domain_names = [
    "rpc.${local.public_testnet_domain}",
    "explorer.${local.public_testnet_domain}",
    "scan.${local.public_testnet_domain}",
    "health.${local.public_testnet_domain}",
  ]

  image_builder_resource_arns = [
    "arn:${data.aws_partition.current.partition}:imagebuilder:${var.aws_region}:${var.aws_account_id}:component/junca-validator-*/*",
    "arn:${data.aws_partition.current.partition}:imagebuilder:${var.aws_region}:${var.aws_account_id}:image-recipe/junca-validator-*/*",
    "arn:${data.aws_partition.current.partition}:imagebuilder:${var.aws_region}:${var.aws_account_id}:infrastructure-configuration/junca-validator-*",
    "arn:${data.aws_partition.current.partition}:imagebuilder:${var.aws_region}:${var.aws_account_id}:distribution-configuration/junca-validator-*",
    "arn:${data.aws_partition.current.partition}:imagebuilder:${var.aws_region}:${var.aws_account_id}:image/junca-validator-*/*",
  ]

  automation_self_mutation_actions = [
    "iam:AttachRolePolicy",
    "iam:DeleteRole",
    "iam:DeleteRolePermissionsBoundary",
    "iam:DeleteRolePolicy",
    "iam:DetachRolePolicy",
    "iam:PutRolePermissionsBoundary",
    "iam:PutRolePolicy",
    "iam:TagRole",
    "iam:UntagRole",
    "iam:UpdateAssumeRolePolicy",
    "iam:UpdateRole",
    "iam:UpdateRoleDescription",
  ]
  kms_key_administration_actions = [
    "kms:CancelKeyDeletion",
    "kms:DescribeKey",
    "kms:DisableKey",
    "kms:EnableKey",
    "kms:EnableKeyRotation",
    "kms:GetKeyPolicy",
    "kms:GetKeyRotationStatus",
    "kms:ListGrants",
    "kms:ListKeyPolicies",
    "kms:ListResourceTags",
    "kms:PutKeyPolicy",
    "kms:RevokeGrant",
    "kms:ScheduleKeyDeletion",
    "kms:TagResource",
    "kms:UntagResource",
    "kms:UpdateKeyDescription",
  ]
  kms_key_readback_actions = [
    "kms:DescribeKey",
    "kms:GetKeyPolicy",
    "kms:GetKeyRotationStatus",
    "kms:ListGrants",
    "kms:ListKeyPolicies",
    "kms:ListResourceTags",
  ]
}

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [var.github_oidc_thumbprint]

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [tags, tags_all]
  }
}

# All protected roles and their one-to-one permissions boundaries are an
# external two-person remediation prerequisite. This read fails before planning
# if any role is absent; the account gate below rejects every boundary drift.
data "aws_iam_role" "protected_preexisting" {
  for_each = local.protected_role_boundary_contract

  name = each.key
}

data "aws_iam_role" "security_remediation" {
  name = "JuncaChainSecurityBootstrapRemediation"
}

# The historical ARN is retained only as a compatibility-safe name. Its
# permissions are now the Foundation boundary; it has no AMI Builder policy.
resource "aws_iam_role" "deployment" {
  name                 = "JuncaChainPublicTestnetDeployment"
  max_session_duration = 3600
  permissions_boundary = local.protected_role_boundary_contract[
    "JuncaChainPublicTestnetDeployment"
  ]

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "ExactFoundationWorkflows"
      Effect = "Allow"
      Principal = {
        Federated = aws_iam_openid_connect_provider.github.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = local.foundation_oidc_subjects
        }
      }
    }]
  })

  tags = {
    RoleBoundary = "Foundation"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role" "ami_builder_controller" {
  name                 = "JuncaChainPublicTestnetAmiBuilder"
  max_session_duration = 3600
  permissions_boundary = local.protected_role_boundary_contract[
    "JuncaChainPublicTestnetAmiBuilder"
  ]

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "ExactAmiBuilderWorkflow"
      Effect = "Allow"
      Principal = {
        Federated = aws_iam_openid_connect_provider.github.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = local.ami_builder_oidc_subjects
        }
      }
    }]
  })

  tags = {
    RoleBoundary = "AmiBuilder"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role" "observer" {
  name                 = "JuncaChainPublicTestnetObserver"
  max_session_duration = 3600
  permissions_boundary = local.protected_role_boundary_contract[
    "JuncaChainPublicTestnetObserver"
  ]

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "ExactObserverWorkflows"
      Effect = "Allow"
      Principal = {
        Federated = aws_iam_openid_connect_provider.github.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = local.observer_oidc_subjects
        }
      }
    }]
  })

  tags = {
    RoleBoundary = "Observer"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role_policy" "automation_self_mutation_deny" {
  for_each = {
    foundation  = aws_iam_role.deployment.name
    ami_builder = aws_iam_role.ami_builder_controller.name
    observer    = aws_iam_role.observer.name
  }

  name = "DenyAutomationIamMutation"
  role = each.value
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "DenyAutomationRoleMutation"
        Effect   = "Deny"
        Action   = local.automation_self_mutation_actions
        Resource = concat(
          local.protected_automation_role_arns,
          local.validator_role_arns
        )
      },
      {
        Sid    = "DenyProtectedManagedPolicyMutation"
        Effect = "Deny"
        Action = [
          "iam:CreatePolicyVersion",
          "iam:DeletePolicy",
          "iam:DeletePolicyVersion",
          "iam:SetDefaultPolicyVersion",
        ]
        Resource = local.protected_managed_policy_arns
      },
      {
        Sid      = "DenyManagedPolicyCreation"
        Effect   = "Deny"
        Action   = "iam:CreatePolicy"
        Resource = "*"
      },
      {
        Sid    = "DenyValidatorInstanceProfileMutation"
        Effect = "Deny"
        Action = [
          "iam:AddRoleToInstanceProfile",
          "iam:CreateInstanceProfile",
          "iam:DeleteInstanceProfile",
          "iam:RemoveRoleFromInstanceProfile",
        ]
        Resource = concat(
          local.validator_instance_profile_arns,
          local.validator_role_arns
        )
      },
      {
        Sid         = "DenyPassingAnyOtherRole"
        Effect      = "Deny"
        Action      = "iam:PassRole"
        NotResource = local.image_builder_instance_role_arn
      },
      {
        Sid    = "DenyGithubOidcProviderMutation"
        Effect = "Deny"
        Action = [
          "iam:AddClientIDToOpenIDConnectProvider",
          "iam:DeleteOpenIDConnectProvider",
          "iam:RemoveClientIDFromOpenIDConnectProvider",
          "iam:TagOpenIDConnectProvider",
          "iam:UntagOpenIDConnectProvider",
          "iam:UpdateOpenIDConnectProviderThumbprint",
        ]
        Resource = aws_iam_openid_connect_provider.github.arn
      },
      {
        Sid    = "DenyKmsKeyCreationGrantsSigningAndAdministration"
        Effect = "Deny"
        Action = [
          "kms:CancelKeyDeletion",
          "kms:CreateGrant",
          "kms:CreateKey",
          "kms:DeleteImportedKeyMaterial",
          "kms:DisableKey",
          "kms:EnableKey",
          "kms:ImportKeyMaterial",
          "kms:PutKeyPolicy",
          "kms:ReplicateKey",
          "kms:RetireGrant",
          "kms:RevokeGrant",
          "kms:ScheduleKeyDeletion",
          "kms:Sign",
          "kms:TagResource",
          "kms:UntagResource",
          "kms:UpdateKeyDescription",
          "kms:UpdatePrimaryRegion",
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "deployment_state" {
  name = "CanonicalTerraformState"
  role = aws_iam_role.deployment.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ListExactCanonicalStateObjects"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.terraform_state.arn
        Condition = {
          StringEquals = {
            "s3:prefix" = [
              "public-testnet/terraform.tfstate",
            ]
          }
        }
      },
      {
        Sid      = "ReadExactCanonicalStateObjects"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = [
          "${aws_s3_bucket.terraform_state.arn}/public-testnet/terraform.tfstate",
        ]
      },
      {
        Sid      = "WriteOnlyRuntimeTerraformState"
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.terraform_state.arn}/public-testnet/terraform.tfstate"
      },
      {
        Sid      = "DescribeCanonicalStateLockTable"
        Effect   = "Allow"
        Action   = "dynamodb:DescribeTable"
        Resource = aws_dynamodb_table.terraform_lock.arn
      },
      {
        Sid    = "UseOnlyRuntimeStateLockKeys"
        Effect = "Allow"
        Action = [
          "dynamodb:DeleteItem",
          "dynamodb:GetItem",
          "dynamodb:PutItem",
        ]
        Resource = aws_dynamodb_table.terraform_lock.arn
        Condition = {
          "ForAllValues:StringEquals" = {
            "dynamodb:LeadingKeys" = local.runtime_state_lock_contract
          }
        }
      },
      {
        Sid    = "UseCanonicalStateEncryption"
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey",
          "kms:Encrypt",
          "kms:GenerateDataKey",
        ]
        Resource = aws_kms_key.terraform_state.arn
      },
      {
        Sid      = "DescribeExactValidatorSignerKeys"
        Effect   = "Allow"
        Action   = "kms:DescribeKey"
        Resource = aws_kms_key.validator_signer[*].arn
      }
    ]
  })
}

resource "aws_iam_role_policy" "deployment_self_permission_readback" {
  name = "SelfPermissionReadback"
  role = aws_iam_role.deployment.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "SimulateCanonicalFoundationRoleOnly"
      Effect   = "Allow"
      Action   = "iam:SimulatePrincipalPolicy"
      Resource = aws_iam_role.deployment.arn
    }]
  })
}

resource "aws_iam_policy" "deployment_infrastructure_allow" {
  name        = "JuncaChainPublicTestnetFoundationEc2Create"
  description = "Read and create tagged Public Testnet EC2 foundation resources"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadEc2FoundationState"
        Effect = "Allow"
        Action = [
          "ec2:DescribeAccountAttributes",
          "ec2:DescribeAvailabilityZones",
          "ec2:DescribeImages",
          "ec2:DescribeInstanceAttribute",
          "ec2:DescribeInstances",
          "ec2:DescribeInstanceStatus",
          "ec2:DescribeInternetGateways",
          "ec2:DescribeNetworkAcls",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DescribePrefixLists",
          "ec2:DescribeRouteTables",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeSnapshots",
          "ec2:DescribeSubnets",
          "ec2:DescribeTags",
          "ec2:DescribeVolumes",
          "ec2:DescribeVolumesModifications",
          "ec2:DescribeVpcAttribute",
          "ec2:DescribeVpcEndpointServices",
          "ec2:DescribeVpcEndpoints",
          "ec2:DescribeVpcs",
          "ec2:GetEbsEncryptionByDefault",
        ]
        Resource = "*"
      },
      {
        Sid    = "CreateOnlyTaggedPublicTestnetResources"
        Effect = "Allow"
        Action = [
          "ec2:CreateInternetGateway",
          "ec2:CreateVpc",
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:RequestTag/Network" = local.public_testnet_network
            "aws:RequestTag/Project" = local.public_testnet_project
            "aws:RequestedRegion"     = var.aws_region
          }
        }
      },
      {
        Sid      = "TagOnlyDuringApprovedEc2Creation"
        Effect   = "Allow"
        Action   = "ec2:CreateTags"
        Resource = local.public_testnet_ec2_resource_arns
        Condition = {
          StringEquals = {
            "aws:RequestTag/Network" = local.public_testnet_network
            "aws:RequestTag/Project" = local.public_testnet_project
            "aws:RequestedRegion"     = var.aws_region
            "ec2:CreateAction" = [
              "CreateInternetGateway",
              "CreateVpc",
            ]
          }
        }
      },
    ]
  })
}

resource "aws_iam_policy" "deployment_infrastructure_mutation" {
  name        = "JuncaChainPublicTestnetFoundationEc2Mutation"
  description = "Mutate only existing tagged Public Testnet EC2 foundation resources"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "UpdateOnlyApprovedTagsOnPublicTestnetResources"
        Effect = "Allow"
        Action = [
          "ec2:CreateTags",
          "ec2:DeleteTags",
        ]
        Resource = local.public_testnet_ec2_resource_arns
        Condition = {
          StringEquals = {
            "aws:ResourceTag/Network" = local.public_testnet_network
            "aws:ResourceTag/Project" = local.public_testnet_project
          }
          "ForAllValues:StringEquals" = {
            "aws:TagKeys" = [
              "AssetsMoved",
              "BridgeActivated",
              "FailureDomain",
              "Governance",
              "JuncaFilesystemVerified",
              "JuncaFinalityCertificateBackfilled",
              "JuncaMigrationState",
              "JuncaRollbackSnapshotId",
              "JuncaStateStoreIntegrity",
              "MainnetChanged",
              "ManagedBy",
              "MigrationRequired",
              "MonetaryUse",
              "Name",
              "PublicRPC",
              "PublicTestnetOnly",
              "StatePath",
              "Validator",
            ]
          }
        }
      },
      {
        Sid    = "MutateOnlyTaggedPublicTestnetEc2Resources"
        Effect = "Allow"
        Action = [
          "ec2:AssociateRouteTable",
          "ec2:AttachInternetGateway",
          "ec2:AttachVolume",
          "ec2:AuthorizeSecurityGroupEgress",
          "ec2:AuthorizeSecurityGroupIngress",
          "ec2:CreateRoute",
          "ec2:DeleteInternetGateway",
          "ec2:DeleteRoute",
          "ec2:DeleteRouteTable",
          "ec2:DeleteSecurityGroup",
          "ec2:DeleteSnapshot",
          "ec2:DeleteSubnet",
          "ec2:DeleteVolume",
          "ec2:DeleteVpc",
          "ec2:DeleteVpcEndpoints",
          "ec2:DetachInternetGateway",
          "ec2:DetachVolume",
          "ec2:DisassociateRouteTable",
          "ec2:ModifyInstanceAttribute",
          "ec2:ModifySubnetAttribute",
          "ec2:ModifyVolume",
          "ec2:ModifyVpcAttribute",
          "ec2:ModifyVpcEndpoint",
          "ec2:RevokeSecurityGroupEgress",
          "ec2:RevokeSecurityGroupIngress",
          "ec2:StartInstances",
          "ec2:StopInstances",
          "ec2:TerminateInstances",
        ]
        Resource = local.public_testnet_ec2_resource_arns
        Condition = {
          StringEquals = {
            "aws:ResourceTag/Network" = local.public_testnet_network
            "aws:ResourceTag/Project" = local.public_testnet_project
          }
        }
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "deployment_infrastructure_allow" {
  role       = aws_iam_role.deployment.id
  policy_arn = aws_iam_policy.deployment_infrastructure_allow.arn
}

resource "aws_iam_role_policy_attachment" "deployment_infrastructure_mutation" {
  role       = aws_iam_role.deployment.id
  policy_arn = aws_iam_policy.deployment_infrastructure_mutation.arn
}

# Preserve the historical inline-policy address while reducing it to an
# immutable tag-boundary deny. The dependency guarantees that the replacement
# managed allow policy is attached before the old broad inline allow is
# narrowed in place.
resource "aws_iam_role_policy" "deployment_infrastructure" {
  name = "PublicTestnetInfrastructure"
  role = aws_iam_role.deployment.id

  depends_on = [
    aws_iam_role_policy_attachment.deployment_infrastructure_allow,
    aws_iam_role_policy_attachment.deployment_infrastructure_mutation,
  ]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "DenyPublicTestnetEc2BoundaryTagMutation"
        Effect = "Deny"
        Action = [
          "ec2:CreateTags",
          "ec2:DeleteTags",
        ]
        Resource = local.public_testnet_ec2_resource_arns
        Condition = {
          "ForAnyValue:StringEquals" = {
            "aws:TagKeys" = [
              "LaunchContract",
              "Network",
              "Project",
              "Role",
            ]
          }
        }
      },
      {
        Sid    = "DenyCanonicalValidatorInstanceMutation"
        Effect = "Deny"
        Action = [
          "ec2:AttachVolume",
          "ec2:DetachVolume",
          "ec2:ModifyInstanceAttribute",
          "ec2:StartInstances",
          "ec2:StopInstances",
          "ec2:TerminateInstances",
        ]
        Resource = "arn:${data.aws_partition.current.partition}:ec2:${var.aws_region}:${var.aws_account_id}:instance/*"
        Condition = {
          StringEquals = {
            "aws:ResourceTag/LaunchContract" = "JuncaValidatorLaunchV1"
            "aws:ResourceTag/Role"           = "Validator"
          }
        }
      },
      {
        Sid      = "DenyUnboundSnapshotCreation"
        Effect   = "Deny"
        Action   = "ec2:CreateSnapshot"
        Resource = "*"
      },
      {
        Sid    = "DenyUnboundEc2ChildResourceCreation"
        Effect = "Deny"
        Action = [
          "ec2:CreateRouteTable",
          "ec2:CreateSecurityGroup",
          "ec2:CreateSubnet",
          "ec2:CreateVolume",
          "ec2:CreateVpcEndpoint",
        ]
        Resource = "*"
      },
      {
        Sid      = "DenyUnattestedValidatorLaunch"
        Effect   = "Deny"
        Action   = "ec2:RunInstances"
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_policy" "deployment_edge" {
  name        = "JuncaChainPublicTestnetFoundationEdge"
  description = "Exact ELB and Route 53 Public Testnet foundation operations"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadElasticLoadBalancing"
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:DescribeAccountLimits",
          "elasticloadbalancing:DescribeListenerAttributes",
          "elasticloadbalancing:DescribeListenerCertificates",
          "elasticloadbalancing:DescribeListeners",
          "elasticloadbalancing:DescribeLoadBalancerAttributes",
          "elasticloadbalancing:DescribeLoadBalancers",
          "elasticloadbalancing:DescribeRules",
          "elasticloadbalancing:DescribeTags",
          "elasticloadbalancing:DescribeTargetGroupAttributes",
          "elasticloadbalancing:DescribeTargetGroups",
          "elasticloadbalancing:DescribeTargetHealth",
        ]
        Resource = "*"
      },
      {
        Sid    = "CreateTaggedElasticLoadBalancingResources"
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:CreateListener",
          "elasticloadbalancing:CreateLoadBalancer",
          "elasticloadbalancing:CreateRule",
          "elasticloadbalancing:CreateTargetGroup",
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:RequestTag/Network" = local.public_testnet_network
            "aws:RequestTag/Project" = local.public_testnet_project
            "aws:RequestedRegion"     = var.aws_region
          }
        }
      },
      {
        Sid    = "MutateTaggedElasticLoadBalancingResources"
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:AddListenerCertificates",
          "elasticloadbalancing:AddTags",
          "elasticloadbalancing:DeleteListener",
          "elasticloadbalancing:DeleteLoadBalancer",
          "elasticloadbalancing:DeleteRule",
          "elasticloadbalancing:DeleteTargetGroup",
          "elasticloadbalancing:DeregisterTargets",
          "elasticloadbalancing:ModifyListener",
          "elasticloadbalancing:ModifyListenerAttributes",
          "elasticloadbalancing:ModifyLoadBalancerAttributes",
          "elasticloadbalancing:ModifyRule",
          "elasticloadbalancing:ModifyTargetGroup",
          "elasticloadbalancing:ModifyTargetGroupAttributes",
          "elasticloadbalancing:RegisterTargets",
          "elasticloadbalancing:RemoveListenerCertificates",
          "elasticloadbalancing:RemoveTags",
          "elasticloadbalancing:SetIpAddressType",
          "elasticloadbalancing:SetRulePriorities",
          "elasticloadbalancing:SetSecurityGroups",
          "elasticloadbalancing:SetSubnets",
        ]
        Resource = local.public_testnet_elb_resource_arns
        Condition = {
          StringEquals = {
            "aws:ResourceTag/Network" = local.public_testnet_network
            "aws:ResourceTag/Project" = local.public_testnet_project
          }
        }
      },
      {
        Sid      = "ChangeOnlyCanonicalPublicTestnetDns"
        Effect   = "Allow"
        Action   = "route53:ChangeResourceRecordSets"
        Resource = local.route53_hosted_zone_arn
        Condition = {
          "ForAllValues:StringLike" = {
            "route53:ChangeResourceRecordSetsNormalizedRecordNames" = local.public_testnet_dns_record_names
          }
          "ForAllValues:StringEquals" = {
            "route53:ChangeResourceRecordSetsActions" = [
              "CREATE",
              "DELETE",
              "UPSERT",
            ]
            "route53:ChangeResourceRecordSetsRecordTypes" = [
              "A",
              "CNAME",
            ]
          }
        }
      },
      {
        Sid    = "ReadCanonicalRoute53"
        Effect = "Allow"
        Action = [
          "route53:GetHostedZone",
          "route53:ListResourceRecordSets",
          "route53:ListTagsForResource",
        ]
        Resource = local.route53_hosted_zone_arn
      },
      {
        Sid      = "ReadRoute53ChangeStatus"
        Effect   = "Allow"
        Action   = "route53:GetChange"
        Resource = "arn:${data.aws_partition.current.partition}:route53:::change/*"
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "deployment_edge" {
  role       = aws_iam_role.deployment.name
  policy_arn = aws_iam_policy.deployment_edge.arn
}

resource "aws_iam_policy" "deployment_observability" {
  name        = "JuncaChainPublicTestnetFoundationObservability"
  description = "Exact ACM, WAF, SNS, Logs, and CloudWatch foundation operations"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "RequestTaggedPublicTestnetCertificates"
        Effect   = "Allow"
        Action   = "acm:RequestCertificate"
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:RequestTag/Network" = local.public_testnet_network
            "aws:RequestTag/Project" = local.public_testnet_project
            "aws:RequestedRegion"     = var.aws_region
            "acm:ValidationMethod"    = "DNS"
          }
          Null = {
            "acm:DomainNames" = "false"
          }
          "ForAllValues:StringEquals" = {
            "acm:DomainNames" = local.public_testnet_certificate_domain_names
          }
        }
      },
      {
        Sid    = "ManageTaggedPublicTestnetCertificates"
        Effect = "Allow"
        Action = [
          "acm:AddTagsToCertificate",
          "acm:DeleteCertificate",
          "acm:DescribeCertificate",
          "acm:ListTagsForCertificate",
          "acm:RemoveTagsFromCertificate",
        ]
        Resource = local.public_testnet_acm_resource_arn
        Condition = {
          StringEquals = {
            "aws:ResourceTag/Network" = local.public_testnet_network
            "aws:ResourceTag/Project" = local.public_testnet_project
          }
        }
      },
      {
        Sid      = "CreateTaggedPublicTestnetWebAcl"
        Effect   = "Allow"
        Action   = "wafv2:CreateWebACL"
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:RequestTag/Network" = local.public_testnet_network
            "aws:RequestTag/Project" = local.public_testnet_project
            "aws:RequestedRegion"     = var.aws_region
          }
        }
      },
      {
        Sid    = "ManageExactPublicTestnetWebAcl"
        Effect = "Allow"
        Action = [
          "wafv2:DeleteWebACL",
          "wafv2:GetWebACL",
          "wafv2:ListResourcesForWebACL",
          "wafv2:ListTagsForResource",
          "wafv2:TagResource",
          "wafv2:UntagResource",
          "wafv2:UpdateWebACL",
        ]
        Resource = local.public_testnet_waf_resource_arns
        Condition = {
          StringEquals = {
            "aws:ResourceTag/Network" = local.public_testnet_network
            "aws:ResourceTag/Project" = local.public_testnet_project
          }
        }
      },
      {
        Sid    = "AssociateExactPublicTestnetWebAcl"
        Effect = "Allow"
        Action = [
          "wafv2:AssociateWebACL",
          "wafv2:DisassociateWebACL",
          "wafv2:GetWebACLForResource",
        ]
        Resource = concat(
          local.public_testnet_waf_resource_arns,
          [local.public_testnet_elb_resource_arns[0]]
        )
      },
      {
        Sid      = "ListRegionalWebAcls"
        Effect   = "Allow"
        Action   = "wafv2:ListWebACLs"
        Resource = "*"
      },
      {
        Sid    = "ManageExactValidatorAlertTopic"
        Effect = "Allow"
        Action = [
          "sns:CreateTopic",
          "sns:DeleteTopic",
          "sns:GetTopicAttributes",
          "sns:ListTagsForResource",
          "sns:SetTopicAttributes",
          "sns:TagResource",
          "sns:UntagResource",
        ]
        Resource = local.public_testnet_sns_resource_arn
      },
      {
        Sid    = "ManageExactValidatorLogGroup"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:DeleteLogGroup",
          "logs:ListTagsForResource",
          "logs:PutRetentionPolicy",
          "logs:TagResource",
          "logs:UntagResource",
        ]
        Resource = local.public_testnet_log_resource_arns
      },
      {
        Sid      = "DescribeValidatorLogGroups"
        Effect   = "Allow"
        Action   = "logs:DescribeLogGroups"
        Resource = "*"
      },
      {
        Sid    = "ManageExactValidatorStatusAlarms"
        Effect = "Allow"
        Action = [
          "cloudwatch:DeleteAlarms",
          "cloudwatch:ListTagsForResource",
          "cloudwatch:PutMetricAlarm",
          "cloudwatch:TagResource",
          "cloudwatch:UntagResource",
        ]
        Resource = local.public_testnet_alarm_resource_arn
      },
      {
        Sid      = "DescribeValidatorStatusAlarms"
        Effect   = "Allow"
        Action   = "cloudwatch:DescribeAlarms"
        Resource = "*"
      },
      {
        Sid      = "CreateElasticLoadBalancingServiceRole"
        Effect   = "Allow"
        Action   = "iam:CreateServiceLinkedRole"
        Resource = "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:role/aws-service-role/elasticloadbalancing.amazonaws.com/AWSServiceRoleForElasticLoadBalancing"
        Condition = {
          StringEquals = {
            "iam:AWSServiceName" = "elasticloadbalancing.amazonaws.com"
          }
        }
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "deployment_observability" {
  role       = aws_iam_role.deployment.name
  policy_arn = aws_iam_policy.deployment_observability.arn
}

resource "aws_iam_policy" "validator_permissions_boundary" {
  count = 3

  name = format(
    "JuncaChainPublicTestnetValidator%02dBoundary",
    count.index + 1
  )
  description = (
    "Maximum permissions for Public Testnet validator " +
    format("%02d", count.index + 1)
  )

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "UseOnlyPublicTestnetSignerKeys"
        Effect = "Allow"
        Action = [
          "kms:DescribeKey",
          "kms:GetPublicKey",
          "kms:Verify",
        ]
        Resource = aws_kms_key.validator_signer[*].arn
      },
      {
        Sid      = "SignOnlyAssignedPublicTestnetKey"
        Effect   = "Allow"
        Action   = "kms:Sign"
        Resource = aws_kms_key.validator_signer[count.index].arn
      },
      {
        Sid    = "WriteExactValidatorLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:DescribeLogStreams",
          "logs:PutLogEvents",
        ]
        Resource = local.public_testnet_log_resource_arns
      },
      {
        Sid      = "PublishOnlyPublicTestnetMetrics"
        Effect   = "Allow"
        Action   = "cloudwatch:PutMetricData"
        Resource = "*"
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = "JUNCA/PublicTestnet"
          }
        }
      },
    ]
  })

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role" "validator" {
  count = 3

  name                 = local.validator_role_names[count.index]
  permissions_boundary = aws_iam_policy.validator_permissions_boundary[count.index].arn

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "Ec2ValidatorWorkloadOnly"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    RoleBoundary = format("Validator%02d", count.index + 1)
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role_policy" "validator_signer_boundary" {
  count = 3
  name  = "validator-${count.index + 1}-signer-boundary"
  role  = aws_iam_role.validator[count.index].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "UseOnlyAssignedSigner"
        Effect   = "Allow"
        Action   = "kms:Sign"
        Resource = aws_kms_key.validator_signer[count.index].arn
      },
      {
        Sid    = "VerifyValidatorQuorum"
        Effect = "Allow"
        Action = [
          "kms:DescribeKey",
          "kms:GetPublicKey",
          "kms:Verify",
        ]
        Resource = aws_kms_key.validator_signer[*].arn
      },
      {
        Sid    = "WriteOperationalTelemetry"
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricData",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_instance_profile" "validator" {
  count = 3
  name  = local.validator_role_names[count.index]
  role  = aws_iam_role.validator[count.index].name

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_policy" "deployment_validator_pass" {
  name        = "JuncaChainPublicTestnetValidatorReadOnly"
  description = "Read Security Bootstrap-owned validator identities while launch remains blocked"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadExactValidatorWorkloadIdentities"
        Effect = "Allow"
        Action = [
          "iam:GetInstanceProfile",
          "iam:GetRole",
          "iam:GetRolePolicy",
          "iam:ListAttachedRolePolicies",
          "iam:ListInstanceProfilesForRole",
          "iam:ListRolePolicies",
        ]
        Resource = concat(
          local.validator_instance_profile_arns,
          local.validator_role_arns
        )
      },
      {
        Sid      = "DenyPassRoleUntilAttestedLaunchContract"
        Effect   = "Deny"
        Action   = "iam:PassRole"
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "deployment_validator_pass" {
  role       = aws_iam_role.deployment.name
  policy_arn = aws_iam_policy.deployment_validator_pass.arn
}

resource "aws_iam_role_policy" "deployment_runtime_acceptance" {
  name = "PublicTestnetRuntimeAcceptance"
  role = aws_iam_role.deployment.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "DenyArbitraryValidatorRootCommand"
      Effect   = "Deny"
      Action   = "ssm:SendCommand"
      Resource = "*"
    }]
  })
}

resource "aws_iam_policy" "validator_image_builder_boundary" {
  name        = "JuncaChainPublicTestnetImageBuilderBoundary"
  description = "Pinned EC2 Image Builder v12 and parameter-free SSM maximum permissions"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "DescribeImageBuilderStorage"
        Effect = "Allow"
        Action = [
          "ec2:DescribeSnapshots",
          "ec2:DescribeVolumes",
        ]
        Resource = "*"
      },
      {
        Sid      = "CreateOnlyImageBuilderTaggedSnapshot"
        Effect   = "Allow"
        Action   = "ec2:CreateSnapshot"
        Resource = "arn:${data.aws_partition.current.partition}:ec2:${var.aws_region}:${var.aws_account_id}:snapshot/*"
        Condition = {
          StringEquals = {
            "aws:RequestTag/CreatedBy" = "EC2 Image Builder"
          }
        }
      },
      {
        Sid      = "SnapshotOnlyImageBuilderTaggedVolume"
        Effect   = "Allow"
        Action   = "ec2:CreateSnapshot"
        Resource = "arn:${data.aws_partition.current.partition}:ec2:${var.aws_region}:${var.aws_account_id}:volume/*"
        Condition = {
          StringEquals = {
            "aws:ResourceTag/CreatedBy" = "EC2 Image Builder"
          }
        }
      },
      {
        Sid      = "TagOnlyDuringImageBuilderSnapshotCreation"
        Effect   = "Allow"
        Action   = "ec2:CreateTags"
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:RequestTag/CreatedBy" = "EC2 Image Builder"
            "ec2:CreateAction"         = "CreateSnapshot"
          }
        }
      },
      {
        Sid      = "ReadSameAccountIsoInputs"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = [
          "arn:${data.aws_partition.current.partition}:s3:::*/*.ISO",
          "arn:${data.aws_partition.current.partition}:s3:::*/*.Iso",
          "arn:${data.aws_partition.current.partition}:s3:::*/*.iso",
        ]
        Condition = {
          StringEquals = {
            "s3:ResourceAccount" = "$${aws:PrincipalAccount}"
          }
        }
      },
      {
        Sid    = "ReadImageBuilderComponents"
        Effect = "Allow"
        Action = [
          "imagebuilder:GetComponent",
          "imagebuilder:GetMarketplaceResource",
        ]
        Resource = "*"
      },
      {
        Sid      = "DecryptOnlyImageBuilderContext"
        Effect   = "Allow"
        Action   = "kms:Decrypt"
        Resource = "*"
        Condition = {
          "ForAnyValue:StringEquals" = {
            "aws:CalledVia"            = ["imagebuilder.amazonaws.com"]
            "kms:EncryptionContextKeys" = "aws:imagebuilder:arn"
          }
        }
      },
      {
        Sid      = "ReadAwsImageBuilderInputs"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "arn:${data.aws_partition.current.partition}:s3:::ec2imagebuilder*"
      },
      {
        Sid      = "WriteOnlyImageBuilderLogs"
        Effect   = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "arn:${data.aws_partition.current.partition}:logs:*:*:log-group:/aws/imagebuilder/*"
      },
      {
        Sid      = "ReadExactJuncaBuildInputBucket"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = "arn:${data.aws_partition.current.partition}:s3:::junca-validator-ami-build-${var.aws_account_id}-*"
      },
      {
        Sid      = "ReadExactJuncaBuildInputs"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "arn:${data.aws_partition.current.partition}:s3:::junca-validator-ami-build-${var.aws_account_id}-*/*"
      },
      {
        Sid    = "ParameterFreeSsmManagedInstanceCore"
        Effect = "Allow"
        Action = [
          "ec2messages:AcknowledgeMessage",
          "ec2messages:DeleteMessage",
          "ec2messages:FailMessage",
          "ec2messages:GetEndpoint",
          "ec2messages:GetMessages",
          "ec2messages:SendReply",
          "ssm:DescribeAssociation",
          "ssm:DescribeDocument",
          "ssm:GetDeployablePatchSnapshotForInstance",
          "ssm:GetDocument",
          "ssm:GetManifest",
          "ssm:ListAssociations",
          "ssm:ListInstanceAssociations",
          "ssm:PutComplianceItems",
          "ssm:PutConfigurePackageResult",
          "ssm:PutInventory",
          "ssm:UpdateAssociationStatus",
          "ssm:UpdateInstanceAssociationStatus",
          "ssm:UpdateInstanceInformation",
          "ssmmessages:CreateControlChannel",
          "ssmmessages:CreateDataChannel",
          "ssmmessages:OpenControlChannel",
          "ssmmessages:OpenDataChannel",
        ]
        Resource = "*"
      },
    ]
  })

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role" "validator_image_builder" {
  name                 = "JuncaChainPublicTestnetImageBuilder"
  permissions_boundary = aws_iam_policy.validator_image_builder_boundary.arn

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "Ec2ImageBuilderAssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    RoleBoundary = "ImageBuilderInstance"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role_policy_attachment" "validator_image_builder_managed" {
  role       = aws_iam_role.validator_image_builder.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/EC2InstanceProfileForImageBuilder"
}

resource "aws_iam_role_policy_attachment" "validator_image_builder_ssm_managed" {
  role       = aws_iam_role.validator_image_builder.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "validator_image_builder_staging_read" {
  # Preserve exact immutable build-input access alongside the two
  # AWS-recommended Image Builder instance policies. Their live default
  # versions and document digests are blocking readbacks in the runbook.
  name = "JuncaValidatorImmutableInputRead"
  role = aws_iam_role.validator_image_builder.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadExactValidatorComponents"
        Effect   = "Allow"
        Action   = "imagebuilder:GetComponent"
        Resource = "arn:${data.aws_partition.current.partition}:imagebuilder:${var.aws_region}:${var.aws_account_id}:component/junca-validator-*/*"
      },
      {
        Sid      = "ListExactEphemeralBuildBuckets"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = "arn:${data.aws_partition.current.partition}:s3:::junca-validator-ami-build-${var.aws_account_id}-*"
      },
      {
        Sid      = "ReadImmutableBuildInputs"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "arn:${data.aws_partition.current.partition}:s3:::junca-validator-ami-build-${var.aws_account_id}-*/*"
      },
      {
        Sid    = "ImageBuilderSsmControlChannels"
        Effect = "Allow"
        Action = [
          "ec2messages:AcknowledgeMessage",
          "ec2messages:DeleteMessage",
          "ec2messages:FailMessage",
          "ec2messages:GetEndpoint",
          "ec2messages:GetMessages",
          "ec2messages:SendReply",
          "ssm:DescribeAssociation",
          "ssm:DescribeDocument",
          "ssm:GetDeployablePatchSnapshotForInstance",
          "ssm:GetDocument",
          "ssm:GetManifest",
          "ssm:ListAssociations",
          "ssm:ListInstanceAssociations",
          "ssm:PutComplianceItems",
          "ssm:PutConfigurePackageResult",
          "ssm:PutInventory",
          "ssm:UpdateAssociationStatus",
          "ssm:UpdateInstanceAssociationStatus",
          "ssm:UpdateInstanceInformation",
          "ssmmessages:CreateControlChannel",
          "ssmmessages:CreateDataChannel",
          "ssmmessages:OpenControlChannel",
          "ssmmessages:OpenDataChannel",
        ]
        Resource = "*"
      },
      {
        Sid    = "DenyImageBuilderKmsEscalation"
        Effect = "Deny"
        Action = [
          "kms:CreateGrant",
          "kms:CreateKey",
          "kms:PutKeyPolicy",
          "kms:ScheduleKeyDeletion",
          "kms:Sign",
        ]
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_instance_profile" "validator_image_builder" {
  name = "JuncaChainPublicTestnetImageBuilder"
  role = aws_iam_role.validator_image_builder.name

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role_policy" "ami_builder_controller" {
  name = "PublicTestnetImmutableAmiBuildOnly"
  role = aws_iam_role.ami_builder_controller.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CreateTaggedValidatorImageBuilderResources"
        Effect = "Allow"
        Action = [
          "imagebuilder:CreateComponent",
          "imagebuilder:CreateDistributionConfiguration",
          "imagebuilder:CreateImage",
          "imagebuilder:CreateImageRecipe",
          "imagebuilder:CreateInfrastructureConfiguration",
        ]
        Resource = local.image_builder_resource_arns
        Condition = {
          StringEquals = {
            "aws:RequestTag/Network" = local.public_testnet_network
            "aws:RequestedRegion"     = var.aws_region
          }
        }
      },
      {
        Sid    = "ReadExactValidatorImageBuilderResources"
        Effect = "Allow"
        Action = [
          "imagebuilder:GetComponent",
          "imagebuilder:GetDistributionConfiguration",
          "imagebuilder:GetImage",
          "imagebuilder:GetImageRecipe",
          "imagebuilder:GetInfrastructureConfiguration",
        ]
        Resource = local.image_builder_resource_arns
      },
      {
        Sid      = "ListValidatorImageBuildVersions"
        Effect   = "Allow"
        Action   = "imagebuilder:ListImageBuildVersions"
        Resource = "*"
      },
      {
        Sid      = "TagOnlyPublicTestnetImageBuilderResources"
        Effect   = "Allow"
        Action   = "imagebuilder:TagResource"
        Resource = local.image_builder_resource_arns
        Condition = {
          StringEquals = {
            "aws:ResourceTag/Network" = local.public_testnet_network
          }
        }
      },
      {
        Sid      = "ReadCanonicalBaseAndBuiltImages"
        Effect   = "Allow"
        Action   = "ec2:DescribeImages"
        Resource = "*"
      },
      {
        Sid      = "TagOnlyPublicTestnetBuiltImages"
        Effect   = "Allow"
        Action   = "ec2:CreateTags"
        Resource = "arn:${data.aws_partition.current.partition}:ec2:${var.aws_region}::image/ami-*"
        Condition = {
          StringEquals = {
            "ec2:ResourceTag/Network" = local.public_testnet_network
          }
        }
      },
      {
        Sid    = "ManageExactEphemeralBuildBuckets"
        Effect = "Allow"
        Action = [
          "s3:CreateBucket",
          "s3:DeleteBucket",
          "s3:DeleteBucketPolicy",
          "s3:GetBucketLocation",
          "s3:ListBucket",
          "s3:PutBucketPolicy",
          "s3:PutBucketPublicAccessBlock",
        ]
        Resource = "arn:${data.aws_partition.current.partition}:s3:::junca-validator-ami-build-${var.aws_account_id}-*"
      },
      {
        Sid    = "ManageExactEphemeralBuildObjects"
        Effect = "Allow"
        Action = [
          "s3:DeleteObject",
          "s3:GetObject",
          "s3:PutObject",
        ]
        Resource = "arn:${data.aws_partition.current.partition}:s3:::junca-validator-ami-build-${var.aws_account_id}-*/*"
      },
      {
        Sid      = "ReadExactImageBuilderProfile"
        Effect   = "Allow"
        Action   = "iam:GetInstanceProfile"
        Resource = aws_iam_instance_profile.validator_image_builder.arn
      },
      {
        Sid      = "CreateImageBuilderServiceRole"
        Effect   = "Allow"
        Action   = "iam:CreateServiceLinkedRole"
        Resource = "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:role/aws-service-role/imagebuilder.amazonaws.com/AWSServiceRoleForImageBuilder"
        Condition = {
          StringEquals = {
            "iam:AWSServiceName" = "imagebuilder.amazonaws.com"
          }
        }
      },
      {
        Sid      = "PassOnlyExactImageBuilderInstanceRole"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = aws_iam_role.validator_image_builder.arn
        Condition = {
          StringEquals = {
            "iam:PassedToService" = [
              "ec2.amazonaws.com",
              "imagebuilder.amazonaws.com",
            ]
          }
        }
      },
    ]
  })
}

resource "aws_iam_role_policy" "observer" {
  name = "PublicTestnetReadOnlyEvidence"
  role = aws_iam_role.observer.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ListExactCanonicalStateObjectsReadOnly"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.terraform_state.arn
        Condition = {
          StringEquals = {
            "s3:prefix" = [
              "public-testnet/terraform.tfstate",
            ]
          }
        }
      },
      {
        Sid      = "ReadCanonicalStateObjectsOnly"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = [
          "${aws_s3_bucket.terraform_state.arn}/public-testnet/terraform.tfstate",
        ]
      },
      {
        Sid    = "DecryptCanonicalStateOnly"
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey",
        ]
        Resource = aws_kms_key.terraform_state.arn
      },
      {
        Sid    = "ReadPublicTestnetEc2Evidence"
        Effect = "Allow"
        Action = [
          "ec2:DescribeAvailabilityZones",
          "ec2:DescribeImages",
          "ec2:DescribeInstances",
          "ec2:DescribeInstanceStatus",
          "ec2:DescribeSnapshots",
          "ec2:DescribeTags",
          "ec2:DescribeVolumes",
        ]
        Resource = "*"
      },
      {
        Sid      = "DiscoverCanonicalHostedZoneByName"
        Effect   = "Allow"
        Action   = "route53:ListHostedZonesByName"
        Resource = "*"
      },
      {
        Sid    = "ReadPublicTestnetTargetHealth"
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:DescribeLoadBalancers",
          "elasticloadbalancing:DescribeTags",
          "elasticloadbalancing:DescribeTargetGroups",
          "elasticloadbalancing:DescribeTargetHealth",
        ]
        Resource = "*"
      },
      {
        Sid    = "ReadCanonicalRoute53Only"
        Effect = "Allow"
        Action = [
          "route53:GetHostedZone",
          "route53:ListResourceRecordSets",
          "route53:ListTagsForResource",
        ]
        Resource = local.route53_hosted_zone_arn
      },
      {
        Sid      = "DescribePublicTestnetSignerKeys"
        Effect   = "Allow"
        Action   = "kms:DescribeKey"
        Resource = aws_kms_key.validator_signer[*].arn
      },
      {
        Sid      = "ReadCanonicalFoundationIdentity"
        Effect   = "Allow"
        Action   = "iam:GetRole"
        Resource = aws_iam_role.deployment.arn
      },
    ]
  })
}

# Exclusive relationship resources are the enforcement point for unmanaged
# policy residue. Security Bootstrap applies these reconciliations; no OIDC
# principal has permissions to attach, detach, create, or version policies.
resource "aws_iam_role_policies_exclusive" "foundation" {
  role_name = aws_iam_role.deployment.name
  policy_names = [
    aws_iam_role_policy.automation_self_mutation_deny["foundation"].name,
    aws_iam_role_policy.deployment_infrastructure.name,
    aws_iam_role_policy.deployment_runtime_acceptance.name,
    aws_iam_role_policy.deployment_self_permission_readback.name,
    aws_iam_role_policy.deployment_state.name,
  ]
}

resource "aws_iam_role_policy_attachments_exclusive" "foundation" {
  role_name = aws_iam_role.deployment.name
  policy_arns = [
    aws_iam_policy.deployment_edge.arn,
    aws_iam_policy.deployment_infrastructure_allow.arn,
    aws_iam_policy.deployment_infrastructure_mutation.arn,
    aws_iam_policy.deployment_observability.arn,
    aws_iam_policy.deployment_validator_pass.arn,
  ]
}

resource "aws_iam_role_policies_exclusive" "ami_builder" {
  role_name = aws_iam_role.ami_builder_controller.name
  policy_names = [
    aws_iam_role_policy.ami_builder_controller.name,
    aws_iam_role_policy.automation_self_mutation_deny["ami_builder"].name,
  ]
}

resource "aws_iam_role_policy_attachments_exclusive" "ami_builder" {
  role_name   = aws_iam_role.ami_builder_controller.name
  policy_arns = []
}

resource "aws_iam_role_policies_exclusive" "observer" {
  role_name = aws_iam_role.observer.name
  policy_names = [
    aws_iam_role_policy.automation_self_mutation_deny["observer"].name,
    aws_iam_role_policy.observer.name,
  ]
}

resource "aws_iam_role_policy_attachments_exclusive" "observer" {
  role_name   = aws_iam_role.observer.name
  policy_arns = []
}

resource "aws_iam_role_policies_exclusive" "image_builder_worker" {
  role_name = aws_iam_role.validator_image_builder.name
  policy_names = [
    aws_iam_role_policy.validator_image_builder_staging_read.name,
  ]
}

resource "aws_iam_role_policy_attachments_exclusive" "image_builder_worker" {
  role_name = aws_iam_role.validator_image_builder.name
  policy_arns = [
    aws_iam_role_policy_attachment.validator_image_builder_managed.policy_arn,
    aws_iam_role_policy_attachment.validator_image_builder_ssm_managed.policy_arn,
  ]
}

resource "aws_iam_role_policies_exclusive" "validator" {
  count = 3

  role_name = aws_iam_role.validator[count.index].name
  policy_names = [
    aws_iam_role_policy.validator_signer_boundary[count.index].name,
  ]
}

resource "aws_iam_role_policy_attachments_exclusive" "validator" {
  count = 3

  role_name = aws_iam_role.validator[count.index].name
  policy_arns = []
}
