terraform {
  backend "s3" {
    # Values are injected only after canonical AWS readback:
    # bucket         = exact dedicated state bucket
    # key            = "public-testnet/terraform.tfstate"
    # region         = exact canonical region
    # dynamodb_table = exact locking table
    # encrypt        = true
    # kms_key_id     = exact state-encryption KMS ARN
    # role_arn       = exact deployment principal ARN
  }
}
