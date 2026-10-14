output "api_endpoint" {
  description = "Base URL of the API."
  value       = aws_apigatewayv2_api.this.api_endpoint
}

output "mint_url" {
  description = "IAM-authenticated endpoint for creating launch links (POST)."
  value       = "${aws_apigatewayv2_api.this.api_endpoint}/tokens"
}

output "tokens_table_name" {
  description = "DynamoDB table holding token hashes and audit fields."
  value       = aws_dynamodb_table.tokens.name
}

output "minter_policy_arn" {
  description = "Attach to identities that may mint launch links."
  value       = aws_iam_policy.minter.arn
}

output "lambda_function_names" {
  description = "Launch and mint Lambda names."
  value       = { for k, f in aws_lambda_function.this : k => f.function_name }
}
