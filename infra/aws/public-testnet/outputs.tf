output "aws_account_id" {
  value = data.aws_caller_identity.current.account_id
}

output "region" {
  value = var.aws_region
}

output "availability_zones" {
  value = var.availability_zones
}


output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "validator_signer_readback" {
  value = [
    for signer in data.aws_kms_key.validator_signer : {
      arn                      = signer.arn
      key_usage                = signer.key_usage
      customer_master_key_spec = signer.customer_master_key_spec
      enabled                  = signer.enabled
    }
  ]
}

output "approved_node_ami_readback" {
  value = {
    id            = data.aws_ami.approved_node.id
    name          = data.aws_ami.approved_node.name
    creation_date = data.aws_ami.approved_node.creation_date
    owner_id      = data.aws_ami.approved_node.owner_id
  }
}

output "validator_instance_ids" {
  value = aws_instance.validator[*].id
}

output "public_rpc_url" {
  value = "https://${local.rpc_hostname}"
}

output "explorer_url" {
  value = "https://${local.explorer_hostname}"
}

output "health_url" {
  value = "https://${local.health_hostname}"
}

output "load_balancer_arn" {
  value = aws_lb.public.arn
}

output "runtime_boundary" {
  value = {
    governance       = "JAIOS Institutional Governance"
    notice           = "Public Testnet / No Monetary Value"
    mainnet_changed  = false
    assets_moved     = false
    bridge_activated = false
  }
}
