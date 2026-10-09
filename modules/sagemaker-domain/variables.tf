variable "domain_name" {
  description = "Name of the SageMaker AI domain."
  type        = string
}

variable "vpc_id" {
  description = "VPC the domain's apps run in."
  type        = string
}

variable "subnet_ids" {
  description = "Subnets for the domain (use private subnets with VpcOnly)."
  type        = list(string)
}

variable "auth_mode" {
  description = "Authentication mode: IAM or SSO."
  type        = string
  default     = "IAM"

  validation {
    condition     = contains(["IAM", "SSO"], var.auth_mode)
    error_message = "auth_mode must be IAM or SSO."
  }
}

variable "app_network_access_type" {
  description = "PublicInternetOnly or VpcOnly. VpcOnly requires NAT or VPC endpoints for AWS service access."
  type        = string
  default     = "VpcOnly"

  validation {
    condition     = contains(["PublicInternetOnly", "VpcOnly"], var.app_network_access_type)
    error_message = "app_network_access_type must be PublicInternetOnly or VpcOnly."
  }
}

variable "create_security_group" {
  description = "Create a security group for domain apps (self-referencing, all egress)."
  type        = bool
  default     = true
}

variable "security_group_ids" {
  description = "Extra security groups to attach to domain apps."
  type        = list(string)
  default     = []
}

variable "create_execution_role" {
  description = "Create the default execution role. If false, set execution_role_arn."
  type        = bool
  default     = true
}

variable "execution_role_arn" {
  description = "Existing execution role ARN (used when create_execution_role = false)."
  type        = string
  default     = null
}

variable "execution_role_policy_arns" {
  description = "Managed policies to attach to the created execution role."
  type        = list(string)
  default     = ["arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"]
}

variable "kms_key_id" {
  description = "KMS key ARN to encrypt the domain's EFS volume. Null uses the AWS managed key."
  type        = string
  default     = null
}

variable "default_landing_uri" {
  description = "Where users land when opening the domain (e.g. studio::)."
  type        = string
  default     = "studio::"
}

variable "studio_web_portal" {
  description = "ENABLED to use the new Studio experience, DISABLED for Studio Classic."
  type        = string
  default     = "ENABLED"
}

variable "efs_retention_policy" {
  description = "Retain or Delete the home EFS volume when the domain is deleted."
  type        = string
  default     = "Retain"

  validation {
    condition     = contains(["Retain", "Delete"], var.efs_retention_policy)
    error_message = "efs_retention_policy must be Retain or Delete."
  }
}

variable "user_profiles" {
  description = "User profiles to create in the domain. Key is the profile name; execution_role_arn overrides the domain default."
  type = map(object({
    execution_role_arn = optional(string)
  }))
  default = {}
}

variable "tags" {
  description = "Tags applied to all resources."
  type        = map(string)
  default     = {}
}
