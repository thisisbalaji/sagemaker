output "domain_id" {
  description = "SageMaker AI domain ID."
  value       = aws_sagemaker_domain.this.id
}

output "domain_arn" {
  description = "SageMaker AI domain ARN."
  value       = aws_sagemaker_domain.this.arn
}

output "domain_url" {
  description = "Studio URL for the domain."
  value       = aws_sagemaker_domain.this.url
}

output "home_efs_file_system_id" {
  description = "EFS volume backing user home directories."
  value       = aws_sagemaker_domain.this.home_efs_file_system_id
}

output "execution_role_arn" {
  description = "Default execution role ARN used by the domain."
  value       = local.execution_role_arn
}

output "security_group_ids" {
  description = "Security groups attached to domain apps."
  value       = local.security_group_ids
}

output "user_profile_arns" {
  description = "Map of user profile name to ARN."
  value       = { for k, v in aws_sagemaker_user_profile.this : k => v.arn }
}
