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
