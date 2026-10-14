data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  for_each = local.functions

  name               = "${var.name}-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = var.tags
}

# Launch: burn tokens and presign. No read/scan/put on the table.
data "aws_iam_policy_document" "launch" {
  statement {
    sid       = "BurnTokens"
    actions   = ["dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.tokens.arn]
  }

  statement {
    sid       = "Presign"
    actions   = ["sagemaker:CreatePresignedDomainUrl"]
    resources = local.user_profile_arns
  }

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.lambda["launch"].arn}:*"]
  }
}

# Mint: check the profile exists and write new tokens. Cannot overwrite (condition in code) or presign.
data "aws_iam_policy_document" "mint" {
  statement {
    sid       = "WriteTokens"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.tokens.arn]
  }

  statement {
    sid       = "CheckProfile"
    actions   = ["sagemaker:DescribeUserProfile"]
    resources = local.user_profile_arns
  }

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.lambda["mint"].arn}:*"]
  }
}

resource "aws_iam_role_policy" "launch" {
  name   = "launch"
  role   = aws_iam_role.lambda["launch"].id
  policy = data.aws_iam_policy_document.launch.json
}

resource "aws_iam_role_policy" "mint" {
  name   = "mint"
  role   = aws_iam_role.lambda["mint"].id
  policy = data.aws_iam_policy_document.mint.json
}

# Attach this to admins, a portal, or a bot that should be able to mint links.
resource "aws_iam_policy" "minter" {
  name        = "${var.name}-minter"
  description = "Allows calling POST /tokens to create Studio launch links."
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "execute-api:Invoke"
      Resource = "${aws_apigatewayv2_api.this.execution_arn}/*/POST/tokens"
    }]
  })
  tags = var.tags
}
