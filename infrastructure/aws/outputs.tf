output "deployment_state" {
  value = var.deployment_enabled ? "PLAN_AUTHORIZED" : "BLOCKED_FAIL_CLOSED"
}

output "registrar_delegation_boundary" {
  value = {
    registrar                    = "external"
    domain                       = var.root_domain
    route53_zone_id              = var.route53_zone_id
    nameserver_readback_required = true
  }
}

output "public_urls" {
  value = var.deployment_enabled ? {
    rpc      = "https://rpc.testnet.${var.root_domain}"
    explorer = "https://explorer.testnet.${var.root_domain}"
    health   = "https://health.testnet.${var.root_domain}"
  } : null
}

output "immutable_boundaries" {
  value = {
    mainnet_changed  = false
    assets_moved     = false
    bridge_activated = false
  }
}
