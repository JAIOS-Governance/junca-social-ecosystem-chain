terraform {
  required_version = ">= 1.7.0"

  # Created with -backend=false, then migrated immediately after the guarded
  # bootstrap apply so the local bootstrap state is never the durable source.
  backend "s3" {}

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
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

resource "terraform_data" "account_gate" {
  lifecycle {
    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.aws_account_id
      error_message = "Authenticated AWS account does not match the approved account binding."
    }
  }
}

resource "aws_kms_key" "terraform_state" {
  description             = "JUNCA Social Ecosystem Chain public testnet Terraform state"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  lifecycle {
    prevent_destroy = true
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
    bucket_key_enabled = true
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
    Statement = [{
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
    }]
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
}

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [var.github_oidc_thumbprint]

  lifecycle {
    ignore_changes = [tags, tags_all]
  }
}

resource "aws_iam_role" "deployment" {
  name                 = "JuncaChainPublicTestnetDeployment"
  max_session_duration = 3600

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "GitHubRepositoryOIDC"
      Effect = "Allow"
      Principal = {
        Federated = aws_iam_openid_connect_provider.github.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = [
            "repo:JAIOS-Governance@308604370/junca-social-ecosystem-chain@1310568313:ref:refs/heads/main",
            "repo:JAIOS-Governance@308604370/junca-social-ecosystem-chain@1310568313:environment:public-testnet"
          ]
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "deployment_state" {
  name = "CanonicalTerraformState"
  role = aws_iam_role.deployment.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ListStateBucket"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.terraform_state.arn
      },
      {
        Sid      = "UseStateObjects"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = "${aws_s3_bucket.terraform_state.arn}/public-testnet/*"
      },
      {
        Sid      = "UseStateLock"
        Effect   = "Allow"
        Action   = ["dynamodb:DescribeTable", "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]
        Resource = aws_dynamodb_table.terraform_lock.arn
      },
      {
        Sid      = "UseStateEncryption"
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
        Resource = aws_kms_key.terraform_state.arn
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
      Sid      = "SimulateCanonicalDeploymentRoleOnly"
      Effect   = "Allow"
      Action   = "iam:SimulatePrincipalPolicy"
      Resource = aws_iam_role.deployment.arn
    }]
  })
}

resource "aws_iam_role_policy" "deployment_infrastructure" {
  name = "PublicTestnetInfrastructure"
  role = aws_iam_role.deployment.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "ManageTaggedPublicTestnetInfrastructure"
      Effect = "Allow"
      Action = [
        "ec2:*",
        "elasticloadbalancing:*",
        "route53:ChangeResourceRecordSets",
        "route53:GetChange",
        "route53:GetHostedZone",
        "route53:ListHostedZones",
        "route53:ListResourceRecordSets",
        "acm:AddTagsToCertificate",
        "acm:DeleteCertificate",
        "acm:DescribeCertificate",
        "acm:ListTagsForCertificate",
        "acm:RequestCertificate",
        "acm:RemoveTagsFromCertificate",
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:GetRole",
        "iam:ListAttachedRolePolicies",
        "iam:ListInstanceProfilesForRole",
        "iam:ListRolePolicies",
        "iam:TagRole",
        "iam:UntagRole",
        "iam:UpdateAssumeRolePolicy",
        "iam:CreatePolicy",
        "iam:DeletePolicy",
        "iam:GetPolicy",
        "iam:GetPolicyVersion",
        "iam:CreatePolicyVersion",
        "iam:DeletePolicyVersion",
        "iam:AttachRolePolicy",
        "iam:DetachRolePolicy",
        "iam:PutRolePolicy",
        "iam:GetRolePolicy",
        "iam:DeleteRolePolicy",
        "iam:CreateInstanceProfile",
        "iam:DeleteInstanceProfile",
        "iam:GetInstanceProfile",
        "iam:AddRoleToInstanceProfile",
        "iam:RemoveRoleFromInstanceProfile",
        "iam:TagInstanceProfile",
        "iam:UntagInstanceProfile",
        "iam:PassRole",
        "logs:*",
        "cloudwatch:*",
        "sns:CreateTopic",
        "sns:DeleteTopic",
        "sns:GetTopicAttributes",
        "sns:ListTagsForResource",
        "sns:SetTopicAttributes",
        "sns:TagResource",
        "sns:UntagResource"
      ]
      Resource = "*"
      Condition = {
        StringEqualsIfExists = {
          "aws:ResourceTag/Project" = "JUNCA Social Ecosystem Chain"
        }
      }
    }]
  })
}

resource "aws_iam_role" "validator_image_builder" {
  name = "JuncaChainPublicTestnetImageBuilder"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "Ec2ImageBuilderAssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

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
  name = "JuncaValidatorImmutableInputRead"
  role = aws_iam_role.validator_image_builder.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
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
      }
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

resource "aws_iam_role_policy" "deployment_ami_build" {
  name = "PublicTestnetImmutableAmiBuild"
  role = aws_iam_role.deployment.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ManagePublicTestnetImageBuild"
        Effect = "Allow"
        Action = [
          "imagebuilder:CreateComponent",
          "imagebuilder:CreateDistributionConfiguration",
          "imagebuilder:CreateImage",
          "imagebuilder:CreateImageRecipe",
          "imagebuilder:CreateInfrastructureConfiguration",
          "imagebuilder:GetComponent",
          "imagebuilder:GetDistributionConfiguration",
          "imagebuilder:GetImage",
          "imagebuilder:GetImageRecipe",
          "imagebuilder:GetInfrastructureConfiguration",
          "imagebuilder:ListImageBuildVersions",
          "imagebuilder:TagResource"
        ]
        Resource = "*"
      },
      {
        Sid      = "ReadCanonicalBaseImageAndAmi"
        Effect   = "Allow"
        Action   = ["ec2:DescribeImages", "ssm:GetParameter"]
        Resource = "*"
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
          "s3:PutBucketPublicAccessBlock"
        ]
        Resource = "arn:${data.aws_partition.current.partition}:s3:::junca-validator-ami-build-${var.aws_account_id}-*"
      },
      {
        Sid      = "ManageImmutableBuildInputs"
        Effect   = "Allow"
        Action   = ["s3:DeleteObject", "s3:GetObject", "s3:PutObject"]
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
        Sid      = "PassExactImageBuilderRole"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = aws_iam_role.validator_image_builder.arn
        Condition = {
          StringEquals = {
            "iam:PassedToService" = [
              "imagebuilder.amazonaws.com",
              "ec2.amazonaws.com"
            ]
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "deployment_runtime_acceptance" {
  name = "PublicTestnetRuntimeAcceptance"
  role = aws_iam_role.deployment.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "RunValidatorAcceptanceViaSsm"
      Effect = "Allow"
      Action = [
        "ssm:DescribeInstanceInformation",
        "ssm:GetCommandInvocation",
        "ssm:ListCommandInvocations",
        "ssm:SendCommand"
      ]
      Resource = "*"
    }]
  })
}
