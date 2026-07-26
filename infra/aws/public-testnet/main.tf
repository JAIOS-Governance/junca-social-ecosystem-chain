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
      condition     = data.aws_ami.approved_node.id == var.node_ami_id
      error_message = "The approved immutable node AMI must exist in the canonical account and be available."
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
  name                 = "junca-social-ecosystem-chain-testnet"
  public_subnet_cidrs  = ["10.67.0.0/24", "10.67.1.0/24", "10.67.2.0/24"]
  private_subnet_cidrs = ["10.67.16.0/20", "10.67.32.0/20", "10.67.48.0/20"]
  rpc_hostname         = "rpc.${var.domain_name}"
  explorer_hostname    = "explorer.${var.domain_name}"
  health_hostname      = "health.${var.domain_name}"
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

resource "aws_security_group" "read_only_services" {
  count = var.enable_public_services ? 1 : 0

  name   = "${local.name}-read-only-services"
  vpc_id = aws_vpc.testnet.id

  ingress {
    description     = "RPC from TLS gateway"
    protocol        = "tcp"
    from_port       = 8545
    to_port         = 8545
    security_groups = [aws_security_group.public_alb[0].id]
  }

  ingress {
    description     = "Explorer from TLS gateway"
    protocol        = "tcp"
    from_port       = 3000
    to_port         = 3000
    security_groups = [aws_security_group.public_alb[0].id]
  }

  ingress {
    description     = "Health from TLS gateway"
    protocol        = "tcp"
    from_port       = 8080
    to_port         = 8080
    security_groups = [aws_security_group.public_alb[0].id]
  }

  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = [aws_vpc.testnet.cidr_block]
  }
}

resource "aws_security_group" "endpoints" {
  name   = "${local.name}-endpoints"
  vpc_id = aws_vpc.testnet.id

  ingress {
    protocol  = "tcp"
    from_port = 443
    to_port   = 443
    security_groups = concat(
      [aws_security_group.validator.id],
      var.enable_public_services ? [aws_security_group.read_only_services[0].id] : [],
    )
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
        Action   = ["kms:GetPublicKey", "kms:Sign", "kms:DescribeKey"]
        Resource = var.validator_signer_arns[count.index]
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
    validator_id        = format("validator-%02d", count.index + 1)
    chain_id            = var.chain_id
    genesis_sha256      = var.genesis_sha256
    node_sha256         = var.node_artifact_sha256
    signer_arn          = var.validator_signer_arns[count.index]
    cloudwatch_log_name = aws_cloudwatch_log_group.validator.name
  })

  lifecycle {
    create_before_destroy = true
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

resource "aws_iam_role" "read_only" {
  count = var.enable_public_services ? 1 : 0

  name = "${local.name}-read-only"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_instance_profile" "read_only" {
  count = var.enable_public_services ? 1 : 0

  name = "${local.name}-read-only"
  role = aws_iam_role.read_only[0].name
}

resource "aws_instance" "rpc" {
  count = var.enable_public_services ? 2 : 0

  ami                         = var.node_ami_id
  instance_type               = var.rpc_instance_type
  subnet_id                   = aws_subnet.private[count.index].id
  vpc_security_group_ids      = [aws_security_group.read_only_services[0].id]
  associate_public_ip_address = false
  iam_instance_profile        = aws_iam_instance_profile.read_only[0].name
  monitoring                  = true

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  root_block_device {
    encrypted   = true
    volume_type = "gp3"
    volume_size = 200
  }

  tags = {
    Name      = format("${local.name}-rpc-%02d", count.index + 1)
    PublicRPC = "gateway-only"
    UnsafeRPC = "denied"
  }
}

resource "aws_instance" "explorer" {
  count = var.enable_public_services ? 2 : 0

  ami                         = var.node_ami_id
  instance_type               = var.explorer_instance_type
  subnet_id                   = aws_subnet.private[count.index + 1].id
  vpc_security_group_ids      = [aws_security_group.read_only_services[0].id]
  associate_public_ip_address = false
  iam_instance_profile        = aws_iam_instance_profile.read_only[0].name
  monitoring                  = true

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  root_block_device {
    encrypted   = true
    volume_type = "gp3"
    volume_size = 300
  }

  tags = {
    Name          = format("${local.name}-explorer-%02d", count.index + 1)
    FinalizedOnly = "true"
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
  port     = 8545
  protocol = "HTTP"
  vpc_id   = aws_vpc.testnet.id
  health_check { path = "/health" }
}

resource "aws_lb_target_group_attachment" "rpc" {
  count            = var.enable_public_services ? 2 : 0
  target_group_arn = aws_lb_target_group.rpc[0].arn
  target_id        = aws_instance.rpc[count.index].id
  port             = 8545
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
  count            = var.enable_public_services ? 2 : 0
  target_group_arn = aws_lb_target_group.explorer[0].arn
  target_id        = aws_instance.explorer[count.index].id
  port             = 3000
}

resource "aws_lb_listener" "https" {
  count = var.enable_public_services ? 1 : 0

  load_balancer_arn = aws_lb.public[0].arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

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
      values = [local.explorer_hostname]
    }
  }
}

resource "aws_route53_record" "public" {
  for_each = var.enable_public_services ? toset([
    local.rpc_hostname,
    local.explorer_hostname,
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
  alarm_actions       = [var.alert_topic_arn]
  dimensions          = { InstanceId = aws_instance.validator[count.index].id }
}
