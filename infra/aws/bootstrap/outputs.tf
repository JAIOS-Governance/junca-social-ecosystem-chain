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
  value = aws_iam_role.deployment.arn
}

output "validator_signer_arns" {
  description = "Three isolated asymmetric validator signer ARNs."
  value       = aws_kms_key.validator_signer[*].arn
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
  }
}
