locals {
  execution_role_arn = var.create_execution_role ? aws_iam_role.execution[0].arn : var.execution_role_arn
  security_group_ids = concat(aws_security_group.domain[*].id, var.security_group_ids)
}

# ---------------------------------------------------------------------------
# Execution role
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "assume_role" {
  statement {
    actions = ["sts:AssumeRole", "sts:SetSourceIdentity"]

    principals {
      type        = "Service"
      identifiers = ["sagemaker.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  count = var.create_execution_role ? 1 : 0

  name               = "${var.domain_name}-execution-role"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "execution" {
  for_each = var.create_execution_role ? toset(var.execution_role_policy_arns) : toset([])

  role       = aws_iam_role.execution[0].name
  policy_arn = each.value
}

# ---------------------------------------------------------------------------
# Security group
# ---------------------------------------------------------------------------
resource "aws_security_group" "domain" {
  count = var.create_security_group ? 1 : 0

  name        = "${var.domain_name}-sagemaker-domain"
  description = "SageMaker AI domain ${var.domain_name}"
  vpc_id      = var.vpc_id
  tags        = var.tags
}

# Apps in the domain talk to each other (e.g. Studio <-> kernel gateways, EFS NFS).
resource "aws_vpc_security_group_ingress_rule" "self" {
  count = var.create_security_group ? 1 : 0

  security_group_id            = aws_security_group.domain[0].id
  referenced_security_group_id = aws_security_group.domain[0].id
  ip_protocol                  = "-1"
  description                  = "Intra-domain traffic"
}

resource "aws_vpc_security_group_egress_rule" "all" {
  count = var.create_security_group ? 1 : 0

  security_group_id = aws_security_group.domain[0].id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "All outbound"
}

# ---------------------------------------------------------------------------
# Domain
# ---------------------------------------------------------------------------
resource "aws_sagemaker_domain" "this" {
  domain_name             = var.domain_name
  auth_mode               = var.auth_mode
  vpc_id                  = var.vpc_id
  subnet_ids              = var.subnet_ids
  app_network_access_type = var.app_network_access_type
  kms_key_id              = var.kms_key_id

  default_user_settings {
    execution_role      = local.execution_role_arn
    security_groups     = local.security_group_ids
    default_landing_uri = var.default_landing_uri
    studio_web_portal   = var.studio_web_portal
  }

  default_space_settings {
    execution_role  = local.execution_role_arn
    security_groups = local.security_group_ids
  }

  retention_policy {
    home_efs_file_system = var.efs_retention_policy
  }

  tags = var.tags

  lifecycle {
    precondition {
      condition     = var.create_execution_role || var.execution_role_arn != null
      error_message = "Set execution_role_arn when create_execution_role is false."
    }
  }
}

# ---------------------------------------------------------------------------
# User profiles
# ---------------------------------------------------------------------------
resource "aws_sagemaker_user_profile" "this" {
  for_each = var.user_profiles

  domain_id         = aws_sagemaker_domain.this.id
  user_profile_name = each.key

  user_settings {
    execution_role  = coalesce(each.value.execution_role_arn, local.execution_role_arn)
    security_groups = local.security_group_ids
  }

  tags = var.tags
}
