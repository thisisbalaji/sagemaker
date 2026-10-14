resource "aws_apigatewayv2_api" "this" {
  name          = var.name
  protocol_type = "HTTP"
  description   = "One-time SageMaker AI Studio launch links"
  tags          = var.tags
}

resource "aws_apigatewayv2_integration" "this" {
  for_each = local.functions

  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.this[each.key].invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "launch_get" {
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "GET /launch"
  target    = "integrations/${aws_apigatewayv2_integration.this["launch"].id}"
}

resource "aws_apigatewayv2_route" "launch_post" {
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "POST /launch"
  target    = "integrations/${aws_apigatewayv2_integration.this["launch"].id}"
}

resource "aws_apigatewayv2_route" "tokens" {
  api_id             = aws_apigatewayv2_api.this.id
  route_key          = "POST /tokens"
  authorization_type = "AWS_IAM"
  target             = "integrations/${aws_apigatewayv2_integration.this["mint"].id}"
}

resource "aws_cloudwatch_log_group" "access" {
  name              = "/aws/apigateway/${var.name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit  = var.throttling_rate_limit
    throttling_burst_limit = var.throttling_burst_limit
  }

  # $context.path excludes the query string, so tokens never reach the access log.
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.access.arn
    format = jsonencode({
      requestId   = "$context.requestId"
      time        = "$context.requestTime"
      ip          = "$context.identity.sourceIp"
      userAgent   = "$context.identity.userAgent"
      routeKey    = "$context.routeKey"
      path        = "$context.path"
      status      = "$context.status"
      latencyMs   = "$context.responseLatency"
      callerArn   = "$context.identity.userArn"
      integration = "$context.integrationErrorMessage"
    })
  }

  tags = var.tags
}

resource "aws_lambda_permission" "api" {
  for_each = local.functions

  statement_id  = "AllowApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.this[each.key].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}
