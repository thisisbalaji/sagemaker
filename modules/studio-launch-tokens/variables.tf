variable "name" {
  description = "Prefix for all resource names."
  type        = string
  default     = "studio-launch"
}

variable "domain_ids" {
  description = "SageMaker AI domain IDs that launch links may open. Must be IAM-mode domains."
  type        = list(string)

  validation {
    condition     = length(var.domain_ids) > 0
    error_message = "Provide at least one domain ID."
  }
}

variable "allowed_cidrs" {
  description = "Client IP ranges allowed to use launch links (e.g. corporate egress). Empty allows any IP."
  type        = list(string)
  default     = []
}

variable "default_ttl_minutes" {
  description = "How long a launch link is valid when the minter does not say."
  type        = number
  default     = 15
}

variable "max_ttl_minutes" {
  description = "Longest launch-link lifetime a minter may request."
  type        = number
  default     = 60
}

variable "presign_expires_seconds" {
  description = "Lifetime of the SageMaker presigned URL the browser is redirected to."
  type        = number
  default     = 15

  validation {
    condition     = var.presign_expires_seconds >= 5 && var.presign_expires_seconds <= 300
    error_message = "presign_expires_seconds must be between 5 and 300."
  }
}

variable "session_expiration_seconds" {
  description = "Studio session length once opened."
  type        = number
  default     = 43200

  validation {
    condition     = var.session_expiration_seconds >= 1800 && var.session_expiration_seconds <= 43200
    error_message = "session_expiration_seconds must be between 1800 and 43200."
  }
}

variable "audit_retention_days" {
  description = "Days to keep token rows (including used ones) before DynamoDB TTL deletes them."
  type        = number
  default     = 90
}

variable "throttling_rate_limit" {
  description = "API Gateway steady-state requests per second."
  type        = number
  default     = 5
}

variable "throttling_burst_limit" {
  description = "API Gateway burst requests."
  type        = number
  default     = 10
}

variable "log_retention_days" {
  description = "CloudWatch log retention for Lambda and API access logs."
  type        = number
  default     = 30
}

variable "point_in_time_recovery" {
  description = "Enable DynamoDB point-in-time recovery (small extra cost)."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags applied to all resources."
  type        = map(string)
  default     = {}
}
