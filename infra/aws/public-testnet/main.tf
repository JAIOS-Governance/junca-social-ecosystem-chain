terraform {
  required_version = ">= 1.7.0"

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
      ManagedBy   = "Terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_route53_zone" "canonical" {
  zone_id      = var.route53_zone_id
  private_zone = false
}

data "aws_ami" "approved_node" {
  owners = ["self"]

  filter {
    name   = "image-id"
    values = [var.node_ami_id]
  }

  filter {
    name   = "state"
    values = ["available"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }

  filter {
    name   = "root-device-type"
    values = ["ebs"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  filter {
    name   = "tag:SourceCommit"
    values = [var.source_commit]
  }

  filter {
    name   = "tag:NodeArtifactSHA256"
    values = [var.node_artifact_sha256]
  }

  filter {
    name   = "tag:GenesisSHA256"
    values = [var.genesis_sha256]
  }

  filter {
    name   = "tag:Network"
    values = ["Public Testnet"]
  }

  filter {
    name   = "tag:Governance"
    values = ["JAIOS Institutional Governance"]
  }
}

data "aws_kms_key" "validator_signer" {
  count  = 3
  key_id = var.validator_signer_arns[count.index]
}

resource "terraform_data" "canonical_binding_gate" {
  lifecycle {
    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.aws_account_id
      error_message = "Authenticated AWS account does not match the canonical account binding."
    }
    precondition {
      condition     = trimsuffix(data.aws_route53_zone.canonical.name, ".") == var.domain_name
      error_message = "Route 53 hosted zone does not match the canonical domain binding."
    }
    precondition {
      condition     = length(toset(var.availability_zones)) == 3
      error_message = "Validator deployment requires three distinct availability zones."
    }
    precondition {
      condition     = var.deployment_principal_arn == "arn:aws:iam::${var.aws_account_id}:role/JuncaChainPublicTestnetDeployment"
      error_message = "Deployment principal must be the canonical dedicated Public Testnet role."
    }
    precondition {
      condition     = alltrue([for az in var.availability_zones : startswith(az, var.aws_region)])
      error_message = "All validator availability zones must belong to the canonical AWS region."
    }
    precondition {
      condition = (
        data.aws_ami.approved_node.id == var.node_ami_id &&
        data.aws_ami.approved_node.architecture == "x86_64" &&
        data.aws_ami.approved_node.root_device_type == "ebs" &&
        data.aws_ami.approved_node.virtualization_type == "hvm" &&
        data.aws_ami.approved_node.tags["SourceCommit"] == var.source_commit &&
        data.aws_ami.approved_node.tags["NodeArtifactSHA256"] == var.node_artifact_sha256 &&
        data.aws_ami.approved_node.tags["GenesisSHA256"] == var.genesis_sha256 &&
        data.aws_ami.approved_node.tags["Network"] == "Public Testnet" &&
        data.aws_ami.approved_node.tags["Governance"] == "JAIOS Institutional Governance"
      )
      error_message = "The approved AMI must be a self-owned available x86_64 EBS/HVM image whose immutable provenance tags exactly match the source commit, node artifact and genesis."
    }
    precondition {
      condition = (
        !var.enable_public_services ||
        (
          var.quorum_acceptance_sha256 != null &&
          var.runtime_acceptance_sha256 != null
        )
      )
      error_message = "Public RPC, Explorer, ALB and DNS remain fail-closed until both quorum and runtime acceptance evidence digests are supplied."
    }
    precondition {
      condition = alltrue([
        for signer in data.aws_kms_key.validator_signer :
        signer.key_usage == "SIGN_VERIFY" &&
        signer.customer_master_key_spec == "ECC_SECG_P256K1" &&
        signer.enabled
      ])
      error_message = "All three validator signers must be enabled SIGN_VERIFY ECC_SECG_P256K1 keys."
    }
  }
}

locals {
  name                  = "junca-social-ecosystem-chain-testnet"
  public_subnet_cidrs   = ["10.67.0.0/24", "10.67.1.0/24", "10.67.2.0/24"]
  private_subnet_cidrs  = ["10.67.16.0/20", "10.67.32.0/20", "10.67.48.0/20"]
  validator_private_ips = ["10.67.16.10", "10.67.32.10", "10.67.48.10"]
  rpc_hostname          = "rpc.${var.domain_name}"
  explorer_hostname     = "explorer.${var.domain_name}"
  scan_hostname         = "scan.${var.domain_name}"
  health_hostname       = "health.${var.domain_name}"
}

resource "aws_sns_topic" "validator_alerts" {
  name              = "${local.name}-validator-alerts"
  kms_master_key_id = "alias/aws/sns"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_acm_certificate" "public_services" {
  domain_name = local.rpc_hostname
  subject_alternative_names = [
    local.explorer_hostname,
    local.scan_hostname,
    local.health_hostname,
  ]
  validation_method = "DNS"

  options {
    certificate_transparency_logging_preference = "ENABLED"
  }

  lifecycle {
    create_before_destroy = true
    prevent_destroy       = true
  }
}

resource "aws_route53_record" "certificate_validation" {
  for_each = {
    for option in aws_acm_certificate.public_services.domain_validation_options :
    option.domain_name => {
      name   = option.resource_record_name
      record = option.resource_record_value
      type   = option.resource_record_type
    }
  }

  allow_overwrite = true
  zone_id         = var.route53_zone_id
  name            = each.value.name
  type            = each.value.type
  ttl             = 300
  records         = [each.value.record]
}

resource "aws_acm_certificate_validation" "public_services" {
  certificate_arn = aws_acm_certificate.public_services.arn
  validation_record_fqdns = [
    for record in aws_route53_record.certificate_validation :
    record.fqdn
  ]
}

resource "aws_vpc" "testnet" {
  cidr_block           = "10.67.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = local.name }
}

resource "aws_internet_gateway" "testnet" {
  vpc_id = aws_vpc.testnet.id
  tags   = { Name = local.name }
}

resource "aws_subnet" "public" {
  count                   = 3
  vpc_id                  = aws_vpc.testnet.id
  availability_zone       = var.availability_zones[count.index]
  cidr_block              = local.public_subnet_cidrs[count.index]
  map_public_ip_on_launch = false
  tags                    = { Name = "${local.name}-public-${count.index + 1}" }
}

resource "aws_subnet" "private" {
  count             = 3
  vpc_id            = aws_vpc.testnet.id
  availability_zone = var.availability_zones[count.index]
  cidr_block        = local.private_subnet_cidrs[count.index]
  tags              = { Name = "${local.name}-private-${count.index + 1}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.testnet.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.testnet.id
  }
}

resource "aws_route_table_association" "public" {
  count          = 3
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "validator" {
  name        = "${local.name}-validator"
  description = "Private validator P2P only"
  vpc_id      = aws_vpc.testnet.id

  ingress {
    description = "Validator P2P quorum"
    protocol    = "tcp"
    from_port   = 30303
    to_port     = 30303
    self        = true
  }

  ingress {
    description     = "Read-only public RPC from TLS gateway"
    protocol        = "tcp"
    from_port       = 8546
    to_port         = 8546
    security_groups = var.enable_public_services ? [aws_security_group.public_alb[0].id] : []
  }

  ingress {
    description     = "Finalized-only explorer from TLS gateway"
    protocol        = "tcp"
    from_port       = 3000
    to_port         = 3000
    security_groups = var.enable_public_services ? [aws_security_group.public_alb[0].id] : []
  }

  egress {
    description = "AWS private endpoints and validator quorum"
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = [aws_vpc.testnet.cidr_block]
  }
}

resource "aws_security_group" "public_alb" {
  count = var.enable_public_services ? 1 : 0

  name   = "${local.name}-public-alb"
  vpc_id = aws_vpc.testnet.id

  ingress {
    description = "Public HTTPS"
    protocol    = "tcp"
    from_port   = 443
    to_port     = 443
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    protocol    = "tcp"
    from_port   = 0
    to_port     = 65535
    cidr_blocks = [aws_vpc.testnet.cidr_block]
  }
}

resource "aws_security_group" "endpoints" {
  name   = "${local.name}-endpoints"
  vpc_id = aws_vpc.testnet.id

  ingress {
    protocol        = "tcp"
    from_port       = 443
    to_port         = 443
    security_groups = [aws_security_group.validator.id]
  }
}

resource "aws_vpc_endpoint" "aws_services" {
  for_each = toset(["kms", "logs", "monitoring", "ssm", "ssmmessages", "ec2messages"])

  vpc_id              = aws_vpc.testnet.id
  service_name        = "com.amazonaws.${var.aws_region}.${each.value}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true
}

resource "aws_iam_role" "validator" {
  count = 3
  name  = "${local.name}-validator-${count.index + 1}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
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
        Action   = ["kms:Sign"]
        Resource = var.validator_signer_arns[count.index]
      },
      {
        Sid      = "VerifyValidatorQuorum"
        Effect   = "Allow"
        Action   = ["kms:GetPublicKey", "kms:Verify", "kms:DescribeKey"]
        Resource = var.validator_signer_arns
      },
      {
        Sid      = "WriteOperationalTelemetry"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents", "cloudwatch:PutMetricData"]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "validator_ssm" {
  count      = 3
  role       = aws_iam_role.validator[count.index].name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "validator" {
  count = 3
  name  = "${local.name}-validator-${count.index + 1}"
  role  = aws_iam_role.validator[count.index].name
}

resource "aws_cloudwatch_log_group" "validator" {
  name              = "/junca/social-ecosystem-chain/public-testnet/validator"
  retention_in_days = 90
}

resource "aws_instance" "validator" {
  count = 3

  ami                         = var.node_ami_id
  instance_type               = var.validator_instance_type
  subnet_id                   = aws_subnet.private[count.index].id
  private_ip                  = local.validator_private_ips[count.index]
  vpc_security_group_ids      = [aws_security_group.validator.id]
  associate_public_ip_address = false
  iam_instance_profile        = aws_iam_instance_profile.validator[count.index].name
  monitoring                  = true

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  root_block_device {
    encrypted   = true
    volume_type = "gp3"
    volume_size = 200
    iops        = 6000
    throughput  = 250
  }

  user_data = templatefile("${path.module}/templates/validator-user-data.sh.tftpl", {
    validator_id   = format("validator-%02d", count.index + 1)
    chain_id       = var.chain_id
    genesis_sha256 = var.genesis_sha256
    node_sha256    = var.node_artifact_sha256
    signer_arn     = var.validator_signer_arns[count.index]
    aws_region     = var.aws_region
    signer_bindings = join(",", [
      for index, arn in var.validator_signer_arns :
      format("validator-%02d=%s", index + 1, arn)
    ])
    peer_endpoints = join(",", [
      for index, address in local.validator_private_ips :
      format("validator-%02d=%s:30303", index + 1, address)
    ])
    cloudwatch_log_name = aws_cloudwatch_log_group.validator.name
  })

  lifecycle {
    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.aws_account_id
      error_message = "AWS account binding mismatch."
    }
  }

  tags = {
    Name          = format("${local.name}-validator-%02d", count.index + 1)
    Validator     = format("%02d", count.index + 1)
    FailureDomain = var.availability_zones[count.index]
    PublicRPC     = "false"
  }
}

resource "aws_lb" "public" {
  count = var.enable_public_services ? 1 : 0

  name                       = "junca-testnet-public"
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.public_alb[0].id]
  subnets                    = aws_subnet.public[*].id
  enable_deletion_protection = true
  drop_invalid_header_fields = true
}

resource "aws_lb_target_group" "rpc" {
  count = var.enable_public_services ? 1 : 0

  name     = "junca-testnet-rpc"
  port     = 8546
  protocol = "HTTP"
  vpc_id   = aws_vpc.testnet.id
  health_check { path = "/health" }
}

resource "aws_lb_target_group_attachment" "rpc" {
  count            = var.enable_public_services ? 3 : 0
  target_group_arn = aws_lb_target_group.rpc[0].arn
  target_id        = aws_instance.validator[count.index].id
  port             = 8546
}

resource "aws_lb_target_group" "explorer" {
  count = var.enable_public_services ? 1 : 0

  name     = "junca-testnet-explorer"
  port     = 3000
  protocol = "HTTP"
  vpc_id   = aws_vpc.testnet.id
  health_check { path = "/health" }
}

resource "aws_lb_target_group_attachment" "explorer" {
  count            = var.enable_public_services ? 3 : 0
  target_group_arn = aws_lb_target_group.explorer[0].arn
  target_id        = aws_instance.validator[count.index].id
  port             = 3000
}

resource "aws_wafv2_web_acl" "public" {
  count = var.enable_public_services ? 1 : 0

  name  = "junca-testnet-public"
  scope = "REGIONAL"

  default_action {
    allow {}
  }

  rule {
    name     = "PerIpRateLimit"
    priority = 1
    action {
      block {}
    }
    statement {
      rate_based_statement {
        aggregate_key_type = "IP"
        limit              = 1200
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "JuncaTestnetPerIpRateLimit"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "JuncaTestnetPublic"
    sampled_requests_enabled   = true
  }
}

resource "aws_wafv2_web_acl_association" "public" {
  count = var.enable_public_services ? 1 : 0

  resource_arn = aws_lb.public[0].arn
  web_acl_arn  = aws_wafv2_web_acl.public[0].arn
}

resource "aws_lb_listener" "https" {
  count = var.enable_public_services ? 1 : 0

  load_balancer_arn = aws_lb.public[0].arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.public_services.certificate_arn

  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "application/json"
      message_body = "{\"error\":\"unknown host\"}"
      status_code  = "404"
    }
  }
}

resource "aws_lb_listener_rule" "rpc" {
  count = var.enable_public_services ? 1 : 0

  listener_arn = aws_lb_listener.https[0].arn
  priority     = 10
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.rpc[0].arn
  }
  condition {
    host_header {
      values = [local.rpc_hostname, local.health_hostname]
    }
  }
}

resource "aws_lb_listener_rule" "explorer" {
  count = var.enable_public_services ? 1 : 0

  listener_arn = aws_lb_listener.https[0].arn
  priority     = 20
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.explorer[0].arn
  }
  condition {
    host_header {
      values = [local.explorer_hostname, local.scan_hostname]
    }
  }
}

resource "aws_route53_record" "public" {
  for_each = var.enable_public_services ? toset([
    local.rpc_hostname,
    local.explorer_hostname,
    local.scan_hostname,
    local.health_hostname,
  ]) : toset([])

  zone_id = var.route53_zone_id
  name    = each.value
  type    = "A"

  alias {
    name                   = aws_lb.public[0].dns_name
    zone_id                = aws_lb.public[0].zone_id
    evaluate_target_health = true
  }
}

resource "aws_cloudwatch_metric_alarm" "validator_status" {
  count = 3

  alarm_name          = "${local.name}-validator-${count.index + 1}-status"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2
  metric_name         = "StatusCheckFailed"
  namespace           = "AWS/EC2"
  period              = 60
  statistic           = "Maximum"
  threshold           = 1
  alarm_actions       = [aws_sns_topic.validator_alerts.arn]
  dimensions          = { InstanceId = aws_instance.validator[count.index].id }
}
