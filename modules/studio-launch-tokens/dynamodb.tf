resource "aws_dynamodb_table" "tokens" {
  name         = "${var.name}-tokens"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "token_hash"

  attribute {
    name = "token_hash"
    type = "S"
  }

  # purge_at = expires_at + audit_retention_days, so used rows remain for auditing.
  ttl {
    attribute_name = "purge_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = var.point_in_time_recovery
  }

  tags = var.tags
}
