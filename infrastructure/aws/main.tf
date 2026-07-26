locals {
  create = var.deployment_enabled ? 1 : 0
  validators = var.deployment_enabled ? {
    validator-01 = 0
    validator-02 = 1
    validator-03 = 2
  } : {}
  tags = {
    Chain       = "JUNCA Social Ecosystem Chain"
    Governance  = "JAIOS Institutional Governance"
    Network     = "Public Testnet / No Monetary Value"
    Mainnet     = "false"
    AssetsMoved = "false"
    Bridge      = "paused"
  }
  unsafe_rpc_methods = join(",", [
    "admin_*", "debug_*", "personal_*", "miner_*",
    "eth_sendRawTransaction", "eth_sendTransaction"
  ])
}

data "aws_subnet" "private" {
  for_each = var.deployment_enabled ? toset(var.private_subnet_ids) : toset([])
  id       = each.value
}

check "three_failure_domains" {
  assert {
    condition = !var.deployment_enabled || (
      length(toset([for subnet in data.aws_subnet.private : subnet.availability_zone])) == 3
    )
    error_message = "Validators require three independently read back Availability Zones."
  }
}

resource "aws_cloudwatch_log_group" "chain" {
  count             = local.create
  name              = "/junca-social-ecosystem-chain/public-testnet"
  retention_in_days = 90
}

resource "aws_security_group" "validator" {
  count       = local.create
  name_prefix = "junca-validator-"
  description = "Validator P2P only; JSON-RPC is loopback/private"
  vpc_id      = var.vpc_id

  ingress {
    description = "Validator P2P"
    from_port   = 30303
    to_port     = 30303
    protocol    = "tcp"
    self        = true
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_iam_role" "validator" {
  for_each = local.validators
  name     = "junca-public-testnet-${each.key}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "validator_signer" {
  for_each = local.validators
  role     = aws_iam_role.validator[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["kms:GetPublicKey", "kms:Sign", "kms:DescribeKey"]
      Resource = var.validator_signer_kms_key_arns[each.value]
    }]
  })
}

resource "aws_iam_instance_profile" "validator" {
  for_each = local.validators
  name     = "junca-public-testnet-${each.key}"
  role     = aws_iam_role.validator[each.key].name
}

resource "aws_instance" "validator" {
  for_each                    = local.validators
  ami                         = var.validator_ami_id
  instance_type               = var.validator_instance_type
  subnet_id                   = var.private_subnet_ids[each.value]
  vpc_security_group_ids      = [aws_security_group.validator[0].id]
  iam_instance_profile        = aws_iam_instance_profile.validator[each.key].name
  associate_public_ip_address = false
  monitoring                  = true

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  root_block_device {
    encrypted   = true
    volume_size = var.validator_volume_size_gib
    volume_type = "gp3"
    tags = {
      Backup = "junca-public-testnet"
    }
  }

  user_data = templatefile("${path.module}/validator-user-data.sh.tftpl", {
    validator_name = each.key
    signer_key_arn = var.validator_signer_kms_key_arns[each.value]
    genesis_sha256 = var.genesis_sha256
    binary_sha256  = var.binary_sha256
    runtime_contract = var.validator_runtime_contract
  })
  user_data_replace_on_change = true

  tags = { Name = each.key }

  lifecycle {
    precondition {
      condition     = !var.deployment_enabled || var.validator_signer_kms_key_arns[each.value] != ""
      error_message = "External signer resource readback is mandatory."
    }
  }
}

resource "aws_lb" "p2p" {
  count              = local.create
  name               = "junca-testnet-p2p"
  internal           = true
  load_balancer_type = "network"
  subnets            = var.private_subnet_ids
}

resource "aws_lb_target_group" "p2p" {
  count       = local.create
  name        = "junca-testnet-p2p"
  port        = 30303
  protocol    = "TCP"
  vpc_id      = var.vpc_id
  target_type = "instance"
}

resource "aws_lb_target_group_attachment" "p2p" {
  for_each         = local.validators
  target_group_arn = aws_lb_target_group.p2p[0].arn
  target_id        = aws_instance.validator[each.key].id
  port             = 30303
}

resource "aws_lb_listener" "p2p" {
  count             = local.create
  load_balancer_arn = aws_lb.p2p[0].arn
  port              = 30303
  protocol          = "TCP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.p2p[0].arn
  }
}

resource "aws_security_group" "public_service" {
  count       = local.create
  name_prefix = "junca-public-service-"
  vpc_id      = var.vpc_id
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "service_tasks" {
  count       = local.create
  name_prefix = "junca-service-tasks-"
  vpc_id      = var.vpc_id
  ingress {
    from_port       = 8545
    to_port         = 8545
    protocol        = "tcp"
    security_groups = [aws_security_group.public_service[0].id]
  }
  ingress {
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [aws_security_group.public_service[0].id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_acm_certificate" "public" {
  count             = local.create
  domain_name       = "rpc.testnet.${var.root_domain}"
  validation_method = "DNS"
  subject_alternative_names = [
    "explorer.testnet.${var.root_domain}",
    "health.testnet.${var.root_domain}"
  ]
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "certificate_validation" {
  for_each = var.deployment_enabled ? {
    for option in aws_acm_certificate.public[0].domain_validation_options :
    option.domain_name => {
      name   = option.resource_record_name
      record = option.resource_record_value
      type   = option.resource_record_type
    }
  } : {}
  zone_id = var.route53_zone_id
  name    = each.value.name
  type    = each.value.type
  ttl     = 300
  records = [each.value.record]
}

resource "aws_acm_certificate_validation" "public" {
  count                   = local.create
  certificate_arn         = aws_acm_certificate.public[0].arn
  validation_record_fqdns = [for record in aws_route53_record.certificate_validation : record.fqdn]
}

resource "aws_lb" "public" {
  count                      = local.create
  name                       = "junca-public-testnet"
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.public_service[0].id]
  subnets                    = var.public_subnet_ids
  drop_invalid_header_fields = true
}

resource "aws_ecs_cluster" "public" {
  count = local.create
  name  = "junca-public-testnet"
}

resource "aws_iam_role" "ecs_execution" {
  count = local.create
  name  = "junca-public-testnet-ecs-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  count      = local.create
  role       = aws_iam_role.ecs_execution[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_ecs_task_definition" "rpc" {
  count                    = local.create
  family                   = "junca-readonly-rpc"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.rpc_cpu
  memory                   = var.rpc_memory
  execution_role_arn       = aws_iam_role.ecs_execution[0].arn
  container_definitions = jsonencode([{
    name         = "readonly-rpc"
    image        = var.rpc_gateway_image
    portMappings = [{ containerPort = 8545 }]
    environment = [
      { name = "CHAIN_NAME", value = "JUNCA Social Ecosystem Chain" },
      { name = "NETWORK_NOTICE", value = "Public Testnet / No Monetary Value" },
      { name = "READ_ONLY", value = "true" },
      { name = "DENY_METHODS", value = local.unsafe_rpc_methods }
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.chain[0].name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "rpc"
      }
    }
  }])
}

resource "aws_lb_target_group" "rpc" {
  count       = local.create
  name        = "junca-readonly-rpc"
  port        = 8545
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"
  health_check {
    path    = "/health"
    matcher = "200"
  }
}

resource "aws_ecs_service" "rpc" {
  count           = local.create
  name            = "junca-readonly-rpc"
  cluster         = aws_ecs_cluster.public[0].id
  task_definition = aws_ecs_task_definition.rpc[0].arn
  desired_count   = var.rpc_desired_count
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.service_tasks[0].id]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.rpc[0].arn
    container_name   = "readonly-rpc"
    container_port   = 8545
  }
  depends_on = [aws_lb_listener.public]
}

resource "aws_ecs_task_definition" "explorer" {
  count                    = local.create
  family                   = "junca-finalized-explorer"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.explorer_cpu
  memory                   = var.explorer_memory
  execution_role_arn       = aws_iam_role.ecs_execution[0].arn
  container_definitions = jsonencode([{
    name         = "finalized-explorer"
    image        = var.explorer_image
    portMappings = [{ containerPort = 8080 }]
    environment = [
      { name = "FINALIZED_INDEX_ONLY", value = "true" },
      { name = "NETWORK_NOTICE", value = "Public Testnet / No Monetary Value" }
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.chain[0].name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "explorer"
      }
    }
  }])
}

resource "aws_lb_target_group" "explorer" {
  count       = local.create
  name        = "junca-finalized-explorer"
  port        = 8080
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"
  health_check {
    path    = "/health"
    matcher = "200"
  }
}

resource "aws_ecs_service" "explorer" {
  count           = local.create
  name            = "junca-finalized-explorer"
  cluster         = aws_ecs_cluster.public[0].id
  task_definition = aws_ecs_task_definition.explorer[0].arn
  desired_count   = var.explorer_desired_count
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.service_tasks[0].id]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.explorer[0].arn
    container_name   = "finalized-explorer"
    container_port   = 8080
  }
  depends_on = [aws_lb_listener.public]
}

resource "aws_lb_listener" "public" {
  count             = local.create
  load_balancer_arn = aws_lb.public[0].arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.public[0].certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.rpc[0].arn
  }
}

resource "aws_lb_listener_rule" "explorer" {
  count        = local.create
  listener_arn = aws_lb_listener.public[0].arn
  priority     = 10
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.explorer[0].arn
  }
  condition {
    host_header {
      values = ["explorer.testnet.${var.root_domain}"]
    }
  }
}

resource "aws_wafv2_web_acl" "public" {
  count = local.create
  name  = "junca-public-testnet"
  scope = "REGIONAL"
  default_action {
    allow {}
  }
  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "junca-public-testnet"
    sampled_requests_enabled   = true
  }
  rule {
    name     = "rate-limit"
    priority = 1
    action {
      block {}
    }
    statement {
      rate_based_statement {
        aggregate_key_type = "IP"
        limit              = 600
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "junca-rate-limit"
      sampled_requests_enabled   = true
    }
  }
}

resource "aws_wafv2_web_acl_association" "public" {
  count        = local.create
  resource_arn = aws_lb.public[0].arn
  web_acl_arn  = aws_wafv2_web_acl.public[0].arn
}

resource "aws_backup_vault" "validator" {
  count = local.create
  name  = "junca-public-testnet"
}

resource "aws_backup_plan" "validator" {
  count = local.create
  name  = "junca-public-testnet"
  rule {
    rule_name         = "daily-finalized-snapshot"
    target_vault_name = aws_backup_vault.validator[0].name
    schedule          = "cron(0 3 * * ? *)"
    lifecycle {
      delete_after = 35
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "disk_capacity" {
  for_each            = local.validators
  alarm_name          = "${each.key}-disk-capacity"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "disk_used_percent"
  namespace           = "JUNCA/PublicTestnet"
  period              = 300
  statistic           = "Maximum"
  threshold           = 80
  treat_missing_data  = "breaching"
  dimensions          = { InstanceId = aws_instance.validator[each.key].id }
}

resource "aws_cloudwatch_metric_alarm" "validator_quorum" {
  count               = local.create
  alarm_name          = "junca-validator-quorum"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  metric_name         = "HealthyValidators"
  namespace           = "JUNCA/PublicTestnet"
  period              = 60
  statistic           = "Minimum"
  threshold           = 3
  treat_missing_data  = "breaching"
}

resource "aws_cloudwatch_metric_alarm" "rpc_head_lag" {
  count               = local.create
  alarm_name          = "junca-rpc-head-lag"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "RpcHeadLag"
  namespace           = "JUNCA/PublicTestnet"
  period              = 60
  statistic           = "Maximum"
  threshold           = 3
  treat_missing_data  = "breaching"
}

resource "aws_route53_record" "public" {
  for_each = var.deployment_enabled ? toset([
    "rpc.testnet.${var.root_domain}",
    "explorer.testnet.${var.root_domain}",
    "health.testnet.${var.root_domain}"
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

resource "aws_route53_record" "public_ipv6" {
  for_each = var.deployment_enabled ? toset([
    "rpc.testnet.${var.root_domain}",
    "explorer.testnet.${var.root_domain}",
    "health.testnet.${var.root_domain}"
  ]) : toset([])
  zone_id = var.route53_zone_id
  name    = each.value
  type    = "AAAA"
  alias {
    name                   = aws_lb.public[0].dns_name
    zone_id                = aws_lb.public[0].zone_id
    evaluate_target_health = true
  }
}
