output "aws_account_id" {
  value = data.aws_caller_identity.current.account_id
}

output "region" {
  value = var.aws_region
}

output "availability_zones" {
  value = var.availability_zones
}

output "validator_instance_ids" {
  value = aws_instance.validator[*].id
}
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
