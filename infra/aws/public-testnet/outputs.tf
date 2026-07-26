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
    id                  = data.aws_ami.approved_node.id
    name                = data.aws_ami.approved_node.name
    creation_date       = data.aws_ami.approved_node.creation_date
    owner_id            = data.aws_ami.approved_node.owner_id
    architecture        = data.aws_ami.approved_node.architecture
    root_device_type    = data.aws_ami.approved_node.root_device_type
    virtualization_type = data.aws_ami.approved_node.virtualization_type
    source_commit       = data.aws_ami.approved_node.tags["SourceCommit"]
    node_sha256         = data.aws_ami.approved_node.tags["NodeArtifactSHA256"]
    genesis_sha256      = data.aws_ami.approved_node.tags["GenesisSHA256"]
    network             = data.aws_ami.approved_node.tags["Network"]
    governance          = data.aws_ami.approved_node.tags["Governance"]
  }
}

output "validator_instance_ids" {
  value = aws_instance.validator[*].id
}

output "public_rpc_url" {
  value = var.enable_public_services ? "https://${local.rpc_hostname}" : null
}

output "explorer_url" {
  value = var.enable_public_services ? "https://${local.explorer_hostname}" : null
}

output "health_url" {
  value = var.enable_public_services ? "https://${local.health_hostname}" : null
}

output "load_balancer_arn" {
  value = try(aws_lb.public[0].arn, null)
}

output "public_services_certificate" {
  value = {
    arn                  = aws_acm_certificate_validation.public_services.certificate_arn
    domain_name          = aws_acm_certificate.public_services.domain_name
    subject_alternatives = aws_acm_certificate.public_services.subject_alternative_names
    validation_method    = aws_acm_certificate.public_services.validation_method
    validation_record_fqdns = [
      for record in aws_route53_record.certificate_validation :
      record.fqdn
    ]
  }
}

output "validator_alert_topic_arn" {
  value = aws_sns_topic.validator_alerts.arn
}

output "deployment_stage" {
  value = var.enable_public_services ? "public-services" : "validators-only"
}

output "public_services_acceptance_readback" {
  value = {
    enabled                   = var.enable_public_services
    quorum_evidence_sha256    = var.quorum_acceptance_sha256
    runtime_evidence_sha256   = var.runtime_acceptance_sha256
    acceptance_evidence_bound = var.quorum_acceptance_sha256 != null && var.runtime_acceptance_sha256 != null
  }
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
