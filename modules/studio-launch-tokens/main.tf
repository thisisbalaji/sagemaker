data "aws_region" "current" {}
data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  region     = data.aws_region.current.region
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition

  user_profile_arns = [
    for d in var.domain_ids : "arn:${local.partition}:sagemaker:${local.region}:${local.account_id}:user-profile/${d}/*"
  ]

  functions = {
    launch = {
      handler = "launch.handler"
      env = {
        TABLE_NAME                 = aws_dynamodb_table.tokens.name
        ALLOWED_CIDRS              = join(",", var.allowed_cidrs)
        PRESIGN_EXPIRES_SECONDS    = tostring(var.presign_expires_seconds)
        SESSION_EXPIRATION_SECONDS = tostring(var.session_expiration_seconds)
      }
    }
    mint = {
      handler = "mint.handler"
      env = {
        TABLE_NAME           = aws_dynamodb_table.tokens.name
        DOMAIN_IDS           = join(",", var.domain_ids)
        DEFAULT_TTL_MINUTES  = tostring(var.default_ttl_minutes)
        MAX_TTL_MINUTES      = tostring(var.max_ttl_minutes)
        AUDIT_RETENTION_DAYS = tostring(var.audit_retention_days)
      }
    }
  }
}

# ---------------------------------------------------------------------------
# Lambda functions (one package, two handlers)
# ---------------------------------------------------------------------------
data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/lambda"
  output_path = "${path.module}/.build/lambda.zip"
  excludes    = ["__pycache__"]
}

resource "aws_cloudwatch_log_group" "lambda" {
  for_each = local.functions

  name              = "/aws/lambda/${var.name}-${each.key}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_lambda_function" "this" {
  for_each = local.functions

  function_name    = "${var.name}-${each.key}"
  role             = aws_iam_role.lambda[each.key].arn
  handler          = each.value.handler
  runtime          = "python3.13"
  architectures    = ["arm64"]
  memory_size      = 256
  timeout          = 10
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256

  environment {
    variables = each.value.env
  }

  tags       = var.tags
  depends_on = [aws_cloudwatch_log_group.lambda]
}
